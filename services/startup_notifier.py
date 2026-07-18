"""
Startup Notifier
Sends a one-time status message to all configured admins right after the bot
comes online, so an admin doesn't have to check logs to confirm TARS is alive.
"""

import logging

from telebot import TeleBot

from config.settings import (
    ADMIN_IDS,
    ALLOWED_CHAT_IDS,
    GROQ_MODEL_TEXT,
    LLM_ENGINE,
    OPENAI_MODEL_TEXT,
    PROACTIVE_CHAT_IDS,
    PROACTIVE_ENABLED,
)

_ENGINE_MODELS = {
    "groq": GROQ_MODEL_TEXT,
    "openai": OPENAI_MODEL_TEXT,
}


def _format_startup_message(mqtt_connected: bool) -> str:
    chat_ids = ", ".join(str(cid) for cid in sorted(ALLOWED_CHAT_IDS)) or "—"
    model = _ENGINE_MODELS.get(LLM_ENGINE, "?")
    proactive_status = f"включена ({len(PROACTIVE_CHAT_IDS)} чат(ов))" if PROACTIVE_ENABLED else "выключена"
    mqtt_status = "подключён" if mqtt_connected else "недоступен"

    return (
        "🚀 TARS запущен и на связи\n\n"
        f"💬 Разрешённые чаты ({len(ALLOWED_CHAT_IDS)}): {chat_ids}\n"
        f"🧠 LLM: {LLM_ENGINE} ({model})\n"
        f"📡 MQTT: {mqtt_status}\n"
        f"🔔 Проактивность: {proactive_status}"
    )


def send_startup_notification(bot: TeleBot, mqtt_connected: bool):
    """
    Sends the startup status message to every configured admin. Each send is
    independent — an admin who never opened a private chat with the bot (so
    Telegram rejects the send) must not block the notification to the others.
    """
    message = _format_startup_message(mqtt_connected)
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, message)
        except Exception as e:
            logging.warning(f"Failed to send startup notification to admin {admin_id}: {e}")
