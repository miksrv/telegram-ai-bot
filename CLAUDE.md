# TARS — Claude Code Guide

## Project Overview

TARS is a Telegram bot for the Russian astronomy community (@astronom_chat), named after the AI from *Interstellar*. It combines an LLM-powered conversational AI with a CubeSat satellite ground station interface.

## Architecture

```
main.py                          # Entry point: starts MQTT + bot polling
config/settings.py               # All configuration, loaded from .env
core/
  brain.py                       # TARSBrain: LLM calls, memory/profile updates, post_proactively()
  memory.py                      # MemoryManager: in-RAM chat + user context, flushed to SQLite on shutdown
  prompts.py                     # System prompt templates and builders (incl. PROACTIVE_PROMPT_TEMPLATE)
  personality_engine.py          # Per-user adaptive behavior rules (0–1 scores → directives)
  cooldown.py                    # CooldownManager: sliding window rate limiter
  proactive_engine.py            # ProactiveEngine: per-chat state machine (daily cap, gap, scheduling)
database/
  db.py                          # SQLite: user_profile, messages tables; all CRUD operations
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
1. `message_handler.handle_message` → observe block (save to `messages` if enrolled) → trigger/reply check → cooldown check
2. `brain.think` → fetches chat history + user profile → builds messages[] array (system prompt + alternating user/assistant turns) → Groq API
3. LLM returns JSON `{reply}` on most turns, or `{reply, profile_update, notes}` on the first message and every 5th (`message_count % 5 == 0`)
4. `db_increment_message_count` always runs; profile averages and notes only updated on designated turns
5. `bot.reply_to` sends response

### Proactive posting (background)
1. `background_service.start_proactive_loop` wakes every `PROACTIVE_LOOP_INTERVAL_SECONDS`
2. For each `PROACTIVE_CHAT_IDS` chat: `proactive_engine.should_post()` checks daily cap, gap, and context size
3. On approval: `brain.post_proactively()` fetches recent messages → Groq API → JSON `{reply}`
4. `bot.send_message()` sends; `proactive_engine.record_post()` advances schedule

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

## Known Issues
- _None currently tracked._ Two previously documented MQTT issues have been resolved:
  - `/status` and `/photo` no longer block the Telegram polling thread — each waits for its MQTT reply in a background daemon thread.
  - Responses are no longer shared/stolen — `mqtt_service` routes each reply to a per-request queue keyed by `request_id`, so concurrent `/status`/`/photo` requests stay isolated.
