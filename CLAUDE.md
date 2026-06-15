# TARS — Claude Code Guide

## Project Overview

TARS is a Telegram bot for the Russian astronomy community (@astronom_chat), named after the AI from *Interstellar*. It combines an LLM-powered conversational AI with a CubeSat satellite ground station interface.

## Architecture

```
main.py                          # Entry point: starts MQTT + bot polling
config/settings.py               # All configuration, loaded from .env
core/
  brain.py                       # TARSBrain: LLM calls, memory/profile updates, post_proactively()
  memory.py                      # MemoryManager: in-RAM chat + user context, loaded from SQLite on startup & flushed on shutdown; add_bot_message/last_sender_is_bot helpers
  prompts.py                     # System prompt templates and builders (incl. PROACTIVE_PROMPT_TEMPLATE)
  personality_engine.py          # Per-user adaptive behavior rules (0–1 scores → directives)
  cooldown.py                    # CooldownManager: sliding window rate limiter
  proactive_engine.py            # ProactiveEngine: per-chat state machine (daily cap, gap, scheduling)
database/
  db.py                          # SQLite: user_profile, chat_memory, user_memory, messages tables; all CRUD + memory persistence (flush_memory/load_memory)
  profile_repo.py                # Re-exports db.py functions used by brain.py
handlers/
  message_handler.py             # Main message routing: observe block, trigger detection, cooldowns, dispatch
  status_handler.py              # /status: requests CubeSat telemetry via MQTT, waits for reply
  photo_handler.py               # /photo: requests CubeSat photo via MQTT, waits for reply
  weather_handler.py             # /weather: validates input, delegates to services/weather_service.py
services/
  telegram_service.py            # Bot init, handler registration
  mqtt_service.py                # MQTT client, per-request response queues keyed by request_id (paho-mqtt)
  background_service.py          # Cleanup daemon + proactive posting daemon threads
  weather_service.py             # OpenWeatherMap API client (used by weather_handler)
utils/
  triggers.py                    # Trigger word detection + is_reply_to_bot
  identity.py                    # Extracts Telegram user identity dict from message
  photo.py                       # Extracts photo URL from Telegram message
```

## Key Data Flows

### Conversational message
1. `message_handler.handle_message` → observe block (save to `messages` if enrolled) → trigger/reply check → cooldown check. When the message is a reply to the bot, the replied-to text is captured and passed to `brain.think` as `reply_to_text`
2. `brain.think` → fetches chat history + user profile → builds messages[] array (system prompt + alternating user/assistant turns) → Groq API. If `reply_to_text` is set and isn't already the latest assistant turn, it is injected as the immediately preceding assistant turn so the model answers the exact message being replied to (handles replies to proactive posts / messages evicted from the rolling memory window)
3. LLM returns JSON `{reply}` on most turns, or `{reply, profile_update, notes}` on the first message and every 5th (`message_count % 5 == 0`)
4. `db_increment_message_count` always runs; profile averages and notes only updated on designated turns
5. `bot.reply_to` sends response

### Proactive posting (background)
1. `background_service.start_proactive_loop` wakes every `PROACTIVE_LOOP_INTERVAL_SECONDS`
2. For each `PROACTIVE_CHAT_IDS` chat: `proactive_engine.should_post()` checks, in order: scheduled `next_attempt_at`, daily cap (`PROACTIVE_MAX_PER_DAY`, resets at UTC midnight), min gap, enough context rows in DB, and that there is at least one new user message since the last proactive post
3. On approval: `brain.post_proactively()` fetches recent messages → Groq API → JSON `{reply}`
4. On success: `bot.send_message()` sends; `memory.add_bot_message()` records the post as a standalone assistant turn in chat memory (so follow-ups/replies have context); `proactive_engine.record_post()` advances schedule (random `PROACTIVE_NEXT_MIN/MAX_SECONDS` window)
5. On failure (no content or exception): `proactive_engine.reschedule_failed()` pushes `next_attempt_at` forward without consuming the daily budget

### CubeSat telemetry (/status)
1. `status_handler.handle_status` → registers a per-request queue (keyed by `request_id`) → publishes `{"command": "get_telemetry", "request_id": ...}` to `cubesat/command`
2. Spawns a background daemon thread that waits up to 30s for the matching reply on `cubesat/telemetry/data` (polling thread is **not** blocked)
3. `format_telemetry_for_telegram` renders Markdown response; the queue is unregistered when done

### CubeSat photo (/photo)
1. `photo_handler.handle_photo` → registers a per-request queue (keyed by `request_id`) → publishes `{"command": "take_photo", "request_id": ..., "params": {"overlay": ...}}` to `cubesat/command`
2. Spawns a background daemon thread that waits up to 45s for the matching reply on `cubesat/payload/photo` (polling thread is **not** blocked)
3. Decodes base64 image, sends via `bot.send_photo`; the queue is unregistered when done

## Configuration (.env)

Copy `.env.example` to `.env`. Required variables:

```env
BOT_TOKEN=          # Telegram bot token
GROQ_API_KEY=       # Groq API key
WEATHER_API_KEY=    # OpenWeatherMap API key
ALLOWED_CHAT_IDS=   # Comma-separated Telegram chat IDs
ADMIN_IDS=          # Comma-separated Telegram user IDs (admins)
```

Optional proactive engagement variables (see `.env.example` for the full list):
```env
PROACTIVE_ENABLED=  # true/false (default: true)
PROACTIVE_CHAT_IDS= # Comma-separated subset of ALLOWED_CHAT_IDS for proactive observation
```

Other optional variables:
```env
LOG_LEVEL=          # DEBUG/INFO/WARNING/ERROR/CRITICAL (default: INFO)
```

`PROACTIVE_CHAT_IDS` is intersected with `ALLOWED_CHAT_IDS` at load time; IDs outside the allowed set are dropped with a warning.

## Models

| Purpose | Model |
|---------|-------|
| Text generation | `llama-3.3-70b-versatile` |
| Image analysis | `meta-llama/llama-4-scout-17b-16e-instruct` |

## LLM Response Contracts

**Conversational path — full update** (`brain.think`, `brain.analyze_image`): used on the first message from a user and every 5th interaction (`message_count % 5 == 0`):
```json
{
  "reply": "Text response in Russian",
  "profile_update": {
    "offtopic": 0.0,
    "provocation": 0.0,
    "spam": 0.0,
    "rudeness": 0.0,
    "verbosity": 0.5,
    "interests": ["astronomy", "astrophotography"]
  },
  "notes": "Short user summary replacing previous value"
}
```

**Conversational path — reply only**: used on all other turns to reduce output tokens:
```json
{
  "reply": "Text response in Russian"
}
```

**Proactive path** (`brain.post_proactively`): only `reply` is returned — no single user is being addressed so `profile_update` and `notes` are absent.
```json
{
  "reply": "Spontaneous message in Russian"
}
```

## User Profile System

- Stored in SQLite (`data/tars_user_profiles.db`)
- `message_count` increments on every bot response (via `increment_message_count()`), independent of profile updates
- Behavioral metrics (`avg_offtopic`, `avg_provocation`, `avg_spam`, `avg_rudeness`, `avg_verbosity`) are updated via cumulative moving average only on full-update turns (first message + every 5th)
- `PersonalityEngine` converts 0–1 float scores into 10-level directive strings injected into the system prompt
- `notes` is an LLM-maintained free-text summary of the user, fully replaced each time it runs

## Rate Limiting

- **Classic cooldown**: 10s between messages per user
- **Sliding window**: max 2 messages per 60s window
- **Penalty**: 180s lockout on breach
- All state is in-RAM only; resets on restart

## MQTT Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `cubesat/command` | Publish | Send commands to CubeSat |
| `cubesat/telemetry/data` | Subscribe | Receive telemetry responses |
| `cubesat/payload/photo` | Subscribe | Receive photo responses |

The MQTT client (`mqtt_service`) runs `loop_forever` in a background daemon thread. On an unexpected disconnect, `on_disconnect` spawns a reconnect loop with exponential backoff (5s → cap 300s, up to 10 retries); a clean disconnect from `stop_mqtt()` does not trigger reconnects. Responses are routed only when the payload is valid JSON carrying a known `request_id`.

## Development & Testing

- Python 3.11. Install deps with `pip install -r requirements.txt` (paho-mqtt, pyTelegramBotAPI, requests, python-dotenv).
- Run tests: `pytest tests/ -v`. `conftest.py` sets fake required env vars before import (since `config/settings.py` calls `require_env()` at import time) and stubs `telebot` if not installed.
- CI (`.github/workflows`) runs, in order: black (`--line-length 120`), isort (`--profile black`), pylint (`fail-under 7.0`, excludes `tests/`), then pytest.
- Formatting/lint config lives in `pyproject.toml` (black, isort, pylint). Match the 120-char line length.

## Known Issues
- _None currently tracked._ Two previously documented MQTT issues have been resolved:
  - `/status` and `/photo` no longer block the Telegram polling thread — each waits for its MQTT reply in a background daemon thread.
  - Responses are no longer shared/stolen — `mqtt_service` routes each reply to a per-request queue keyed by `request_id`, so concurrent `/status`/`/photo` requests stay isolated.

## TODO / Roadmap
- **Semantic recall from the `messages` table (RAG).** The conversational path (`brain.think`) only sees the rolling in-RAM window (`MAX_CONTEXT_MESSAGES`); anything older is forgotten even though it persists in the `messages` table. Add retrieval over that table — keyword or embedding-based — so the bot can pull in relevant older context on demand (e.g. a user's equipment or a past observation). Note: this trades tokens for memory depth (retrieved snippets enter the prompt), so it is intentionally deferred until the cost/benefit is tuned (e.g. retrieve only on long-gap replies or when the query references absent context).
