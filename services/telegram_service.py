"""
Telegram Service
Handles Telegram bot initialization and handler registration
"""

import logging
from telebot import TeleBot
from telebot.types import Message

from handlers import message_handler, status_handler, weather_handler, photo_handler
from config.settings import BOT_TOKEN, ALLOWED_CHAT_IDS


def init_bot() -> TeleBot:
    """
    Initializes the TeleBot instance and registers handlers.
    """
    bot = TeleBot(BOT_TOKEN, parse_mode=None)
    bot.bot_id = bot.get_me().id  # Cache bot ID once at startup

    # --- Status command handler ---
    @bot.message_handler(commands=["status"])
    def _status_handler(message: Message):
        status_handler.handle_status(bot, message, ALLOWED_CHAT_IDS)

    @bot.message_handler(commands=["photo"])
    def photo_handler_wrapper(message: Message):
        photo_handler.handle_photo(bot, message, ALLOWED_CHAT_IDS)

    # --- Weather command handler ---
    @bot.message_handler(commands=["weather"])
    def _weather_handler(message: Message):
        weather_handler.handle_weather(bot, message, ALLOWED_CHAT_IDS)

    # --- Main message handler (text & photos) ---
    @bot.message_handler(content_types=["text", "photo"])
    def _main_handler(message: Message):
        message_handler.handle_message(bot, message, ALLOWED_CHAT_IDS)

    logging.info("Telegram handlers registered successfully")
    return bot
