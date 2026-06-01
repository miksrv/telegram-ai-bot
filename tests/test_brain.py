from core.brain import TARSBrain


def make_brain() -> TARSBrain:
    return TARSBrain()


# --------------------------------------------------
# _build_messages_array — reply-to context injection
# --------------------------------------------------


def test_messages_array_basic_shape():
    brain = make_brain()
    history = [(100, "user", "привет"), (100, "assistant", "здравствуй")]
    messages = brain._build_messages_array(history, "как дела?", "SYS")
    assert messages[0] == {"role": "system", "content": "SYS"}
    assert messages[1] == {"role": "user", "content": "User#100: привет"}
    assert messages[2] == {"role": "assistant", "content": "здравствуй"}
    assert messages[-1] == {"role": "user", "content": "как дела?"}


def test_reply_to_injected_when_absent_from_history():
    """Replying to a proactive post (not in memory) surfaces it as the last assistant turn."""
    brain = make_brain()
    messages = brain._build_messages_array([], "да, согласен", "SYS", reply_to_text="Кто-нибудь видел вчера комету?")
    assert messages[-2] == {"role": "assistant", "content": "Кто-нибудь видел вчера комету?"}
    assert messages[-1] == {"role": "user", "content": "да, согласен"}


def test_reply_to_not_duplicated_when_already_last_assistant_turn():
    brain = make_brain()
    history = [(100, "user", "вопрос"), (100, "assistant", "мой ответ")]
    messages = brain._build_messages_array(history, "уточнение", "SYS", reply_to_text="мой ответ")
    # No extra assistant turn appended — it is already the latest one.
    assistant_turns = [m for m in messages if m["role"] == "assistant"]
    assert assistant_turns == [{"role": "assistant", "content": "мой ответ"}]


def test_empty_reply_to_text_is_ignored():
    brain = make_brain()
    messages = brain._build_messages_array([], "сообщение", "SYS", reply_to_text="   ")
    assert messages[-1] == {"role": "user", "content": "сообщение"}
    assert all(m["role"] != "assistant" for m in messages)
