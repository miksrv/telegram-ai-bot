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
    starmap_handler,
    stats_handler,
    status_handler,
    weather_handler,
)
from services.mqtt_service import register_status_listener


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

    # --- Starmap (star-chart) command handlers ---
    @bot.message_handler(commands=["sky"])
    def _sky_handler(message: Message):
        starmap_handler.handle_sky(bot, message, ALLOWED_CHAT_IDS)

    @bot.message_handler(commands=["horizon"])
    def _horizon_handler(message: Message):
        starmap_handler.handle_horizon(bot, message, ALLOWED_CHAT_IDS)

    @bot.message_handler(commands=["skymap"])
    def _skymap_handler(message: Message):
        starmap_handler.handle_skymap(bot, message, ALLOWED_CHAT_IDS)

    @bot.message_handler(commands=["galaxy"])
    def _galaxy_handler(message: Message):
        starmap_handler.handle_galaxy(bot, message, ALLOWED_CHAT_IDS)

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

    # Rebuild the '/' menu whenever the starmap-service comes up or goes down.
    # register_status_listener also fires once immediately with the current
    # state, so the menu is published right away regardless of MQTT timing.
    register_status_listener(lambda online: _publish_command_menu(bot, online))

    return bot


def _build_commands(starmap_online: bool):
    """Builds the '/' autocomplete list; star-chart commands appear only when the service is up."""
    commands = [
        BotCommand("help", "Описание бота и список команд"),
        BotCommand("weather", "Погода для наблюдений: /weather <город>"),
        #         BotCommand("status", "Телеметрия спутника CubeSat"),
        #         BotCommand("photo", "Снимок с камеры CubeSat"),
        BotCommand("stats", "Статистика бота"),
    ]
    if starmap_online:
        commands += [
            BotCommand("sky", "Карта неба над городом сейчас: /sky <город>"),
            BotCommand("horizon", "Небо у горизонта: /horizon <город> [сторона]"),
            BotCommand("skymap", "Полная карта звёздного неба"),
            BotCommand("galaxy", "Карта неба в галактических координатах"),
        ]
    return commands


def _publish_command_menu(bot: TeleBot, starmap_online: bool):
    """
    Publishes the command list shown in the Telegram '/' autocomplete.

    Uses the default scope, so the menu is visible to everyone in every chat,
    including large groups (the list is a property of the bot, not per-chat or
    per-member). Visibility here is cosmetic — access is still enforced by each
    handler. Failures are non-fatal.
    """
    commands = _build_commands(starmap_online)
    try:
        bot.set_my_commands(commands)
        logging.info(
            "Bot command menu registered (%d commands, starmap_online=%s)",
            len(commands),
            starmap_online,
        )
    except Exception as e:
        logging.warning(f"Failed to set bot command menu: {e}")
