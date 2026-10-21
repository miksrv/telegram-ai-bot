from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core import reactions
from core.reactions import ALLOWED_REACTION_EMOJI, RANDOM_REACTIONS, match_keyword, maybe_react, pick_reaction


def make_message(text="Смотрел галактику Андромеды", chat_id=-1, message_id=7):
    return SimpleNamespace(text=text, caption=None, chat=SimpleNamespace(id=chat_id), message_id=message_id)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    reactions._last_reaction_at.clear()
    monkeypatch.setattr(reactions, "REACTIONS_ENABLED", True)
    monkeypatch.setattr(reactions, "REACTIONS_KEYWORD_PROBABILITY", 1.0)
    monkeypatch.setattr(reactions, "REACTIONS_RANDOM_PROBABILITY", 0.0)
    monkeypatch.setattr(reactions, "REACTIONS_MIN_GAP_SECONDS", 600)


# --------------------------------------------------
# keyword matching
# --------------------------------------------------


@pytest.mark.parametrize(
    "text, emoji",
    [
        ("Сфотографировал галактику Андромеды", "🤩"),
        ("Красивая туманность Ориона", "🤩"),
        ("Check out this nebula", "🤩"),
        ("Что будет, если упасть в чёрную дыру?", "🤯"),
        ("Сверхновая в M82!", "😱"),
        ("Купил новый телескоп Добсон", "🔥"),
        ("Сегодня полнолуние", "🌚"),
        ("Спасибо большое", "🙏"),
        ("Поздравляю всех!", "🎉"),
        ("напишу скрипт на Python", "👨‍💻"),
        ("опять облачно, не повезло", "😢"),
        ("ахаха, ну ты даешь", "🤣"),
    ],
)
def test_keyword_match(text, emoji):
    assert match_keyword(text) == emoji


def test_keyword_match_is_case_insensitive():
    assert match_keyword("ГАЛАКТИКИ") == "🤩"


def test_keyword_must_start_a_word():
    # "sun" must not fire inside other words; "луна" stem must not fire mid-word
    assert match_keyword("sunday plans") is None
    assert match_keyword("привет всем в чате") is None
    assert match_keyword("") is None


def test_every_keyword_and_random_emoji_is_allowed_by_telegram():
    keyword_emoji = {emoji for emoji, _ in reactions._COMPILED}
    assert keyword_emoji <= ALLOWED_REACTION_EMOJI
    assert set(RANDOM_REACTIONS) <= ALLOWED_REACTION_EMOJI


def test_keyword_list_is_substantial():
    assert sum(len(p) for _, p in reactions._KEYWORD_PATTERNS) >= 100


# --------------------------------------------------
# probabilities
# --------------------------------------------------


def test_pick_reaction_keyword_hit_when_roll_below_probability(monkeypatch):
    monkeypatch.setattr(reactions, "REACTIONS_KEYWORD_PROBABILITY", 0.15)
    monkeypatch.setattr(reactions.random, "random", lambda: 0.10)
    assert pick_reaction("галактика") == "🤩"


def test_pick_reaction_keyword_miss_when_roll_above_probability(monkeypatch):
    monkeypatch.setattr(reactions, "REACTIONS_KEYWORD_PROBABILITY", 0.15)
    monkeypatch.setattr(reactions.random, "random", lambda: 0.50)
    assert pick_reaction("галактика") is None


def test_pick_reaction_random_pool_for_unmatched_text(monkeypatch):
    monkeypatch.setattr(reactions, "REACTIONS_RANDOM_PROBABILITY", 0.02)
    monkeypatch.setattr(reactions.random, "random", lambda: 0.01)
    monkeypatch.setattr(reactions.random, "choice", lambda pool: pool[0])
    assert pick_reaction("просто болтаем") == RANDOM_REACTIONS[0]


def test_pick_reaction_none_for_unmatched_text_when_roll_high(monkeypatch):
    monkeypatch.setattr(reactions, "REACTIONS_RANDOM_PROBABILITY", 0.02)
    monkeypatch.setattr(reactions.random, "random", lambda: 0.5)
    assert pick_reaction("просто болтаем") is None


def test_random_pool_not_used_for_keyword_message_that_missed_roll(monkeypatch):
    monkeypatch.setattr(reactions, "REACTIONS_KEYWORD_PROBABILITY", 0.0)
    monkeypatch.setattr(reactions, "REACTIONS_RANDOM_PROBABILITY", 1.0)
    assert pick_reaction("галактика") is None


# --------------------------------------------------
# maybe_react: toggle, cooldown, errors
# --------------------------------------------------


def test_maybe_react_sends_reaction():
    bot = MagicMock()
    assert maybe_react(bot, make_message()) is True
    args = bot.set_message_reaction.call_args.args
    assert args[0] == -1 and args[1] == 7
    assert len(args[2]) == 1


def test_maybe_react_disabled_by_toggle(monkeypatch):
    monkeypatch.setattr(reactions, "REACTIONS_ENABLED", False)
    bot = MagicMock()
    assert maybe_react(bot, make_message()) is False
    bot.set_message_reaction.assert_not_called()


def test_maybe_react_respects_per_chat_cooldown(monkeypatch):
    bot = MagicMock()
    assert maybe_react(bot, make_message(chat_id=-1)) is True
    assert maybe_react(bot, make_message(chat_id=-1)) is False  # same chat, inside the gap
    assert maybe_react(bot, make_message(chat_id=-2)) is True  # other chat unaffected
    assert bot.set_message_reaction.call_count == 2


def test_maybe_react_allowed_again_after_gap(monkeypatch):
    bot = MagicMock()
    assert maybe_react(bot, make_message()) is True
    reactions._last_reaction_at[-1] -= 601
    assert maybe_react(bot, make_message()) is True


def test_maybe_react_no_match_no_call():
    bot = MagicMock()
    assert maybe_react(bot, make_message(text="просто болтаем")) is False
    bot.set_message_reaction.assert_not_called()


def test_maybe_react_swallows_telegram_errors():
    bot = MagicMock()
    bot.set_message_reaction.side_effect = RuntimeError("REACTION_INVALID")
    assert maybe_react(bot, make_message()) is False  # no exception


# --------------------------------------------------
# message_handler hook
# --------------------------------------------------


def _handler_message(text, is_bot=False, chat_type="supergroup"):
    return SimpleNamespace(
        text=text,
        caption=None,
        content_type="text",
        message_id=5,
        chat=SimpleNamespace(id=-1, type=chat_type),
        from_user=SimpleNamespace(
            id=10, is_bot=is_bot, first_name="A", last_name="", username="a", language_code="ru", is_premium=False
        ),
        reply_to_message=None,
    )


@pytest.mark.parametrize(
    "text, is_bot, chat_type, called",
    [
        ("смотрю на галактику", False, "supergroup", True),
        ("/weather Москва", False, "supergroup", False),
        ("тарс, что за галактика?", False, "supergroup", False),  # the bot answers it instead
        ("смотрю на галактику", True, "supergroup", False),
    ],
)
def test_handler_reaction_hook(monkeypatch, text, is_bot, chat_type, called):
    from handlers import message_handler as mh

    seen = MagicMock()
    monkeypatch.setattr(mh, "maybe_react", seen)
    monkeypatch.setattr(mh, "PROACTIVE_CHAT_IDS", set())
    monkeypatch.setattr(mh, "is_reply_to_bot", lambda bot, message: False)
    monkeypatch.setattr(mh, "extract_photo_url", lambda bot, message: (None, "", False))
    monkeypatch.setattr(mh.brain, "think", lambda **kw: "ответ")

    mh.handle_message(MagicMock(), _handler_message(text, is_bot, chat_type), {-1})
    assert seen.called is called
