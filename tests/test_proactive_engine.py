from core.proactive_engine import ProactiveEngine


def make_engine() -> ProactiveEngine:
    return ProactiveEngine()


# --------------------------------------------------
# should_post_reply / record_reply / reschedule_reply_failed
# --------------------------------------------------


def test_should_post_reply_none_when_no_candidate(monkeypatch):
    from core import proactive_engine as pe_mod

    engine = make_engine()
    chat_id = -1

    monkeypatch.setattr(pe_mod, "get_recent_messages", lambda *a, **k: [{"text": "x"}] * 10)
    monkeypatch.setattr(pe_mod, "get_reply_candidate", lambda *a, **k: None)
    # Force the reply window open immediately for this test.
    engine._init_chat(chat_id)
    engine._state[chat_id]["next_reply_attempt_at"] = 0

    assert engine.should_post_reply(chat_id) is None


def test_should_post_reply_returns_candidate_when_eligible(monkeypatch):
    from core import proactive_engine as pe_mod

    engine = make_engine()
    chat_id = -2
    candidate = {"id": 1, "telegram_message_id": 42, "first_name": "Иван", "username": "ivan", "text": "..."}

    monkeypatch.setattr(pe_mod, "get_recent_messages", lambda *a, **k: [{"text": "x"}] * 10)
    monkeypatch.setattr(pe_mod, "get_reply_candidate", lambda *a, **k: candidate)
    engine._init_chat(chat_id)
    engine._state[chat_id]["next_reply_attempt_at"] = 0

    assert engine.should_post_reply(chat_id) == candidate


def test_should_post_reply_respects_daily_cap(monkeypatch):
    from core import proactive_engine as pe_mod

    engine = make_engine()
    chat_id = -3

    monkeypatch.setattr(pe_mod, "get_recent_messages", lambda *a, **k: [{"text": "x"}] * 10)
    monkeypatch.setattr(pe_mod, "get_reply_candidate", lambda *a, **k: {"id": 1})
    engine._init_chat(chat_id)
    engine._state[chat_id]["next_reply_attempt_at"] = 0
    monkeypatch.setattr(pe_mod, "PROACTIVE_REPLY_MAX_PER_DAY", 1)
    engine.record_reply(chat_id)  # consumes the whole daily budget

    assert engine.should_post_reply(chat_id) is None


def test_should_post_reply_respects_shared_min_gap(monkeypatch):
    """A recent general post blocks the reply too — both share PROACTIVE_MIN_GAP_SECONDS."""
    import time

    from core import proactive_engine as pe_mod

    engine = make_engine()
    chat_id = -4

    monkeypatch.setattr(pe_mod, "get_recent_messages", lambda *a, **k: [{"text": "x"}] * 10)
    monkeypatch.setattr(pe_mod, "get_reply_candidate", lambda *a, **k: {"id": 1})
    engine._init_chat(chat_id)
    engine._state[chat_id]["next_reply_attempt_at"] = 0
    engine._state[chat_id]["last_posted_at"] = time.time()

    assert engine.should_post_reply(chat_id) is None


def test_record_reply_parks_at_day_boundary_when_cap_reached(monkeypatch):
    from core import proactive_engine as pe_mod

    monkeypatch.setattr(pe_mod, "PROACTIVE_REPLY_MAX_PER_DAY", 1)
    engine = make_engine()
    chat_id = -5
    engine._init_chat(chat_id)
    day_reset_at = engine._state[chat_id]["day_reset_at"]

    engine.record_reply(chat_id)

    s = engine._state[chat_id]
    assert s["reply_count_today"] == 1
    assert s["next_reply_attempt_at"] == day_reset_at
    assert s["last_posted_at"] > 0


def test_record_reply_schedules_later_today_while_budget_remains(monkeypatch):
    import time

    from core import proactive_engine as pe_mod

    monkeypatch.setattr(pe_mod, "PROACTIVE_REPLY_MAX_PER_DAY", 3)
    monkeypatch.setattr(pe_mod, "PROACTIVE_NEXT_MIN_SECONDS", 100)
    monkeypatch.setattr(pe_mod, "PROACTIVE_NEXT_MAX_SECONDS", 200)
    engine = make_engine()
    chat_id = -50
    engine._init_chat(chat_id)
    engine._state[chat_id]["day_reset_at"] = time.time() + 86400

    for expected_count in (1, 2):
        before = time.time()
        engine.record_reply(chat_id)
        s = engine._state[chat_id]
        assert s["reply_count_today"] == expected_count
        assert before + 100 <= s["next_reply_attempt_at"] <= time.time() + 200
        assert s["next_reply_attempt_at"] < s["day_reset_at"]

    engine.record_reply(chat_id)  # third reply hits the cap
    s = engine._state[chat_id]
    assert s["next_reply_attempt_at"] == s["day_reset_at"]


def test_reschedule_reply_failed_does_not_consume_budget():
    engine = make_engine()
    chat_id = -6
    engine._init_chat(chat_id)

    engine.reschedule_reply_failed(chat_id)

    s = engine._state[chat_id]
    assert s["reply_count_today"] == 0


def test_day_reset_clears_reply_count_and_reschedules(monkeypatch):
    import time

    engine = make_engine()
    chat_id = -7
    engine._init_chat(chat_id)
    engine._state[chat_id]["reply_count_today"] = 1
    engine._state[chat_id]["day_reset_at"] = time.time() - 1  # already in the past

    engine._reset_day_if_needed(chat_id)

    s = engine._state[chat_id]
    assert s["reply_count_today"] == 0
    assert s["next_reply_attempt_at"] > time.time()


# --------------------------------------------------
# "bot spoke last" guard (general posts and direct replies)
# --------------------------------------------------


def _open_engine(monkeypatch, chat_id, latest_user_ts, bot_at):
    """Engine whose every other post/reply condition is satisfied."""
    from core import proactive_engine as pe_mod

    engine = make_engine()
    monkeypatch.setattr(pe_mod, "get_recent_messages", lambda *a, **k: [{"text": "x"}] * 10)
    monkeypatch.setattr(pe_mod, "get_latest_message_timestamp", lambda *a, **k: latest_user_ts)
    monkeypatch.setattr(pe_mod, "get_reply_candidate", lambda *a, **k: {"id": 1})
    monkeypatch.setattr(pe_mod.memory, "last_bot_message_at", lambda cid: bot_at)
    engine._init_chat(chat_id)
    engine._state[chat_id]["next_attempt_at"] = 0
    engine._state[chat_id]["next_reply_attempt_at"] = 0
    return engine


def test_should_post_blocked_when_bot_spoke_last(monkeypatch):
    engine = _open_engine(monkeypatch, -60, latest_user_ts=1000, bot_at=1500)
    assert engine.should_post(-60) is False


def test_should_post_allowed_when_user_wrote_after_bot(monkeypatch):
    engine = _open_engine(monkeypatch, -61, latest_user_ts=2000, bot_at=1500)
    assert engine.should_post(-61) is True


def test_should_post_allowed_when_bot_time_unknown(monkeypatch):
    """After a restart the bot's last-message time is unknown (0): do not block."""
    engine = _open_engine(monkeypatch, -62, latest_user_ts=2000, bot_at=0)
    assert engine.should_post(-62) is True


def test_should_post_reply_blocked_when_bot_spoke_last(monkeypatch):
    engine = _open_engine(monkeypatch, -63, latest_user_ts=1000, bot_at=1500)
    assert engine.should_post_reply(-63) is None


def test_should_post_reply_allowed_when_user_wrote_after_bot(monkeypatch):
    engine = _open_engine(monkeypatch, -64, latest_user_ts=2000, bot_at=1500)
    assert engine.should_post_reply(-64) == {"id": 1}
