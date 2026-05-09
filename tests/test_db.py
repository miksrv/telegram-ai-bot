from database.db import (
    get_user_profile,
    increment_message_count,
    update_user_profile,
    update_user_notes,
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
    expected = {"message_count", "avg_offtopic", "avg_provocation",
                "avg_spam", "avg_rudeness", "avg_verbosity",
                "interests", "notes", "first_name", "last_name", "username"}
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
    update_user_profile(_TEST_USER, {
        "offtopic": 1.0,
        "provocation": 0.0,
        "spam": 0.0,
        "rudeness": 0.0,
        "verbosity": 0.5,
        "interests": ["astronomy"],
    })
    profile = get_user_profile(_TEST_USER)
    assert profile["avg_offtopic"] > 0.0
    assert "astronomy" in profile["interests"]


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
