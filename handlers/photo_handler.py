import json
import logging
import time
import base64
from io import BytesIO
from telebot import TeleBot, types
from services.mqtt_service import send_command, get_incoming_message
from config.settings import ADMIN_IDS

logger = logging.getLogger(__name__)
MAX_WAIT = 45.0  # больше, чем для телеметрии — фото может дольше

def handle_photo(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает /photo [overlay] — запрашивает фото с CubeSat
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверка доступа (как в /status)
    if message.chat.type == "private" and user_id not in ADMIN_IDS:
        bot.reply_to(message, "Доступ запрещён.")
        return

    args = message.text.split()
    overlay = len(args) > 1 and args[1].lower() in ("true", "1", "yes", "overlay")

    bot.reply_to(message, f"Запрашиваю фото с CubeSat... {'с оверлеем' if overlay else ''} ⏳")

    # Генерируем уникальный request_id
    request_id = f"photo_{int(time.time())}"

    # Отправляем команду
    photo_cmd = {
        "action": "cubesat/command/photo",
        "request_id": request_id,
        "params": {
            "overlay": overlay
        }
    }

    if not send_command(photo_cmd, topic="cubesat/command/photo"):
        bot.send_message(chat_id, "❌ Не удалось отправить запрос на фото.")
        return

    # Ожидание ответа в cubesat/payload/photo
    start = time.time()
    received = False

    while time.time() - start < MAX_WAIT:
        msg = get_incoming_message(timeout=0.8)
        if msg is None:
            time.sleep(0.2)
            continue

        topic = msg.get("topic")
        payload_str = msg.get("payload")

        if topic == "cubesat/payload/photo":
            try:
                data = json.loads(payload_str)
                if str(data.get("request_id")) != request_id:
                    continue  # не наш ответ

                if data.get("status") != "ok":
                    reason = data.get("reason", "Неизвестная ошибка")
                    bot.send_message(chat_id, f"❌ CubeSat не смог сделать фото: {reason}")
                    received = True
                    break

                # Есть фото в base64
                photo_b64 = data.get("photo_base64")
                if not photo_b64:
                    bot.send_message(chat_id, "Фото сделано, но данные изображения отсутствуют 😕")
                    received = True
                    break

                # Декодируем base64 → bytes
                photo_bytes = base64.b64decode(photo_b64)

                # Отправляем фото в чат
                bot.send_photo(
                    chat_id=chat_id,
                    photo=BytesIO(photo_bytes),
                    caption=(
                        f"Фото с CubeSat\n"
                        f"Время: {data.get('taken_at', '—')}\n"
                        f"Размер: {data.get('size_bytes', 0) // 1024} KB\n"
                        f"Путь на борту: {data.get('path', '—')}"
                    )
                )
                received = True
                break

            except json.JSONDecodeError:
                logger.error(f"Невалидный JSON в фото-ответе: {payload_str[:200]}...")
                bot.send_message(chat_id, "Получен ответ, но формат некорректный 😕")
                received = True
                break
            except Exception as e:
                logger.exception("Ошибка обработки фото из MQTT")
                bot.send_message(chat_id, f"Ошибка при получении фото: {str(e)}")
                received = True
                break

    if not received:
        bot.send_message(chat_id, "⏰ Таймаут: фото не пришло за 45 секунд. Попробуйте позже.")