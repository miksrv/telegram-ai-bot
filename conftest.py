import os
import sys
from unittest.mock import MagicMock

# Must be set before any project module is imported.
# config/settings.py calls require_env() at import time, so these must exist
# in os.environ before the first import of any project module.
# In CI these are also set at the job level in checks.yml / sonarcloud.yml.
os.environ.setdefault("BOT_TOKEN", "fake_bot_token_for_testing")
os.environ.setdefault("GROQ_API_KEY", "fake_groq_key")
os.environ.setdefault("WEATHER_API_KEY", "fake_weather_key")
os.environ.setdefault("ALLOWED_CHAT_IDS", "-100123456789")
os.environ.setdefault("ADMIN_IDS", "123456789")

# Pinned so a developer's local .env (LLM_ENGINE/OPENAI_API_KEY, gitignored,
# not present in CI) can't leak into test runs and change engine/fallback
# behavior the tests assert on. config/settings.py's load_dotenv() never
# overrides variables already set here.
os.environ.setdefault("LLM_ENGINE", "groq")
os.environ.setdefault("OPENAI_API_KEY", "")

# Stub out telebot if the package is not installed (e.g. running tests without
# the full venv). In CI requirements.txt is installed so the real package is used.
if "telebot" not in sys.modules:
    _telebot_stub = MagicMock()
    sys.modules["telebot"] = _telebot_stub
    sys.modules["telebot.types"] = _telebot_stub.types

# Stub out paho-mqtt the same way for environments without the full venv, so
# services.mqtt_service can be imported in tests. In CI the real package is used.
if "paho" not in sys.modules:
    _paho_stub = MagicMock()
    sys.modules["paho"] = _paho_stub
    sys.modules["paho.mqtt"] = _paho_stub.mqtt
    sys.modules["paho.mqtt.client"] = _paho_stub.mqtt.client
