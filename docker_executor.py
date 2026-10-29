"""Управление Docker-контейнером и выполнение кода внутри него."""
from __future__ import annotations

import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container


@dataclass
class ExecResult:
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_message(self, max_chars: int = 4000) -> str:
        out = self.output.strip() or "(пустой вывод)"
        if len(out) > max_chars:
            out = out[:max_chars] + f"\n... [обрезано, всего {len(self.output)} символов]"
        return f"exit_code={self.exit_code}\n--- output ---\n{out}"


class DockerExecutor:
    def __init__(
        self,
        image: str,
        container_name: str,
        workspace: str = "/workspace",
        exec_timeout: int = 180,
    ) -> None:
        self.image = image
        self.container_name = container_name
        self.workspace = workspace
        self.exec_timeout = exec_timeout
        self._client = docker.from_env()
        self._workdir: Path = Path(tempfile.mkdtemp(prefix="lmstudio-sandbox-"))
        self._container: Container | None = None

    @property
    def host_workdir(self) -> Path:
        return self._workdir

    def build_image(self, dockerfile, tag, context=None):
        """Собирает образ из Dockerfile."""
        context = context or dockerfile.parent
        print(f"[docker] сборка образа {tag} из {dockerfile} ...")
        _, logs = self._client.images.build(
            path=str(context),
            dockerfile=dockerfile.name,
            tag=tag,
            rm=True,
        )
        for chunk in logs:
            line = chunk.get("stream") if isinstance(chunk, dict) else None
            if line:
                print("  " + line.rstrip())
    def _ensure_image(self) -> None:
        try:
            self._client.images.get(self.image)
        except ImageNotFound:
            print(f"[docker] образ {self.image} не найден, скачиваю...")
            self._client.images.pull(self.image)

    def start(self) -> Container:
        if self._container is not None:
            self._container.reload()
            if self._container.status == "running":
                return self._container

        try:
            old = self._client.containers.get(self.container_name)
            print(f"[docker] удаляю старый контейнер {self.container_name} ...")
            old.remove(force=True)
        except NotFound:
            pass
        except DockerException:
            pass

        self._ensure_image()
        print(f"[docker] запускаю контейнер {self.container_name} ({self.image}) ...")
        self._container = self._client.containers.run(
            self.image,
            command=["sleep", "infinity"],
            name=self.container_name,
            working_dir=self.workspace,
            volumes={str(self._workdir): {"bind": self.workspace, "mode": "rw"}},
            detach=True,
            tty=False,
            auto_remove=False,
        )
        return self._container

    @property
    def container(self) -> Container:
        if self._container is None:
            return self.start()
        self._container.reload()
        if self._container.status != "running":
            print("[docker] контейнер не запущен, перезапускаю ...")
            self._container.start()
        return self._container

    def stop(self, remove: bool = True) -> None:
        if self._container is None:
            return
        try:
            self._container.stop(timeout=5)
        except Exception:
            pass
        if remove:
            try:
                self._container.remove(force=True)
            except Exception:
                pass
        self._container = None

    def exec_shell(self, command: str, timeout: int | None = None) -> ExecResult:
        c = self.container
        try:
            res = c.exec_run(
                ["bash", "-lc", command],
                workdir=self.workspace,
                demux=False,
                tty=False,
            )
        except DockerException as exc:
            return ExecResult(exit_code=1, output=f"[docker error] {exc}")
        output = (res.output or b"").decode("utf-8", errors="replace")
        return ExecResult(exit_code=int(res.exit_code or 0), output=output)

    def write_file(self, filename: str, content: str) -> Path:
        safe = filename.strip().lstrip("/\\").replace("\\", "/")
        target = self._workdir / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def run_python(self, filename: str) -> ExecResult:
        return self.exec_shell(f"python {shlex.quote(filename)}")

    def run_bash(self, filename: str) -> ExecResult:
        return self.exec_shell(f"bash {shlex.quote(filename)}")
