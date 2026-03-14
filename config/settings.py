import os
import logging
from typing import Set
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"ENV variable {name} is not set")
    return value

def parse_chat_ids(raw: str) -> Set[int]:
    try:
        return {int(x.strip()) for x in raw.split(",") if x.strip()}
    except ValueError:
        logging.error("Invalid ALLOWED_CHAT_IDS format")
        return set()

# --------------------------------------------------
# Environment Variables
# --------------------------------------------------

BOT_TOKEN = require_env("BOT_TOKEN")
GROQ_API_KEY = require_env("GROQ_API_KEY")
WEATHER_API_KEY = require_env("WEATHER_API_KEY")
ALLOWED_CHAT_IDS = parse_chat_ids(require_env("ALLOWED_CHAT_IDS"))
ADMIN_IDS = parse_chat_ids(require_env("ADMIN_IDS"))

# --------------------------------------------------
# Models
# --------------------------------------------------

MODEL_TEXT = "llama-3.3-70b-versatile"
MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"

# --------------------------------------------------
# Limits / Behavior
# --------------------------------------------------

MAX_INPUT_CHARS = 1500
MAX_CONTEXT_MESSAGES = 10
MEMORY_LIMIT = 50
MEMORY_TTL_SECONDS = 3600 * 24

# --------------------------------------------
# Additional rate limit parameters
# (can be moved to settings later)
# --------------------------------------------

RATE_LIMIT_COUNT = 2
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_PENALTY = 180
USER_COOLDOWN_SECONDS = 10

# --------------------------------------------------
# MQTT Settings
# --------------------------------------------------

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

# --------------------------------------------------
# Database
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

DB_PATH = os.path.join(
    BASE_DIR,
    "data",
    "tars_user_profiles.db"
)

# --------------------------------------------------
# Allowed shell commands
# --------------------------------------------------

ALLOWED_COMMANDS = {
    "status": True
}

# --------------------------------------------------
# Proactive Engagement
# --------------------------------------------------

PROACTIVE_ENABLED             = os.getenv("PROACTIVE_ENABLED", "true").lower() == "true"
_proactive_parsed             = parse_chat_ids(os.getenv("PROACTIVE_CHAT_IDS", ""))
PROACTIVE_CHAT_IDS            = _proactive_parsed & ALLOWED_CHAT_IDS
_dropped                      = _proactive_parsed - ALLOWED_CHAT_IDS
if _dropped:
    logging.warning("Proactive chat IDs not in ALLOWED_CHAT_IDS (ignored): %s", _dropped)
PROACTIVE_MAX_PER_DAY         = int(os.getenv("PROACTIVE_MAX_PER_DAY", "5"))
PROACTIVE_MIN_GAP_SECONDS     = int(os.getenv("PROACTIVE_MIN_GAP_SECONDS", "3600"))
PROACTIVE_NEXT_MIN_SECONDS    = int(os.getenv("PROACTIVE_NEXT_MIN_SECONDS", "7200"))
PROACTIVE_NEXT_MAX_SECONDS    = int(os.getenv("PROACTIVE_NEXT_MAX_SECONDS", "14400"))
PROACTIVE_CONTEXT_MESSAGES    = int(os.getenv("PROACTIVE_CONTEXT_MESSAGES", "25"))
PROACTIVE_MIN_CONTEXT_MESSAGES = int(os.getenv("PROACTIVE_MIN_CONTEXT_MESSAGES", "10"))
PROACTIVE_MIN_WORD_COUNT      = int(os.getenv("PROACTIVE_MIN_WORD_COUNT", "3"))
PROACTIVE_MIN_CHAR_COUNT      = int(os.getenv("PROACTIVE_MIN_CHAR_COUNT", "15"))
MESSAGE_TTL_SECONDS           = int(os.getenv("MESSAGE_TTL_SECONDS", "86400"))
CLEANUP_LOOP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_LOOP_INTERVAL_SECONDS", "1800"))
PROACTIVE_LOOP_INTERVAL_SECONDS = int(os.getenv("PROACTIVE_LOOP_INTERVAL_SECONDS", "600"))