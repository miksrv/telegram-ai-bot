from database.db import (
    get_image_usage_count,
    get_reply_candidate,
    get_user_profile,
    increment_image_usage,
    increment_message_count,
    mark_message_replied,
    save_message,
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
        "first_name",
        "last_name",
        "username",
    }
    assert expected.issubset(profile.keys())


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
