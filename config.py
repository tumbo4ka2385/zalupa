"""Загрузка конфигурации из переменных окружения / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass
class Config:
    lm_base_url: str
    lm_api_key: str
    lm_model: str | None
    temperature: float
    max_tokens: int
    docker_image: str
    container_name: str
    workspace: str
    max_steps: int
    exec_timeout: int


def load_config() -> Config:
    model = os.getenv("LM_STUDIO_MODEL") or None
    return Config(
        lm_base_url=_env("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
        lm_api_key=_env("LM_STUDIO_API_KEY", "lm-studio"),
        lm_model=model,
        temperature=float(_env("TEMPERATURE", "0.2")),
        max_tokens=int(_env("MAX_TOKENS", "2048")),
        docker_image=_env("DOCKER_IMAGE", "python:3.12-slim"),
        container_name=_env("CONTAINER_NAME", "lmstudio-sandbox"),
        workspace=_env("CONTAINER_WORKSPACE", "/workspace"),
        max_steps=int(_env("MAX_STEPS", "25")),
        exec_timeout=int(_env("EXEC_TIMEOUT", "180")),
    )
