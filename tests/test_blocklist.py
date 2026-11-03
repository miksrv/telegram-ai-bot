from types import SimpleNamespace

import pytest

from config.settings import parse_chat_ids
from database import db
from database.db import get_reply_candidate, save_message
from handlers import message_handler
from utils import blocklist


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Isolated SQLite file so reruns never see rows left by earlier runs (or the real data/ DB)."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db._init_db()


def _msg(user_id):
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id))


def test_blocked_user_detected(monkeypatch):
    monkeypatch.setattr(blocklist, "BLOCKED_USER_IDS", {111})
    assert blocklist.is_blocked_user(_msg(111)) is True


def test_other_user_not_blocked(monkeypatch):
    monkeypatch.setattr(blocklist, "BLOCKED_USER_IDS", {111})
    assert blocklist.is_blocked_user(_msg(222)) is False


def test_empty_blocklist_blocks_nobody(monkeypatch):
    monkeypatch.setattr(blocklist, "BLOCKED_USER_IDS", set())
    assert blocklist.is_blocked_user(_msg(111)) is False


@pytest.mark.parametrize("message", [SimpleNamespace(from_user=None), SimpleNamespace()])
def test_message_without_sender_is_not_blocked(monkeypatch, message):
    monkeypatch.setattr(blocklist, "BLOCKED_USER_IDS", {111})
    assert blocklist.is_blocked_user(message) is False


def test_blocked_ids_parse_like_other_id_lists():
    assert parse_chat_ids("1, 2,,3") == {1, 2, 3}
    assert parse_chat_ids("") == set()


def test_reply_candidate_skips_blocked_user(temp_db, monkeypatch):
    chat_id = -9_000_201
    save_message(chat_id, 9_000_011, 1, "Bad", "bad", "это достаточно длинное сообщение от заблокированного")
    save_message(chat_id, 9_000_012, 2, "Ok", "ok", "это достаточно длинное сообщение от обычного юзера")
    monkeypatch.setattr(db, "BLOCKED_USER_IDS", {9_000_011})
    for _ in range(10):
        candidate = get_reply_candidate(chat_id, min_word_count=6)
        assert candidate is not None
        assert candidate["telegram_message_id"] == 2


def test_reply_candidate_none_when_only_blocked_user(temp_db, monkeypatch):
    chat_id = -9_000_202
    save_message(chat_id, 9_000_013, 1, "Bad", "bad", "это достаточно длинное сообщение от заблокированного")
    monkeypatch.setattr(db, "BLOCKED_USER_IDS", {9_000_013})
    assert get_reply_candidate(chat_id, min_word_count=6) is None


def test_malformed_blocked_ids_fail_loudly():
    with pytest.raises(RuntimeError, match="BLOCKED_USER_IDS"):
        parse_chat_ids("111,abc", "BLOCKED_USER_IDS", strict=True)


def test_malformed_lenient_list_still_returns_empty():
    assert parse_chat_ids("111,abc", "ADMIN_IDS") == set()


def test_recent_messages_skip_blocked_user(temp_db, monkeypatch):
    chat_id = -9_000_203
    save_message(chat_id, 9_000_021, 1, "Bad", "bad", "сообщение заблокированного")
    save_message(chat_id, 9_000_022, 2, "Ok", "ok", "сообщение обычного")
    monkeypatch.setattr(db, "BLOCKED_USER_IDS", {9_000_021})
    assert [m["text"] for m in db.get_recent_messages(chat_id, 10)] == ["сообщение обычного"]
    assert db.get_recent_user_messages(chat_id, 9_000_021, 10) == []
    assert db.get_recent_user_messages(chat_id, 9_000_022, 10) == ["сообщение обычного"]


def test_quoted_text_dropped_for_blocked_author(monkeypatch):
    monkeypatch.setattr(message_handler, "BLOCKED_USER_IDS", {111})
    quoted = SimpleNamespace(from_user=SimpleNamespace(id=111), text="секрет", caption=None)
    assert message_handler._quoted_text(quoted) is None


def test_quoted_text_kept_for_other_author(monkeypatch):
    monkeypatch.setattr(message_handler, "BLOCKED_USER_IDS", {111})
    quoted = SimpleNamespace(from_user=SimpleNamespace(id=222), text="привет", caption=None)
    assert message_handler._quoted_text(quoted) == "привет"
