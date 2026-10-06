"""Tests for /status: CubeSat telemetry formatting and the version footer.

The version line (config.settings.BOT_VERSION) must appear on every outcome —
success, timeout, a failed send, and a malformed reply — so it's always
visible regardless of whether CubeSat answered.
"""

import threading
from queue import Empty

import handlers.status_handler as status_handler
from config.settings import BOT_VERSION

ALLOWED = {-100123456789}


class _TrackingThread(threading.Thread):
    """Real threading.Thread subclass that records every instance created, so
    tests can join the background wait-and-respond thread before asserting."""

    created: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _TrackingThread.created.append(self)


def _patch_sync_thread(monkeypatch):
    _TrackingThread.created.clear()
    monkeypatch.setattr(status_handler.threading, "Thread", _TrackingThread)


def _run_and_wait(bot, message, allowed=ALLOWED):
    status_handler.handle_status(bot, message, allowed)
    for t in list(_TrackingThread.created):
        t.join(timeout=2)


class _EmptyQueue:
    """Stands in for the MQTT response queue when no reply ever arrives."""

    def get(self, timeout=None):
        raise Empty


class _FilledQueue:
    def __init__(self, payload: dict):
        import json

        self._msg = {"topic": "cubesat/telemetry/data", "payload": json.dumps(payload)}

    def get(self, timeout=None):
        return self._msg


class _RawQueue:
    """Returns a payload string as-is (for malformed-JSON tests)."""

    def __init__(self, payload_str: str):
        self._msg = {"topic": "cubesat/telemetry/data", "payload": payload_str}

    def get(self, timeout=None):
        return self._msg


class _FakeChat:
    def __init__(self, chat_id, chat_type="group"):
        self.id = chat_id
        self.type = chat_type


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeMessage:
    def __init__(self, chat_id=-100123456789, user_id=42, chat_type="group"):
        self.chat = _FakeChat(chat_id, chat_type)
        self.from_user = _FakeUser(user_id)


class _FakeBot:
    def __init__(self):
        self.replies = []
        self.sent = []

    def reply_to(self, message, text):
        self.replies.append(text)

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


VERSION_LINE = f"Версия TARS: v{BOT_VERSION}"


def test_version_line_matches_the_version_file():
    assert status_handler.VERSION_LINE == VERSION_LINE
    assert BOT_VERSION != "unknown"


def test_unauthorized_access_shows_no_version_footer():
    bot = _FakeBot()
    message = _FakeMessage(chat_id=-999, chat_type="group")
    status_handler.handle_status(bot, message, ALLOWED)
    assert bot.replies == ["Доступ запрещён."]
    assert not bot.sent


def test_send_command_failure_includes_version(monkeypatch):
    monkeypatch.setattr(status_handler, "register_request", lambda rid: _EmptyQueue())
    monkeypatch.setattr(status_handler, "send_command", lambda *a, **kw: False)
    monkeypatch.setattr(status_handler, "unregister_request", lambda rid: None)

    bot = _FakeBot()
    status_handler.handle_status(bot, _FakeMessage(), ALLOWED)

    assert len(bot.sent) == 1
    assert "Не удалось отправить запрос телеметрии" in bot.sent[0]
    assert VERSION_LINE in bot.sent[0]


def test_timeout_includes_version(monkeypatch):
    _patch_sync_thread(monkeypatch)
    monkeypatch.setattr(status_handler, "register_request", lambda rid: _EmptyQueue())
    monkeypatch.setattr(status_handler, "send_command", lambda *a, **kw: True)
    monkeypatch.setattr(status_handler, "unregister_request", lambda rid: None)

    bot = _FakeBot()
    _run_and_wait(bot, _FakeMessage())

    assert len(bot.sent) == 1
    assert "Таймаут" in bot.sent[0]
    assert VERSION_LINE in bot.sent[0]


def test_malformed_json_reply_includes_version(monkeypatch):
    _patch_sync_thread(monkeypatch)
    monkeypatch.setattr(status_handler, "register_request", lambda rid: _RawQueue("not json"))
    monkeypatch.setattr(status_handler, "send_command", lambda *a, **kw: True)
    monkeypatch.setattr(status_handler, "unregister_request", lambda rid: None)

    bot = _FakeBot()
    _run_and_wait(bot, _FakeMessage())

    assert len(bot.sent) == 1
    assert "некорректный" in bot.sent[0]
    assert VERSION_LINE in bot.sent[0]


def test_successful_telemetry_includes_version(monkeypatch):
    _patch_sync_thread(monkeypatch)
    monkeypatch.setattr(
        status_handler, "register_request", lambda rid: _FilledQueue({"state": "NOMINAL", "eps": {"battery": 90}})
    )
    monkeypatch.setattr(status_handler, "send_command", lambda *a, **kw: True)
    monkeypatch.setattr(status_handler, "unregister_request", lambda rid: None)

    bot = _FakeBot()
    _run_and_wait(bot, _FakeMessage())

    assert len(bot.sent) == 1
    assert "NOMINAL" in bot.sent[0]
    assert VERSION_LINE in bot.sent[0]


# --------------------------------------------------
# format_telemetry_for_telegram — version footer on both branches
# --------------------------------------------------


def test_format_telemetry_appends_version_with_data():
    text = status_handler.format_telemetry_for_telegram({"state": "NOMINAL", "eps": {"battery": 90}})
    assert "NOMINAL" in text
    assert VERSION_LINE in text


def test_format_telemetry_appends_version_when_empty():
    text = status_handler.format_telemetry_for_telegram({})
    assert "нет" in text
    assert VERSION_LINE in text
