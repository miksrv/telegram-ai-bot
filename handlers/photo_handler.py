import json
import logging
import threading
import time
import base64
from io import BytesIO
from queue import Empty

from telebot import TeleBot, types
from services.mqtt_service import send_command, register_request, unregister_request
from config.settings import ADMIN_IDS

logger = logging.getLogger(__name__)
MAX_WAIT = 45.0  # больше, чем для телеметрии — фото может дольше


def handle_photo(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает /photo [overlay] — запрашивает фото с CubeSat.
    Ожидание ответа выполняется в фоновом потоке (не блокирует polling).
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверка доступа (как в /status)
    if (message.chat.type == "private" and user_id not in ADMIN_IDS) or \
            (chat_id not in allowed_chat_ids and message.chat.type != "private"):
        bot.reply_to(message, "Доступ запрещён.")
        return

    args = message.text.split()
    overlay = len(args) > 1 and args[1].lower() in ("true", "1", "yes", "overlay")

    bot.reply_to(message, f"Запрашиваю фото с CubeSat... {'с оверлеем' if overlay else ''} ⏳")

    # Генерируем уникальный request_id
    request_id = f"photo_{int(time.time())}"

    # Register queue BEFORE sending the command to avoid missing a fast response
    q = register_request(request_id)

    photo_cmd = {
        "command": "take_photo",
        "request_id": request_id,
        "params": {
            "overlay": overlay
        }
    }

    if not send_command(photo_cmd, topic="cubesat/command"):
        unregister_request(request_id)
        bot.send_message(chat_id, "❌ Не удалось отправить запрос на фото.")
        return

    def wait_and_respond():
        try:
            try:
                msg = q.get(timeout=MAX_WAIT)
            except Empty:
                bot.send_message(chat_id, "⏰ Таймаут: фото не пришло за 45 секунд. Попробуйте позже.")
                return

            payload_str = msg.get("payload")
            try:
                data = json.loads(payload_str)

                if data.get("status") != "SUCCESS":
                    reason = data.get("reason", "Неизвестная ошибка")
                    bot.send_message(chat_id, f"❌ CubeSat не смог сделать фото: {reason}")
                    return

                # Есть фото в base64
                photo_b64 = data.get("photo_base64")
                if not photo_b64:
                    bot.send_message(chat_id, "Фото сделано, но данные изображения отсутствуют 😕")
                    return

                # Декодируем base64 → bytes
                photo_bytes = base64.b64decode(photo_b64)

                # Отправляем фото в чат
                bot.send_photo(
                    chat_id=chat_id,
                    photo=BytesIO(photo_bytes),
                    caption=(
                        f"Фото с CubeSat\n"
                        f"Время: {data.get('taken_at', '—')}\n"
                        f"Размер: {data.get('size_bytes', 0) // 1024} KB"
                    )
                )

            except json.JSONDecodeError:
                logger.error(f"Невалидный JSON в фото-ответе: {payload_str[:200]}...")
                bot.send_message(chat_id, "Получен ответ, но формат некорректный 😕")
            except Exception as e:
                logger.exception("Ошибка обработки фото из MQTT")
                bot.send_message(chat_id, f"Ошибка при получении фото: {str(e)}")
        finally:
            unregister_request(request_id)

    threading.Thread(target=wait_and_respond, daemon=True).start()
