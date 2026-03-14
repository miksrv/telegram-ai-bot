""" Telegram Status Handler
Handles /status command — fetches real CubeSat telemetry via MQTT
"""

import json
import logging
import threading
import time
from datetime import datetime
from queue import Empty

from telebot import TeleBot, types
from services.mqtt_service import send_command, register_request, unregister_request
from config.settings import ADMIN_IDS

MAX_WAIT = 30.0

logger = logging.getLogger(__name__)


def handle_status(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Обрабатывает команду /status:
    - Запрашивает телеметрию у CubeSat через MQTT
    - Ожидает ответ в фоновом потоке (не блокирует polling)
    - Отправляет полученные данные пользователю
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверка прав доступа
    if (message.chat.type == "private" and user_id not in ADMIN_IDS) or \
            (chat_id not in allowed_chat_ids and message.chat.type != "private"):
        bot.reply_to(message, "Доступ запрещён.")
        return

    bot.reply_to(message, "Запрашиваю актуальную телеметрию CubeSat... ⏳")

    request_id = str(int(time.time()))

    # Register queue BEFORE sending the command to avoid missing a fast response
    q = register_request(request_id)

    if not send_command({"command": "get_telemetry", "request_id": request_id}, topic="cubesat/command"):
        unregister_request(request_id)
        bot.send_message(chat_id, "❌ Не удалось отправить запрос телеметрии.")
        return

    def wait_and_respond():
        try:
            try:
                msg = q.get(timeout=MAX_WAIT)
            except Empty:
                bot.send_message(chat_id, "⏰ Таймаут: телеметрия не пришла за 30 секунд. Попробуйте позже.")
                return

            payload_str = msg["payload"]
            try:
                data = json.loads(payload_str)
                status_text = format_telemetry_for_telegram(data)
                bot.send_message(
                    chat_id,
                    status_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except json.JSONDecodeError:
                logger.error(f"Невалидный JSON в телеметрии: {payload_str[:200]}...")
                bot.send_message(chat_id, "Получены данные, но формат некорректный 😕")
            except Exception as e:
                logger.exception("Ошибка обработки телеметрии")
                bot.send_message(chat_id, f"Ошибка при обработке ответа: {str(e)}")
        finally:
            unregister_request(request_id)

    threading.Thread(target=wait_and_respond, daemon=True).start()


# ──────────────────────────────────────────────────────────────
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
        if "external_power" in eps: lines.append(f"  ☀️ Внешнее питание: {eps['external_power']}")

    # ADCS (ориентация)
    if "adcs" in data:
        adcs = data["adcs"]
        lines.append("\n*ADCS:*")
        if "roll"  in adcs: lines.append(f" • Roll:  {adcs['roll']:.2f}°")
        if "pitch" in adcs: lines.append(f" • Pitch: {adcs['pitch']:.2f}°")
        if "yaw"   in adcs: lines.append(f" • Yaw:   {adcs['yaw']:.2f}°")
        if "accel_g" in adcs:
            accel = adcs["accel_g"]
            lines.append(f" • Accel (g): {accel.get('x', '—')}/{accel.get('y', '—')}/{accel.get('z', '—')}")
        if "gyro_dps" in adcs:
            gyro = adcs["gyro_dps"]
            lines.append(f" • Gyro (°/s): {gyro.get('x', '—')}/{gyro.get('y', '—')}/{gyro.get('z', '—')}")

    # Payload (если есть)
    if "payload" in data:
        pl = data["payload"]
        lines.append("\n*Payload:*")
        if "temperature" in pl: lines.append(f" • Temperature: {pl['temperature']} °C")
        if "humidity" in pl: lines.append(f" • Humidity: {pl['humidity']} %")
        if "pressure" in pl: lines.append(f" • Pressure: {pl['pressure']} hPa")

    # Системные метрики (если передаются)
    if "system" in data:
        sys = data["system"]
        lines.append("\n*System (RPi):*")
        if "cpu_percent" in sys: lines.append(f" • CPU: {sys['cpu_percent']:.1f}%")
        if "ram_percent" in sys: lines.append(f" • RAM: {sys['ram_percent']:.1f}%")
        if "swap_percent" in sys: lines.append(f" • Swap: {sys['swap_percent']:.1f}%")
        if "disk_percent" in sys: lines.append(f" • Disk: {sys['disk_percent']:.1f}%")
        if "uptime_seconds" in sys:
            uptime_hours = sys["uptime_seconds"] // 3600
            uptime_minutes = (sys["uptime_seconds"] % 3600) // 60
            lines.append(f" • Uptime: {int(uptime_hours)}h {int(uptime_minutes)}m")
        if "cpu_temperature" in sys: lines.append(f" • CPU Temp: {sys['cpu_temperature']} °C")

    if len(lines) <= 2:
        return "Получена телеметрия, но данных для отображения нет 😔"

    return "\n".join(lines)
