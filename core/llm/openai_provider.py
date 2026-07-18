import requests

from config.settings import OPENAI_API_KEY, OPENAI_MODEL_TEXT, OPENAI_MODEL_VISION
from core.llm.base import LLMProvider, LLMQuotaExceededError, build_session, is_quota_error, post_with_retry


class OpenAIProvider(LLMProvider):
    name = "openai"

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self._session = build_session()
        self._headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

    def complete(
        self,
        messages: list,
        *,
        kind: str = "text",
        temperature: float,
        max_tokens: int,
        top_p: float,
        json_mode: bool = True,
    ) -> str:
        model = OPENAI_MODEL_VISION if kind == "vision" else OPENAI_MODEL_TEXT

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = post_with_retry(self._session, self.API_URL, self._headers, payload)
        except requests.exceptions.HTTPError as e:
            if is_quota_error(e.response):
                raise LLMQuotaExceededError(f"{self.name}: {e}") from e
            raise

        return response.json()["choices"][0]["message"]["content"].strip()
