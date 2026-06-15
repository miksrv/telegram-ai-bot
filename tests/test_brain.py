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


def test_ancient_reply_prunes_unrelated_history():
    """Replying to an old bot message outside the window drops misleading recent history."""
    brain = make_brain()
    history = [
        (100, "user", "какая сегодня погода"),
        (100, "assistant", "облачно, наблюдения не выйдут"),
    ]
    messages = brain._build_messages_array(
        history,
        "и какое же увеличение лучше",
        "SYS",
        reply_to_text="Для Сатурна на этой апертуре оптимально около 150x",
    )
    # Unrelated recent turns are dropped; only the quoted message anchors the reply.
    assert messages == [
        {"role": "system", "content": "SYS"},
        {"role": "assistant", "content": "Для Сатурна на этой апертуре оптимально около 150x"},
        {"role": "user", "content": "и какое же увеличение лучше"},
    ]


def test_reply_to_other_user_is_folded_into_message():
    """A reply to another user's message is folded in as context, not a bot turn."""
    brain = make_brain()
    history = [(100, "user", "что-то старое"), (100, "assistant", "ответ бота")]
    messages = brain._build_messages_array(
        history,
        "ТАРС, это правда?",
        "SYS",
        reply_to_text="Луна сегодня в перигее",
        reply_to_is_bot=False,
    )
    # History preserved; no spurious assistant turn for the quote.
    assert messages[-1]["role"] == "user"
    assert "Луна сегодня в перигее" in messages[-1]["content"]
    assert "ТАРС, это правда?" in messages[-1]["content"]
    assert {"role": "assistant", "content": "Луна сегодня в перигее"} not in messages


def test_in_window_reply_keeps_history():
    """Replying to a message still in the window keeps the surrounding context."""
    brain = make_brain()
    history = [
        (100, "user", "вопрос про телескоп"),
        (100, "assistant", "Для Сатурна на этой апертуре оптимально около 150x увеличения"),
    ]
    messages = brain._build_messages_array(
        history,
        "а для Юпитера",
        "SYS",
        reply_to_text="Для Сатурна на этой апертуре оптимально около 150x увеличения",
    )
    # History is preserved; the quoted turn is already the latest assistant turn.
    assert messages[1] == {"role": "user", "content": "User#100: вопрос про телескоп"}
    assert messages[-1] == {"role": "user", "content": "а для Юпитера"}
