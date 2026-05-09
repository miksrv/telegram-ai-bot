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
