from core.memory import MemoryManager


def make_mm() -> MemoryManager:
    """Fresh MemoryManager with empty in-RAM storage (DB may exist but is empty in CI)."""
    mm = MemoryManager()
    mm.chat_storage.clear()
    mm._last_bot_at.clear()
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
# add_bot_message (proactive posts)
# --------------------------------------------------


def test_add_bot_message_records_standalone_assistant_turn():
    mm = make_mm()
    mm.add_bot_message(1, "spontaneous thought")
    history = mm.get_chat_history(1)
    assert history == [(0, "assistant", "spontaneous thought")]
    assert mm.last_sender_is_bot(1) is True


def test_add_bot_message_then_user_reply_keeps_both():
    mm = make_mm()
    mm.add_bot_message(1, "proactive post")
    mm.add_chat_memory(1, 100, "user reply", "bot answer")
    history = mm.get_chat_history(1)
    assert history[0] == (0, "assistant", "proactive post")
    assert history[1] == (100, "user", "user reply")
    assert history[2] == (100, "assistant", "bot answer")


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


# --------------------------------------------------
# last_bot_message_at
# --------------------------------------------------


def test_last_bot_message_at_unknown_chat_is_zero():
    assert make_mm().last_bot_message_at(999) == 0


def test_last_bot_message_at_set_by_reply_and_proactive_post():
    mm = make_mm()
    mm.add_chat_memory(1, 100, "hello", "hi")
    assert mm.last_bot_message_at(1) > 0
    mm.add_bot_message(2, "post")
    assert mm.last_bot_message_at(2) > 0


def test_last_bot_message_at_seeded_from_restored_history(monkeypatch):
    """After a restart the guard must still know the bot spoke last (persisted history)."""
    import core.memory as memory_mod

    monkeypatch.setattr(memory_mod, "_persona_changed", lambda: False)
    monkeypatch.setattr(
        memory_mod,
        "load_memory",
        lambda: {
            1: {"last_access": 1000.0, "history": [(5, "user", "q"), (5, "assistant", "a")]},
            2: {"last_access": 2000.0, "history": [(0, "assistant", "post"), (7, "user", "q")]},
            3: {"last_access": 3000.0, "history": []},
        },
    )
    mm = MemoryManager()
    assert mm.last_bot_message_at(1) == 1000.0
    assert mm.last_bot_message_at(2) == 0
    assert mm.last_bot_message_at(3) == 0


def test_persona_switch_drops_history_but_keeps_bot_time(monkeypatch):
    import core.memory as memory_mod

    monkeypatch.setattr(memory_mod, "_persona_changed", lambda: True)
    monkeypatch.setattr(
        memory_mod,
        "load_memory",
        lambda: {1: {"last_access": 1000.0, "history": [(5, "user", "q"), (5, "assistant", "a")]}},
    )
    mm = MemoryManager()
    assert mm.get_chat_history(1) == []
    assert mm.last_bot_message_at(1) == 1000.0


def test_persona_marker_missing_counts_as_same_persona(tmp_path):
    import core.memory as memory_mod

    marker = str(tmp_path / "sub" / "active_persona")
    assert memory_mod._persona_changed(marker) is False
    memory_mod._record_persona(marker)
    assert memory_mod._persona_changed(marker) is False
    with open(marker, "w", encoding="utf-8") as f:
        f.write("someone-else")
    assert memory_mod._persona_changed(marker) is True


def test_flush_records_the_persona_with_the_history(monkeypatch):
    import core.memory as memory_mod

    calls = []
    monkeypatch.setattr(memory_mod, "load_memory", dict)
    monkeypatch.setattr(memory_mod, "flush_memory", lambda storage: calls.append("history"))
    monkeypatch.setattr(memory_mod, "_record_persona", lambda: calls.append("marker"))
    MemoryManager().flush()
    assert calls == ["history", "marker"]
