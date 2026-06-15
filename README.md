# TARS - Telegram AI Bot

TARS is a Telegram bot for the Russian astronomy community, named after the AI from *Interstellar*. It combines a conversational AI assistant (powered by Groq) with a CubeSat satellite ground station interface over MQTT.

---

## Features

- **Conversational AI** - responds to mentions ("tars", "TARS", "тарс") and direct replies in group chats; uses Groq's LLaMA models for text and vision
- **Proactive engagement** - autonomously observes chat activity and posts spontaneous, context-aware messages on a scheduled cadence (daily cap, configurable timing, no user trigger required)
- **Adaptive personality** - tracks per-user behavioral metrics (off-topic rate, rudeness, verbosity, etc.) and adjusts response style automatically
- **User profiles** - persists interests, behavioral scores, and LLM-maintained notes per user in SQLite
- **Image analysis** - analyzes photos posted in the chat with astronomical context awareness
- **CubeSat telemetry** - `/status` fetches live telemetry from a connected CubeSat via MQTT
- **CubeSat photo** - `/photo` requests a photo from the CubeSat payload camera, received as base64 over MQTT
- **Weather** - `/weather <city>` fetches current weather from OpenWeatherMap
- **Rate limiting** - per-user sliding window rate limiter with configurable penalty cooldowns
- **Conversation memory** - in-RAM chat history passed to the LLM as structured conversation turns, persisted to SQLite on shutdown and reloaded on restart

---

## Project Structure

```
telegram-ai-bot/
├── main.py                          # Entry point
├── config/
│   └── settings.py                  # All configuration (loaded from .env)
├── core/
│   ├── brain.py                     # LLM calls, memory/profile updates, proactive posting
│   ├── memory.py                    # In-RAM conversation context (chat + user), SQLite persistence
│   ├── prompts.py                   # System prompt templates (conversational + proactive)
│   ├── personality_engine.py        # Per-user adaptive behavior rules
│   ├── proactive_engine.py          # Per-chat state machine (daily cap, gap, scheduling)
│   └── cooldown.py                  # Sliding window rate limiter
├── database/
│   ├── db.py                        # SQLite: user_profile, chat_memory, user_memory, messages tables; CRUD + memory persistence
│   └── profile_repo.py              # Re-export layer used by brain.py
├── handlers/
│   ├── message_handler.py           # Message routing: observe, trigger detection, cooldowns
│   ├── status_handler.py            # /status command (CubeSat telemetry)
│   ├── photo_handler.py             # /photo command (CubeSat camera)
│   └── weather_handler.py           # /weather command
├── services/
│   ├── telegram_service.py          # Bot initialization and handler registration
│   ├── mqtt_service.py              # MQTT client, per-request response queues
│   ├── background_service.py        # Cleanup daemon + proactive posting daemon
│   └── weather_service.py           # OpenWeatherMap API client
└── utils/
    ├── triggers.py                  # Trigger word detection + reply-to-bot check
    ├── identity.py                  # Telegram identity extraction
    └── photo.py                     # Telegram photo URL extraction
```

---

## Requirements

- Python 3.10+
- A Groq API key (free tier available at [console.groq.com](https://console.groq.com))
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An OpenWeatherMap API key (free tier available)
- An MQTT broker (e.g., Mosquitto) running on port 1883 — only required for `/status` and `/photo`

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

3. **Configure the environment:**
   ```sh
   cp .env.example .env
   # Edit .env and fill in your credentials
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

All settings are loaded from `.env` via `config/settings.py`. Copy `.env.example` to `.env` and fill in the required values.

### Required

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token from BotFather |
| `GROQ_API_KEY` | Groq API key |
| `WEATHER_API_KEY` | OpenWeatherMap API key |
| `ALLOWED_CHAT_IDS` | Comma-separated list of authorized group chat IDs |
| `ADMIN_IDS` | Comma-separated list of admin Telegram user IDs |

### Proactive Engagement (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROACTIVE_ENABLED` | `true` | Master toggle; set to `false` to disable the feature entirely |
| `PROACTIVE_CHAT_IDS` | _(empty)_ | Comma-separated chat IDs to enroll for proactive observation and posting. Must be a subset of `ALLOWED_CHAT_IDS`. If empty, proactive posting is inactive even if enabled |
| `PROACTIVE_MAX_PER_DAY` | `5` | Maximum proactive posts per chat per calendar day (UTC) |
| `PROACTIVE_MIN_GAP_SECONDS` | `3600` | Minimum seconds between two consecutive proactive posts (1 hour) |
| `PROACTIVE_NEXT_MIN_SECONDS` | `7200` | Lower bound of the random reschedule window after a post (2 hours) |
| `PROACTIVE_NEXT_MAX_SECONDS` | `14400` | Upper bound of the random reschedule window after a post (4 hours) |
| `PROACTIVE_CONTEXT_MESSAGES` | `25` | Number of recent messages passed to the LLM as context |
| `PROACTIVE_MIN_CONTEXT_MESSAGES` | `10` | Minimum messages in DB before proactive posting activates for a chat |
| `PROACTIVE_MIN_WORD_COUNT` | `3` | Minimum word count for a message to be saved for context |
| `PROACTIVE_MIN_CHAR_COUNT` | `15` | Minimum character count (alternative to word count; OR logic) |
| `MESSAGE_TTL_SECONDS` | `86400` | How long a message is retained in the DB (24 hours) |
| `CLEANUP_LOOP_INTERVAL_SECONDS` | `1800` | Cleanup daemon wake interval (30 minutes) |
| `PROACTIVE_LOOP_INTERVAL_SECONDS` | `600` | Proactive posting daemon wake interval (10 minutes) |

### Logging (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

### Behavioral tuning (edit `settings.py` directly)

| Setting | Default | Description |
|---------|---------|-------------|
| `USER_COOLDOWN_SECONDS` | `10` | Minimum seconds between responses per user |
| `RATE_LIMIT_COUNT` | `2` | Max messages per rate limit window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |
| `RATE_LIMIT_PENALTY` | `180` | Lockout duration after rate limit breach |
| `MAX_CONTEXT_MESSAGES` | `10` | Chat messages included in LLM context |
| `MAX_INPUT_CHARS` | `1500` | Max characters accepted from user input |
| `MEMORY_TTL_SECONDS` | `86400` | Seconds before inactive chat context is evicted from RAM |

---

## Commands

| Command | Access | Description |
|---------|--------|-------------|
| `tars <message>` | All allowed chats | Mention the bot to start a conversation |
| `/status` | Allowed chats | Fetch live CubeSat telemetry |
| `/photo [overlay]` | Allowed chats | Request a photo from the CubeSat camera |
| `/weather <city>` | Allowed chats | Get current weather for a city |

The bot also responds when users reply directly to any of its messages. When the reply targets a bot message that is no longer in the rolling chat memory (e.g. an older message or a proactive post), the replied-to text is surfaced to the LLM so it answers the exact message being referenced.

---

## Proactive Engagement

When enabled, TARS passively observes text messages in enrolled chats and periodically posts spontaneous, context-aware messages — observations, questions, or dry remarks — without any user trigger.

**How it works:**

1. Every qualifying message (text, non-command, ≥3 words or ≥15 characters) sent in a `PROACTIVE_CHAT_IDS` chat is stored in the `messages` table.
2. A background daemon wakes every `PROACTIVE_LOOP_INTERVAL_SECONDS` and checks each enrolled chat.
3. The chat is eligible only when **all** conditions hold: the per-chat schedule (`next_attempt_at`) has elapsed, the daily cap (`PROACTIVE_MAX_PER_DAY`, reset at UTC midnight) is not reached, the minimum gap has passed, there is enough context (≥ `PROACTIVE_MIN_CONTEXT_MESSAGES` rows), and at least one new user message has arrived since the last proactive post.
4. On approval the LLM is called with the recent message history, and the generated reply is sent via `bot.send_message()`. The post is also recorded in chat memory (as a standalone assistant turn) so later replies/follow-ups have context, and the next attempt is scheduled in a random `PROACTIVE_NEXT_MIN_SECONDS`–`PROACTIVE_NEXT_MAX_SECONDS` window.
5. If generation fails (no content or an error), the daily budget is preserved and the next attempt is simply pushed forward.

The LLM is **never** called reactively by this feature — only the scheduled daemon triggers it. A separate cleanup daemon purges messages older than `MESSAGE_TTL_SECONDS` every `CLEANUP_LOOP_INTERVAL_SECONDS`.

To activate, set at minimum:
```env
PROACTIVE_CHAT_IDS=-1001234567890
```

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

Responses are routed back to the originating command via a per-request queue keyed by `request_id`, so concurrent `/status` and `/photo` requests never collide, and neither command blocks the Telegram polling thread (each waits for its reply in a background daemon thread). On an unexpected disconnect the client automatically reconnects with exponential backoff (5s → capped at 300s, up to 10 attempts).

If no MQTT broker is available, the bot starts normally — only `/status` and `/photo` will be non-functional.

---

## Deployment

### Running as a systemd service (Linux)

Create a service file at `/etc/systemd/system/tars.service`:

```ini
[Unit]
Description=TARS Telegram Bot
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=tars
WorkingDirectory=/opt/tars
ExecStart=/opt/tars/venv/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
EnvironmentFile=/opt/tars/.env

[Install]
WantedBy=multi-user.target
```

Then enable and start:
```sh
sudo systemctl daemon-reload
sudo systemctl enable tars
sudo systemctl start tars
sudo journalctl -u tars -f   # follow logs
```

### Recommended server setup

```sh
# Create a dedicated user
sudo useradd -r -m -d /opt/tars tars

# Clone and set up
sudo -u tars git clone https://github.com/yourusername/telegram-ai-bot.git /opt/tars
cd /opt/tars
sudo -u tars python3 -m venv venv
sudo -u tars venv/bin/pip install -r requirements.txt

# Create the data directory (SQLite database lives here)
sudo -u tars mkdir -p /opt/tars/data

# Create the .env file
sudo -u tars cp .env.example .env
sudo -u tars nano .env   # fill in credentials

# Create the systemd unit (see the service file above) and start it
sudo nano /etc/systemd/system/tars.service   # paste the unit from the section above
sudo systemctl daemon-reload
sudo systemctl enable --now tars
```

### MQTT broker (Mosquitto)

If using CubeSat features, install and start Mosquitto:
```sh
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

The bot connects to `localhost:1883` by default. To change the broker address, set `MQTT_BROKER` and `MQTT_PORT` in `settings.py`.

### Updating

```sh
sudo systemctl stop tars
sudo -u tars git pull
sudo -u tars venv/bin/pip install -r requirements.txt
sudo systemctl start tars
```

---

## Access Control

- The bot only responds in chats listed in `ALLOWED_CHAT_IDS`
- In private chats, only users listed in `ADMIN_IDS` receive responses
- Unauthorized mentions in other groups receive a redirect message pointing to @astronom_chat
- Proactive posting only occurs in chats explicitly listed in `PROACTIVE_CHAT_IDS`

---

## Troubleshooting

**Bot doesn't respond in a group**
- Confirm the group's chat ID is in `ALLOWED_CHAT_IDS` (use `@userinfobot` to find it)
- Ensure the bot has been added to the group and has permission to read messages
- For groups with privacy mode, disable it via BotFather or make the bot an admin

**`ModuleNotFoundError: No module named 'services'`**
- Run the bot from the project root directory: `python main.py`, not `python core/brain.py`

**`RuntimeError: ENV variable X is not set`**
- Check your `.env` file — all five required variables must be present and non-empty

**MQTT connection failed**
- Verify Mosquitto is running: `mosquitto -v` or `systemctl status mosquitto`
- Default broker is `localhost:1883` — adjust `MQTT_BROKER` / `MQTT_PORT` in `settings.py` if needed

**`/status` or `/photo` times out**
- Confirm the CubeSat OBC is powered on and connected to the same MQTT broker
- Check that it publishes responses to the correct topics with a matching `request_id`

**Proactive posting not working**
- Verify `PROACTIVE_CHAT_IDS` contains valid chat IDs that are also in `ALLOWED_CHAT_IDS`
- The bot needs at least `PROACTIVE_MIN_CONTEXT_MESSAGES` (default: 10) saved messages before it will post — the chat needs some activity first
- Check logs for `"Proactive engagement active for N chat(s)"` at startup

---

## Development & Testing

- Run the test suite with `pytest tests/ -v`. `conftest.py` injects fake required env vars before import (since `config/settings.py` validates them at import time) and stubs `telebot` when it isn't installed, so tests run without real credentials.
- CI runs, in order: `black --check --line-length 120 .`, `isort --check-only --profile black`, `pylint` (on non-test files, `fail-under 7.0`), then `pytest`.
- Formatting and lint settings live in `pyproject.toml` — match the 120-character line length and run black/isort before committing.

---

## TODO / Roadmap

- **Semantic recall from the `messages` table (RAG).** Conversations currently use only the rolling in-RAM context window; older messages are forgotten even though they are persisted in the `messages` table. A future improvement is retrieval over that history (keyword or embedding-based) so the bot can recall relevant older context on demand. This is intentionally deferred because retrieved snippets enter the prompt and cost tokens — it should be gated (e.g. only on long-gap replies or when the message references context that is no longer in the window).

---

## License

MIT License
