"""CLI: LM Studio + Docker code agent.

Команды:
  models  — показать доступные модели в LM Studio
  build   — собрать образ песочницы из docker/sandbox.Dockerfile
  run     — выполнить одну задачу
  chat    — интерактивный режим (несколько задач подряд)
  shell   — запустить контейнер и подсказать, как зайти внутрь
  reset   — удалить контейнер и очистить рабочую папку
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from agent import CodeAgent, StepLog
from config import load_config
from docker_executor import DockerExecutor
from lmstudio_client import LMStudioClient

console = Console()
ROOT = Path(__file__).parent.resolve()


def print_step(log: StepLog) -> None:
    console.rule(f"[bold]Шаг {log.index}[/bold]")
    if log.assistant_reply.strip():
        console.print(Panel(Markdown(log.assistant_reply), border_style="cyan", title="Модель"))
    for filename, result in log.executions:
        style = "green" if result.ok else "red"
        console.print(
            Panel(
                result.output.rstrip() or "(пустой вывод)",
                title=f"[{style}]{filename}  exit={result.exit_code}[/{style}]",
                border_style=style,
            )
        )


def cmd_models(_args: argparse.Namespace) -> int:
    cfg = load_config()
    llm = LMStudioClient(cfg)
    try:
        models = llm.list_models()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    if not models:
        console.print("[yellow]LM Studio не вернул ни одной модели.[/yellow]")
        return 1
    console.print(f"[bold]Доступные модели в {cfg.lm_base_url}:[/bold]")
    for m in models:
        console.print(f"  • {m}")
    return 0


def cmd_build(_args: argparse.Namespace) -> int:
    cfg = load_config()
    dockerfile = ROOT / "docker" / "sandbox.Dockerfile"
    if not dockerfile.exists():
        console.print(f"[red]Не найден {dockerfile}[/red]")
        return 1
    ex = DockerExecutor(image=cfg.docker_image, container_name=cfg.container_name)
    tag = cfg.docker_image
    try:
        ex.build_image(dockerfile=dockerfile, tag=tag, context=dockerfile.parent)
    except Exception as exc:
        console.print(f"[red]Ошибка сборки: {exc}[/red]")
        return 1
    console.print(f"[green]Образ {tag} собран.[/green]")
    return 0


def _make_runtime():
    cfg = load_config()
    llm = LMStudioClient(cfg)
    ex = DockerExecutor(
        image=cfg.docker_image,
        container_name=cfg.container_name,
        workspace=cfg.workspace,
        exec_timeout=cfg.exec_timeout,
    )
    ex.start()
    agent = CodeAgent(cfg, llm, ex, on_step=print_step)
    return cfg, llm, ex, agent


def cmd_run(args: argparse.Namespace) -> int:
    _, _, ex, agent = _make_runtime()
    try:
        console.print(Panel(args.task, title="Задача", border_style="magenta"))
        agent.run_task(args.task)
    finally:
        if args.rm:
            ex.stop(remove=True)
            shutil.rmtree(ex.host_workdir, ignore_errors=True)
    return 0


def cmd_chat(_args: argparse.Namespace) -> int:
    cfg, llm, ex, agent = _make_runtime()
    console.print(
        Panel(
            f"Модель: [bold]{llm.model}[/bold]\n"
            f"Контейнер: [bold]{cfg.container_name}[/bold]\n"
            f"workspace на хосте: {ex.host_workdir}\n\n"
            "Пишите задачи. `exit` — выйти, `reset` — очистить контекст.",
            title="Интерактивный режим",
            border_style="green",
        )
    )
    history: list = []
    try:
        while True:
            try:
                task = Prompt.ask("[bold blue]задача[/bold blue]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not task:
                continue
            if task.lower() in {"exit", "quit", ":q"}:
                break
            if task.lower() == "reset":
                history = []
                console.print("[yellow]История очищена.[/yellow]")
                continue
            try:
                history = agent.run_task(task, history=history)
            except RuntimeError as exc:
                console.print(f"[red]{exc}[/red]")
            console.print("[green]OK задача завершена[/green]\n")
    finally:
        ex.stop(remove=False)
    return 0


def cmd_shell(_args: argparse.Namespace) -> int:
    cfg = load_config()
    ex = DockerExecutor(
        image=cfg.docker_image,
        container_name=cfg.container_name,
        workspace=cfg.workspace,
    )
    ex.start()
    console.print(
        f"[green]Контейнер {cfg.container_name} запущен.[/green]\n"
        f"Откройте второй терминал и выполните:\n\n"
        f"  docker exec -it {cfg.container_name} bash\n\n"
        f"Файлы синхронизированы с {ex.host_workdir}"
    )
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    cfg = load_config()
    ex = DockerExecutor(image=cfg.docker_image, container_name=cfg.container_name)
    ex.stop(remove=True)
    shutil.rmtree(ex.host_workdir, ignore_errors=True)
    console.print("[green]Контейнер остановлен, временная папка удалена.[/green]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lmstudio-docker-agent",
        description="LM Studio + Docker: модель пишет код, контейнер его исполняет.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("models", help="показать модели, доступные в LM Studio").set_defaults(func=cmd_models)
    sub.add_parser("build", help="собрать образ песочницы").set_defaults(func=cmd_build)

    r = sub.add_parser("run", help="выполнить одну задачу")
    r.add_argument("task", help="текст задачи")
    r.add_argument("--rm", action="store_true", help="удалить контейнер и папку после выполнения")
    r.set_defaults(func=cmd_run)

    sub.add_parser("chat", help="интерактивный режим").set_defaults(func=cmd_chat)
    sub.add_parser("shell", help="запустить контейнер и подсказать, как зайти внутрь").set_defaults(func=cmd_shell)
    sub.add_parser("reset", help="удалить контейнер и временные файлы").set_defaults(func=cmd_reset)
    return p


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Прервано пользователем.[/yellow]")
        return 130
    except Exception as exc:
        console.print(f"[red]Ошибка: {exc}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
