import os
import logging
from typing import Set
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

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