"""
Telegram Weather Handler
Handles /weather command
"""

import logging

from telebot import TeleBot, types

from services.weather_service import get_weather
from utils.typing_action import typing_action


def handle_weather(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Ignore messages from unauthorized chats
    if chat_id not in allowed_chat_ids and message.chat.type != "private":
        return

    # Get city name from command arguments
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        bot.reply_to(message, "Usage: /weather <city>")
        return

    city = args[1].strip()

    try:
        with typing_action(bot, chat_id):
            weather_text = get_weather(city)
        bot.reply_to(message, weather_text)
    except Exception as e:
        logging.error(f"Weather error: {e}")
        bot.reply_to(message, "Не удалось получить погоду 😔")
