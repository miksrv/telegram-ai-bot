from core.personality_engine import PersonalityEngine


def _profile(**overrides):
    base = {
        "avg_offtopic": 0.0,
        "avg_provocation": 0.0,
        "avg_spam": 0.0,
        "avg_rudeness": 0.0,
        "avg_verbosity": 0.0,
    }
    base.update(overrides)
    return base


# --------------------------------------------------
# quantize()
# --------------------------------------------------


def test_quantize_zero():
    assert PersonalityEngine.quantize(0.0) == 0


def test_quantize_one():
    assert PersonalityEngine.quantize(1.0) == 9


def test_quantize_midpoint():
    assert PersonalityEngine.quantize(0.5) == 5


def test_quantize_clamps_below_zero():
    assert PersonalityEngine.quantize(-0.5) == 0


def test_quantize_clamps_above_one():
    assert PersonalityEngine.quantize(1.5) == 9


def test_quantize_near_boundary():
    assert PersonalityEngine.quantize(0.09) == 0
    assert PersonalityEngine.quantize(0.10) == 1


# --------------------------------------------------
# build_prompt_rules()
# --------------------------------------------------


def test_rules_returns_string():
    result = PersonalityEngine.build_prompt_rules(_profile())
    assert isinstance(result, str)


def test_rules_all_zero_still_has_verbosity_rule():
    # verbosity=0 maps to level 0 → "Be concise." (non-empty rule)
    result = PersonalityEngine.build_prompt_rules(_profile())
    assert "Adaptive response behavior" in result
    assert "concise" in result.lower()


def test_rules_high_values_contain_multiple_directives():
    profile = _profile(
        avg_offtopic=0.9,
        avg_provocation=0.9,
        avg_spam=0.9,
        avg_rudeness=0.9,
        avg_verbosity=0.9,
    )
    result = PersonalityEngine.build_prompt_rules(profile)
    assert "Adaptive response behavior" in result
    # High scores produce restrictive directives
    assert result.count("\n-") >= 4


def test_rules_low_offtopic_produces_no_offtopic_directive():
    # Levels 0–1 for offtopic map to empty string (no directive)
    profile = _profile(avg_offtopic=0.05)
    result = PersonalityEngine.build_prompt_rules(profile)
    assert "steer" not in result.lower()
    assert "relevance" not in result.lower()


# --------------------------------------------------
# familiarity_rule() — newcomer / regular directives from message_count
# --------------------------------------------------


def test_familiarity_rule_newcomer_below_threshold():
    rule = PersonalityEngine.familiarity_rule(0)
    assert "newcomer" in rule.lower()


def test_familiarity_rule_regular_at_or_above_threshold():
    rule = PersonalityEngine.familiarity_rule(PersonalityEngine.REGULAR_THRESHOLD)
    assert "regular" in rule.lower()


def test_familiarity_rule_middle_band_is_empty():
    mid = (PersonalityEngine.NEWCOMER_THRESHOLD + PersonalityEngine.REGULAR_THRESHOLD) // 2
    assert PersonalityEngine.familiarity_rule(mid) == ""


# --------------------------------------------------
# depth_rule() — directive from the "experience" structured fact
# --------------------------------------------------


def test_depth_rule_beginner():
    assert "basic" in PersonalityEngine.depth_rule("beginner").lower()


def test_depth_rule_advanced():
    assert PersonalityEngine.depth_rule("advanced") != ""


def test_depth_rule_pro():
    assert PersonalityEngine.depth_rule("pro") != ""


def test_depth_rule_is_case_insensitive():
    assert PersonalityEngine.depth_rule("BEGINNER") == PersonalityEngine.depth_rule("beginner")


def test_depth_rule_unknown_or_empty_returns_empty_string():
    assert PersonalityEngine.depth_rule("amateur") == ""
    assert PersonalityEngine.depth_rule("") == ""
    assert PersonalityEngine.depth_rule(None) == ""


# --------------------------------------------------
# build_prompt_rules() — familiarity/depth wired into the full rule set
# --------------------------------------------------


def test_build_prompt_rules_includes_familiarity_rule():
    profile = _profile(message_count=0)
    result = PersonalityEngine.build_prompt_rules(profile)
    assert "newcomer" in result.lower()


def test_build_prompt_rules_includes_depth_rule_from_facts():
    profile = _profile(message_count=10, facts={"experience": "advanced"})
    result = PersonalityEngine.build_prompt_rules(profile)
    assert "strong background" in result.lower() or "advanced" in result.lower()


# --------------------------------------------------
# attitudes (mood + reputation -> persona attitude keys)
# --------------------------------------------------


def _att_profile(**kw):
    base = {
        "avg_offtopic": 0.0,
        "avg_provocation": 0.0,
        "avg_spam": 0.0,
        "avg_rudeness": 0.0,
        "avg_verbosity": 0.5,
        "avg_friendliness": 0.0,
        "mood": "",
        "mood_turns": 0,
        "message_count": 10,
        "facts": {},
    }
    base.update(kw)
    return base


def test_normalize_mood_accepts_known_tags_only():
    assert PersonalityEngine.normalize_mood(" Rude ") == "rude"
    assert PersonalityEngine.normalize_mood("neutral") == ""
    assert PersonalityEngine.normalize_mood(None) == ""
    assert PersonalityEngine.normalize_mood(5) == ""


def test_neutral_mid_band_user_has_no_attitudes():
    assert PersonalityEngine.attitudes(_att_profile()) == []


def test_current_mood_comes_first_and_only_while_held():
    p = _att_profile(mood="rude", mood_turns=3, avg_friendliness=0.8, message_count=30)
    assert PersonalityEngine.attitudes(p) == [
        ("rude", "just now"),
        ("friend", "habitually"),
        ("regular", "30 talks so far"),
    ]
    later = PersonalityEngine.attitudes(_att_profile(mood="rude", mood_turns=1))
    assert later[0] == ("rude", "still, from a recent message")
    assert all(key != "rude" for key, _ in PersonalityEngine.attitudes(_att_profile(mood="rude", mood_turns=0)))


def test_reputation_newcomer_and_expertise():
    first = PersonalityEngine.attitudes(_att_profile(message_count=0))
    assert first == [("newcomer", "first talk")]
    p = _att_profile(avg_provocation=0.3, message_count=1, facts={"experience": "pro"})
    assert PersonalityEngine.attitudes(p) == [
        ("provocative", "habitually"),
        ("newcomer", "few talks so far"),
        ("expert", "pro"),
    ]


def test_attitude_note_uses_persona_texts_and_skips_unknown_keys():
    p = _att_profile(mood="friendly", mood_turns=1, message_count=1)
    note = PersonalityEngine.build_attitude_note(p, {"friend": "Be warm."}, "Миша")
    assert "(Миша)" in note
    assert "- friend (still, from a recent message): Be warm." in note
    assert "newcomer" not in note
    assert PersonalityEngine.build_attitude_note(p, {}, "Миша") == ""
