# TARS Roadmap

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
