"""
OpenAI Images API client for the /image command.

Image generation always goes straight to OpenAI's Images API regardless of
LLM_ENGINE — this is a separate API surface from chat completions and is not
routed through core/llm/engine.py's provider registry. It reuses the shared
HTTP retry plumbing (build_session/post_with_retry/is_quota_error) from
core/llm/base.py, since that logic is provider-agnostic transport handling,
not chat-completions-specific.
"""

import base64
import logging

import requests

from config.settings import IMAGE_GEN_MODEL, IMAGE_GEN_SIZE, OPENAI_API_KEY
from core.llm.base import build_session, is_quota_error, post_with_retry

logger = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/images/generations"

# Error codes/types OpenAI uses for a moderation/content-policy rejection on
# the Images API (a 400 with a {"error": {"code"/"type": ...}} body), mirrored
# from the quota-signal pattern in core/llm/base.py.
_CONTENT_POLICY_SIGNALS = {"content_policy_violation", "moderation_blocked"}

_session = build_session()


class ImageGenerationError(Exception):
    """Base exception for /image generation failures."""


class ImageQuotaExceededError(ImageGenerationError):
    """Raised when OpenAI reports the account is out of balance/quota for image generation."""

    def __init__(self, detail: str = ""):
        super().__init__(f"ImageQuotaExceededError: {detail}" if detail else "ImageQuotaExceededError")


class ImageContentPolicyError(ImageGenerationError):
    """Raised when OpenAI rejects the prompt/result for violating its content policy."""

    def __init__(self, detail: str = ""):
        super().__init__(f"ImageContentPolicyError: {detail}" if detail else "ImageContentPolicyError")


class ImageEmptyResponseError(ImageGenerationError):
    """Raised when the API answers 200 OK but no usable image data is present."""

    def __init__(self, detail: str = ""):
        super().__init__(f"ImageEmptyResponseError: {detail}" if detail else "ImageEmptyResponseError")


def _is_content_policy_error(response) -> bool:
    """True if an HTTP error response indicates a content-policy/moderation rejection."""
    if response is None:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") or {}
    signal = {str(error.get("code") or "").lower(), str(error.get("type") or "").lower()}
    return bool(signal & _CONTENT_POLICY_SIGNALS)


def generate_image(prompt: str) -> bytes:
    """Generates an image via OpenAI's Images API and returns the raw PNG bytes.

    Raises ImageQuotaExceededError, ImageContentPolicyError, ImageEmptyResponseError
    on known failure modes, or re-raises the original HTTPError for anything else.
    """
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": IMAGE_GEN_MODEL,
        "prompt": prompt,
        "quality": "low",
        "n": 1,
        "size": IMAGE_GEN_SIZE,
    }

    try:
        response = post_with_retry(_session, API_URL, headers, payload)
    except requests.exceptions.HTTPError as e:
        if is_quota_error(e.response):
            raise ImageQuotaExceededError(str(e)) from e
        if _is_content_policy_error(e.response):
            raise ImageContentPolicyError(str(e)) from e
        raise

    try:
        b64_data = response.json()["data"][0]["b64_json"]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ImageEmptyResponseError(f"malformed response body: {e!r}") from e

    if not b64_data:
        raise ImageEmptyResponseError("empty b64_json field")

    try:
        return base64.b64decode(b64_data)
    except (ValueError, TypeError) as e:
        raise ImageEmptyResponseError(f"could not decode base64 image data: {e!r}") from e
