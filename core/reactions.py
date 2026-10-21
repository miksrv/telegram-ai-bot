"""
Keyword-driven message reactions — no LLM involved.

For ordinary chat messages the bot occasionally puts an emoji reaction on them:
with REACTIONS_KEYWORD_PROBABILITY when the text matches an astronomy/chat
keyword, with a much smaller REACTIONS_RANDOM_PROBABILITY (from a tiny pool)
when it matches nothing. A per-chat cooldown (REACTIONS_MIN_GAP_SECONDS) keeps
it rare. Telegram bots may only use a fixed emoji set (ReactionTypeEmoji);
everything this module can pick is checked against ALLOWED_REACTION_EMOJI.
"""

import logging
import random
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

from telebot import types

from config.settings import (
    REACTIONS_ENABLED,
    REACTIONS_KEYWORD_PROBABILITY,
    REACTIONS_MIN_GAP_SECONDS,
    REACTIONS_RANDOM_PROBABILITY,
)

logger = logging.getLogger(__name__)

# The emoji Telegram's Bot API accepts in ReactionTypeEmoji (as documented at
# https://core.telegram.org/bots/api#reactiontypeemoji).
ALLOWED_REACTION_EMOJI = frozenset(
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 🍾 "
    "💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡".split()
)

# Reactions for messages with no keyword match (rare, deliberately neutral).
RANDOM_REACTIONS: Tuple[str, ...] = ("👍", "🔥", "🤔", "👀")

# (emoji, regex alternatives). Patterns are matched against the lowercased text at a
# word start, so "галактик" also matches "галактики"/"галактику"; add "\b" at the end
# of a pattern to forbid trailing letters. The first emoji whose patterns match wins,
# so more specific topics come first.
_KEYWORD_PATTERNS: List[Tuple[str, Tuple[str, ...]]] = [
    (
        "😱",
        (
            "сверхнов",
            "supernova",
            "взрыв",
            "explosion",
            "столкновени",
            "collision",
            "астероид",
            "asteroid",
            "метеорит",
            "катастроф",
            "гамма-всплеск",
            "gamma.ray burst",
            "опасн",
        ),
    ),
    (
        "🤯",
        (
            r"чёрн\w* дыр",
            r"черн\w* дыр",
            "black hole",
            "вселенн",
            "universe",
            "бесконечн",
            "парадокс",
            "квазар",
            "quasar",
            "нейтронн",
            "neutron star",
            "пульсар",
            "pulsar",
            "большой взрыв",
            "big bang",
            r"т[её]мн\w* матер",
            "dark matter",
        ),
    ),
    (
        "🤩",
        (
            "галактик",
            "galax",
            "туманност",
            "nebula",
            "млечн",
            "milky way",
            "андромед",
            "andromeda",
            "комет",
            "comet",
            "сатурн",
            "saturn",
            "юпитер",
            "jupiter",
            "аврор",
            "сияни",
            "aurora",
            "астрофот",
            "astrophoto",
            "созвезд",
            "constellation",
        ),
    ),
    (
        "🔥",
        (
            "телескоп",
            "telescope",
            "добсон",
            "dobson",
            "рефлектор",
            "рефрактор",
            "монтировк",
            "астрограф",
            "объектив",
            "апертур",
            "aperture",
            "ccd",
        ),
    ),
    (
        "🌚",
        (
            "луна",
            "луны",
            "луну",
            "лунн",
            "луне",
            "луной",
            r"moon\b",
            "полнолуни",
            "новолуни",
            "затмени",
            "eclipse",
        ),
    ),
    (
        "⚡",
        (
            r"магнитн\w* бур",
            r"солнечн\w* вспышк",
            "вспышк",
            "flare",
            "solar storm",
            "корональн",
            r"солнц",
            r"sun\b",
        ),
    ),
    (
        "👀",
        (
            "метеор",
            "meteor",
            "персеид",
            "perseid",
            "спутник",
            "satellite",
            "starlink",
            "старлинк",
            r"мкс\b",
            r"iss\b",
            "транзит",
            "видел",
            "наблюда",
        ),
    ),
    (
        "🤓",
        (
            "спектр",
            "spectr",
            "параллакс",
            "красное смещение",
            "redshift",
            "формул",
            "уравнени",
            "гравитац",
            "gravity",
            "релятив",
            "фотометр",
            "кеплер",
            "kepler",
            "ньютон",
            "эйнштейн",
            "einstein",
        ),
    ),
    (
        "👨‍💻",
        (
            "python",
            "питон",
            r"код\b",
            "скрипт",
            "script",
            "github",
            r"api\b",
            "программ",
            "arduino",
            "ардуино",
            "raspberry",
            "малин",
            "mqtt",
            "stellarium",
            "стеллариум",
            "pixinsight",
            "siril",
            "phd2",
            "sharpcap",
        ),
    ),
    ("🙏", ("спасибо", "благодар", "thanks", "thank you")),
    ("🎉", ("поздравл", "congrat", r"ура\b", "с днём рождения", "с днем рождения", "праздник")),
    (
        "👏",
        (
            "получилось",
            "удалось",
            "первый кадр",
            "first light",
            "молодец",
            "отличн",
            "great shot",
            "красив",
            "beautiful",
            "шикарн",
            "потрясающ",
            "amazing",
        ),
    ),
    ("🤣", ("хаха", "ахах", r"лол\b", r"lol\b", "haha")),
    ("😁", ("шутк", "прикол", "funny")),
    (
        "😢",
        (
            "облачн",
            r"тучи\b",
            r"туч\b",
            "cloud",
            "дождь",
            "не повезло",
            "к сожалению",
            "жаль",
            "засвет",
            "light pollution",
            "поломк",
            "сломал",
            "не работает",
            "грустн",
            r"sad\b",
        ),
    ),
    (
        "🤔",
        (
            "почему",
            "зачем",
            "подскажите",
            "вопрос",
            "интересно",
            "как думаете",
            r"why\b",
            "wonder",
        ),
    ),
    ("💯", ("согласен", "согласна", "именно", "agree", "exactly", r"100\s?%")),
]

_COMPILED: List[Tuple[str, "re.Pattern"]] = [
    (emoji, re.compile(r"\b(?:" + "|".join(patterns) + ")", re.IGNORECASE)) for emoji, patterns in _KEYWORD_PATTERNS
]

# Per-chat unix time of the last reaction the bot attempted.
_last_reaction_at: Dict[int, float] = {}
_lock = threading.Lock()


def match_keyword(text: str) -> Optional[str]:
    """Returns the emoji for the first keyword group matching `text`, else None."""
    lowered = (text or "").lower()
    for emoji, pattern in _COMPILED:
        if pattern.search(lowered):
            return emoji
    return None


def pick_reaction(text: str) -> Optional[str]:
    """Rolls the dice: a keyword emoji with REACTIONS_KEYWORD_PROBABILITY, or, when
    no keyword matched, a random pool emoji with REACTIONS_RANDOM_PROBABILITY.
    Returns None for "no reaction".
    """
    emoji = match_keyword(text)
    if emoji is not None:
        return emoji if random.random() < REACTIONS_KEYWORD_PROBABILITY else None
    if random.random() < REACTIONS_RANDOM_PROBABILITY:
        return random.choice(RANDOM_REACTIONS)
    return None


def _try_claim(chat_id: int, now: float) -> bool:
    """Atomically checks the per-chat cooldown and, if it has elapsed, claims the slot."""
    with _lock:
        if now - _last_reaction_at.get(chat_id, 0.0) < REACTIONS_MIN_GAP_SECONDS:
            return False
        _last_reaction_at[chat_id] = now
        return True


def maybe_react(bot, message) -> bool:
    """Possibly reacts to `message`. Returns True if a reaction was sent.

    The caller decides which messages qualify (allowed chat, human, not a command).
    Never raises: a Telegram failure is logged and swallowed.
    """
    if not REACTIONS_ENABLED:
        return False
    try:
        text = message.text or message.caption or ""
        chat_id = message.chat.id
        now = time.time()

        emoji = pick_reaction(text)
        if emoji is None or emoji not in ALLOWED_REACTION_EMOJI:
            return False

        # Check-and-claim in one locked step, only once a reaction is actually chosen
        # (a no-reaction roll must not burn the cooldown); claimed before the network
        # call so concurrent handlers cannot both react within the gap.
        if not _try_claim(chat_id, now):
            return False
        bot.set_message_reaction(chat_id, message.message_id, [types.ReactionTypeEmoji(emoji)])
        logger.info("Reacted %s in chat=%s message_id=%s", emoji, chat_id, message.message_id)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Reaction failed: %s", e)
        return False
