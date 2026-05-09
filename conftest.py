import os
import sys
from unittest.mock import MagicMock

# Must be set before any project module is imported.
# config/settings.py calls require_env() at import time, so these must exist
# in os.environ before the first import of any project module.
# In CI these are also set at the job level in ci.yml.
os.environ.setdefault("BOT_TOKEN", "fake_bot_token_for_testing")
os.environ.setdefault("GROQ_API_KEY", "fake_groq_key")
os.environ.setdefault("WEATHER_API_KEY", "fake_weather_key")
os.environ.setdefault("ALLOWED_CHAT_IDS", "-100123456789")
os.environ.setdefault("ADMIN_IDS", "123456789")

# Stub out telebot if the package is not installed (e.g. running tests without
# the full venv). In CI requirements.txt is installed so the real package is used.
if "telebot" not in sys.modules:
    _telebot_stub = MagicMock()
    sys.modules["telebot"] = _telebot_stub
    sys.modules["telebot.types"] = _telebot_stub.types
