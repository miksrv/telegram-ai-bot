import core.prompts as prompts_mod
from core.prompts import (
    build_capabilities_line,
    build_general_system_prompt,
    build_proactive_prompt,
    build_proactive_reply_prompt,
    build_reply_only_system_prompt,
)

IDENTITY = "- Telegram ID: 123\n- First name: Test\n- Username: @testuser\n"
PROFILE = "Adaptive response behavior:\n- Be concise.\n\nInterests: astronomy\nNotes: test user"
CONTEXT = "User#123: что такое пульсар?\nTARS: Пульсар — это..."
MESSAGE = "Расскажи про чёрные дыры"


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


# --------------------------------------------------
# build_proactive_reply_prompt
# --------------------------------------------------


def test_proactive_reply_prompt_contains_target():
    result = build_proactive_reply_prompt(
        ["Алексей: привет"], "Мария", "Что за туманность видно сегодня вечером?", "2024-01-01 12:00 UTC"
    )
    assert "Мария" in result
    assert "Что за туманность видно сегодня вечером?" in result
    assert "Алексей: привет" in result


def test_proactive_reply_prompt_contains_reply_field():
    result = build_proactive_reply_prompt(["User: test"], "User", "test target", "2024-01-01 12:00 UTC")
    assert '"reply"' in result


def test_proactive_reply_prompt_contains_utc_time():
    utc = "2024-06-15 09:30 UTC"
    result = build_proactive_reply_prompt(["User: test"], "User", "test target", utc)
    assert utc in result


# --------------------------------------------------
# Self-identity / personalization — shared across conversational templates
# --------------------------------------------------


def test_general_system_prompt_contains_self_identity():
    result = build_general_system_prompt(IDENTITY, PROFILE)
    assert "ТАРС" in result and "TARS" in result
    assert "third-person" in result.lower()


def test_reply_only_system_prompt_contains_self_identity():
    result = build_reply_only_system_prompt(IDENTITY, PROFILE)
    assert "ТАРС" in result and "TARS" in result


def test_general_system_prompt_contains_personalization_rule():
    result = build_general_system_prompt(IDENTITY, PROFILE)
    assert "personalization" in result.lower()


def test_proactive_prompt_contains_self_identity():
    result = build_proactive_prompt(["User: test"], "2024-01-01 12:00 UTC")
    assert "ТАРС" in result and "TARS" in result


def test_proactive_reply_prompt_contains_self_identity():
    result = build_proactive_reply_prompt(["User: test"], "User", "test target", "2024-01-01 12:00 UTC")
    assert "ТАРС" in result and "TARS" in result


# --------------------------------------------------
# build_capabilities_line — dynamic, toggled by IMAGE_GEN_ENABLED and
# starmap-service availability
# --------------------------------------------------


def test_capabilities_line_mentions_image_command_when_enabled(monkeypatch):
    monkeypatch.setattr(prompts_mod, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr(prompts_mod, "is_starmap_online", lambda: False)
    result = build_capabilities_line()
    assert "/image" in result


def test_capabilities_line_omits_image_command_when_disabled(monkeypatch):
    monkeypatch.setattr(prompts_mod, "IMAGE_GEN_ENABLED", False)
    monkeypatch.setattr(prompts_mod, "is_starmap_online", lambda: False)
    result = build_capabilities_line()
    assert "/image" not in result
    assert "cannot" in result.lower()


def test_capabilities_line_includes_starmap_commands_when_online(monkeypatch):
    monkeypatch.setattr(prompts_mod, "IMAGE_GEN_ENABLED", False)
    monkeypatch.setattr(prompts_mod, "is_starmap_online", lambda: True)
    result = build_capabilities_line()
    assert "/sky" in result
    assert "/galaxy" in result


def test_capabilities_line_excludes_starmap_commands_when_offline(monkeypatch):
    monkeypatch.setattr(prompts_mod, "IMAGE_GEN_ENABLED", False)
    monkeypatch.setattr(prompts_mod, "is_starmap_online", lambda: False)
    result = build_capabilities_line()
    assert "/sky" not in result


def test_capabilities_line_always_lists_core_commands(monkeypatch):
    monkeypatch.setattr(prompts_mod, "IMAGE_GEN_ENABLED", False)
    monkeypatch.setattr(prompts_mod, "is_starmap_online", lambda: False)
    result = build_capabilities_line()
    for cmd in ("/weather", "/status", "/photo", "/help"):
        assert cmd in result


def test_general_system_prompt_includes_capabilities(monkeypatch):
    monkeypatch.setattr(prompts_mod, "IMAGE_GEN_ENABLED", True)
    monkeypatch.setattr(prompts_mod, "is_starmap_online", lambda: False)
    result = build_general_system_prompt(IDENTITY, PROFILE)
    assert "/image" in result
