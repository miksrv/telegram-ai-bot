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


def test_ancient_reply_to_other_user_folds_and_prunes():
    """Reply to another user's OLD message: folded as context, no bot turn, history dropped."""
    brain = make_brain()
    history = [(100, "user", "что-то старое"), (100, "assistant", "ответ бота")]
    messages = brain._build_messages_array(
        history,
        "ТАРС, это правда?",
        "SYS",
        reply_to_text="Луна сегодня в перигее",
        reply_to_is_bot=False,
    )
    # Quote is out of window -> recent history dropped, folded into the user turn.
    assert messages == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": '(в ответ на сообщение: "Луна сегодня в перигее")\nТАРС, это правда?'},
    ]


def test_in_window_reply_to_other_user_keeps_history_and_folds():
    """Reply to another user's recent message keeps history and folds an explicit reference."""
    brain = make_brain()
    quoted = "Сегодня шикарно видна туманность Ориона"
    history = [(100, "user", quoted), (200, "assistant", "да, M42 эффектна")]
    messages = brain._build_messages_array(
        history, "ТАРС подтверди", "SYS", reply_to_text=quoted, reply_to_is_bot=False
    )
    # History preserved...
    assert messages[1] == {"role": "user", "content": f"User#100: {quoted}"}
    # ...and the current turn folds in the reference, with no bot turn for the quote.
    assert messages[-1]["role"] == "user"
    assert quoted in messages[-1]["content"]
    assert "ТАРС подтверди" in messages[-1]["content"]
    assert {"role": "assistant", "content": quoted} not in messages


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


# --------------------------------------------------
# analyze_image — caption in context, history pruning, multimodal turn
# --------------------------------------------------


class _FakeImg:
    content = b"\xff\xd8\xff\xe0"

    def raise_for_status(self):
        pass


def test_analyze_image_prunes_history_and_builds_multimodal_turn(monkeypatch):
    """A photo from a reply ignores recent chat history and answers about the image itself."""
    from core import brain as brain_mod

    captured = {}

    monkeypatch.setattr(brain_mod.session, "get", lambda *a, **k: _FakeImg())

    def fake_call(self, model, messages, **kw):
        captured["model"] = model
        captured["messages"] = messages
        return '{"reply": "наблюдение"}'

    monkeypatch.setattr(brain_mod.TARSBrain, "_call_llm", fake_call)

    chat_id, user_id = 987_654, 9_000_111
    # Seed unrelated recent chatter that must NOT leak into an old-photo analysis.
    brain_mod.memory.add_chat_memory(chat_id, user_id, "болтаем про погоду", "ответ про погоду")

    reply = brain_mod.brain.analyze_image(
        chat_id=chat_id,
        user_id=user_id,
        image_url="http://example/img.jpg",
        caption="что это за объект",
        identity={"id": user_id, "first_name": "CI"},
        photo_from_reply=True,
    )

    assert reply == "наблюдение"

    msgs = captured["messages"]
    # photo_from_reply -> no history turns: only system + the multimodal user turn.
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    content = msgs[-1]["content"]
    assert any(p["type"] == "image_url" for p in content)
    assert any(p["type"] == "text" and "что это за объект" in p["text"] for p in content)

    # The photo is recorded in chat memory with a marker and the caption.
    history = brain_mod.memory.get_chat_history(chat_id)
    assert history[-2] == (user_id, "user", "[изображение] что это за объект")
    assert history[-1] == (user_id, "assistant", "наблюдение")


# --------------------------------------------------
# _process_llm_response — empty/invalid replies must be treated as an error,
# never sent to Telegram as an empty message (bot.reply_to rejects empty text).
# --------------------------------------------------


def test_process_llm_response_treats_empty_reply_as_error(monkeypatch):
    from core import brain as brain_mod

    monkeypatch.setattr(brain_mod.TARSBrain, "_call_llm", lambda self, *a, **kw: '{"reply": ""}')

    calls = {"memory": 0, "count": 0}
    monkeypatch.setattr(
        brain_mod.memory,
        "add_chat_memory",
        lambda *a, **kw: calls.__setitem__("memory", calls["memory"] + 1),
    )
    monkeypatch.setattr(
        brain_mod,
        "db_increment_message_count",
        lambda *a, **kw: calls.__setitem__("count", calls["count"] + 1),
    )

    brain = make_brain()
    reply, err = brain._process_llm_response(
        "text",
        [{"role": "system", "content": "SYS"}],
        temperature=0.8,
        max_tokens=100,
        top_p=0.9,
        chat_id=1,
        user_id=2,
        user_input="hi",
    )

    assert reply is None
    assert err == "Ошибка ответа логического модуля"
    # An error response skips memory/profile side effects, same as invalid JSON.
    assert calls["memory"] == 0
    assert calls["count"] == 0


def test_process_llm_response_returns_reply_when_present(monkeypatch):
    from core import brain as brain_mod

    monkeypatch.setattr(brain_mod.TARSBrain, "_call_llm", lambda self, *a, **kw: '{"reply": "привет!"}')
    monkeypatch.setattr(brain_mod.memory, "add_chat_memory", lambda *a, **kw: None)
    monkeypatch.setattr(brain_mod, "db_increment_message_count", lambda *a, **kw: None)

    brain = make_brain()
    reply, err = brain._process_llm_response(
        "text",
        [{"role": "system", "content": "SYS"}],
        temperature=0.8,
        max_tokens=100,
        top_p=0.9,
        chat_id=1,
        user_id=2,
        user_input="hi",
    )

    assert reply == "привет!"
    assert err is None


# --------------------------------------------------
# post_proactive_reply — once-daily direct reply to a specific message
# --------------------------------------------------


def test_post_proactive_reply_targets_selected_message(monkeypatch):
    """The target message/author picked by the caller reach the prompt in a single LLM call."""
    from core import brain as brain_mod

    captured = {}

    def fake_get_recent_messages(chat_id, limit):
        return [{"first_name": "Иван", "username": "ivan", "text": f"сообщение {i}"} for i in range(limit)]

    monkeypatch.setattr(brain_mod, "get_recent_messages", fake_get_recent_messages)

    def fake_call(self, model, messages, **kw):
        captured["prompt"] = messages[0]["content"]
        captured["call_count"] = captured.get("call_count", 0) + 1
        return '{"reply": "ответ по существу"}'

    monkeypatch.setattr(brain_mod.TARSBrain, "_call_llm", fake_call)

    reply = brain_mod.brain.post_proactive_reply(
        chat_id=123,
        target_text="Кто-нибудь наблюдал вчера туманность Ориона в телескоп?",
        target_author="Мария",
    )

    assert reply == "ответ по существу"
    assert captured["call_count"] == 1  # exactly one API call — no separate selection call
    assert "Мария" in captured["prompt"]
    assert "Кто-нибудь наблюдал вчера туманность Ориона в телескоп?" in captured["prompt"]


def test_post_proactive_reply_returns_none_on_insufficient_context(monkeypatch):
    from core import brain as brain_mod

    monkeypatch.setattr(brain_mod, "get_recent_messages", lambda chat_id, limit: [])

    reply = brain_mod.brain.post_proactive_reply(chat_id=123, target_text="что-то", target_author="Кто-то")
    assert reply is None
