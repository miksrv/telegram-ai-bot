"""
Trigger Utilities
Handles detection of bot mentions in text messages
"""

import re
from typing import Set

from telebot import TeleBot, types

# Define trigger words (can be expanded)
TRIGGERS = {"ТАRS", "тарс", "tars", "tars,", "тарс,"}

# Precompile regex for performance
TRIGGER_REGEX = re.compile(r"\b(" + "|".join(re.escape(t) for t in TRIGGERS) + r")\b", re.IGNORECASE)


def is_calling_tars(text: str) -> bool:
    """
    Returns True if the message contains a trigger word for the bot.
    """
    if not text:
        return False
    return bool(TRIGGER_REGEX.search(text))


def is_reply_to_bot(bot: TeleBot, message: types.Message) -> bool:
    """
    Checks if the message is a reply to the bot.
    Uses bot.bot_id cached at startup to avoid a Telegram API call per message.
    """
    bot_id = getattr(bot, "bot_id", None) or bot.get_me().id
    return (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_id
    )


def add_trigger(new_trigger: str, triggers_set: Set[str] = TRIGGERS):
    """
    Adds a new trigger word to the trigger set and recompiles regex.
    """
    triggers_set.add(new_trigger)
    global TRIGGER_REGEX
    TRIGGER_REGEX = re.compile(r"\b(" + "|".join(re.escape(t) for t in triggers_set) + r")\b", re.IGNORECASE)
