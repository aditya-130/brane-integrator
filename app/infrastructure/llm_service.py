import json
import logging
from abc import ABC, abstractmethod

from openai import OpenAI

from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)


class LlmService(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        ...

    @abstractmethod
    def complete_structured(self, system_prompt: str, user_prompt: str, schema: dict) -> dict | None:
        ...


class OpenAILlmService(LlmService):
    def __init__(self):
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL
        self.usage_log: list[dict] = []

    def _log_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        entry = {
            "model": self._model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
        self.usage_log.append(entry)
        logger.info(
            "OpenAI usage: model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d",
            self._model, usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            self._log_usage(response)
            return response.choices[0].message.content
        except Exception as e:
            logger.error("OpenAI complete error: %s", e)
            return None

    def complete_structured(self, system_prompt: str, user_prompt: str, schema: dict) -> dict | None:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_schema", "json_schema": schema},
            )
            self._log_usage(response)
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error("OpenAI complete_structured error: %s", e)
            return None
