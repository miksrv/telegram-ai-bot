"""
Telegram Image Generation Handler
Handles /image <prompt> by generating an image via OpenAI's Images API
(services/image_service.py) and enforces a persisted per-user daily quota
(database/db.py's image_generation_usage table), in addition to the existing
spam cooldown shared with every other command.
"""

import logging
import threading
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

    Быстрые проверки (чат, промпт, cooldown, атомарное резервирование слота
    дневного лимита) выполняются синхронно здесь же; сам вызов OpenAI — долгая
    операция — выполняется в фоновом потоке, как у /photo, чтобы не занимать
    ограниченный пул воркеров Telegram-диспетчера.
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

    # Atomic check-and-reserve: a single conditional upsert at the DB layer, so
    # two in-flight /image calls from the same user can't both pass the check
    # before either increments (see database/db.py's try_reserve_image_slot).
    if not db.try_reserve_image_slot(user_id, IMAGE_GEN_MAX_PER_DAY):
        bot.reply_to(
            message,
            f"Достигнут дневной лимит генерации изображений ({IMAGE_GEN_MAX_PER_DAY} в сутки). "
            "Лимит обновляется в полночь по UTC.",
        )
        return

    working = safe_reply(bot, message, "Генерирую изображение… ⏳")

    def generate_and_respond():
        try:
            with typing_action(bot, chat_id):
                image_bytes = generate_image(prompt)
        except ImageContentPolicyError:
            db.release_image_usage(user_id)
            safe_delete(bot, chat_id, working)
            safe_reply(bot, message, "Запрос отклонён модерацией OpenAI — попробуйте переформулировать описание 🙅")
            return
        except ImageQuotaExceededError as e:
            logger.error(f"Image generation quota exceeded: {e}")
            db.release_image_usage(user_id)
            safe_delete(bot, chat_id, working)
            safe_reply(
                bot, message, "Сервис генерации изображений временно недоступен (исчерпана квота). Попробуйте позже."
            )
            return
        except Exception:
            logger.exception("Image generation failed")
            db.release_image_usage(user_id)
            safe_delete(bot, chat_id, working)
            safe_reply(bot, message, "Не удалось сгенерировать изображение 😔")
            return

        # Generation succeeded, so the reserved slot stays consumed from here
        # on — including if the send below fails. The alternative (releasing
        # it on a delivery failure) would let a user dodge the quota via a
        # handler that reliably fails delivery, so this is a deliberate
        # trade-off, not an oversight.
        try:
            safe_delete(bot, chat_id, working)
            bot.send_photo(
                chat_id,
                BytesIO(image_bytes),
                reply_to_message_id=message.message_id,
                allow_sending_without_reply=True,
            )
        except Exception:
            logger.exception("Failed to send generated image")
            safe_reply(
                bot,
                message,
                "Изображение сгенерировано, но не удалось отправить — попытка учтена в дневном лимите 😔",
            )

    threading.Thread(target=generate_and_respond, daemon=True).start()
