# TARS — Telegram AI Bot

TARS is a Telegram bot for the Russian astronomy community, named after the AI from *Interstellar*. It combines a conversational AI assistant (powered by Groq) with a CubeSat satellite ground station interface over MQTT.

---

## Features

- **Conversational AI** — responds to mentions ("tars", "TARS", "тарс") and replies in group chats; uses Groq's LLaMA models for text and vision
- **Adaptive personality** — tracks per-user behavioral metrics (off-topic rate, rudeness, verbosity, etc.) and adjusts response style automatically
- **User profiles** — persists interests, behavioral scores, and LLM-maintained notes per user in SQLite
- **CubeSat telemetry** — `/status` fetches live telemetry from a connected CubeSat via MQTT and displays it in a formatted message
- **CubeSat photo** — `/photo` requests a photo from the CubeSat payload camera, received as base64 over MQTT and sent directly to the chat
- **Image analysis** — analyzes photos posted in the chat with astronomical context awareness
- **Weather** — `/weather <city>` fetches current weather from OpenWeatherMap
- **Rate limiting** — per-user sliding window rate limiter with configurable penalty cooldowns

---

## Project Structure

```
telegram-ai-bot/
├── main.py                      # Entry point
├── config/
│   └── settings.py              # All configuration (loaded from .env)
├── core/
│   ├── brain.py                 # LLM calls, memory and profile updates
│   ├── memory.py                # In-RAM conversation context manager
│   ├── prompts.py               # System prompt templates
│   ├── personality_engine.py    # Per-user adaptive behavior rules
│   └── cooldown.py              # Rate limiter
├── database/
│   ├── db.py                    # SQLite operations (user_profile table)
│   └── profile_repo.py          # Repository layer
├── handlers/
│   ├── message_handler.py       # Main message routing
│   ├── status_handler.py        # /status command (CubeSat telemetry)
│   ├── photo_handler.py         # /photo command (CubeSat camera)
│   └── weather_handler.py       # /weather command
├── services/
│   ├── telegram_service.py      # Bot initialization and handler registration
│   ├── mqtt_service.py          # MQTT client and message queue
│   └── weather_service.py       # OpenWeatherMap API client
└── utils/
    ├── triggers.py              # Trigger word detection
    ├── identity.py              # Telegram identity extraction
    └── photo.py                 # Telegram photo URL extraction
```

---

## Requirements

- Python 3.10+
- A Groq API key (free tier available)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An OpenWeatherMap API key
- An MQTT broker (e.g., Mosquitto) running locally on port 1883 for CubeSat features

---

## Installation

1. **Clone the repository:**
   ```sh
   git clone https://github.com/yourusername/telegram-ai-bot.git
   cd telegram-ai-bot
   ```

2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

3. **Create a `.env` file** in the project root:
   ```env
   BOT_TOKEN=your_telegram_bot_token
   GROQ_API_KEY=your_groq_api_key
   WEATHER_API_KEY=your_openweathermap_api_key
   ALLOWED_CHAT_IDS=-1001234567890,-1009876543210
   ADMIN_IDS=123456789
   ```

4. **Create the data directory:**
   ```sh
   mkdir -p data
   ```

5. **Run the bot:**
   ```sh
   python main.py
   ```
   The SQLite database (`data/tars_user_profiles.db`) is created automatically on first run.

---

## Configuration

All configuration is in `config/settings.py`, loaded from environment variables.

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram bot token from BotFather |
| `GROQ_API_KEY` | Yes | Groq API key |
| `WEATHER_API_KEY` | Yes | OpenWeatherMap API key |
| `ALLOWED_CHAT_IDS` | Yes | Comma-separated list of authorized group chat IDs |
| `ADMIN_IDS` | Yes | Comma-separated list of admin Telegram user IDs |

**Behavioral tuning (edit `settings.py` directly):**

| Setting | Default | Description |
|---------|---------|-------------|
| `USER_COOLDOWN_SECONDS` | `10` | Minimum seconds between responses per user |
| `RATE_LIMIT_COUNT` | `2` | Max messages per rate limit window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |
| `RATE_LIMIT_PENALTY` | `180` | Lockout duration after rate limit breach |
| `MAX_CONTEXT_MESSAGES` | `10` | Chat messages included in LLM context |
| `MAX_INPUT_CHARS` | `1500` | Max characters accepted from user input |
| `MEMORY_TTL_SECONDS` | `86400` | Seconds before inactive chat memory is evicted |

---

## Commands

| Command | Access | Description |
|---------|--------|-------------|
| `tars <message>` | All allowed chats | Mention the bot to start a conversation |
| `/status` | Allowed chats + admins | Fetch live CubeSat telemetry |
| `/photo [overlay]` | Allowed chats + admins | Request a photo from the CubeSat camera |
| `/weather <city>` | Allowed chats + admins | Get current weather for a city |

The bot also responds when users reply directly to any of its messages.

---

## MQTT Integration

The bot connects to a local MQTT broker (`localhost:1883`) and uses the following topics:

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `cubesat/command` | Publish | Send commands to the CubeSat OBC |
| `cubesat/telemetry/data` | Subscribe | Receive telemetry responses |
| `cubesat/payload/photo` | Subscribe | Receive photo responses |

Command format (JSON):
```json
{"command": "get_telemetry", "request_id": "1741000000"}
{"command": "take_photo",    "request_id": "photo_1741000000", "params": {"overlay": false}}
```

If no MQTT broker is available, the bot will log an error and continue running — only the `/status` and `/photo` commands will be non-functional.

---

## Access Control

- The bot only responds in chats listed in `ALLOWED_CHAT_IDS`
- In private chats, only users listed in `ADMIN_IDS` receive responses
- Unauthorized mentions in other groups receive a redirect message pointing to @astronom_chat

---

## Troubleshooting

**Bot doesn't respond in a group**
- Confirm the group's chat ID is in `ALLOWED_CHAT_IDS` (use `@userinfobot` to find it)
- Ensure the bot has been added to the group and has permission to read messages

**`ModuleNotFoundError: No module named 'services'`**
- Run the bot from the project root directory, not from a subdirectory

**`RuntimeError: ENV variable X is not set`**
- Check your `.env` file — all five required variables must be present

**MQTT connection failed**
- Verify Mosquitto (or another broker) is running: `mosquitto -v`
- Default broker is `localhost:1883` — change `MQTT_BROKER` / `MQTT_PORT` in `settings.py` if needed

**`/status` or `/photo` times out**
- Confirm the CubeSat OBC is powered on and connected to the same broker
- Check that it publishes to the correct response topics with a matching `request_id`

---

## License

MIT License
