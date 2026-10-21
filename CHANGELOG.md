# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-10-21

### Added

- Swappable bot persona: the name, character, tone, self-identity names and
  extra trigger words moved out of `core/prompts.py` into `personas/<name>.md`
  files, selected with the new `PERSONA` setting (an unknown name fails at
  startup). Structural prompt rules (JSON contract, plain text, user card,
  capabilities, profile updates) stay in code and apply to every persona.
  `tars` reproduces the previous behavior; the new `peasant` persona (Микула, a
  peasant from ancient Rus' who speaks stylized Old Russian and is amazed by
  modern things) is the new default. The bot still answers to "тарс"/"tars"
  and, additionally, to the active persona's own name; both names are declared
  as referring to the bot in the self-identity rule.
- Keyword-based emoji reactions to ordinary chat messages, without any LLM
  call (`core/reactions.py`): `REACTIONS_ENABLED`,
  `REACTIONS_KEYWORD_PROBABILITY` (0.15), `REACTIONS_RANDOM_PROBABILITY`
  (0.02, only for messages with no keyword match) and a per-chat
  `REACTIONS_MIN_GAP_SECONDS` (600). Only emoji Telegram allows for bot
  reactions are used; messages the bot answers anyway are skipped.

### Changed

- `PROACTIVE_MAX_PER_DAY` default 5 -> 2.
- `PROACTIVE_REPLY_MAX_PER_DAY` default 1 -> 4.
- Proactive posts and direct replies are skipped while the bot's own message is
  newer than the latest observed user message, so the bot no longer talks to
  itself in a quiet chat. The guard also holds right after a restart: the
  bot's last-message time is restored from the persisted chat memory.

### Fixed

- After a direct reply the next one was always parked until the next UTC day,
  as if the daily cap were 1. It is now scheduled later the same day
  (`PROACTIVE_NEXT_MIN/MAX_SECONDS`) while budget remains.

## [1.1.0] - 2026-10-10

### Added

- Conversation history now labels turns with the speaker's real name (first
  name, falling back to `@username`, then `User#<id>`) via one batched DB
  lookup per turn instead of always showing `User#<id>`.
- A small, char-truncated background block of the current user's own earlier
  messages (outside the rolling context window) is injected into the system
  prompt's user card, clearly labeled as background so it never derails the
  live conversation (`PERSONALIZATION_EARLIER_MESSAGES_COUNT`,
  `PERSONALIZATION_EARLIER_MESSAGE_CHARS`).
- Structured user facts (`name`, `location`, `equipment`, `experience`,
  `topics`) maintained by the model via a new `facts` field on the full-update
  JSON contract, merged incrementally into a new `user_profile.facts` column
  (idempotent migration) and rendered compactly into the user card.
- `PersonalityEngine` gained two cheap positive directives: a familiarity rule
  from `message_count` (newcomer vs. regular) and a depth rule from the
  `experience` fact (beginner/advanced/pro).
- The full profile-update turn now runs every `PROFILE_FULL_UPDATE_INTERVAL`
  messages (default every 3rd, was every 5th), configurable via `.env`.
- System prompt: a terse self-identity line ("ТАРС"/"TARS"/"Тарс*" in any case
  or diminutive, including third-person mentions, refers to the bot) and a
  personalization line (use the user card, address by name occasionally,
  never recite the profile), shared by all conversational templates and
  cheaply by the proactive ones. A new dynamic capabilities block
  (`core.prompts.build_capabilities_line()`) states that image replies aren't
  possible and that `/image <description>` is the way to generate one (only
  when `IMAGE_GEN_ENABLED`), plus the other commands currently usable
  (star-chart commands only while starmap-service is online).

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

[1.1.0]: https://github.com/miksrv/telegram-ai-bot/releases/tag/v1.1.0
[1.0.0]: https://github.com/miksrv/telegram-ai-bot/releases/tag/v1.0.0
