"""
Telegram Photo Utilities
Handles extracting photo URLs and captions from Telegram messages
"""

from typing import Tuple, Optional
from telebot import TeleBot
from telebot.types import Message
from config.settings import BOT_TOKEN


def extract_photo_url(bot: TeleBot, message: Message) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts the largest photo URL and its caption from a Telegram message.

    Returns a tuple: (photo_url, caption)
    Returns (None, None) if no photo found.
    """

    target_msg = message

    # If this is a reply to a photo, use the replied message
    if message.reply_to_message and message.reply_to_message.photo:
        target_msg = message.reply_to_message

    if not target_msg.photo:
        return None, None

    # Get the largest photo
    largest_photo = target_msg.photo[-1]

    # Get file info from Telegram
    file_info = bot.get_file(largest_photo.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    # Determine caption: priority order
    caption = message.text or message.caption or target_msg.caption or ""

    return url, caption
