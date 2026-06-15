"""
Telegram Photo Utilities
Handles extracting photo URLs and captions from Telegram messages
"""

from typing import Optional, Tuple

from telebot import TeleBot
from telebot.types import Message


def extract_photo_url(bot: TeleBot, message: Message) -> Tuple[Optional[str], Optional[str], bool]:
    """
    Extracts the largest photo URL and its caption from a Telegram message.

    Returns a tuple: (photo_url, caption, from_reply)
    `from_reply` is True when the photo comes from the replied-to (older) message
    rather than the current one — i.e. the user is asking about an existing photo.
    Returns (None, None, False) if no photo found.
    """

    target_msg = message
    from_reply = False

    # If this is a reply to a photo, use the replied message
    if message.reply_to_message and message.reply_to_message.photo:
        target_msg = message.reply_to_message
        from_reply = True

    if not target_msg.photo:
        return None, None, False

    # Get the largest photo
    largest_photo = target_msg.photo[-1]

    # Get file info from Telegram
    file_info = bot.get_file(largest_photo.file_id)
    url = bot.get_file_url(largest_photo.file_id)

    # Determine caption: priority order
    caption = message.text or message.caption or target_msg.caption or ""

    return url, caption, from_reply
