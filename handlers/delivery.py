"""
Shared delivery helpers for MQTT-backed commands.

Both the CubeSat photo flow (/photo) and the starmap chart commands follow the
same UX: reply to the user's command with a transient "working" status message,
then — once the result arrives — delete that status message and post the result
as a fresh reply to the original command. These helpers keep that mechanism
identical across handlers and swallow the inevitable Telegram edge cases
(message already gone, reply target deleted, etc.).
"""

import logging

from telebot import TeleBot, types

logger = logging.getLogger(__name__)


def safe_reply(bot: TeleBot, message: types.Message, text: str):
    """Replies to `message`, returning the sent Message (or None on failure)."""
    try:
        return bot.reply_to(message, text)
    except Exception:
        logger.exception("Failed to send status/reply message")
        return None


def safe_delete(bot: TeleBot, chat_id: int, status_message) -> None:
    """Deletes the transient status message, ignoring errors (already gone / too old)."""
    if status_message is None:
        return
    try:
        bot.delete_message(chat_id, status_message.message_id)
    except Exception:
        logger.debug("Could not delete status message (already removed?)")
