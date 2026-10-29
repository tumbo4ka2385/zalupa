"""Агент: LM Studio пишет код -> код исполняется в Docker -> результат возвращается модели."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from config import Config
from docker_executor import DockerExecutor, ExecResult
from lmstudio_client import LMStudioClient

CODE_BLOCK_RE = re.compile(
    r"```(?P<lang>[A-Za-z0-9_+\-]*)\s*\n(?P<code>.*?)```",
    re.DOTALL,
)
FILE_HINT_RE = re.compile(r"^\s*(?:#|//)\s*file\s*:\s*(?P<name>[\w./\-]+)\s*$", re.IGNORECASE)

SYSTEM_PROMPT = """\
Ты — автономный агент-программист. Твоя задача — решать задачи, ПИША И ИСПОЛНЯЯ код
внутри изолированного Docker-контейнера.

ОКРУЖЕНИЕ:
- ОС: Debian Linux (образ python:3.12-slim или близкий)
- Рабочая директория: /workspace (файлы сохраняются между шагами)
- Доступен Python 3.12, pip, bash
- Интернет внутри контейнера есть (можно pip install, apt-get и т.п.)
- НЕТ GUI, НЕТ доступа к файлам хоста за пределами /workspace

ФОРМАТ ОТВЕТА:
1. Коротко (1–3 предложения) объясни, что собираешься сделать.
2. Дай один или несколько fenced-блоков с кодом:
   - ```python ... ``` — сохранится как файл и запустится через python <файл>
   - ```bash ... ```   — сохранится как файл и запустится через bash <файл>
3. Чтобы задать имя файла, первой строкой внутри блока напиши комментарий:
   # file: my_script.py
   Если имя не указано — агент сам подберёт имя.
4. НЕ пиши длинных объяснений после блока — сначала код, остальное по делу.

ВАЖНО:
- После каждого блока ты получишь сообщение вида:
  «Результат выполнения: exit_code=..., output=...»
  Используй его, чтобы исправить ошибки или сделать следующий шаг.
- НЕ повторяй уже успешно выполненный код.
- Если нужен новый файл — просто дай новый блок с нужным # file: ...
- Когда задача ПОЛНОСТЬЮ выполнена и проверена, ответь ровно одной строкой:
  TASK_COMPLETE
  без каких-либо блоков кода.
"""


@dataclass
class StepLog:
    index: int
    assistant_reply: str
    executions: list


class CodeAgent:
    def __init__(
        self,
        cfg: Config,
        llm: LMStudioClient,
        executor: DockerExecutor,
        on_step: Callable | None = None,
    ) -> None:
        self.cfg = cfg
        self.llm = llm
        self.executor = executor
        self.on_step = on_step or (lambda _log: None)

    def run_task(self, task: str, history: list | None = None) -> list:
        messages: list = list(history) if history else []
        if not messages:
            messages.append({"role": "system", "content": SYSTEM_PROMPT})
        messages.append({"role": "user", "content": f"ЗАДАЧА:\n{task}"})

        for step in range(1, self.cfg.max_steps + 1):
            reply = self.llm.chat(messages)
            messages.append({"role": "assistant", "content": reply})

            executions: list = []
            blocks = list(CODE_BLOCK_RE.finditer(reply))

            if not blocks:
                if self._is_complete(reply):
                    self.on_step(StepLog(step, reply, executions))
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "В твоём ответе нет блока с кодом. Либо дай код в ```python/```bash, "
                            "либо, если задача выполнена, ответь ровно: TASK_COMPLETE"
                        ),
                    }
                )
                self.on_step(StepLog(step, reply, executions))
                continue

            for i, block in enumerate(blocks, start=1):
                lang = (block.group("lang") or "").strip().lower()
                code = block.group("code").rstrip()

                if lang not in {"python", "py", "bash", "sh", "shell"}:
                    lang = "bash"

                filename, clean_code = self._extract_filename(code, lang, step, i)
                self.executor.write_file(filename, clean_code)

                if lang in {"python", "py"}:
                    result = self.executor.run_python(filename)
                else:
                    result = self.executor.run_bash(filename)

                executions.append((filename, result))
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Результат выполнения файла {filename}:\n"
                            f"{result.to_message()}"
                        ),
                    }
                )

            self.on_step(StepLog(step, reply, executions))

            if self._is_complete(reply) and all(r.ok for _, r in executions):
                break
        else:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Достигнут лимит шагов ({self.cfg.max_steps}). "
                        "Подведи итог: что успел сделать, что осталось."
                    ),
                }
            )
            summary = self.llm.chat(messages)
            messages.append({"role": "assistant", "content": summary})

        return messages

    @staticmethod
    def _is_complete(text: str) -> bool:
        return "TASK_COMPLETE" in text.upper()

    @staticmethod
    def _extract_filename(code: str, lang: str, step: int, idx: int):
        lines = code.splitlines()
        if lines:
            m = FILE_HINT_RE.match(lines[0])
            if m:
                name = m.group("name")
                rest = "\n".join(lines[1:]).lstrip("\n")
                return name, rest
        ext = "py" if lang in {"python", "py"} else "sh"
        return f"step_{step:02d}_{idx}.{ext}", code
