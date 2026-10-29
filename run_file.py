"""run_file.py — запускает задачу, прочитанную из UTF-8 файла."""
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from agent import CodeAgent, StepLog
from config import load_config
from docker_executor import DockerExecutor
from lmstudio_client import LMStudioClient

console = Console()


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


def main() -> int:
    if len(sys.argv) < 2:
        console.print("[red]Использование: python run_file.py <путь-к-файлу>[/red]")
        return 1

    task_file = Path(sys.argv[1])
    if not task_file.exists():
        console.print(f"[red]Файл не найден: {task_file}[/red]")
        return 1

    task = task_file.read_text(encoding="utf-8")
    preview = task if len(task) <= 400 else task[:400] + "..."
    console.print(Panel(preview, title=f"Задача из {task_file.name}", border_style="magenta"))

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
    try:
        agent.run_task(task)
    finally:
        ex.stop(remove=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
