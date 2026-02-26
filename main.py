"""
Main entry point for TARS Telegram Bot
Initializes all services and starts polling
"""

import logging
import signal
import sys
import os
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.telegram_service import init_bot
from config.settings import ALLOWED_CHAT_IDS
from services.mqtt_service import start_mqtt

# --- Graceful shutdown handler ---
def shutdown(signum, frame):
    logging.info("Shutting down TARS...")
    sys.exit(0)


# --- Signal registration ---
signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# --- Main ---
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logging.info("TARS v1.1 Systems Online")
    logging.info(f"Allowed Chats: {len(ALLOWED_CHAT_IDS)}")

    start_mqtt(background=True)

    bot = init_bot()

    # --- Start polling ---
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.critical(f"Critical Crash: {e}")
            time.sleep(10)
