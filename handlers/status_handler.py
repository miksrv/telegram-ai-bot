"""
Telegram Status Handler
Handles /status command and system information reporting
"""

import logging
from telebot import TeleBot, types

from services.system_service import get_system_status
from config.settings import ADMIN_IDS


def handle_status(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Handles the /status command and returns system information.
    """

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Ignore messages from unauthorized chats
    if (message.chat.type == "private" and user_id not in ADMIN_IDS) or \
       (chat_id not in allowed_chat_ids and message.chat.type != "private"):
        return

    # Send status message as HTML
    try:
        bot.send_message(chat_id, get_system_status(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Failed to send status message: {e}")
