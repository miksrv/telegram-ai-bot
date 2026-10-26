"""
Telegram /me Handler
Handles /me — the bot describes, in its persona's voice, how it sees the asking user
(profile, interests, notes and the attitude engine's view of them).
"""

import logging

from telebot import TeleBot, types

from config.settings import ADMIN_IDS
from core.brain import brain
from core.cooldown import cooldowns
from utils.identity import extract_telegram_identity
from utils.typing_action import typing_action


def handle_me(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает команду /me: бот голосом персоны рассказывает, каким видит собеседника.
    Работает в разрешённых чатах и у администраторов в личке; тратит один вызов LLM,
    поэтому подчиняется тому же ограничению частоты, что и обычные вопросы.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    if (message.chat.type == "private" and user_id not in ADMIN_IDS) or (
        chat_id not in allowed_chat_ids and message.chat.type != "private"
    ):
        return

    if not cooldowns.allowed(user_id):
        bot.reply_to(
            message, "Вы задаете слишком много вопросов. Пожалуйста, подождите немного перед следующим сообщением."
        )
        return

    try:
        with typing_action(bot, chat_id):
            reply = brain.describe_user(user_id, extract_telegram_identity(message))
        bot.reply_to(message, reply)
    except Exception as e:
        logging.error(f"/me error: {e}")
