import logging
import os
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
WEATHER_API_KEY = require_env("WEATHER_API_KEY")
ALLOWED_CHAT_IDS = parse_chat_ids(require_env("ALLOWED_CHAT_IDS"))
ADMIN_IDS = parse_chat_ids(require_env("ADMIN_IDS"))

# --------------------------------------------------
# LLM Engine
# --------------------------------------------------
# Selects which cloud LLM core/llm powers the bot with. Only the API key for
# the active engine is required; the other provider's key may be left blank.
# Add a new provider by adding a file under core/llm/ implementing
# LLMProvider and registering it in core/llm/engine.py's _PROVIDERS dict.

LLM_ENGINE = os.getenv("LLM_ENGINE", "groq").strip().lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if LLM_ENGINE not in ("groq", "openai"):
    raise RuntimeError(f"Unknown LLM_ENGINE '{LLM_ENGINE}', expected 'groq' or 'openai'")
if LLM_ENGINE == "groq" and not GROQ_API_KEY:
    raise RuntimeError("LLM_ENGINE=groq requires GROQ_API_KEY to be set")
if LLM_ENGINE == "openai" and not OPENAI_API_KEY:
    raise RuntimeError("LLM_ENGINE=openai requires OPENAI_API_KEY to be set")

GROQ_MODEL_TEXT = os.getenv("GROQ_MODEL_TEXT", "llama-3.3-70b-versatile")
GROQ_MODEL_VISION = os.getenv("GROQ_MODEL_VISION", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENAI_MODEL_TEXT = os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini")
OPENAI_MODEL_VISION = os.getenv("OPENAI_MODEL_VISION", "gpt-4o-mini")

# --------------------------------------------------
# Limits / Behavior
# --------------------------------------------------

MAX_INPUT_CHARS = 1500
MAX_CONTEXT_MESSAGES = 10
MEMORY_LIMIT = 50
MEMORY_TTL_SECONDS = 3600 * 24

# Weight of the freshest sample in the behavioral profile's exponential
# moving average (0..1). Higher = more reactive to recent behavior.
PROFILE_EMA_ALPHA = float(os.getenv("PROFILE_EMA_ALPHA", "0.3"))

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
# Starmap service (MQTT star-chart generation)
# --------------------------------------------------
# Shared MQTT contract with the starmap-service repository (its API.md is the
# single source of truth). The bot publishes render requests and receives a
# `queued` acknowledgement followed by a final `ok`/`error` reply, plus a
# retained availability status on STARMAP_STATUS_TOPIC.

STARMAP_COMMAND_TOPIC = "starmap/command"
STARMAP_RESULT_TOPIC = "starmap/result"
STARMAP_STATUS_TOPIC = "starmap/status"

# Total time to wait for a finished chart (queued ack + render). The service
# targets ~90–120s on the Raspberry Pi, so allow a generous margin.
STARMAP_MAX_WAIT = int(os.getenv("STARMAP_MAX_WAIT", "120"))

# Directory the starmap-service writes rendered charts into, shared with the
# bot host. `image_path` values in starmap results are validated against this
# directory (realpath + prefix check) before being read, so a compromised
# service or broker cannot point the bot at arbitrary host files. When unset,
# file reads are disabled and only the base64 fallback is used.
STARMAP_IMAGE_DIR = os.getenv("STARMAP_IMAGE_DIR", "")

# When true, the bot deletes the rendered chart file from STARMAP_IMAGE_DIR after
# it has been successfully delivered to Telegram, so charts don't accumulate on
# disk. Only applies to the `file` mode (image_path); the base64 fallback has no
# file to remove. Deletion is best-effort and only the file that was just sent is
# removed (path already validated against STARMAP_IMAGE_DIR). (default: false)
STARMAP_DELETE_AFTER_SEND = os.getenv("STARMAP_DELETE_AFTER_SEND", "false").lower() == "true"

# --------------------------------------------------
# Database
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

DB_PATH = os.path.join(BASE_DIR, "data", "tars_user_profiles.db")

# --------------------------------------------------
# Allowed shell commands
# --------------------------------------------------

ALLOWED_COMMANDS = {"status": True}

# --------------------------------------------------
# Proactive Engagement
# --------------------------------------------------

PROACTIVE_ENABLED = os.getenv("PROACTIVE_ENABLED", "true").lower() == "true"
_proactive_parsed = parse_chat_ids(os.getenv("PROACTIVE_CHAT_IDS", ""))
PROACTIVE_CHAT_IDS = _proactive_parsed & ALLOWED_CHAT_IDS
_dropped = _proactive_parsed - ALLOWED_CHAT_IDS
if _dropped:
    logging.warning("Proactive chat IDs not in ALLOWED_CHAT_IDS (ignored): %s", _dropped)
PROACTIVE_MAX_PER_DAY = int(os.getenv("PROACTIVE_MAX_PER_DAY", "5"))
PROACTIVE_MIN_GAP_SECONDS = int(os.getenv("PROACTIVE_MIN_GAP_SECONDS", "3600"))
PROACTIVE_NEXT_MIN_SECONDS = int(os.getenv("PROACTIVE_NEXT_MIN_SECONDS", "7200"))
PROACTIVE_NEXT_MAX_SECONDS = int(os.getenv("PROACTIVE_NEXT_MAX_SECONDS", "14400"))
PROACTIVE_CONTEXT_MESSAGES = int(os.getenv("PROACTIVE_CONTEXT_MESSAGES", "25"))
PROACTIVE_MIN_CONTEXT_MESSAGES = int(os.getenv("PROACTIVE_MIN_CONTEXT_MESSAGES", "10"))
PROACTIVE_MIN_WORD_COUNT = int(os.getenv("PROACTIVE_MIN_WORD_COUNT", "3"))
PROACTIVE_MIN_CHAR_COUNT = int(os.getenv("PROACTIVE_MIN_CHAR_COUNT", "15"))

# Once-daily direct reply to a specific past message (in addition to the
# general proactive posts above). Target selection happens in Python/SQL, not
# via the LLM, so only one API call (the reply itself) is ever spent on it.
PROACTIVE_REPLY_ENABLED = os.getenv("PROACTIVE_REPLY_ENABLED", "true").lower() == "true"
PROACTIVE_REPLY_MAX_PER_DAY = int(os.getenv("PROACTIVE_REPLY_MAX_PER_DAY", "1"))
# Minimum word count for a message to qualify as a reply target — deliberately
# higher than PROACTIVE_MIN_WORD_COUNT so a two-word message is never picked.
PROACTIVE_REPLY_MIN_WORD_COUNT = int(os.getenv("PROACTIVE_REPLY_MIN_WORD_COUNT", "8"))
# Random delay window (from UTC midnight) before the daily reply becomes
# eligible to fire, so it doesn't always land right after the day resets.
PROACTIVE_REPLY_MIN_DELAY_SECONDS = int(os.getenv("PROACTIVE_REPLY_MIN_DELAY_SECONDS", "3600"))
PROACTIVE_REPLY_MAX_DELAY_SECONDS = int(os.getenv("PROACTIVE_REPLY_MAX_DELAY_SECONDS", "43200"))

MESSAGE_TTL_SECONDS = int(os.getenv("MESSAGE_TTL_SECONDS", "86400"))
CLEANUP_LOOP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_LOOP_INTERVAL_SECONDS", "1800"))
PROACTIVE_LOOP_INTERVAL_SECONDS = int(os.getenv("PROACTIVE_LOOP_INTERVAL_SECONDS", "600"))
