# TARS Roadmap

## Bugs

### Medium

**[BUG-4] `is_reply_to_bot` calls `bot.get_me()` on every message**
`utils/triggers.py` calls `bot.get_me()` for every incoming message to obtain the bot's own user ID. This issues an HTTP request to the Telegram API on every single message.
Fix: cache the bot ID once at startup (e.g., call `bot.get_me()` in `init_bot` and store `bot.bot_id`).

**[BUG-5] `user_storage` in `MemoryManager` is never cleaned up**
`MemoryManager.cleanup()` only evicts expired `chat_storage` entries. `user_storage` grows unboundedly for the lifetime of the process, one entry per user who ever messaged the bot.
Fix: add TTL-based eviction for `user_storage` using the same `MEMORY_TTL_SECONDS` mechanism.

**[BUG-6] `CooldownManager.cleanup()` is never called**
`message_handler.py` calls `memory.cleanup()` with 5% probability, but never calls `cooldowns.cleanup()`. The cooldown dictionaries (`_last_action`, `_windows`, `_penalty_until`) accumulate stale entries indefinitely.
Fix: call `cooldowns.cleanup()` in the same block as `memory.cleanup()`.

**[BUG-7] `/photo` command missing group chat authorization check**
`photo_handler.handle_photo` only blocks private-chat non-admins. It does not check whether the message originates from an allowed group chat (`ALLOWED_CHAT_IDS`). Any user in any group chat can issue `/photo`.
Fix: add the same `chat_id not in allowed_chat_ids` guard used in `status_handler`.

### Low

**[BUG-8] Duplicate `{user_profile_summary}` in system prompt**
`core/prompts.py` `GENERAL_PROMPT_TEMPLATE` inserts `{user_profile_summary}` twice: once under "Adaptive behavior directives" and again under "User profile". The profile summary is sent to the LLM twice every request, wasting tokens.
Fix: remove one of the two occurrences.

**[BUG-9] `TRIGGERS` set in `config/settings.py` is dead code**
`config/settings.py` defines a `TRIGGERS` set that is never imported anywhere. `utils/triggers.py` maintains its own independent copy. The settings constant serves no purpose.
Fix: remove `TRIGGERS` from `settings.py`, or import from there into `triggers.py`.

**[BUG-10] `ProfileRepository` class is unused**
`database/profile_repo.py` defines a `ProfileRepository` class with static methods. `brain.py` imports the underlying db functions directly (via `from database.profile_repo import db_get_user_profile...`), bypassing the class entirely. The class is dead code.
Fix: either use `ProfileRepository` consistently in `brain.py`, or remove the class and keep only the function re-exports.

**[BUG-11] `get_connection()` docstring says "Singleton" but creates a new connection each call**
The function comment is misleading. The actual singleton is the module-level `conn` variable.
Fix: correct the docstring.

---

## Improvements

### Reliability

**[IMP-1] Persistent memory across restarts**
`MemoryManager` is RAM-only. All conversation context is lost when the bot restarts. For a long-running community bot, this breaks conversational continuity.
Options: periodically flush chat/user history to SQLite, or use Redis.

**[IMP-2] MQTT reconnect strategy**
`on_disconnect` calls `client.reconnect()` after a 5-second sleep, but this runs inside the paho callback thread and can cause issues if reconnection fails repeatedly. A proper exponential backoff loop with a maximum retry count would be more robust.

**[IMP-3] Graceful shutdown should close DB and MQTT**
`main.py` catches `SIGINT`/`SIGTERM` but only calls `sys.exit(0)`. The SQLite connection and MQTT client are not explicitly closed. `database/db.py` even defines `close_connection()` but it is never called.
Fix: call `close_connection()` and `mqtt_client.disconnect()` in the shutdown handler.

### Features

**[IMP-4] `/status` and `/photo` progress feedback**
Currently the user receives only one "requesting…" message and then waits silently for up to 30–45s. A follow-up "still waiting…" message at the halfway point would improve UX.

**[IMP-5] Admin command to view user profile**
Admins have no way to inspect a user's stored behavioral profile or notes. An `/admin profile <user_id>` command would be useful for moderation.

**[IMP-6] `/clear` or `/reset` command**
No mechanism for users to reset their conversation memory or profile scores. Useful when a user wants a fresh start with the bot.

**[IMP-7] Weather command UX**
`/weather` currently requires a city name argument. Handling the case where no argument is provided (replying with usage instructions) would improve the user experience.

**[IMP-8] Vision analysis for CubeSat photos**
Photos received from the CubeSat via `/photo` are sent directly to the chat without any analysis. Passing them through `brain.analyze_image` would add scientific commentary.

### Code Quality

**[IMP-9] Consolidate trigger configuration**
`TRIGGERS` appears in both `config/settings.py` (unused) and `utils/triggers.py` (hardcoded). A single source of truth in `settings.py`, imported by `triggers.py`, would be cleaner.

**[IMP-10] Type annotations on public interfaces**
Several public functions lack return type annotations (`handle_message`, `handle_status`, `handle_photo`, `start_mqtt`). Adding them would improve IDE support and catch bugs earlier.

**[IMP-11] Replace `time.sleep` in MQTT wait loops with event-driven approach**
The `time.sleep(0.2)` in the polling loops in `status_handler` and `photo_handler` is a busy-wait anti-pattern. Using `threading.Event` or `asyncio` would be cleaner and more efficient.
