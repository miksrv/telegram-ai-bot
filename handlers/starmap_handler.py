"""
Telegram Starmap Handler
Handles star-chart commands (/sky, /horizon, /skymap, /galaxy) by requesting
renders from the starmap-service over MQTT.

The MQTT contract (see the starmap-service API.md) returns two replies per
request: a `queued` acknowledgement followed by a final `ok`/`error`. Waiting
happens in a background daemon thread so the Telegram polling loop is never
blocked (same pattern as /status and /photo).
"""

import base64
import json
import logging
import os
import threading
import time
from io import BytesIO
from queue import Empty

from telebot import TeleBot, types

from config.settings import ADMIN_IDS, STARMAP_COMMAND_TOPIC, STARMAP_IMAGE_DIR, STARMAP_MAX_WAIT
from handlers.delivery import safe_delete, safe_reply
from services.mqtt_service import (
    is_starmap_online,
    register_request,
    send_command,
    unregister_request,
)
from services.weather_service import get_coordinates

logger = logging.getLogger(__name__)

# Status message shown once the service confirms it started working (queued ack).
_WORKING_TEXT = "Начал процесс генерации карты, это может занять несколько минут."

# Compass directions accepted by /horizon (Russian + English aliases → API code).
_DIRECTIONS = {
    "с": "N",
    "n": "N",
    "север": "N",
    "св": "NE",
    "ne": "NE",
    "северо-восток": "NE",
    "в": "E",
    "e": "E",
    "восток": "E",
    "юв": "SE",
    "se": "SE",
    "юго-восток": "SE",
    "ю": "S",
    "s": "S",
    "юг": "S",
    "юз": "SW",
    "sw": "SW",
    "юго-запад": "SW",
    "з": "W",
    "w": "W",
    "запад": "W",
    "сз": "NW",
    "nw": "NW",
    "северо-запад": "NW",
}

# Monotonic counter to keep request_ids unique even within the same second.
_counter_lock = threading.Lock()
_counter = 0


def _next_request_id(map_type: str) -> str:
    global _counter
    with _counter_lock:
        _counter += 1
        n = _counter
    return f"starmap_{map_type}_{int(time.time())}_{n}"


def _access_denied(message: types.Message, allowed_chat_ids: set) -> bool:
    chat_id = message.chat.id
    user_id = message.from_user.id
    return (message.chat.type == "private" and user_id not in ADMIN_IDS) or (
        chat_id not in allowed_chat_ids and message.chat.type != "private"
    )


def _precheck(bot: TeleBot, message: types.Message, allowed_chat_ids: set) -> bool:
    """Access + availability gate shared by every starmap command."""
    if _access_denied(message, allowed_chat_ids):
        bot.reply_to(message, "Доступ запрещён.")
        return False
    if not is_starmap_online():
        bot.reply_to(message, "🛰 Сервис генерации карт сейчас недоступен. Попробуйте позже.")
        return False
    return True


def _resolve_coords(bot: TeleBot, message: types.Message, city: str):
    """Returns (lat, lon) for a city or None (after replying with an error)."""
    try:
        return get_coordinates(city)
    except ValueError:
        bot.reply_to(message, f"Не нашёл город «{city}». Проверьте название.")
    except Exception:
        logger.exception("Geocoding failed for city=%s", city)
        bot.reply_to(message, "Не удалось определить координаты города 😔")
    return None


def _is_allowed_image_path(image_path: str) -> bool:
    """True if `image_path` resolves inside the configured STARMAP_IMAGE_DIR.

    Guards against a compromised service or broker pointing `image_path` at an
    arbitrary host file (which the bot would otherwise read and upload to the
    chat). When STARMAP_IMAGE_DIR is unset, file reads are disabled and only the
    base64 fallback is used. Uses realpath on both sides so symlinks and `..`
    segments cannot escape the allowed directory.
    """
    if not STARMAP_IMAGE_DIR:
        return False
    base = os.path.realpath(STARMAP_IMAGE_DIR)
    resolved = os.path.realpath(image_path)
    return resolved == base or resolved.startswith(base + os.sep)


def _send_chart(bot: TeleBot, message: types.Message, data: dict, caption: str, filename: str) -> None:
    """Delivers the finished chart as a document, replying to the original command.

    Sent as a document (not a compressed photo) so the full-resolution chart
    arrives intact. Supports both the default `file` mode (read image_path from
    the shared filesystem) and the `base64` fallback.
    """
    chat_id = message.chat.id
    image_path = data.get("image_path")
    image_b64 = data.get("image_base64")

    # Reject any path outside the configured shared directory before touching
    # the filesystem; fall back to the base64 payload instead.
    if image_path and not _is_allowed_image_path(image_path):
        logger.warning("Rejected starmap image_path outside STARMAP_IMAGE_DIR: %s", image_path)
        image_path = None

    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                bot.send_document(
                    chat_id,
                    f,
                    reply_to_message_id=message.message_id,
                    caption=caption,
                    visible_file_name=filename,
                    allow_sending_without_reply=True,
                )
            return
        if image_b64:
            bot.send_document(
                chat_id,
                BytesIO(base64.b64decode(image_b64)),
                reply_to_message_id=message.message_id,
                caption=caption,
                visible_file_name=filename,
                allow_sending_without_reply=True,
            )
            return
        if image_path:
            logger.error("starmap image_path not accessible to the bot: %s", image_path)
            safe_reply(bot, message, "Карта сгенерирована, но файл изображения недоступен боту 😕")
            return
        safe_reply(bot, message, "Карта сгенерирована, но изображение отсутствует в ответе 😕")
    except Exception:
        logger.exception("Failed to send starmap chart to Telegram")
        safe_reply(bot, message, "Карта готова, но не удалось её отправить 😕")


def _run(bot: TeleBot, message: types.Message, command: dict, caption: str, filename: str) -> None:
    """Publishes the command and waits for the result in a daemon thread.

    UX (shared with /photo): once the service confirms it started working
    (the `queued` ack), a transient status message is posted as a reply to the
    command. When the chart is ready that status message is deleted and the
    result is posted as a fresh reply to the same command.
    """
    chat_id = message.chat.id
    request_id = command["request_id"]

    # Unbounded queue: the contract delivers a `queued` reply then a final one.
    q = register_request(request_id, maxsize=0)

    if not send_command(command, topic=STARMAP_COMMAND_TOPIC):
        unregister_request(request_id)
        safe_reply(bot, message, "❌ Не удалось отправить запрос на генерацию карты.")
        return

    def wait_and_respond():
        deadline = time.time() + STARMAP_MAX_WAIT
        working = None  # transient "started" status message
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    safe_delete(bot, chat_id, working)
                    safe_reply(bot, message, "⏰ Карта не была сгенерирована вовремя. Попробуйте позже.")
                    return

                try:
                    msg = q.get(timeout=remaining)
                except Empty:
                    safe_delete(bot, chat_id, working)
                    safe_reply(bot, message, "⏰ Карта не была сгенерирована вовремя. Попробуйте позже.")
                    return

                payload_str = msg["payload"]
                try:
                    data = json.loads(payload_str)
                except json.JSONDecodeError:
                    logger.error("Невалидный JSON в ответе starmap: %s", payload_str[:200])
                    continue

                status = data.get("status")
                if status == "queued":
                    if working is None:
                        text = _WORKING_TEXT
                        position = data.get("position", 0)
                        if position:
                            text += f"\nВ очереди перед вами: {position}."
                        working = safe_reply(bot, message, text)
                    continue
                if status == "error":
                    safe_delete(bot, chat_id, working)
                    safe_reply(bot, message, f"❌ {data.get('error', 'Не удалось сгенерировать карту.')}")
                    return
                if status == "ok":
                    safe_delete(bot, chat_id, working)
                    _send_chart(bot, message, data, caption, filename)
                    return

                logger.warning("Неизвестный статус ответа starmap: %s", status)
        finally:
            unregister_request(request_id)

    threading.Thread(target=wait_and_respond, daemon=True).start()


def handle_sky(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """/sky <город> — купол неба над наблюдателем прямо сейчас (map_type: zenith)."""
    if not _precheck(bot, message, allowed_chat_ids):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        bot.reply_to(message, "Использование: /sky <город>\nНапример: /sky Москва")
        return

    city = args[1].strip()
    coords = _resolve_coords(bot, message, city)
    if coords is None:
        return
    lat, lon = coords

    command = {
        "request_id": _next_request_id("zenith"),
        "map_type": "zenith",
        "observer": {"lat": lat, "lon": lon},
    }
    _run(bot, message, command, caption=f"🌌 Небо над «{city}» прямо сейчас", filename="sky.png")


def handle_horizon(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """/horizon <город> [сторона света] — панорама неба у горизонта (map_type: horizon)."""
    if not _precheck(bot, message, allowed_chat_ids):
        return

    tokens = message.text.split()[1:]  # drop the /horizon token
    if not tokens:
        bot.reply_to(
            message,
            "Использование: /horizon <город> [сторона света]\nНапример: /horizon Москва ЮЗ",
        )
        return

    direction = "S"
    # A trailing compass token selects the direction; the rest is the city name.
    # Only consume it when there's also a city left (so "/horizon Юг" stays a city).
    if len(tokens) > 1 and tokens[-1].lower() in _DIRECTIONS:
        direction = _DIRECTIONS[tokens[-1].lower()]
        tokens = tokens[:-1]

    city = " ".join(tokens).strip()
    if not city:
        bot.reply_to(message, "Использование: /horizon <город> [сторона света]")
        return

    coords = _resolve_coords(bot, message, city)
    if coords is None:
        return
    lat, lon = coords

    command = {
        "request_id": _next_request_id("horizon"),
        "map_type": "horizon",
        "observer": {"lat": lat, "lon": lon},
        "options": {"direction": direction},
    }
    _run(
        bot,
        message,
        command,
        caption=f"🌅 Небо у горизонта над «{city}», направление {direction}",
        filename="horizon.png",
    )


def handle_skymap(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """/skymap — полная карта всего неба в координатах RA/DEC (map_type: full)."""
    if not _precheck(bot, message, allowed_chat_ids):
        return

    command = {"request_id": _next_request_id("full"), "map_type": "full"}
    _run(bot, message, command, caption="🗺 Полная карта звёздного неба", filename="skymap.png")


def handle_galaxy(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """/galaxy — карта всего неба в галактических координатах (map_type: galactic)."""
    if not _precheck(bot, message, allowed_chat_ids):
        return

    command = {"request_id": _next_request_id("galactic"), "map_type": "galactic"}
    _run(bot, message, command, caption="🌌 Карта неба в галактических координатах", filename="galaxy.png")
