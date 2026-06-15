"""
Telegram Stats Handler
Handles /stats command — reports aggregate database statistics in Russian.
"""

import logging
from datetime import datetime

from telebot import TeleBot, types

from config.settings import ADMIN_IDS
from database.db import get_db_stats


def _format_ts(ts: int) -> str:
    """Formats a Unix timestamp as local date/time, or a dash if absent."""
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def format_stats(stats: dict) -> str:
    """Renders the statistics dictionary as a Russian Telegram message."""
    return (
        "📊 Статистика TARS\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"💬 Всего ответов бота: {stats['interactions']}\n"
        f"🗂 Сообщений в памяти: {stats['stored_messages']}\n"
        f"📡 Наблюдаемых чатов: {stats['observed_chats']}\n"
        f"🕐 Самое старое сообщение: {_format_ts(stats['oldest_message_ts'])}\n"
        f"🕒 Самое свежее сообщение: {_format_ts(stats['newest_message_ts'])}"
    )


def handle_stats(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает команду /stats: выводит агрегированную статистику из БД.
    Доступна администраторам в личке и в разрешённых чатах.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    if (message.chat.type == "private" and user_id not in ADMIN_IDS) or (
        chat_id not in allowed_chat_ids and message.chat.type != "private"
    ):
        bot.reply_to(message, "Доступ запрещён.")
        return

    try:
        stats = get_db_stats()
        bot.reply_to(message, format_stats(stats))
    except Exception as e:
        logging.error(f"Stats error: {e}")
        bot.reply_to(message, "Не удалось получить статистику 😔")
