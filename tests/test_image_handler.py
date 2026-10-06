import logging
import threading

import handlers.image_handler as image_handler
from services.image_service import ImageContentPolicyError, ImageQuotaExceededError

ALLOWED = {-100123456789}

_MAX_PER_DAY = 5


class _TrackingThread(threading.Thread):
    """Real threading.Thread subclass that records every instance created.

    The handler now spawns a background thread for the slow OpenAI call (like
    /photo), so tests need a way to wait for that thread (and any nested ones,
    e.g. typing_action's heartbeat thread) to actually finish before asserting
    — a thread that merely runs its target synchronously would deadlock
    typing_action, whose heartbeat loop only exits once the *caller*
    (running concurrently) sets its stop event after the `with` block body
    returns.
    """

    created: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _TrackingThread.created.append(self)


def _patch_sync_thread(monkeypatch):
    _TrackingThread.created.clear()
    monkeypatch.setattr(image_handler.threading, "Thread", _TrackingThread)


def _run_and_wait(bot, message, allowed=ALLOWED):
    """Calls handle_image and blocks until every thread it (transitively) spawned finishes."""
    image_handler.handle_image(bot, message, allowed)
    for t in list(_TrackingThread.created):
        t.join(timeout=2)


class _FakeChat:
    def __init__(self, chat_id, chat_type="group"):
        self.id = chat_id
        self.type = chat_type


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeMessage:
    def __init__(self, text, chat_id=-100123456789, user_id=42, message_id=7, chat_type="group"):
        self.text = text
        self.chat = _FakeChat(chat_id, chat_type)
        self.from_user = _FakeUser(user_id)
        self.message_id = message_id


class _FakeBot:
    def __init__(self):
        self.replies = []
        self.deleted = []
        self.sent_photos = []
        self._next_message_id = 100

    def reply_to(self, message, text):
        self._next_message_id += 1
        self.replies.append(text)
        return type("Sent", (), {"message_id": self._next_message_id})()

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)

    def send_chat_action(self, chat_id, action):
        pass

    def send_photo(self, chat_id, photo, reply_to_message_id=None, allow_sending_without_reply=None):
        self.sent_photos.append(photo)


def test_empty_prompt_shows_usage():
    bot = _FakeBot()
    image_handler.handle_image(bot, _FakeMessage("/image"), ALLOWED)
    assert len(bot.replies) == 1
    assert "Использование" in bot.replies[0]
    assert not bot.sent_photos


def test_blank_prompt_shows_usage():
    bot = _FakeBot()
    image_handler.handle_image(bot, _FakeMessage("/image    "), ALLOWED)
    assert len(bot.replies) == 1
    assert "Использование" in bot.replies[0]


def test_unauthorized_chat_is_ignored():
    bot = _FakeBot()
    message = _FakeMessage("/image комета", chat_id=-999, chat_type="group")
    image_handler.handle_image(bot, message, ALLOWED)
    assert bot.replies == []
    assert not bot.sent_photos


def test_cooldown_rejection(monkeypatch):
    bot = _FakeBot()
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: False)
    image_handler.handle_image(bot, _FakeMessage("/image комета"), ALLOWED)
    assert len(bot.replies) == 1
    assert "слишком много" in bot.replies[0]
    assert not bot.sent_photos


def test_daily_limit_reached(monkeypatch):
    bot = _FakeBot()
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: True)
    monkeypatch.setattr(image_handler.db, "try_reserve_image_slot", lambda uid, max_per_day: False)
    image_handler.handle_image(bot, _FakeMessage("/image комета"), ALLOWED)
    assert len(bot.replies) == 1
    assert "лимит" in bot.replies[0].lower()
    assert not bot.sent_photos


def test_successful_generation_reserves_slot_before_calling_openai(monkeypatch):
    _patch_sync_thread(monkeypatch)
    bot = _FakeBot()
    reserved = []
    released = []
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: True)
    monkeypatch.setattr(
        image_handler.db,
        "try_reserve_image_slot",
        lambda uid, max_per_day: reserved.append(uid) or True,
    )
    monkeypatch.setattr(image_handler.db, "release_image_usage", lambda uid: released.append(uid))
    monkeypatch.setattr(image_handler, "generate_image", lambda prompt: b"image-bytes")

    _run_and_wait(bot, _FakeMessage("/image комета изо льда"))

    assert reserved == [42]
    assert released == []  # successful generation keeps the reserved slot
    assert len(bot.sent_photos) == 1
    assert bot.deleted  # transient status message was cleaned up


def test_content_policy_failure_releases_reserved_slot(monkeypatch):
    _patch_sync_thread(monkeypatch)
    bot = _FakeBot()
    released = []
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: True)
    monkeypatch.setattr(image_handler.db, "try_reserve_image_slot", lambda uid, max_per_day: True)
    monkeypatch.setattr(image_handler.db, "release_image_usage", lambda uid: released.append(uid))

    def _raise(prompt):
        raise ImageContentPolicyError("blocked")

    monkeypatch.setattr(image_handler, "generate_image", _raise)

    _run_and_wait(bot, _FakeMessage("/image запрещённый контент"))

    assert released == [42]
    assert not bot.sent_photos
    assert any("модерацией" in r for r in bot.replies)


def test_quota_exceeded_failure_releases_reserved_slot(monkeypatch, caplog):
    _patch_sync_thread(monkeypatch)
    bot = _FakeBot()
    released = []
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: True)
    monkeypatch.setattr(image_handler.db, "try_reserve_image_slot", lambda uid, max_per_day: True)
    monkeypatch.setattr(image_handler.db, "release_image_usage", lambda uid: released.append(uid))

    def _raise(prompt):
        raise ImageQuotaExceededError("no money")

    monkeypatch.setattr(image_handler, "generate_image", _raise)

    with caplog.at_level(logging.ERROR):
        _run_and_wait(bot, _FakeMessage("/image дорогой арт"))

    assert released == [42]
    assert not bot.sent_photos
    assert any("недоступен" in r for r in bot.replies)
    assert any("quota" in rec.message.lower() or "exceed" in rec.message.lower() for rec in caplog.records)


def test_generic_failure_releases_reserved_slot(monkeypatch):
    _patch_sync_thread(monkeypatch)
    bot = _FakeBot()
    released = []
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: True)
    monkeypatch.setattr(image_handler.db, "try_reserve_image_slot", lambda uid, max_per_day: True)
    monkeypatch.setattr(image_handler.db, "release_image_usage", lambda uid: released.append(uid))

    def _raise(prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(image_handler, "generate_image", _raise)

    _run_and_wait(bot, _FakeMessage("/image что-то"))

    assert released == [42]
    assert not bot.sent_photos
    assert any("Не удалось" in r for r in bot.replies)


def test_delivery_failure_after_success_does_not_release_slot(monkeypatch):
    _patch_sync_thread(monkeypatch)
    bot = _FakeBot()
    released = []
    monkeypatch.setattr(image_handler.cooldowns, "allowed", lambda uid: True)
    monkeypatch.setattr(image_handler.db, "try_reserve_image_slot", lambda uid, max_per_day: True)
    monkeypatch.setattr(image_handler.db, "release_image_usage", lambda uid: released.append(uid))
    monkeypatch.setattr(image_handler, "generate_image", lambda prompt: b"image-bytes")

    def _raise_send(*args, **kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(bot, "send_photo", _raise_send)

    _run_and_wait(bot, _FakeMessage("/image что-то"))

    assert released == []  # slot stays consumed — the attempt was still counted
    assert any("учтена в дневном лимите" in r for r in bot.replies)
