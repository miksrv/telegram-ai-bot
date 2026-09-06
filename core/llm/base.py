"""
Shared interface and HTTP plumbing for cloud LLM connectors.

Every provider (Groq, OpenAI, ...) implements `LLMProvider.complete()` and
uses `build_session()`/`post_with_retry()` for the actual HTTP call. Groq and
OpenAI's chat completions APIs share the same request/response shape, so this
retry logic is provider-agnostic.
"""

import logging
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Error codes/types (in the shared {"error": {"message","type","code"}} body
# shape both Groq and OpenAI use) that mean "the account is out of
# balance/quota", as opposed to a transient or auth/config error. Deliberately
# narrow: an ordinary rate-limit 429 (no matching code) is NOT quota
# exhaustion — post_with_retry retries those with backoff instead.
_QUOTA_ERROR_SIGNALS = {"insufficient_quota", "billing_hard_limit_reached", "exceeded_quota"}


class LLMQuotaExceededError(Exception):
    """Raised by a provider when the API reports the account is out of
    balance/quota (see is_quota_error), so LLMEngine can fail over to a
    configured fallback provider instead of just propagating the error."""


class LLMEmptyResponseError(Exception):
    """Raised by a provider when the API answered 200 OK but the completion
    carries no usable text (see extract_message_content).

    The common real-world case is a model refusal: with
    `response_format: json_object` OpenAI returns `message.content: null` and
    puts the refusal text in `message.refusal` (or sets
    `finish_reason: content_filter`). That is not a transport failure, so it is
    kept distinct from HTTP errors — the caller can answer the user in-character
    instead of reporting a generic "logic module failure"."""

    def __init__(self, provider: str, finish_reason=None, refusal=None, detail=None):
        self.provider = provider
        self.finish_reason = finish_reason
        self.refusal = refusal
        self.detail = detail
        parts = [f"{provider}: completion has no text content"]
        if finish_reason:
            parts.append(f"finish_reason={finish_reason}")
        if refusal:
            parts.append(f"refusal={refusal!r}")
        if detail:
            parts.append(detail)
        super().__init__("; ".join(parts))


def extract_message_content(body: dict, provider: str) -> str:
    """Pulls the assistant text out of a chat-completions response body.

    Groq and OpenAI share the same `{"choices": [{"message": {...}, "finish_reason": ...}]}`
    shape. Returns the stripped text; raises LLMEmptyResponseError when the
    content is missing/null/blank (model refusal, content filter, or a malformed
    body) instead of letting an AttributeError escape from `.strip()`.
    """
    try:
        choice = body["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise LLMEmptyResponseError(provider, detail=f"malformed response body: {e!r}") from e

    content = message.get("content")

    # Some OpenAI-compatible backends return content as a list of parts.
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )

    if isinstance(content, str) and content.strip():
        return content.strip()

    finish_reason = choice.get("finish_reason")
    refusal = message.get("refusal")
    logging.warning(
        f"{provider} returned an empty completion: finish_reason={finish_reason!r} refusal={refusal!r} "
        f"content={content!r}"
    )
    raise LLMEmptyResponseError(provider, finish_reason=finish_reason, refusal=refusal)


def is_quota_error(response) -> bool:
    """True if an HTTP error response indicates quota/billing exhaustion."""
    if response is None:
        return False
    if response.status_code == 402:
        return True
    if response.status_code != 429:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") or {}
    signal = {str(error.get("code") or "").lower(), str(error.get("type") or "").lower()}
    return bool(signal & _QUOTA_ERROR_SIGNALS)


def build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def _retry_after_seconds(response) -> Optional[float]:
    """Parses a `Retry-After` header (seconds form) if present and valid."""
    value = response.headers.get("Retry-After") if response is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def post_with_retry(session: requests.Session, url: str, headers: dict, payload: dict, retries: int = 3):
    for attempt in range(retries):
        try:
            response = session.post(
                url,
                headers=headers,
                json=payload,
                timeout=(5, 60),
            )

            response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as e:
            resp = e.response

            # Ordinary rate-limit 429s are transient and worth retrying; billing/quota
            # exhaustion (is_quota_error) is not — propagate it immediately so the
            # caller can convert it to LLMQuotaExceededError without wasted attempts.
            # Any other HTTP error (401, 400, ...) also propagates immediately.
            if resp is None or resp.status_code != 429 or is_quota_error(resp):
                raise

            logging.warning(f"LLM API rate-limited (attempt {attempt+1}/{retries}): {e}")

            if attempt == retries - 1:
                raise

            time.sleep(_retry_after_seconds(resp) or 2**attempt)

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
            ConnectionResetError,
        ) as e:

            logging.warning(f"LLM API retry {attempt+1}/{retries}: {e}")

            if attempt == retries - 1:
                raise

            time.sleep(2**attempt)  # exponential backoff


class LLMProvider:
    """Common interface every cloud LLM connector must implement."""

    name = "base"

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
        """Sends a chat completion request and returns the raw response content.

        `kind` is "text" or "vision" — lets the provider pick its own model
        for that role without the caller knowing concrete model names.
        """
        raise NotImplementedError
