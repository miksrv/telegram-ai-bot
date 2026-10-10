# TARS — Claude Code Guide

## Project Overview

TARS is a Telegram bot for the Russian astronomy community (@astronom_chat), named after the AI from *Interstellar*. It combines an LLM-powered conversational AI with a CubeSat satellite ground station interface.

## Architecture

```
VERSION                           # Running version, MAJOR.MINOR.PATCH (see "Versioning & Releases" below)
CHANGELOG.md                      # Keep a Changelog history, one entry per release
main.py                          # Entry point: starts MQTT + bot polling
config/settings.py               # All configuration, loaded from .env; also reads VERSION into BOT_VERSION
core/
  brain.py                       # TARSBrain: builds prompts/context, memory/profile updates, post_proactively(); delegates the actual model call to core/llm
  llm/                           # Pluggable cloud LLM engine (see "LLM Engine" section below)
    engine.py                    # LLMEngine: picks the active provider from LLM_ENGINE, single .complete() entry point used by brain.py
    base.py                      # LLMProvider interface + shared HTTP session/retry helper
    groq_provider.py              # GroqProvider(LLMProvider)
    openai_provider.py            # OpenAIProvider(LLMProvider)
  memory.py                      # MemoryManager: in-RAM chat + user context, loaded from SQLite on startup & flushed on shutdown; add_bot_message/last_sender_is_bot/get_user_earlier_messages helpers
  prompts.py                     # System prompt templates and builders (incl. PROACTIVE_PROMPT_TEMPLATE, build_capabilities_line())
  personality_engine.py          # Per-user adaptive behavior rules (0–1 scores + message_count/experience fact → directives)
  cooldown.py                    # CooldownManager: sliding window rate limiter
  proactive_engine.py            # ProactiveEngine: per-chat state machine (daily cap, gap, scheduling) for both general posts and the once-daily direct reply
database/
  db.py                          # SQLite: user_profile, chat_memory, user_memory, messages, image_generation_usage tables; all CRUD + memory persistence (flush_memory/load_memory)
  profile_repo.py                # Re-exports db.py functions used by brain.py
handlers/
  message_handler.py             # Main message routing: observe block, trigger detection, cooldowns, dispatch
  status_handler.py              # /status: requests CubeSat telemetry via MQTT, waits for reply
  photo_handler.py               # /photo: requests CubeSat photo via MQTT, waits for reply
  weather_handler.py             # /weather: validates input, delegates to services/weather_service.py
  stats_handler.py               # /stats: aggregate DB statistics (db.get_db_stats), Russian output
  help_handler.py                # /help, /start: static bot description + command list (Russian)
  starmap_handler.py             # /sky, /horizon, /skymap, /galaxy: requests star charts from starmap-service via MQTT
  image_handler.py               # /image: generates an image via services/image_service.py, enforces the per-user daily quota
  delivery.py                    # Shared status-message lifecycle (safe_reply/safe_delete) for MQTT result delivery (/photo + starmap) and reused by /image
services/
  telegram_service.py            # Bot init, handler registration
  mqtt_service.py                # MQTT client, per-request response queues keyed by request_id (paho-mqtt); tracks starmap-service availability from its retained status topic + notifies listeners
  background_service.py          # Cleanup daemon + proactive posting daemon threads
  weather_service.py             # OpenWeatherMap client: get_weather() (used by weather_handler) + get_coordinates() (city → lat/lon, reused by starmap commands)
  image_service.py                # OpenAI Images API client for /image: generate_image() + its own exception hierarchy; always talks to OpenAI directly, independent of LLM_ENGINE
  startup_notifier.py            # send_startup_notification(): DMs every ADMIN_IDS user once at boot with allowed chats, active LLM engine/model, MQTT status, proactive status
utils/
  triggers.py                    # Trigger word detection + is_reply_to_bot
  identity.py                    # Extracts Telegram user identity dict from message
  photo.py                       # Extracts photo URL from Telegram message
  typing_action.py               # typing_action() context manager: keeps the "typing..." indicator alive (refreshed every few seconds) for the duration of a slow call
```

## LLM Engine

`core/brain.py` never talks to a cloud API directly — every model call goes through `core/llm/llm_engine.complete(messages, *, kind, temperature, max_tokens, top_p, json_mode=True)`, where `kind` is `"text"` or `"vision"` (not a literal model name). `LLMEngine.__init__` picks a provider class from a registry dict keyed by `settings.LLM_ENGINE` (`"groq"` or `"openai"`) and instantiates it once at import time (`core/llm/engine.py`'s module-level `llm_engine` singleton). Each provider (`GroqProvider`, `OpenAIProvider` in `core/llm/groq_provider.py`/`openai_provider.py`) owns its own HTTP session, base URL, auth header, and resolves its own text/vision model name for `kind` — `brain.py` is fully decoupled from provider-specific model names. Groq's and OpenAI's chat completions APIs share the same request/response shape (messages/temperature/max_tokens/top_p/`response_format: json_object`, and the same `image_url` multimodal content-part format for vision), so both providers reuse the same `build_session`/`post_with_retry` helper in `core/llm/base.py`. **To add a new provider:** add one file implementing `LLMProvider.complete()` and one line in `core/llm/engine.py`'s `_PROVIDERS` dict — nothing in `brain.py` changes.

Only the API key for the active engine is validated at startup (`config/settings.py`); the inactive provider's key may be left blank in `.env`.

**Retries.** `post_with_retry` (`core/llm/base.py`) retries transient connection errors (via `build_session`'s urllib3 `Retry` adapter for HTTP 500/502/503/504, and a manual loop for `ConnectionError`/`Timeout`/`ChunkedEncodingError`) and, separately, ordinary rate-limit `429`s — up to 3 attempts with backoff, honoring the `Retry-After` header when the provider sends one. A `429` is only retried when `is_quota_error()` says it is **not** billing exhaustion; a genuine quota `429`/`402` propagates immediately (no wasted attempts) so it reaches the fallback logic below without delay.

**Empty completions / refusals.** A `200 OK` whose `choices[0].message.content` is `null` or blank is a real-world case, not a transport error: in JSON mode OpenAI puts a model refusal into `message.refusal` (or sets `finish_reason: content_filter`) and leaves `content` null. Both providers therefore go through `core.llm.base.extract_message_content()`, which logs `finish_reason`/`refusal` and raises `LLMEmptyResponseError` instead of crashing on `.strip()`. `LLMEngine` does **not** fail over on it (it's not a quota problem); `brain.think`/`analyze_image` catch it separately and answer with `LLM_REFUSAL_REPLY` ("Логический модуль отклонил этот запрос…") rather than the generic `LLM_FAILURE_REPLY` ("Сбой логического модуля…"), which is now reserved for genuinely unexpected exceptions. `_parse_json_safe` never raises (garbage between braces returns `None` → `LLM_BAD_RESPONSE_REPLY`), and a non-string/`null` `reply` field is treated as empty.

**Automatic quota fallback.** If the *other* provider's API key also happens to be filled in, `LLMEngine.__init__` builds it as a standby `fallback_provider` (no separate config toggle — purely derived from whether `GROQ_API_KEY`/`OPENAI_API_KEY` is non-empty). When the active provider's HTTP call fails with a billing/quota-exhaustion error, the provider raises `core.llm.base.LLMQuotaExceededError` (detected via `is_quota_error()`, which only matches HTTP 402 or a 429 whose body carries an OpenAI-style `error.code`/`error.type` such as `insufficient_quota` — an ordinary rate-limit 429 with no such code is left alone, since that's already handled by `post_with_retry`'s backoff, and auth/config errors like 401 are never treated as quota errors so they don't get silently masked by a provider switch). `LLMEngine.complete()` catches that exception, logs it, **permanently** swaps `self.provider` to the standby for the rest of the process's lifetime (clearing `fallback_provider` so it never bounces back), and retries the same call once against the new provider. A bot restart re-evaluates `LLM_ENGINE` from scratch.

## Key Data Flows

### Startup notification
`main.py` calls `start_mqtt()` and `init_bot()`, then `services/startup_notifier.send_startup_notification(bot, mqtt_connected)` before any other background loop starts. It DMs every user in `ADMIN_IDS` (not just chats — this requires each admin to have started a private chat with the bot at least once, or Telegram rejects that individual send) with the allowed chat IDs, the active `LLM_ENGINE` + its text model, whether the initial MQTT connect succeeded, and whether proactive engagement is enabled. Each admin send is wrapped independently so one admin who never DM'd the bot doesn't block the notification to the others.

### Conversational message
1. `message_handler.handle_message` → observe block (save to `messages` if enrolled) → trigger/reply check → cooldown check. When the message is a reply to the bot, the replied-to text is captured and passed to `brain.think` as `reply_to_text`
2. The `brain.think`/`analyze_image` call runs inside a `utils.typing_action.typing_action(bot, chat_id)` context manager, which sends Telegram's "typing" chat action immediately and re-sends it every ~4s from a background thread for as long as the block runs (Telegram clears the indicator after ~5s otherwise) — it stops the moment the call returns, before the reply is sent. `handlers/weather_handler.py` uses the same helper around its (much shorter) weather API call
3. `brain.think` → `_build_user_context` fetches chat history + user profile, plus one batched `database.db.get_display_names()` lookup for every distinct user_id in the window (one query, not N) so history turns are labeled with a real name (first_name, falling back to `@username`, then `User#<id>`) instead of always `User#<id>`. It also builds a terse "earlier messages from this user" background block — up to `PERSONALIZATION_EARLIER_MESSAGES_COUNT` of this user's own messages that fell out of the rolling window (from `memory.get_user_earlier_messages`, with `database.db.get_recent_user_messages` as a DB supplement when memory doesn't hold enough), each truncated to `PERSONALIZATION_EARLIER_MESSAGE_CHARS` and deduped against the current window — then builds messages[] array (system prompt + alternating user/assistant turns) → the active LLM engine (`core/llm`, see above). If `reply_to_text` is set and isn't already the latest assistant turn, it is injected as the immediately preceding assistant turn so the model answers the exact message being replied to (handles replies to proactive posts / messages evicted from the rolling memory window)
4. LLM returns JSON `{reply}` on most turns, or `{reply, profile_update, notes, facts}` on the first message and every `PROFILE_FULL_UPDATE_INTERVAL`-th turn thereafter (default every 3rd, `message_count % PROFILE_FULL_UPDATE_INTERVAL == 0`)
5. `db_increment_message_count` always runs; profile averages, notes, and structured facts only updated on designated turns — both happen inside the `typing_action` block, before it exits
6. `bot.reply_to` sends response, after the typing heartbeat has already stopped

Both conversational system-prompt templates (and, cheaply, the two proactive templates) also carry a fixed self-identity line ("ТАРС"/"TARS"/"Тарс*" in any case/diminutive means the bot, including third-person mentions) and a personalization line (use the user card, address by name occasionally, never recite the profile). `core.prompts.build_capabilities_line()` builds a dynamic 1-3 line capabilities block per call: whether `/image` is available (`IMAGE_GEN_ENABLED`) and the other commands currently usable, including the four star-chart commands only while `services.mqtt_service.is_starmap_online()` is true — so the bot never advertises a command that would just fail.

### Proactive posting (background)
1. `background_service.start_proactive_loop` wakes every `PROACTIVE_LOOP_INTERVAL_SECONDS`
2. For each `PROACTIVE_CHAT_IDS` chat: `proactive_engine.should_post()` checks, in order: scheduled `next_attempt_at`, daily cap (`PROACTIVE_MAX_PER_DAY`, resets at UTC midnight), min gap, enough context rows in DB, and that there is at least one new user message since the last proactive post
3. On approval: `brain.post_proactively()` fetches recent messages → the active LLM engine → JSON `{reply}`
4. On success: `bot.send_message()` sends; `memory.add_bot_message()` records the post as a standalone assistant turn in chat memory (so follow-ups/replies have context); `proactive_engine.record_post()` advances schedule (random `PROACTIVE_NEXT_MIN/MAX_SECONDS` window)
5. On failure (no content or exception): `proactive_engine.reschedule_failed()` pushes `next_attempt_at` forward without consuming the daily budget

### Proactive direct reply (background, once daily)
Gated by its own master toggle, `PROACTIVE_REPLY_ENABLED` (default `true`) — checked in `background_service.start_proactive_loop` before `should_post_reply()` is even called. In addition to the general posts above, the same loop iteration (when a general post did not fire) can address one specific past message directly, as a Telegram reply.
1. `proactive_engine.should_post_reply()` checks its own schedule (`next_reply_attempt_at`, randomized once per UTC day within `PROACTIVE_REPLY_MIN/MAX_DELAY_SECONDS` of midnight), the daily cap (`PROACTIVE_REPLY_MAX_PER_DAY`, default 1), and the shared `PROACTIVE_MIN_GAP_SECONDS` gap against the last proactive action (post or reply)
2. Target selection is pure SQL/Python, not an LLM call: `database.db.get_reply_candidate()` picks a random message from the `messages` table with `word_count >= PROACTIVE_REPLY_MIN_WORD_COUNT` (screens out short, e.g. two-word, messages) and `replied_at = 0` (never used before). Photo messages never qualify — the observe block only ever saves `content_type == "text"` rows, so nothing with an image is in the table to begin with
3. On a candidate: `brain.post_proactive_reply()` fetches recent context, builds a prompt naming the target author/text, and makes a single call to the active LLM engine → JSON `{reply}`
4. On success: `bot.send_message(..., reply_to_message_id=...)` sends it as a genuine Telegram reply to the target; `memory.add_bot_message()` records it in chat memory; `database.db.mark_message_replied()` flags the target row so it is never picked again; `proactive_engine.record_reply()` consumes the daily budget
5. On failure (no content or exception): `proactive_engine.reschedule_reply_failed()` retries later without consuming the daily budget, and the target message is not marked as replied

### CubeSat telemetry (/status)
1. `status_handler.handle_status` → registers a per-request queue (keyed by `request_id`) → publishes `{"command": "get_telemetry", "request_id": ...}` to `cubesat/command`
2. Spawns a background daemon thread that waits up to 30s for the matching reply on `cubesat/telemetry/data` (polling thread is **not** blocked)
3. `format_telemetry_for_telegram` renders Markdown response; the queue is unregistered when done
4. Every reply — success, a failed send, a malformed payload, or the 30s timeout — ends with a `Версия TARS: v{BOT_VERSION}` footer (`status_handler.VERSION_LINE`), so the running version is visible even when CubeSat never answers

### Star charts (/sky, /horizon, /skymap, /galaxy)
Integration with the separate **starmap-service** repo (its `API.md` is the shared, authoritative MQTT contract — do not change it unilaterally).
1. `starmap_handler` gates each command on access + `is_starmap_online()` (refuses with a Russian "service unavailable" message when the service is down)
2. For observer-bound charts (`/sky` → `zenith`, `/horizon` → `horizon`) the city argument is resolved to coordinates via `weather_service.get_coordinates()` (OpenWeatherMap geocoding). `/skymap` (`full`) and `/galaxy` (`galactic`) need no coordinates. `/horizon` accepts an optional trailing compass direction (RU/EN aliases → `N..NW`, default `S`)
3. Registers a per-request queue with `register_request(request_id, maxsize=0)` — **unbounded**, because the contract delivers **two** replies per request: a `queued` acknowledgement (with `position`) then a final `ok`/`error`. Publishes `{request_id, map_type, observer?, options?}` to `starmap/command`
4. A background daemon thread loops on the queue until `STARMAP_MAX_WAIT` (default 120s). On the first `queued` ack it posts a transient "Начал процесс генерации карты…" status message **as a reply to the command**. On `ok` it deletes that status message and posts the chart **as a document** (`send_document`, not a compressed photo) replying to the command — reading `image_path` from the shared filesystem (only if it resolves inside `STARMAP_IMAGE_DIR` via `_is_allowed_image_path`; paths outside it are rejected and logged, guarding against a compromised service/broker reading arbitrary host files), falling back to decoding `image_base64`. When `STARMAP_DELETE_AFTER_SEND` is enabled (default `false`), the delivered file is removed from `STARMAP_IMAGE_DIR` (best-effort, errors only logged) after a successful send from `image_path` — never for the base64 fallback — so charts don't accumulate on disk. On `error`/timeout it deletes the status message and replies with the message. The status-message lifecycle (`safe_reply`/`safe_delete`) lives in `handlers/delivery.py` and is shared with `/photo`
5. **Dynamic command menu:** `mqtt_service` subscribes to the retained `starmap/status` topic and tracks online/offline; `telegram_service` registers a status listener that rebuilds `set_my_commands` so the four chart commands appear in the Telegram `/` menu only while the service is online (and disappear via the service's Last Will when it dies)

> Gap noted in the service: `map_type: optic` (object through a given optic) requires explicit `target.ra`/`target.dec`; resolving an object name (e.g. `M31`) to coordinates is not implemented server-side, so no `/optic`-style command is exposed yet.

### CubeSat photo (/photo)
1. `photo_handler.handle_photo` → registers a per-request queue (keyed by `request_id`) → publishes `{"command": "take_photo", "request_id": ..., "params": {"overlay": ...}}` to `cubesat/command`
2. Posts a transient "Запрашиваю фото…" status message as a reply to the command, then spawns a background daemon thread that waits up to 45s for the matching reply on `cubesat/payload/photo` (polling thread is **not** blocked)
3. On success: deletes the status message and decodes the base64 image, sending it **as a photo** (`bot.send_photo`, compressed) replying to the command; on failure/timeout it deletes the status message and replies with the reason. Uses the same `safe_reply`/`safe_delete` lifecycle helpers (`handlers/delivery.py`) as the starmap commands — the only difference is photo vs document. The queue is unregistered when done

### Image generation (/image)
Always calls OpenAI's Images API directly (`services/image_service.py`) regardless of `LLM_ENGINE` — this is a separate API surface from chat completions, not routed through `core/llm/engine.py`, so it works even when the bot's conversational engine is Groq.
1. `image_handler.handle_image` gates on chat access, then extracts the prompt as everything after `/image ` (or `/image@botname `); an empty prompt gets a short Russian usage reply and nothing else runs
2. Applies the same spam cooldown as every other command (`core.cooldown.cooldowns.allowed(user_id)`) before touching OpenAI, then checks the persisted daily quota: `database.db.get_image_usage_count(user_id) >= IMAGE_GEN_MAX_PER_DAY` (default 5/day, resets at UTC midnight) — both rejections reply in Russian and consume neither cooldown slot beyond the normal check nor the quota
3. Posts a transient "Генерирую изображение…" status message as a reply to the command (`handlers/delivery.py`'s `safe_reply`, same lifecycle as `/photo`/starmap), then calls `services.image_service.generate_image(prompt)` inside a `utils.typing_action.typing_action(bot, chat_id)` block — `model=IMAGE_GEN_MODEL` (default `gpt-image-2.5-sunburst`), `quality=low`, `size=IMAGE_GEN_SIZE`, reusing `build_session`/`post_with_retry`/`is_quota_error` from `core/llm/base.py` for the HTTP call
4. On success: `database.db.increment_image_usage(user_id)` consumes one unit of the daily quota, the status message is deleted, and the decoded PNG bytes are sent with `bot.send_photo` replying to the original command
5. On failure the status message is deleted and the quota is **not** consumed: `ImageContentPolicyError` (OpenAI moderation rejection) gets a "rejected by moderation" reply, `ImageQuotaExceededError` (OpenAI billing/quota exhaustion) gets a "temporarily unavailable" reply and is logged at error level (an operational signal, not a user error), and any other exception gets a generic Russian failure reply and a logged traceback

## Configuration (.env)

Copy `.env.example` to `.env`. Required variables:

```env
BOT_TOKEN=          # Telegram bot token
WEATHER_API_KEY=    # OpenWeatherMap API key
ALLOWED_CHAT_IDS=   # Comma-separated Telegram chat IDs
ADMIN_IDS=          # Comma-separated Telegram user IDs (admins)
```

LLM engine selection — only the key for the active engine is required (see "LLM Engine" above):
```env
LLM_ENGINE=      # "groq" or "openai" (default: groq)
GROQ_API_KEY=    # Required when LLM_ENGINE=groq
OPENAI_API_KEY=  # Required when LLM_ENGINE=openai
```

Optional proactive engagement variables (see `.env.example` for the full list):
```env
PROACTIVE_ENABLED=  # true/false (default: true)
PROACTIVE_CHAT_IDS= # Comma-separated subset of ALLOWED_CHAT_IDS for proactive observation
```

Other optional variables:
```env
LOG_LEVEL=                  # DEBUG/INFO/WARNING/ERROR/CRITICAL (default: INFO)
STARMAP_MAX_WAIT=           # Seconds to wait for a finished star chart (default: 120)
STARMAP_IMAGE_DIR=          # Shared dir for chart files; image_path is validated against it (default: unset → base64 only)
STARMAP_DELETE_AFTER_SEND=  # Delete the delivered chart file from STARMAP_IMAGE_DIR after sending (default: false)
PROACTIVE_REPLY_ENABLED=    # Master toggle for the once-daily direct reply feature (default: true)
GROQ_MODEL_TEXT=            # Override Groq's text model (default: llama-3.3-70b-versatile)
GROQ_MODEL_VISION=          # Override Groq's vision model (default: meta-llama/llama-4-scout-17b-16e-instruct)
OPENAI_MODEL_TEXT=          # Override OpenAI's text model (default: gpt-4o-mini)
OPENAI_MODEL_VISION=        # Override OpenAI's vision model (default: gpt-4o-mini)
IMAGE_GEN_ENABLED=          # Master toggle for the /image command (default: true); when true OPENAI_API_KEY is required even if LLM_ENGINE=groq
IMAGE_GEN_MODEL=            # OpenAI image generation model (default: gpt-image-2.5-sunburst)
IMAGE_GEN_MAX_PER_DAY=      # Per-user daily /image quota, persisted in SQLite (default: 5)
IMAGE_GEN_SIZE=             # Output image size passed to the Images API (default: 1024x1024)
PROFILE_FULL_UPDATE_INTERVAL=              # How often (in bot responses), plus always on message 0, the full profile_update/notes/facts turn runs (default: 3)
PERSONALIZATION_EARLIER_MESSAGES_COUNT=    # Max earlier messages from the current user surfaced as background context (default: 3)
PERSONALIZATION_EARLIER_MESSAGE_CHARS=     # Char cap per earlier-message snippet above (default: 150)
```

`PROACTIVE_CHAT_IDS` is intersected with `ALLOWED_CHAT_IDS` at load time; IDs outside the allowed set are dropped with a warning.

## Models

Default model per provider/role (overridable via the `*_MODEL_TEXT`/`*_MODEL_VISION` env vars above):

| Provider | Text generation | Image analysis |
|----------|------------------|-----------------|
| Groq (`LLM_ENGINE=groq`, default) | `llama-3.3-70b-versatile` | `meta-llama/llama-4-scout-17b-16e-instruct` |
| OpenAI (`LLM_ENGINE=openai`) | `gpt-4o-mini` | `gpt-4o-mini` |

## LLM Response Contracts

**Conversational path — full update** (`brain.think`, `brain.analyze_image`): used on the first message from a user and every `PROFILE_FULL_UPDATE_INTERVAL`-th interaction thereafter (default every 3rd, `message_count % PROFILE_FULL_UPDATE_INTERVAL == 0`):
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
  "notes": "Short rolling summary of communication style/behavioral hints",
  "facts": {
    "name": "How the user likes to be addressed",
    "location": "...",
    "equipment": "...",
    "experience": "beginner|amateur|advanced|pro",
    "topics": ["recurring topics"]
  }
}
```
`facts` carries only keys that are new or changed this turn — the code merges them into the stored facts (`database.db.update_user_facts`), and a `null`/empty value deletes that key. Keys outside the fixed small set above are dropped defensively, same spirit as `_apply_profile_update`'s handling of `profile_update`/`notes`.

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
- Behavioral metrics (`avg_offtopic`, `avg_provocation`, `avg_spam`, `avg_rudeness`, `avg_verbosity`) are updated via an exponential moving average (`avg = alpha * sample + (1 - alpha) * avg`, `PROFILE_EMA_ALPHA`, default `0.3`) only on full-update turns (first message + every `PROFILE_FULL_UPDATE_INTERVAL`-th, default every 3rd). EMA (not a cumulative average) is deliberate: since updates only land on a fraction of turns, a cumulative average keyed on `message_count` would shrink each new sample's weight too fast and freeze the profile
- `PersonalityEngine` converts 0–1 float scores into 10-level directive strings injected into the system prompt, plus two cheap positive rules: `familiarity_rule(message_count)` (newcomer below `NEWCOMER_THRESHOLD` → slightly more explanatory/welcoming; regular at/above `REGULAR_THRESHOLD` → address by name/known facts, skip re-introductions) and `depth_rule(experience)` (from the `experience` structured fact: beginner/advanced/pro each get one terse depth directive, `amateur`/unset get none)
- `notes` is an LLM-maintained short free-text summary of communication style and behavioral hints, fully replaced each time it runs; durable structured facts live separately in `facts` (JSON column, see "LLM Response Contracts" above) — a small fixed set of keys (`name`, `location`, `equipment`, `experience`, `topics`) merged incrementally via `database.db.update_user_facts()`, rendered compactly into the system prompt's user card (`key: value; ...`, empty values omitted)
- Conversation history turns are labeled with the speaker's real name (`database.db.get_display_names()`, one batched query per turn for every distinct user_id in the window) instead of `User#<id>`, falling back to `@username` then `User#<id>` when no profile row/first_name exists
- A small, char-truncated "earlier messages from this user" background block (`PERSONALIZATION_EARLIER_MESSAGES_COUNT`, `PERSONALIZATION_EARLIER_MESSAGE_CHARS`) surfaces this user's own messages that fell out of the rolling context window, sourced from the in-RAM memory deque first and `database.db.get_recent_user_messages()` as an optional supplement — injected into the system prompt's user card, never into messages[], and clearly labeled as background so it doesn't derail the live conversation

## Image Generation Quota

- Persisted in SQLite, table `image_generation_usage(user_id, usage_date, count)`, primary key `(user_id, usage_date)` — `usage_date` is the UTC calendar date, so the quota resets at UTC midnight like the proactive daily caps
- `database.db.get_image_usage_count(user_id)` reads today's count (0 if no row yet); `database.db.increment_image_usage(user_id)` upserts it — only called after a successful generation, never on failure, so a rejected/failed attempt doesn't cost the user their quota
- Separate from the in-RAM spam cooldown (`core.cooldown`): the cooldown throttles request *rate*, this quota caps daily *spend* on OpenAI's Images API

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
| `starmap/command` | Publish | Send chart render requests to starmap-service |
| `starmap/result` | Subscribe | Receive `queued`/`ok`/`error` replies (routed by `request_id`) |
| `starmap/status` | Subscribe | starmap-service availability (`online`/`offline`, retained + LWT); drives the dynamic command menu |

The MQTT client (`mqtt_service`) runs `loop_forever` in a background daemon thread. On an unexpected disconnect, `on_disconnect` spawns a reconnect loop with exponential backoff (5s → cap 300s, up to 10 retries); a clean disconnect from `stop_mqtt()` does not trigger reconnects. Responses are routed only when the payload is valid JSON carrying a known `request_id`.

## Development & Testing

- Python 3.11. Install deps with `pip install -r requirements.txt` (paho-mqtt, pyTelegramBotAPI, requests, python-dotenv).
- Run tests: `pytest tests/ -v`. `conftest.py` sets fake required env vars before import (since `config/settings.py` calls `require_env()` at import time) and stubs `telebot` if not installed.
- CI (`.github/workflows`) runs, in order: black (`--line-length 120`), isort (`--profile black`), pylint (`fail-under 7.0`, excludes `tests/`), then pytest.
- Formatting/lint config lives in `pyproject.toml` (black, isort, pylint). Match the 120-char line length.

## Versioning & Releases

- The running version lives in the `VERSION` file at the repo root as plain `MAJOR.MINOR.PATCH` (semver: major = breaking change, minor = new feature, patch = fix). `config/settings.py` reads it once at import time into `BOT_VERSION` (fallback `"unknown"` if the file is missing).
- `/status` shows the version on every reply (see "CubeSat telemetry (/status)" above), so it's always visible in Telegram without needing shell/log access.
- When work on a branch is ready for a PR: bump `VERSION` and add a `CHANGELOG.md` entry (Keep a Changelog style) in the same branch, before committing/opening the PR.
- `CHANGELOG.md` is written in English only, whatever language the task or the bot's user-facing texts are in (quote Russian UI strings only when the exact text matters, e.g. a reply message).
- After the PR is merged: switch to `main`, pull, tag the merge commit `vX.Y.Z` (annotated tag), push the tag, then publish a GitHub release for that tag at https://github.com/miksrv/telegram-ai-bot/releases — e.g. `gh release create vX.Y.Z --title vX.Y.Z --notes <changelog section>`.

## Known Issues
- _None currently tracked._ Two previously documented MQTT issues have been resolved:
  - `/status` and `/photo` no longer block the Telegram polling thread — each waits for its MQTT reply in a background daemon thread.
  - Responses are no longer shared/stolen — `mqtt_service` routes each reply to a per-request queue keyed by `request_id`, so concurrent `/status`/`/photo` requests stay isolated.

## TODO / Roadmap
- **Semantic recall from the `messages` table (RAG).** The conversational path (`brain.think`) only sees the rolling in-RAM window (`MAX_CONTEXT_MESSAGES`); anything older is forgotten even though it persists in the `messages` table. Add retrieval over that table — keyword or embedding-based — so the bot can pull in relevant older context on demand (e.g. a user's equipment or a past observation). Note: this trades tokens for memory depth (retrieved snippets enter the prompt), so it is intentionally deferred until the cost/benefit is tuned (e.g. retrieve only on long-gap replies or when the query references absent context).
