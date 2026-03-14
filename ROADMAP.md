# TARS Roadmap

## Bug Fixes & Code Quality

Identified through static analysis of the current codebase. No new features —
only correctness, safety, and maintainability improvements.

---

### [FIX-1] Correctness: UTC Midnight Uses Local Date

**File:** `core/proactive_engine.py` — `_next_utc_midnight()`

`date.today()` returns the **local** system date. If the server is not in UTC,
the day boundary drifts. The `day_reset_at` label claims UTC but the value is
wrong.

- [ ] **FIX-1.1** Replace `date.today()` with `datetime.now(timezone.utc).date()`:
  ```python
  from datetime import datetime, timedelta, timezone
  tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
  day_reset_at = calendar.timegm(tomorrow.timetuple())
  ```

---

### [FIX-2] Security: Bot Token Embedded in Photo URL

**File:** `utils/photo.py`

The module imports `BOT_TOKEN` from settings and bakes it into a
`api.telegram.org/file/…` URL. Any log line, debug session, or test that prints
the URL leaks the token. Telegram provides the file URL directly via `get_file()`.

- [ ] **FIX-2.1** Remove the `BOT_TOKEN` import from `utils/photo.py`.
- [ ] **FIX-2.2** Replace manual URL construction with:
  ```python
  file_info = bot.get_file(photo.file_id)
  return file_info.file_path  # already a full URL
  ```
  Update the call site in `photo_handler.py` to pass `bot` into the helper, or
  resolve the URL inside the handler and pass it in.

---

### [FIX-3] Reliability: MQTT Connection Failure Silently Ignored at Startup

**File:** `main.py`, `services/mqtt_service.py`

`start_mqtt()` returns `False` when the broker is unreachable, but `main.py`
discards the return value. The bot starts normally; `/status` and `/photo`
commands then silently time out for 30–45 seconds per request.

- [ ] **FIX-3.1** In `main.py`, check the return value of `start_mqtt()` and log
  a prominent warning when it is `False`:
  ```python
  if not start_mqtt():
      logging.warning("MQTT unavailable — /status and /photo commands will not work")
  ```

---

### [FIX-4] Thread Safety: Missing Locks on Shared Mutable State

Three classes mutate shared dictionaries from multiple threads without
synchronisation.

**FIX-4.1 — `CooldownManager` (`core/cooldown.py`)**
- [ ] Add a `threading.Lock` instance; acquire it around all reads and writes to
  `_last_message`, `_window`, and `_penalty` in `allowed()` and `cleanup()`.

**FIX-4.2 — `MemoryManager` (`core/memory.py`)**
- [ ] Add a `threading.Lock`; acquire it when reading or writing `_chat_context`
  and `_user_context` dicts. Convert the deque to a list inside the lock before
  slicing in `get_chat_context()` to avoid iteration races.

**FIX-4.3 — `ProactiveEngine` (`core/proactive_engine.py`)**
- [ ] Add a `threading.Lock`; acquire it around all `_state` mutations and reads
  in `should_post()`, `record_post()`, and `_reset_day_if_needed()`.

---

### [FIX-5] Correctness: Empty Message Text Reaches `brain.think()`

**File:** `handlers/message_handler.py`

`text_content = message.text or message.caption or ""` can yield an empty string
for messages that carry only media. That empty string propagates through the
trigger check and, if a reply-to-bot edge case is hit, reaches `brain.think("")`.

- [ ] **FIX-5.1** Add an early return after `text_content` is assigned:
  ```python
  if not text_content.strip():
      return
  ```

---

### [FIX-6] Correctness: Interests List Grows Unbounded

**File:** `database/db.py` — `update_user_profile()`

Each `profile_update` appends the LLM-generated interests list to the existing
CSV string without deduplication or a length cap. Over many interactions a user's
`interests` field inflates to hundreds of items and starts consuming meaningful
space in the system prompt.

- [ ] **FIX-6.1** When merging interests, deduplicate and cap at 20 entries:
  ```python
  existing = set(profile.get("interests", []))
  incoming = set(profile_update.get("interests", []))
  merged = list(existing | incoming)[:20]
  ```

---

### [FIX-7] Error Handling: Weather API Fields Accessed Without Guard

**File:** `handlers/weather_handler.py`

Wind speed and other nested fields are accessed with direct key indexing. For
some location types (sea points, stations) the OpenWeatherMap API omits `wind`
or `rain` keys entirely, causing an unhandled `KeyError` that surfaces as a
silent failure to the user.

- [ ] **FIX-7.1** Replace direct key access for optional fields with `.get()`
  plus a safe fallback:
  ```python
  wind_speed = data.get("wind", {}).get("speed", "н/д")
  ```

---

### [FIX-8] Reliability: SQLite Directory Not Created Automatically

**File:** `database/db.py` — `_init_db()`

If the `data/` directory does not exist (fresh clone, Docker volume not mounted),
the first `sqlite3.connect(DB_PATH)` call raises `OperationalError` before any
table can be created.

- [ ] **FIX-8.1** Add directory creation at the top of `_init_db()`:
  ```python
  os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
  ```

---

### [FIX-9] Dead Code: `services/llm_service.py` Never Imported

**File:** `services/llm_service.py`

The module defines `generate_text_reply()` and `generate_image_reply()` but is
never imported anywhere. `core/brain.py` implements its own LLM calling logic
(`_call_llm`). This is leftover from a refactoring that was never completed.

- [ ] **FIX-9.1** Remove `services/llm_service.py` entirely; it adds dead surface
  area and misleads future readers about where LLM calls originate.

---

### [FIX-10] Code Quality: Duplicate Logging Configuration

**Files:** `config/settings.py` (runs on import), `main.py`

`logging.basicConfig(...)` is called twice. The second call in `main.py` is a
no-op because `basicConfig` only takes effect when no handlers are yet
registered — but it creates a confusing illusion that the format or level can be
changed there.

- [ ] **FIX-10.1** Remove the `logging.basicConfig` call from `config/settings.py`
  and keep only the one in `main.py`, which runs at a predictable point before
  any other module is imported.

---

### [FIX-11] Observability: Use `logging.exception()` in Silent `except` Blocks

**Files:** `core/brain.py`, `services/background_service.py`, others

Several `except Exception as e:` blocks call `logging.error(str(e))`, which
discards the traceback. When these paths fire in production the stack trace is
lost, making the root cause invisible.

- [ ] **FIX-11.1** Replace `logging.error(...)` inside bare `except` clauses with
  `logging.exception(...)` (or pass `exc_info=True`) wherever the full traceback
  is useful for diagnosis. Specifically: `brain.think()`, `brain.analyze_image()`,
  `brain.post_proactively()`, and the background loop bodies.

---

### [FIX-12] Config: Log Dropped Proactive Chat IDs

**File:** `config/settings.py`

IDs in `PROACTIVE_CHAT_IDS` that are not present in `ALLOWED_CHAT_IDS` are
silently dropped. A misconfigured `.env` gives no diagnostic hint.

- [ ] **FIX-12.1** After the intersection, compute and log the dropped set:
  ```python
  dropped = parsed_ids - ALLOWED_CHAT_IDS
  if dropped:
      logging.warning("Proactive chat IDs not in ALLOWED_CHAT_IDS (ignored): %s", dropped)
  ```
