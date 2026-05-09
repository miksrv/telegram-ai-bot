from core.prompts import (
    build_general_prompt,
    build_general_system_prompt,
    build_proactive_prompt,
    build_reply_only_prompt,
    build_reply_only_system_prompt,
)

IDENTITY = "- Telegram ID: 123\n- First name: Test\n- Username: @testuser\n"
PROFILE = "Adaptive response behavior:\n- Be concise.\n\nInterests: astronomy\nNotes: test user"
CONTEXT = "User#123: что такое пульсар?\nTARS: Пульсар — это..."
MESSAGE = "Расскажи про чёрные дыры"


# --------------------------------------------------
# build_general_prompt (with profile_update + notes)
# --------------------------------------------------


def test_general_prompt_contains_reply_field():
    result = build_general_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert '"reply"' in result


def test_general_prompt_contains_profile_update():
    result = build_general_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert '"profile_update"' in result


def test_general_prompt_contains_notes():
    result = build_general_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert '"notes"' in result


def test_general_prompt_contains_message():
    result = build_general_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert MESSAGE in result


def test_general_prompt_contains_context():
    result = build_general_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert CONTEXT in result


# --------------------------------------------------
# build_reply_only_prompt (reply only, no profile fields)
# --------------------------------------------------


def test_reply_only_prompt_contains_reply_field():
    result = build_reply_only_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert '"reply"' in result


def test_reply_only_prompt_no_profile_update():
    result = build_reply_only_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert '"profile_update"' not in result


def test_reply_only_prompt_no_notes():
    result = build_reply_only_prompt(CONTEXT, IDENTITY, PROFILE, MESSAGE)
    assert '"notes"' not in result


# --------------------------------------------------
# build_general_system_prompt (messages-array path, no context/message)
# --------------------------------------------------


def test_general_system_prompt_has_profile_update():
    result = build_general_system_prompt(IDENTITY, PROFILE)
    assert '"profile_update"' in result


def test_general_system_prompt_does_not_contain_context():
    result = build_general_system_prompt(IDENTITY, PROFILE)
    assert CONTEXT not in result


def test_general_system_prompt_does_not_contain_message():
    result = build_general_system_prompt(IDENTITY, PROFILE)
    assert MESSAGE not in result


# --------------------------------------------------
# build_reply_only_system_prompt
# --------------------------------------------------


def test_reply_only_system_prompt_no_profile_update():
    result = build_reply_only_system_prompt(IDENTITY, PROFILE)
    assert '"profile_update"' not in result


def test_reply_only_system_prompt_has_reply():
    result = build_reply_only_system_prompt(IDENTITY, PROFILE)
    assert '"reply"' in result


# --------------------------------------------------
# build_proactive_prompt
# --------------------------------------------------


def test_proactive_prompt_contains_context_lines():
    lines = ["Алексей: привет", "Мария: что нового в астрономии?"]
    result = build_proactive_prompt(lines, "2024-01-01 12:00 UTC")
    assert "Алексей: привет" in result
    assert "Мария: что нового" in result


def test_proactive_prompt_contains_reply_field():
    result = build_proactive_prompt(["User: test"], "2024-01-01 12:00 UTC")
    assert '"reply"' in result


def test_proactive_prompt_contains_utc_time():
    utc = "2024-06-15 09:30 UTC"
    result = build_proactive_prompt(["User: test"], utc)
    assert utc in result


def test_proactive_prompt_context_size_matches():
    lines = ["a", "b", "c"]
    result = build_proactive_prompt(lines, "2024-01-01 00:00 UTC")
    assert "3" in result  # context_size=3 appears in the prompt
