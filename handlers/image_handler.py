"""
Telegram Image Generation Handler
Handles /image <prompt> by generating an image via OpenAI's Images API
(services/image_service.py) and enforces a persisted per-user daily quota
(database/db.py's image_generation_usage table), in addition to the existing
spam cooldown shared with every other command.
"""

import logging
from io import BytesIO

from telebot import TeleBot, types

from config.settings import IMAGE_GEN_MAX_PER_DAY
from core.cooldown import cooldowns
from database import db
from handlers.delivery import safe_delete, safe_reply
from services.image_service import (
    ImageContentPolicyError,
    ImageQuotaExceededError,
    generate_image,
)
from utils.typing_action import typing_action

logger = logging.getLogger(__name__)

_USAGE_TEXT = "Использование: /image <описание>\nНапример: /image космонавт верхом на комете, цифровая живопись"
_COOLDOWN_TEXT = "Вы задаете слишком много вопросов. Пожалуйста, подождите немного перед следующим сообщением."


def handle_image(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает /image <описание>: генерирует изображение через OpenAI Images API.
    Ожидание ответа выполняется синхронно внутри typing_action — запрос к OpenAI
    обычно короче, чем MQTT-команды /photo и /sky, поэтому отдельный поток не нужен.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in allowed_chat_ids and message.chat.type != "private":
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        bot.reply_to(message, _USAGE_TEXT)
        return
    prompt = args[1].strip()

    if not cooldowns.allowed(user_id):
        bot.reply_to(message, _COOLDOWN_TEXT)
        return

    if db.get_image_usage_count(user_id) >= IMAGE_GEN_MAX_PER_DAY:
        bot.reply_to(
            message,
            f"Достигнут дневной лимит генерации изображений ({IMAGE_GEN_MAX_PER_DAY} в сутки). "
            "Лимит обновляется в полночь по UTC.",
        )
        return

    working = safe_reply(bot, message, "Генерирую изображение… ⏳")

    try:
        with typing_action(bot, chat_id):
            image_bytes = generate_image(prompt)

        # Only consumed on success, so a failed attempt never costs the user's quota.
        db.increment_image_usage(user_id)
        safe_delete(bot, chat_id, working)
        bot.send_photo(
            chat_id,
            BytesIO(image_bytes),
            reply_to_message_id=message.message_id,
            allow_sending_without_reply=True,
        )
    except ImageContentPolicyError:
        safe_delete(bot, chat_id, working)
        safe_reply(bot, message, "Запрос отклонён модерацией OpenAI — попробуйте переформулировать описание 🙅")
    except ImageQuotaExceededError as e:
        logger.error(f"Image generation quota exceeded: {e}")
        safe_delete(bot, chat_id, working)
        safe_reply(
            bot, message, "Сервис генерации изображений временно недоступен (исчерпана квота). Попробуйте позже."
        )
    except Exception:
        logger.exception("Image generation failed")
        safe_delete(bot, chat_id, working)
        safe_reply(bot, message, "Не удалось сгенерировать изображение 😔")
