from database.db import get_db_stats, get_user_profile, increment_message_count, save_message
from handlers.help_handler import HELP_TEXT
from handlers.stats_handler import format_stats


def test_get_db_stats_has_expected_shape():
    stats = get_db_stats()
    expected = {
        "users",
        "interactions",
        "stored_messages",
        "observed_chats",
        "oldest_message_ts",
        "newest_message_ts",
    }
    assert expected == set(stats.keys())
    assert all(isinstance(stats[k], int) for k in stats)


def test_get_db_stats_counts_reflect_activity():
    user = 9_100_001
    get_user_profile(user, {"first_name": "CI"})
    before = get_db_stats()
    increment_message_count(user)
    save_message(-100_999, user, 42, "CI", "ci", "наблюдаю Юпитер сегодня вечером")
    after = get_db_stats()
    assert after["interactions"] >= before["interactions"] + 1
    assert after["stored_messages"] >= before["stored_messages"] + 1
    assert after["newest_message_ts"] > 0


def test_format_stats_is_russian_and_includes_numbers():
    stats = {
        "users": 7,
        "interactions": 123,
        "stored_messages": 45,
        "observed_chats": 2,
        "oldest_message_ts": 0,
        "newest_message_ts": 0,
    }
    text = format_stats(stats)
    assert "Статистика TARS" in text
    assert "Пользователей: 7" in text
    assert "123" in text
    # No timestamps -> dashes, not a crash
    assert "—" in text


def test_help_text_lists_all_commands():
    for cmd in ("/help", "/weather", "/status", "/photo", "/stats"):
        assert cmd in HELP_TEXT
    assert "astronom_chat" in HELP_TEXT
