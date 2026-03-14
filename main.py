"""
Main entry point for TARS Telegram Bot
Initializes all services and starts polling
"""

import logging
import os
from dotenv import load_dotenv

# Load .env and configure logging before any other import.
# This ensures basicConfig takes effect for module-level log calls made
# during import, and that LOG_LEVEL from .env is respected.
load_dotenv()

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

import signal
import sys
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.telegram_service import init_bot
from config.settings import (
    ALLOWED_CHAT_IDS,
    PROACTIVE_ENABLED,
    PROACTIVE_CHAT_IDS,
    CLEANUP_LOOP_INTERVAL_SECONDS,
    PROACTIVE_LOOP_INTERVAL_SECONDS,
)
from services.mqtt_service import start_mqtt, stop_mqtt
from core.memory import memory
from database.db import close_connection

# --- Graceful shutdown handler ---
def shutdown(signum, frame):
    logging.info("Shutting down TARS...")
    memory.flush()
    stop_mqtt()
    close_connection()
    sys.exit(0)


# --- Signal registration ---
signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# --- Main ---
if __name__ == "__main__":
    logging.info("TARS v1.1 Systems Online")
    logging.info(f"Allowed Chats: {len(ALLOWED_CHAT_IDS)}")

    if not start_mqtt(background=True):
        logging.warning("MQTT unavailable — /status and /photo commands will not work")

    bot = init_bot()

    # --- Proactive Engagement ---
    if PROACTIVE_ENABLED:
        from core.proactive_engine import proactive_engine
        from services.background_service import start_cleanup_loop, start_proactive_loop
        start_cleanup_loop(CLEANUP_LOOP_INTERVAL_SECONDS)
        start_proactive_loop(bot, PROACTIVE_CHAT_IDS, proactive_engine, PROACTIVE_LOOP_INTERVAL_SECONDS)
        logging.info(f"Proactive engagement active for {len(PROACTIVE_CHAT_IDS)} chat(s)")

    # --- Start polling ---
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.critical(f"Critical Crash: {e}")
            time.sleep(10)
