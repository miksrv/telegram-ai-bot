from core.memory import MemoryManager


def make_mm() -> MemoryManager:
    """Fresh MemoryManager with empty in-RAM storage (DB may exist but is empty in CI)."""
    mm = MemoryManager()
    mm.chat_storage.clear()
    mm.user_storage.clear()
    return mm


# --------------------------------------------------
# get_chat_context / get_chat_history
# --------------------------------------------------

def test_empty_chat_context_returns_empty_string():
    mm = make_mm()
    assert mm.get_chat_context(999) == ""


def test_empty_chat_history_returns_empty_list():
    mm = make_mm()
    assert mm.get_chat_history(999) == []


def test_add_and_get_chat_context_contains_messages():
    mm = make_mm()
    mm.add_chat_memory(chat_id=1, user_id=100, user_msg="hello", bot_reply="hi there")
    ctx = mm.get_chat_context(1)
    assert "hello" in ctx
    assert "hi there" in ctx


def test_chat_history_returns_raw_tuples():
    mm = make_mm()
    mm.add_chat_memory(chat_id=1, user_id=100, user_msg="hello", bot_reply="hi")
    history = mm.get_chat_history(1)
    assert len(history) == 2
    assert history[0] == (100, "user", "hello")
    assert history[1] == (100, "assistant", "hi")


def test_chat_history_multiple_turns():
    mm = make_mm()
    mm.add_chat_memory(1, 100, "msg1", "reply1")
    mm.add_chat_memory(1, 101, "msg2", "reply2")
    history = mm.get_chat_history(1)
    assert len(history) == 4
    assert history[0] == (100, "user", "msg1")
    assert history[2] == (101, "user", "msg2")


# --------------------------------------------------
# last_sender_is_bot
# --------------------------------------------------

def test_last_sender_is_bot_after_reply():
    mm = make_mm()
    mm.add_chat_memory(1, 100, "hello", "hi")
    assert mm.last_sender_is_bot(1) is True


def test_last_sender_not_bot_on_unknown_chat():
    mm = make_mm()
    assert mm.last_sender_is_bot(999) is False


# --------------------------------------------------
# get_stats
# --------------------------------------------------

def test_stats_empty_chat():
    mm = make_mm()
    used, total = mm.get_stats(999)
    assert used == 0
    assert total == 0


def test_stats_counts_entries():
    mm = make_mm()
    mm.add_chat_memory(1, 100, "m1", "r1")
    mm.add_chat_memory(1, 100, "m2", "r2")
    used, total = mm.get_stats(1)
    assert total == 4
    assert used <= total


# --------------------------------------------------
# size
# --------------------------------------------------

def test_size_tracks_active_chats():
    mm = make_mm()
    mm.add_chat_memory(10, 1, "a", "b")
    mm.add_chat_memory(20, 1, "c", "d")
    assert mm.size()["chats"] == 2
