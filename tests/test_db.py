from database.db import (
    get_display_names,
    get_image_usage_count,
    get_recent_user_messages,
    get_reply_candidate,
    get_user_profile,
    increment_image_usage,
    increment_message_count,
    mark_message_replied,
    release_image_usage,
    save_message,
    try_reserve_image_slot,
    update_user_facts,
    update_user_notes,
    update_user_profile,
)

# Use a high ID unlikely to collide with real data in local dev environments
_TEST_USER = 9_000_001
_IDENTITY = {"first_name": "CI", "last_name": "Test", "username": "ci_test"}


def _fresh_profile():
    """Return a clean profile, creating it if it doesn't exist."""
    return get_user_profile(_TEST_USER, _IDENTITY)


# --------------------------------------------------
# get_user_profile
# --------------------------------------------------


def test_profile_created_on_first_access():
    profile = _fresh_profile()
    assert isinstance(profile["message_count"], int)
    assert isinstance(profile["avg_offtopic"], float)
    assert isinstance(profile["avg_verbosity"], float)
    assert profile["first_name"] == "CI"


def test_profile_has_expected_keys():
    profile = _fresh_profile()
    expected = {
        "message_count",
        "avg_offtopic",
        "avg_provocation",
        "avg_spam",
        "avg_rudeness",
        "avg_verbosity",
        "interests",
        "notes",
        "facts",
        "first_name",
        "last_name",
        "username",
    }
    assert expected.issubset(profile.keys())


def test_fresh_profile_has_empty_facts():
    user = 9_000_401
    profile = get_user_profile(user, _IDENTITY)
    assert profile["facts"] == {}


# --------------------------------------------------
# increment_message_count
# --------------------------------------------------


def test_increment_message_count_increases_by_one():
    before = get_user_profile(_TEST_USER)["message_count"]
    increment_message_count(_TEST_USER)
    after = get_user_profile(_TEST_USER)["message_count"]
    assert after == before + 1


# --------------------------------------------------
# update_user_profile
# --------------------------------------------------


def test_update_profile_changes_averages():
    increment_message_count(_TEST_USER)  # ensure count > 0
    update_user_profile(
        _TEST_USER,
        {
            "offtopic": 1.0,
            "provocation": 0.0,
            "spam": 0.0,
            "rudeness": 0.0,
            "verbosity": 0.5,
            "interests": ["astronomy"],
        },
    )
    profile = get_user_profile(_TEST_USER)
    assert profile["avg_offtopic"] > 0.0
    assert "astronomy" in profile["interests"]


def test_interests_dedup_keeps_newest_and_survives_commas():
    user = 9_000_777
    get_user_profile(user, _IDENTITY)
    increment_message_count(user)
    base = {"offtopic": 0.0, "provocation": 0.0, "spam": 0.0, "rudeness": 0.0, "verbosity": 0.5}
    update_user_profile(user, {**base, "interests": ["Луна", "галактики, туманности"]})
    update_user_profile(user, {**base, "interests": ["Луна", "кометы"]})
    interests = get_user_profile(user)["interests"]
    # Comma inside an interest is preserved (JSON storage, not split).
    assert "галактики, туманности" in interests
    # Deduplicated — "Луна" appears once.
    assert interests.count("Луна") == 1
    # Freshest interest is retained.
    assert "кометы" in interests


# --------------------------------------------------
# update_user_notes
# --------------------------------------------------


def test_update_notes_replaces_value():
    update_user_notes(_TEST_USER, "Тестовый пользователь, интересуется астрофизикой")
    profile = get_user_profile(_TEST_USER)
    assert "астрофизикой" in profile["notes"]


def test_update_notes_fully_replaces():
    update_user_notes(_TEST_USER, "first notes")
    update_user_notes(_TEST_USER, "second notes")
    profile = get_user_profile(_TEST_USER)
    assert profile["notes"] == "second notes"
    assert "first" not in profile["notes"]


# --------------------------------------------------
# get_reply_candidate / mark_message_replied
# --------------------------------------------------

# Each test below uses its own chat ID to stay isolated from the others.


def test_reply_candidate_excludes_short_messages():
    chat_id = -9_000_101
    save_message(chat_id, _TEST_USER, 1, "CI", "ci_test", "два слова")
    candidate = get_reply_candidate(chat_id, min_word_count=6)
    assert candidate is None


def test_reply_candidate_returns_qualifying_message():
    chat_id = -9_000_102
    save_message(chat_id, _TEST_USER, 2, "CI", "ci_test", "это достаточно длинное сообщение для ответа бота")
    candidate = get_reply_candidate(chat_id, min_word_count=6)
    assert candidate is not None
    assert candidate["telegram_message_id"] == 2
    assert "длинное сообщение" in candidate["text"]


def test_marked_message_is_never_picked_again():
    chat_id = -9_000_103
    save_message(chat_id, _TEST_USER, 3, "CI", "ci_test", "это единственное достаточно длинное сообщение здесь")
    candidate = get_reply_candidate(chat_id, min_word_count=6)
    assert candidate is not None
    mark_message_replied(candidate["id"])
    assert get_reply_candidate(chat_id, min_word_count=6) is None


# --------------------------------------------------
# get_image_usage_count / increment_image_usage
# --------------------------------------------------


# Each test below uses its own user ID and/or a fixed fake "today" (via
# _today_utc patching) to stay isolated from the others and from reruns
# against the same on-disk SQLite file (counts are deltas, not absolute
# zero-based values, since a leftover row from a previous run is possible).


def test_image_usage_starts_at_zero_for_a_fresh_user():
    user = 9_000_201
    assert get_image_usage_count(user) == 0


def test_image_usage_increments():
    user = 9_000_202
    before = get_image_usage_count(user)
    increment_image_usage(user)
    assert get_image_usage_count(user) == before + 1
    increment_image_usage(user)
    increment_image_usage(user)
    assert get_image_usage_count(user) == before + 3


def test_image_usage_is_isolated_by_user():
    user_a = 9_000_203
    user_b = 9_000_204
    before_a = get_image_usage_count(user_a)
    before_b = get_image_usage_count(user_b)
    increment_image_usage(user_a)
    increment_image_usage(user_a)
    assert get_image_usage_count(user_a) == before_a + 2
    assert get_image_usage_count(user_b) == before_b


def test_image_usage_is_isolated_by_date(monkeypatch):
    import database.db as db_module

    user = 9_000_205
    monkeypatch.setattr(db_module, "_today_utc", lambda: "2000-01-01")
    before_day_one = get_image_usage_count(user)
    increment_image_usage(user)
    increment_image_usage(user)
    assert get_image_usage_count(user) == before_day_one + 2

    monkeypatch.setattr(db_module, "_today_utc", lambda: "2000-01-02")
    before_day_two = get_image_usage_count(user)
    # A distinct row per date: switching the fake "today" must not carry over
    # day one's count, which was just bumped to at least before_day_one + 2.
    assert before_day_two < before_day_one + 2
    increment_image_usage(user)
    assert get_image_usage_count(user) == before_day_two + 1


# --------------------------------------------------
# try_reserve_image_slot / release_image_usage
# --------------------------------------------------

# Each test below patches _today_utc to a fresh, random one-off token (not a
# real date — it's only ever used as an opaque DB key) so the (user_id,
# usage_date) row it touches is guaranteed brand new, both across tests in
# this run and across reruns against the same on-disk SQLite file. That makes
# plain zero-based assertions safe here, unlike the fixed-date tests above.


def _fresh_fake_today(monkeypatch):
    import uuid

    import database.db as db_module

    token = f"test-{uuid.uuid4()}"
    monkeypatch.setattr(db_module, "_today_utc", lambda: token)


def test_reserve_slot_succeeds_under_the_cap(monkeypatch):
    _fresh_fake_today(monkeypatch)
    user = 9_000_301
    assert try_reserve_image_slot(user, max_per_day=3) is True
    assert get_image_usage_count(user) == 1
    assert try_reserve_image_slot(user, max_per_day=3) is True
    assert get_image_usage_count(user) == 2


def test_reserve_slot_fails_once_cap_is_reached(monkeypatch):
    """Sequential proof of the atomic SQL condition: once count == max_per_day,
    a further reservation attempt must not be granted and must not increment
    the stored count further. This is the boundary case the reviewer asked
    to be exercised directly, without needing a real multi-threaded race."""
    _fresh_fake_today(monkeypatch)
    user = 9_000_302
    max_per_day = 2
    assert try_reserve_image_slot(user, max_per_day) is True
    assert try_reserve_image_slot(user, max_per_day) is True
    assert get_image_usage_count(user) == max_per_day

    # At the cap: the next call must be rejected and leave the count untouched.
    assert try_reserve_image_slot(user, max_per_day) is False
    assert get_image_usage_count(user) == max_per_day


def test_release_image_usage_decrements_a_reserved_slot(monkeypatch):
    _fresh_fake_today(monkeypatch)
    user = 9_000_303
    assert try_reserve_image_slot(user, max_per_day=5) is True
    assert get_image_usage_count(user) == 1

    release_image_usage(user)
    assert get_image_usage_count(user) == 0


def test_release_image_usage_does_not_go_negative(monkeypatch):
    _fresh_fake_today(monkeypatch)
    user = 9_000_304
    assert get_image_usage_count(user) == 0

    release_image_usage(user)  # no row yet / already at zero
    assert get_image_usage_count(user) == 0


# --------------------------------------------------
# update_user_facts — structured facts merge/validation (option C)
# --------------------------------------------------


def test_update_user_facts_stores_new_keys():
    user = 9_000_501
    get_user_profile(user, _IDENTITY)
    update_user_facts(user, {"name": "Иван", "experience": "beginner"})
    facts = get_user_profile(user)["facts"]
    assert facts == {"name": "Иван", "experience": "beginner"}


def test_update_user_facts_merges_without_losing_unrelated_keys():
    user = 9_000_502
    get_user_profile(user, _IDENTITY)
    update_user_facts(user, {"name": "Иван", "location": "Москва"})
    update_user_facts(user, {"experience": "advanced"})
    facts = get_user_profile(user)["facts"]
    assert facts == {"name": "Иван", "location": "Москва", "experience": "advanced"}


def test_update_user_facts_null_value_deletes_key():
    user = 9_000_503
    get_user_profile(user, _IDENTITY)
    update_user_facts(user, {"name": "Иван", "location": "Москва"})
    update_user_facts(user, {"location": None})
    facts = get_user_profile(user)["facts"]
    assert facts == {"name": "Иван"}


def test_update_user_facts_ignores_unknown_keys():
    user = 9_000_504
    get_user_profile(user, _IDENTITY)
    update_user_facts(user, {"name": "Иван", "unexpected_key": "junk"})
    facts = get_user_profile(user)["facts"]
    assert facts == {"name": "Иван"}
    assert "unexpected_key" not in facts


def test_update_user_facts_ignores_bad_value_type():
    user = 9_000_505
    get_user_profile(user, _IDENTITY)
    update_user_facts(user, {"name": {"nested": "dict"}})
    facts = get_user_profile(user)["facts"]
    assert facts == {}


# --------------------------------------------------
# get_display_names — batched lookup for conversation-history labeling
# --------------------------------------------------


def test_get_display_names_prefers_first_name():
    user = 9_000_601
    get_user_profile(user, {"first_name": "Иван", "last_name": "", "username": "ivan"})
    names = get_display_names([user])
    assert names[user] == "Иван"


def test_get_display_names_falls_back_to_username():
    user = 9_000_602
    get_user_profile(user, {"first_name": "", "last_name": "", "username": "nick"})
    names = get_display_names([user])
    assert names[user] == "@nick"


def test_get_display_names_unknown_user_absent_from_result():
    names = get_display_names([9_999_999_999])
    assert 9_999_999_999 not in names


def test_get_display_names_empty_input_returns_empty_dict():
    assert get_display_names([]) == {}


# --------------------------------------------------
# get_recent_user_messages — DB supplement for the per-user earlier-messages
# background block
# --------------------------------------------------


def _unique_chat_id() -> int:
    """A chat_id guaranteed not to collide with a previous run's leftover rows
    in the on-disk SQLite file (unlike a fixed constant, see the image-usage
    tests above for the same concern with usage_date)."""
    import uuid

    return -(uuid.uuid4().int % 1_000_000_000)


def test_get_recent_user_messages_filters_by_user_and_orders_oldest_first():
    chat_id = _unique_chat_id()
    user_a, user_b = 9_000_611, 9_000_612
    save_message(chat_id, user_a, 1, "A", "a", "первое сообщение")
    save_message(chat_id, user_b, 2, "B", "b", "чужое сообщение")
    save_message(chat_id, user_a, 3, "A", "a", "второе сообщение")

    messages = get_recent_user_messages(chat_id, user_a, limit=5)
    assert messages == ["первое сообщение", "второе сообщение"]


def test_get_recent_user_messages_respects_limit():
    chat_id = _unique_chat_id()
    user = 9_000_613
    for i in range(5):
        save_message(chat_id, user, i, "A", "a", f"сообщение {i}")

    messages = get_recent_user_messages(chat_id, user, limit=2)
    assert len(messages) == 2
    assert messages == ["сообщение 3", "сообщение 4"]


# --------------------------------------------------
# Migration idempotency — the "facts" column on pre-existing databases
# --------------------------------------------------


def test_facts_column_migration_is_idempotent(tmp_path, monkeypatch):
    """A DB created before the "facts" column existed must gain it on the next
    startup, and running the migration twice must not raise."""
    import sqlite3

    import database.db as db_module

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE user_profile (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            message_count INTEGER DEFAULT 0,
            avg_offtopic REAL DEFAULT 0.0,
            avg_provocation REAL DEFAULT 0.0,
            avg_spam REAL DEFAULT 0.0,
            avg_rudeness REAL DEFAULT 0.0,
            avg_verbosity REAL DEFAULT 0.5,
            interests TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            last_updated INTEGER
        )
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))

    db_module._init_db()
    db_module._init_db()  # second run must be a no-op, not raise

    conn = sqlite3.connect(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profile)")}
    conn.close()
    assert "facts" in cols
