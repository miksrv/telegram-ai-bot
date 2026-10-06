import base64

import pytest
import requests

import services.image_service as image_service
from services.image_service import (
    ImageContentPolicyError,
    ImageEmptyResponseError,
    ImageQuotaExceededError,
    generate_image,
)


class _FakeHTTPResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return self._body


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002
        self.calls += 1
        return self._responses.pop(0)


def test_generate_image_returns_decoded_bytes(monkeypatch):
    raw = b"fake-png-bytes"
    b64 = base64.b64encode(raw).decode()
    session = _FakeSession([_FakeHTTPResponse(200, {"data": [{"b64_json": b64}]})])
    monkeypatch.setattr(image_service, "_session", session)

    result = generate_image("a comet made of cheese")

    assert result == raw
    assert session.calls == 1


def test_generate_image_raises_content_policy_error(monkeypatch):
    session = _FakeSession(
        [_FakeHTTPResponse(400, {"error": {"code": "content_policy_violation", "type": "invalid_request_error"}})]
    )
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(ImageContentPolicyError):
        generate_image("something not allowed")


def test_generate_image_raises_content_policy_error_moderation_blocked(monkeypatch):
    session = _FakeSession([_FakeHTTPResponse(400, {"error": {"code": "moderation_blocked"}})])
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(ImageContentPolicyError):
        generate_image("something not allowed")


def test_generate_image_raises_quota_exceeded_on_402(monkeypatch):
    session = _FakeSession([_FakeHTTPResponse(402, {"error": {}})])
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(ImageQuotaExceededError):
        generate_image("a nebula")


def test_generate_image_raises_quota_exceeded_on_429_insufficient_quota(monkeypatch):
    session = _FakeSession([_FakeHTTPResponse(429, {"error": {"code": "insufficient_quota"}})])
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(ImageQuotaExceededError):
        generate_image("a nebula")


def test_generate_image_raises_empty_response_on_missing_field(monkeypatch):
    session = _FakeSession([_FakeHTTPResponse(200, {"data": [{}]})])
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(ImageEmptyResponseError):
        generate_image("a galaxy")


def test_generate_image_raises_empty_response_on_malformed_body(monkeypatch):
    session = _FakeSession([_FakeHTTPResponse(200, {"data": []})])
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(ImageEmptyResponseError):
        generate_image("a galaxy")


def test_generate_image_propagates_other_http_errors(monkeypatch):
    session = _FakeSession([_FakeHTTPResponse(401, {"error": {"code": "invalid_api_key"}})])
    monkeypatch.setattr(image_service, "_session", session)

    with pytest.raises(requests.exceptions.HTTPError):
        generate_image("a planet")
