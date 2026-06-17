"""
Telegram Service
Handles Telegram bot initialization and handler registration
"""

import logging

from telebot import TeleBot
from telebot.types import BotCommand, Message

from config.settings import ALLOWED_CHAT_IDS, BOT_TOKEN
from handlers import (
    help_handler,
    message_handler,
    photo_handler,
    stats_handler,
    status_handler,
    weather_handler,
)


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

    # --- Stats command handler ---
    @bot.message_handler(commands=["stats"])
    def _stats_handler(message: Message):
        stats_handler.handle_stats(bot, message, ALLOWED_CHAT_IDS)

    # --- Help command handler ---
    @bot.message_handler(commands=["help", "start"])
    def _help_handler(message: Message):
        help_handler.handle_help(bot, message, ALLOWED_CHAT_IDS)

    # --- Main message handler (text & photos) ---
    @bot.message_handler(content_types=["text", "photo"])
    def _main_handler(message: Message):
        message_handler.handle_message(bot, message, ALLOWED_CHAT_IDS)

    logging.info("Telegram handlers registered successfully")

    _register_command_menu(bot)

    return bot


def _register_command_menu(bot: TeleBot):
    """
    Publishes the command list shown in the Telegram '/' autocomplete.

    Uses the default scope, so the menu is visible to everyone in every chat,
    including large groups (the list is a property of the bot, not per-chat or
    per-member). Visibility here is cosmetic — access is still enforced by each
    handler. Failures are non-fatal.
    """
    commands = [
        BotCommand("help", "Описание бота и список команд"),
        BotCommand("weather", "Погода для наблюдений: /weather <город>"),
        #         BotCommand("status", "Телеметрия спутника CubeSat"),
        #         BotCommand("photo", "Снимок с камеры CubeSat"),
        BotCommand("stats", "Статистика бота"),
    ]
    try:
        bot.set_my_commands(commands)
        logging.info("Bot command menu registered (%d commands)", len(commands))
    except Exception as e:
        logging.warning(f"Failed to set bot command menu: {e}")
