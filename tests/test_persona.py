import pytest

import core.prompts as prompts_mod
from config.settings import list_personas
from core.persona import load_persona, parse_persona
from core.prompts import build_general_system_prompt, build_proactive_prompt, build_proactive_reply_prompt

VALID = """name: Бот
self_names: Бот, Ботик*
triggers: Бот, Ботяра
---
comment line, ignored
## identity
You are a bot {with braces}.
## style
- Be brief.
## humor
No jokes.
## proactive_character
Stay a bot.
"""


def test_parse_persona_reads_header_and_sections():
    p = parse_persona("bot", VALID)
    assert p.name == "Бот"
    assert p.self_names == ("Бот", "Ботик*")
    assert p.triggers == ("бот", "ботяра")
    assert p.identity == "You are a bot {with braces}."
    assert p.style == "- Be brief."


def test_parse_persona_accepts_crlf_and_bom():
    p = parse_persona("bot", "\ufeff" + VALID.replace("\n", "\r\n"))
    assert p.name == "Бот"
    assert p.style == "- Be brief."
    assert "\r" not in p.identity


def test_parse_persona_rejects_missing_separator():
    with pytest.raises(ValueError):
        parse_persona("bad", "name: x\n## identity\nhi\n")


def test_parse_persona_rejects_missing_section():
    with pytest.raises(ValueError):
        parse_persona("bad", VALID.replace("## humor\nNo jokes.\n", ""))


def test_all_self_names_always_include_tars_without_duplicates():
    names = parse_persona("bot", VALID).all_self_names()
    assert names[:2] == ["Бот", "Ботик*"]
    assert {"ТАРС", "TARS", "Тарс*"} <= set(names)
    tars = load_persona("tars").all_self_names()
    assert tars == ["ТАРС", "TARS", "Тарс*"]


def test_shipped_personas_load():
    keys = list_personas()
    assert {"tars", "peasant"} <= set(keys)
    for key in keys:
        p = load_persona(key)
        assert p.name and p.identity and p.style


def test_peasant_declares_its_trigger():
    assert "микул" in load_persona("peasant").triggers


def test_active_persona_triggers_are_registered():
    from utils.triggers import TRIGGERS, is_calling_tars

    assert {"тарс", "tars"} <= TRIGGERS
    assert is_calling_tars("Привет, ТАРС")


def test_prompts_use_persona_text_and_survive_braces(monkeypatch):
    monkeypatch.setattr(prompts_mod, "persona", parse_persona("bot", VALID))
    general = build_general_system_prompt("id", "profile")
    assert "You are a bot {with braces}." in general
    assert "- Be brief." in general
    assert "No jokes." in general
    assert '"Бот"/"Ботик*"/"ТАРС"/"TARS"/"Тарс*"' in general
    assert "Stay a bot." in build_proactive_prompt(["a"], "t")
    assert "Stay a bot." in build_proactive_reply_prompt(["a"], "u", "x", "t")


def test_tars_persona_keeps_original_character(monkeypatch):
    monkeypatch.setattr(prompts_mod, "persona", load_persona("tars"))
    general = build_general_system_prompt("id", "profile")
    assert 'You are TARS, an autonomous robot from the movie "Interstellar".' in general
    assert "calm and direct in tone" in general
    assert '"ТАРС"/"TARS"/"Тарс*"' in general
    assert "dry, precise, slightly ironic" in build_proactive_prompt(["a"], "t")


def test_peasant_prompt_names_both_identities(monkeypatch):
    monkeypatch.setattr(prompts_mod, "persona", load_persona("peasant"))
    general = build_general_system_prompt("id", "profile")
    assert "Микула" in general and "TARS" in general
    assert "JSON" in general


def test_reminder_section_is_optional():
    assert parse_persona("bot", VALID).reminder == ""
    p = parse_persona("bot", VALID + "## reminder\nStay a bot, always.\n")
    assert p.reminder == "Stay a bot, always."


def test_persona_reminder_is_sent_right_after_the_user_turn(monkeypatch):
    import core.brain as brain_mod

    history = [(5, "user", "q"), (5, "assistant", "old voice")]
    monkeypatch.setattr(brain_mod, "persona", parse_persona("bot", VALID + "## reminder\nStay a bot.\n"))
    msgs = brain_mod.brain._build_messages_array(history, "now", "SYS")
    assert msgs[-1] == {"role": "system", "content": "Stay a bot."}
    assert msgs[-2]["content"] == "now"
    # Ancient-reply path (quoted text not in the window) gets the reminder too.
    msgs = brain_mod.brain._build_messages_array(history, "now", "SYS", reply_to_text="a long-gone bot message")
    assert msgs[-1] == {"role": "system", "content": "Stay a bot."}

    monkeypatch.setattr(brain_mod, "persona", parse_persona("bot", VALID))
    msgs = brain_mod.brain._build_messages_array(history, "now", "SYS")
    assert all(m["role"] != "system" for m in msgs[1:])


def test_attitudes_section_is_parsed_into_a_dict():
    p = parse_persona("bot", VALID + "## attitudes\n- Rude: Be cold.\n- friend: Be warm.\nnot a bullet\n- broken\n")
    assert p.attitudes == {"rude": "Be cold.", "friend": "Be warm."}
    assert parse_persona("bot", VALID).attitudes == {}


def test_shipped_personas_cover_every_attitude_key():
    keys = {"rude", "provocative", "offtopic", "spammer", "friend", "newcomer", "regular", "expert", "beginner"}
    for key in ("tars", "peasant"):
        assert keys <= set(load_persona(key).attitudes)


def test_attitude_note_joins_the_reminder_turn(monkeypatch):
    import core.brain as brain_mod

    monkeypatch.setattr(brain_mod, "persona", parse_persona("bot", VALID + "## reminder\nStay a bot.\n"))
    msgs = brain_mod.brain._build_messages_array([], "now", "SYS", attitude_note="NOTE")
    assert msgs[-1] == {"role": "system", "content": "Stay a bot.\n\nNOTE"}
