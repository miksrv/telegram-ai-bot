""" Telegram Status Handler
Handles /status command — now fetches real CubeSat telemetry via MQTT
"""

import json
import logging
import time
from datetime import datetime, timezone
from telebot import TeleBot, types
from services.mqtt_service import send_command, get_incoming_message
from config.settings import ADMIN_IDS

MAX_WAIT = 30.0

logger = logging.getLogger(__name__)

def handle_status(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает команду /status:
    - Запрашивает телеметрию у CubeSat через MQTT
    - Ждёт и отправляет полученные данные пользователю
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверка прав доступа
    if (message.chat.type == "private" and user_id not in ADMIN_IDS) or \
            (chat_id not in allowed_chat_ids and message.chat.type != "private"):
        bot.reply_to(message, "Доступ запрещён.")
        return

    # Сообщение о начале запроса
    bot.reply_to(message, "Запрашиваю актуальную телеметрию CubeSat... ⏳")

    # Шаг 1: Отправка команды на получение телеметрии
    telemetry_cmd = {
        "action": "cubesat/command/telemetry",
        "request_id": str(int(time.time())),
        "params": {}
    }

    if not send_command(telemetry_cmd, topic="cubesat/command/telemetry"):
        bot.send_message(chat_id, "❌ Не удалось отправить запрос телеметрии.")
        return

    # Шаг 2: Ожидание ответа (максимум 25–30 секунд)
    start = time.time()
    received = False

    while time.time() - start < MAX_WAIT:
        msg = get_incoming_message(timeout=0.8)

        if msg is None:
            time.sleep(0.2)
            continue

        topic = msg["topic"]
        payload_str = msg["payload"]

        # Проверяем, что это именно ответ с телеметрией
        if topic in ["cubesat/telemetry/data"]:
            try:
                data = json.loads(payload_str)

                # Форматируем красивый ответ
                status_text = format_telemetry_for_telegram(data)

                bot.send_message(
                    chat_id,
                    status_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                received = True
                break

            except json.JSONDecodeError:
                logger.error(f"Невалидный JSON в телеметрии: {payload_str[:200]}...")
                bot.send_message(chat_id, "Получены данные, но формат некорректный 😕")
                received = True
                break

            except Exception as e:
                logger.exception("Ошибка обработки телеметрии")
                bot.send_message(chat_id, f"Ошибка при обработке ответа: {str(e)}")
                received = True
                break

    if not received:
        bot.send_message(chat_id, "⏰ Таймаут: телеметрия не пришла за 30 секунд. Попробуйте позже.")

# ──────────────────────────────────────────────────────────────
# Пример функции форматирования (адаптируй под реальную структуру твоей телеметрии)
def format_telemetry_for_telegram(data: dict) -> str:
    """
    Преобразует словарь телеметрии в читаемый Markdown-текст для Telegram
    """
    lines = ["*Статус CubeSat* 🚀\n"]

    # Общее состояние
    if "state" in data or "obc_state" in data:
        state = data.get("state") or data.get("obc_state", "—")
        lines.append(f"• Состояние OBC: **{state}**")

    # Время
    if "timestamp" in data:
        iso_ts = data["timestamp"]
        try:
            # Парсим ISO8601 (с поддержкой Z)
            if iso_ts.endswith("Z"):
                dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(iso_ts)
            # Преобразуем в локальное время
            local_dt = dt.astimezone()
            formatted = local_dt.strftime("%d.%m.%Y %H:%M:%S")
            lines.append(f"• Время: {formatted}")
        except Exception:
            lines.append(f"• Время: {iso_ts}")

    # EPS (энергетика)
    if "eps" in data:
        eps = data["eps"]
        lines.append("\n*EPS:*")
        if "battery" in eps:     lines.append(f"  🔋 Заряд: {eps['battery']}%")
        if "voltage" in eps:     lines.append(f"  ⚡ Напряжение: {eps['voltage']} V")
        if "solar_power" in eps: lines.append(f"  ☀️ Солнечная мощность: {eps['solar_power']} mW")

    # ADCS (ориентация)
    if "adcs" in data:
        adcs = data["adcs"]
        lines.append("\n*ADCS:*")
        if "roll"  in adcs: lines.append(f"  Roll:  {adcs['roll']:.2f}°")
        if "pitch" in adcs: lines.append(f"  Pitch: {adcs['pitch']:.2f}°")
        if "yaw"   in adcs: lines.append(f"  Yaw:   {adcs['yaw']:.2f}°")

    # Payload (если есть)
    if "payload" in data:
        pl = data["payload"]
        lines.append("\n*Payload:*")
        if "temperature" in pl: lines.append(f"  Температура: {pl['temperature']} °C")
        # ... добавь свои поля

    # Системные метрики (если передаются)
    if "system" in data:
        sys = data["system"]
        lines.append("\n*Система (RPi):*")
        if "cpu_percent" in sys: lines.append(f"  CPU: {sys['cpu_percent']:.1f}%")
        if "cpu_temperature_c" in sys: lines.append(f"  Temp: {sys['cpu_temperature_c']} °C")

    if len(lines) <= 2:
        return "Получена телеметрия, но данных для отображения нет 😔"

    return "\n".join(lines)