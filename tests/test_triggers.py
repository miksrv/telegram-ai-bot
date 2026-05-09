from utils.triggers import is_calling_tars


def test_lowercase_tars():
    assert is_calling_tars("привет tars как дела") is True


def test_uppercase_tars():
    assert is_calling_tars("TARS объясни") is True


def test_mixed_case_tars():
    assert is_calling_tars("Tars, помоги") is True


def test_cyrillic_тарс():
    assert is_calling_tars("тарс, что такое нейтронная звезда?") is True


def test_cyrillic_uppercase_ТАРС():
    assert is_calling_tars("ТАРС расскажи") is True


def test_tars_at_start_of_string():
    assert is_calling_tars("tars расскажи про Марс") is True


def test_no_trigger_word():
    assert is_calling_tars("привет всем в чате") is False


def test_empty_string():
    assert is_calling_tars("") is False


def test_none_returns_false():
    assert is_calling_tars(None) is False


def test_tars_not_matched_as_substring():
    # "tars" must be a whole word — "tartars" should not match
    assert is_calling_tars("tartars sauce") is False


def test_command_slash_no_match():
    assert is_calling_tars("/status") is False


def test_tars_with_punctuation_after():
    assert is_calling_tars("tars!") is True
