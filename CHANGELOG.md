# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-06

First official release of TARS. The bot today:

- Conversational AI for the group chat, switchable between Groq and OpenAI
  (`LLM_ENGINE`), with automatic failover to the other provider on quota
  exhaustion.
- Per-user adaptive profiles (behavioral averages, interests, notes) that
  shape a personality layer injected into every prompt.
- Proactive engagement: spontaneous posts on a schedule, plus a once-daily
  direct reply to a specific past message.
- CubeSat ground-station commands over MQTT: `/status` (telemetry) and
  `/photo`.
- Star chart requests over MQTT to the companion starmap-service: `/sky`,
  `/horizon`, `/skymap`, `/galaxy`.
- `/weather`, `/stats`, `/help`, and `/image` (OpenAI image generation with a
  per-user daily quota).
- Startup notification to admins with engine, model, and MQTT/proactive
  status.

### Added

- `VERSION` file as the single source of truth for the running version
  (`config.settings.BOT_VERSION`).
- `/status` now shows the bot version on every reply, including timeouts and
  errors, so it's visible even when CubeSat doesn't answer.

### Fixed

- A full profile-update turn whose `notes` field came back as a JSON object
  instead of a string (observed with gpt-4o-mini) crashed sqlite3's parameter
  binding and discarded an already-generated reply. `notes` is now normalized
  (string used as-is, dict/list serialized, anything else dropped with a
  warning), `profile_update` is validated as a dict, and both optional side
  effects can no longer turn a valid reply into a failure.

[1.0.0]: https://github.com/miksrv/telegram-ai-bot/releases/tag/v1.0.0
