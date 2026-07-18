"""
LLMEngine — the single entry point core/brain.py talks to.

Picks the active connector from LLM_ENGINE and exposes one .complete() call.
Adding a new cloud LLM means adding one provider file implementing
LLMProvider and one line in _PROVIDERS below — nothing else changes.

Automatic quota fallback: if the *other* provider's API key also happens to
be configured, it's kept on standby. When the active provider raises
LLMQuotaExceededError (account out of balance/quota — see
core/llm/base.py:is_quota_error), the engine permanently switches to that
standby provider for the rest of the process's lifetime and retries the call
once. No config toggle is needed beyond filling in both API keys; if only one
key is set, there's nothing to fall back to and the error just propagates.
"""

import logging

from config.settings import GROQ_API_KEY, LLM_ENGINE, OPENAI_API_KEY
from core.llm.base import LLMQuotaExceededError
from core.llm.groq_provider import GroqProvider
from core.llm.openai_provider import OpenAIProvider

_PROVIDERS = {
    "groq": GroqProvider,
    "openai": OpenAIProvider,
}

# Used only to decide whether a standby fallback provider can be built (its
# key is non-empty). Assumes exactly one "other" provider — revisit this if a
# third provider is ever added alongside Groq/OpenAI.
_PROVIDER_API_KEYS = {
    "groq": GROQ_API_KEY,
    "openai": OPENAI_API_KEY,
}


class LLMEngine:
    def __init__(self, engine_name: str = LLM_ENGINE):
        provider_cls = _PROVIDERS.get(engine_name)
        if provider_cls is None:
            raise RuntimeError(f"Unknown LLM_ENGINE '{engine_name}', expected one of {sorted(_PROVIDERS)}")

        self.provider = provider_cls()
        logging.info(f"LLM engine active: {self.provider.name}")

        self.fallback_provider = None
        for name, provider_cls in _PROVIDERS.items():
            if name != engine_name and _PROVIDER_API_KEYS.get(name):
                self.fallback_provider = provider_cls()
                logging.info(f"LLM fallback engine on standby: {self.fallback_provider.name}")
                break

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
        try:
            return self.provider.complete(
                messages,
                kind=kind,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                json_mode=json_mode,
            )
        except LLMQuotaExceededError as e:
            if self.fallback_provider is None:
                raise

            logging.error(
                f"{self.provider.name} out of quota ({e}); switching to fallback "
                f"{self.fallback_provider.name} for the remainder of this run"
            )
            self.provider = self.fallback_provider
            self.fallback_provider = None

            return self.provider.complete(
                messages,
                kind=kind,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                json_mode=json_mode,
            )


# Module-level singleton
llm_engine = LLMEngine()
