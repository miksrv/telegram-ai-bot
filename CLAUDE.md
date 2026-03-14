# TARS — Claude Code Guide

## Project Overview

TARS is a Telegram bot for the Russian astronomy community (@astronom_chat), named after the AI from *Interstellar*. It combines an LLM-powered conversational AI with a CubeSat satellite ground station interface.

## Architecture

```
main.py                          # Entry point: starts MQTT + bot polling
config/settings.py               # All configuration, loaded from .env
core/
  brain.py                       # TARSBrain: LLM calls, memory/profile updates
  memory.py                      # MemoryManager: in-RAM chat + user context, flushed to SQLite on shutdown
  prompts.py                     # System prompt templates and builders
  personality_engine.py          # Per-user adaptive behavior rules (0–1 scores → directives)
  cooldown.py                    # CooldownManager: sliding window rate limiter
database/
  db.py                          # SQLite: user_profile table, CRUD operations
  profile_repo.py                # Re-exports db.py functions used by brain.py
handlers/
  message_handler.py             # Main message routing: trigger detection, cooldowns, dispatch
  status_handler.py              # /status: requests CubeSat telemetry via MQTT, waits for reply
  photo_handler.py               # /photo: requests CubeSat photo via MQTT, waits for reply
  weather_handler.py             # /weather: calls OpenWeatherMap API
services/
  telegram_service.py            # Bot init, handler registration
  mqtt_service.py                # MQTT client, message queue (paho-mqtt)
  llm_service.py                 # (exists, not actively used — brain.py handles LLM calls)
utils/
  triggers.py                    # Trigger word detection + is_reply_to_bot
  identity.py                    # Extracts Telegram user identity dict from message
  photo.py                       # Extracts photo URL from Telegram message
```

## Key Data Flows

### Conversational message
1. `message_handler.handle_message` → trigger/reply check → cooldown check
2. `brain.think` → builds prompt from memory + user profile → Groq API
3. LLM returns JSON `{reply, profile_update, notes}` → memory updated, profile saved to SQLite
4. `bot.reply_to` sends response

### CubeSat telemetry (/status)
1. `status_handler.handle_status` → publishes `{"command": "get_telemetry"}` to `cubesat/command`
2. Blocks polling thread waiting up to 30s for reply on `cubesat/telemetry/data`
3. `format_telemetry_for_telegram` renders Markdown response

### CubeSat photo (/photo)
1. `photo_handler.handle_photo` → publishes `{"command": "take_photo"}` to `cubesat/command`
2. Blocks polling thread waiting up to 45s for reply on `cubesat/payload/photo`
3. Decodes base64 image, sends via `bot.send_photo`

## Configuration (.env)

```env
BOT_TOKEN=          # Telegram bot token
GROQ_API_KEY=       # Groq API key
WEATHER_API_KEY=    # OpenWeatherMap API key
ALLOWED_CHAT_IDS=   # Comma-separated Telegram chat IDs
ADMIN_IDS=          # Comma-separated Telegram user IDs (admins)
```

## Models

| Purpose | Model |
|---------|-------|
| Text generation | `llama-3.3-70b-versatile` |
| Image analysis | `meta-llama/llama-4-scout-17b-16e-instruct` |

## LLM Response Contract

The LLM always returns valid JSON:
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

## User Profile System

- Stored in SQLite (`data/tars_user_profiles.db`)
- Behavioral metrics (`avg_offtopic`, `avg_provocation`, `avg_spam`, `avg_rudeness`, `avg_verbosity`) are updated via cumulative moving average each interaction
- `PersonalityEngine` converts 0–1 float scores into 10-level directive strings injected into the system prompt
- `notes` is an LLM-maintained free-text summary of the user, fully replaced each time

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

See `ROADMAP.md` for a full list of bugs and planned improvements.

**Critical issues to be aware of:**
- `database/db.py` uses a global shared SQLite cursor that is not thread-safe — concurrent writes from different threads can race
- `status_handler` and `photo_handler` block the Telegram polling thread for up to 30–45s, preventing other messages from being handled during that window
- The MQTT message queue is shared — concurrent `/status` or `/photo` requests from multiple users can steal each other's responses
