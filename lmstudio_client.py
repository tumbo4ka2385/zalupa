"""Клиент LM Studio (совместим с OpenAI Chat Completions API)."""
from __future__ import annotations

import sys
from typing import Iterable

from openai import OpenAI

from config import Config


class LMStudioClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = OpenAI(
            base_url=cfg.lm_base_url,
            api_key=cfg.lm_api_key,
        )
        self._model: str | None = cfg.lm_model

    def list_models(self) -> list[str]:
        try:
            resp = self.client.models.list()
        except Exception as exc:
            raise RuntimeError(
                f"Не удалось получить список моделей из LM Studio ({self.cfg.lm_base_url}). "
                f"Убедитесь, что сервер запущен. Детали: {exc}"
            ) from exc
        return [m.id for m in resp.data]

    @property
    def model(self) -> str:
        if self._model:
            return self._model
        models = self.list_models()
        if not models:
            raise RuntimeError(
                "LM Studio вернул пустой список моделей. Загрузите модель в LM Studio."
            )
        self._model = models[0]
        print(f"[lmstudio] авто-выбор модели: {self._model}", file=sys.stderr)
        return self._model

    def chat(self, messages: Iterable[dict]) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        except Exception as exc:
            raise RuntimeError(f"Ошибка при обращении к LM Studio: {exc}") from exc
        return resp.choices[0].message.content or ""
