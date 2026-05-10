import logging
from abc import ABC, abstractmethod
from openai import OpenAI
from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)


class LlmService(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        ...


class OpenAILlmService(LlmService):
    def __init__(self):
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("OpenAI error: %s", e)
            return None
