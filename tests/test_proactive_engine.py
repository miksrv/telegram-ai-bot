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
    engine.record_reply(chat_id)  # consumes the default daily budget of 1

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


def test_record_reply_consumes_budget_and_parks_next_attempt():
    engine = make_engine()
    chat_id = -5
    engine._init_chat(chat_id)
    day_reset_at = engine._state[chat_id]["day_reset_at"]

    engine.record_reply(chat_id)

    s = engine._state[chat_id]
    assert s["reply_count_today"] == 1
    assert s["next_reply_attempt_at"] == day_reset_at
    assert s["last_posted_at"] > 0


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
