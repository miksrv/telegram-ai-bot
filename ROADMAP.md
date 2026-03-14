# TARS Roadmap

---

## AI Features

This section tracks planned improvements to TARS's core AI behavior. Each feature is
grounded in analysis of the current stack (see `CLAUDE.md`) and targets the specific
context of a Russian-language astronomy community chat.

---

### [AI-1] Proactive Engagement Mode

**Problem.**
TARS participates only when explicitly mentioned or replied to. Conversations flow
past it — observations shared, questions left hanging, celestial events mentioned —
without any involvement. This makes TARS feel like a vending machine rather than a
community member. At the same time, any mechanism that calls the LLM on every message
would be prohibitively expensive and noisy.

**Solution.**
Two complementary mechanisms work in tandem:

1. **Passive observation** — every qualifying text message in an authorized chat is
   stored in a new `messages` table. This is pure bookkeeping: no LLM is involved.
   The table is the source of truth for "what the community has been talking about."

2. **Proactive posting loop** — a background daemon thread wakes on a scheduled
   cadence and decides, per chat, whether to have TARS post a spontaneous message.
   The LLM is called *only* at this point, using the recent message history as
   context. The loop enforces a hard daily cap (default: 5 per chat) and a minimum
   gap between consecutive posts to prevent clustering.

The LLM is **never** called reactively by this feature. It is called only when the
proactive loop decides it is time to post, or when a user explicitly triggers TARS
through the normal path.

---

#### New Database Table: `messages`

Stores qualifying text messages from chats listed in `PROACTIVE_CHAT_IDS`. This is
a strict subset of `ALLOWED_CHAT_IDS`: a chat may be authorized to receive TARS
replies without being enrolled in proactive observation. Images, stickers, audio,
video, and documents are excluded. Messages with fewer than `PROACTIVE_MIN_WORD_COUNT`
words **and** fewer than `PROACTIVE_MIN_CHAR_COUNT` characters are also excluded (the
two thresholds are OR-ed: a message passing either threshold is saved).

```sql
CREATE TABLE IF NOT EXISTS messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id             INTEGER NOT NULL,
    user_id             INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    first_name          TEXT    DEFAULT '',
    username            TEXT    DEFAULT '',
    text                TEXT    NOT NULL,
    word_count          INTEGER NOT NULL,
    timestamp           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, timestamp);
```

`first_name` and `username` are denormalized from the Telegram message object at
insert time so context rendering never needs a join to `user_profile`, and
historical context remains readable even if a user later changes their display name.

`word_count` is precomputed at insert time (`len(text.split())`) so the proactive
loop can filter in SQL without a Python round-trip.

Messages are retained for `MESSAGE_TTL_SECONDS` (default: `86400`, 24 hours) and
purged by the cleanup daemon described below.

---

#### Proactive State Machine: `ProactiveEngine`

A per-chat in-RAM state machine that governs when TARS is allowed to post
proactively. State resets on restart (the daily cap is a UX constraint, not a
safety invariant, so this is acceptable).

State stored per `chat_id`:

```python
{
    "count_today":     int,  # posts sent so far today (0..PROACTIVE_MAX_PER_DAY)
    "day_reset_at":    int,  # Unix timestamp of next UTC midnight; counter resets here
    "last_posted_at":  int,  # Unix timestamp of the last proactive post (0 = never)
    "next_attempt_at": int,  # Unix timestamp: earliest the loop may fire again
}
```

`should_post(chat_id)` returns `True` only when **all** of the following hold:
- `time.time() >= next_attempt_at`
- `count_today < PROACTIVE_MAX_PER_DAY`
- `time.time() - last_posted_at >= PROACTIVE_MIN_GAP_SECONDS`
- The `messages` table has at least `PROACTIVE_MIN_CONTEXT_MESSAGES` rows for this
  chat (prevents posting into a silent or newly-joined chat)

`record_post(chat_id)` is called after a successful send:
- Increments `count_today`
- Updates `last_posted_at = now`
- If `count_today < PROACTIVE_MAX_PER_DAY`: sets `next_attempt_at = now +
  random.randint(PROACTIVE_NEXT_MIN_SECONDS, PROACTIVE_NEXT_MAX_SECONDS)`.
- If the daily cap is now reached: sets `next_attempt_at = day_reset_at` instead.

`_reset_day_if_needed(chat_id)` is called at the top of every `should_post()` call.
If `time.time() >= day_reset_at`: resets `count_today = 0` and advances
`day_reset_at` to the following UTC midnight.

---

#### Background Service: `services/background_service.py`

A new module that hosts both daemon threads. Neither loop blocks the Telegram
polling thread.

**Cleanup loop** (`start_cleanup_loop`):
Wakes every `CLEANUP_LOOP_INTERVAL_SECONDS` (default: `1800`, 30 minutes) and runs:
```sql
DELETE FROM messages WHERE timestamp < ?
```
with `cutoff = int(time.time()) - MESSAGE_TTL_SECONDS`. Logs the number of rows
deleted. Wrapped in `try/except` so a transient DB error does not kill the thread.

**Proactive loop** (`start_proactive_loop`):
Wakes every `PROACTIVE_LOOP_INTERVAL_SECONDS` (default: `600`, 10 minutes) and
iterates over `allowed_chat_ids`. For each chat:
1. Calls `engine.should_post(chat_id)`.
2. If `False`: skip.
3. If `True`: calls `brain.post_proactively(chat_id)` to generate a reply.
4. On success: sends via `bot.send_message(chat_id, reply)`, calls
   `engine.record_post(chat_id)`, adds the reply to `MemoryManager` chat context
   so subsequent triggered responses know what TARS said spontaneously.
5. On LLM failure: logs the error, does **not** call `record_post()` (a failed
   attempt does not consume the daily budget), reschedules
   `next_attempt_at = now + PROACTIVE_NEXT_MIN_SECONDS`.

---

#### New Prompt: `PROACTIVE_PROMPT_TEMPLATE`

Stored in `core/prompts.py` alongside `GENERAL_PROMPT_TEMPLATE`. Produces only
`{"reply": "..."}` — there is no single user being addressed, so `profile_update`
and `notes` are absent and must not appear in the output.

```
You are TARS, an autonomous robot from the movie "Interstellar".
You are monitoring an astronomy community chat. You have decided to post a
spontaneous message — an observation, a thought-provoking question, or a dry,
intelligent remark grounded in what the community has recently been discussing.

You must output **valid JSON only** with this exact structure:
{
  "reply": "<your message in Russian>"
}

Rules:
- Write in Russian.
- Do not address any specific user by name. Speak to the chat as a whole.
- The message should feel like a natural interjection: a curiosity, a provocation,
  a wry observation, or an open question — not a reply to any single person.
- 1 to 3 sentences maximum. Brevity is mandatory.
- Maintain the TARS character: dry, precise, slightly ironic, technically minded.
- Do not greet, apologize, announce yourself, or explain that you are speaking
  spontaneously. Just say the thing.
- Do not repeat or paraphrase anything from the most recent TARS message in context.
- Base the remark on the conversation context provided. Do not invent events,
  objects, or names not present in the context.
- Never output anything outside the JSON object.

Recent conversation ({context_size} most recent messages, oldest first):
{context}

Current UTC time: {utc_time}
```

The builder function `build_proactive_prompt(context_lines, utc_time)` formats this
template. `context_lines` is a list of `"FirstName: text"` strings retrieved from
the `messages` table.

---

#### User Profile Seeding (No LLM)

Every time a message is saved to `messages`, the system ensures a `user_profile`
row exists for that user via a new `ensure_user_profile_exists()` function:

```sql
INSERT OR IGNORE INTO user_profile(user_id, first_name, last_name, username, last_updated)
VALUES (?, ?, ?, ?, ?)
```

`INSERT OR IGNORE` makes this a zero-cost no-op when the profile already exists —
no prior `SELECT` is needed. No LLM is involved at any stage. The only fields
populated are those directly available from the Telegram `Message` object:
`user_id`, `first_name`, `last_name`, `username`. All behavioral metrics default
to their column defaults (`0.0` / `0.5`).

---

#### New Settings (`config/settings.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `PROACTIVE_ENABLED` | `True` | Master toggle; disables both daemon threads when `False` |
| `PROACTIVE_CHAT_IDS` | `set[int]` | Explicit set of chat IDs for which observation and proactive posting are active. Parsed from `PROACTIVE_CHAT_IDS` in `.env` (same comma-separated format as `ALLOWED_CHAT_IDS`). Must be a subset of `ALLOWED_CHAT_IDS`; any ID not in `ALLOWED_CHAT_IDS` is silently ignored at startup. |
| `PROACTIVE_MAX_PER_DAY` | `5` | Hard cap on proactive posts per chat per calendar day (UTC) |
| `PROACTIVE_MIN_GAP_SECONDS` | `3600` | Minimum seconds between any two consecutive proactive posts |
| `PROACTIVE_NEXT_MIN_SECONDS` | `7200` | Lower bound of the random reschedule window after a post |
| `PROACTIVE_NEXT_MAX_SECONDS` | `14400` | Upper bound of the random reschedule window after a post |
| `PROACTIVE_CONTEXT_MESSAGES` | `25` | Number of recent messages passed to the LLM as context |
| `PROACTIVE_MIN_CONTEXT_MESSAGES` | `10` | Minimum rows in `messages` before proactive posting activates for a chat |
| `PROACTIVE_MIN_WORD_COUNT` | `3` | Word-count lower bound for saving a message |
| `PROACTIVE_MIN_CHAR_COUNT` | `15` | Character-count lower bound (alternative to word count; OR logic) |
| `MESSAGE_TTL_SECONDS` | `86400` | How long a message row is retained (24 hours) |
| `CLEANUP_LOOP_INTERVAL_SECONDS` | `1800` | Interval between cleanup daemon passes |
| `PROACTIVE_LOOP_INTERVAL_SECONDS` | `600` | Interval between proactive daemon passes |

---

#### Sub-tasks

**A — Database layer**

- [x] **AI-3.1** Add the `messages` table definition and `idx_messages_chat_ts`
      index to `_init_db()` in `database/db.py`.
- [x] **AI-3.2** Add `save_message(chat_id, user_id, telegram_message_id,
      first_name, username, text)` to `database/db.py`. Compute
      `word_count = len(text.split())` before the `INSERT`. Single write, no prior
      `SELECT`.
- [x] **AI-3.3** Add `get_recent_messages(chat_id, limit) -> list[dict]` to
      `database/db.py`:
      ```sql
      SELECT first_name, username, text
      FROM messages
      WHERE chat_id = ?
      ORDER BY timestamp DESC
      LIMIT ?
      ```
      Reverse the result list before returning so the oldest row appears first
      in the context string.
- [x] **AI-3.4** Add `purge_expired_messages(ttl_seconds) -> int` to
      `database/db.py`. Returns `cursor.rowcount` for the caller to log.
- [x] **AI-3.5** Add `ensure_user_profile_exists(user_id, first_name, last_name,
      username)` to `database/db.py` using `INSERT OR IGNORE`. No reads,
      no LLM, no exceptions on duplicate.

**B — Configuration**

- [x] **AI-3.6** Add all thirteen settings from the table above to
      `config/settings.py` with the specified defaults and a `# Proactive
      Engagement` section comment. Parse `PROACTIVE_CHAT_IDS` with the existing
      `parse_chat_ids()` helper, then intersect the result with `ALLOWED_CHAT_IDS`
      and log a warning for any ID that was dropped:
      `PROACTIVE_CHAT_IDS = parse_chat_ids(os.getenv("PROACTIVE_CHAT_IDS", "")) & ALLOWED_CHAT_IDS`.

**C — Message filtering and saving**

- [x] **AI-3.7** In `message_handler.handle_message()`, insert an "observe" block
      immediately after the authorized-chat guard and before the trigger/reply check.
      Execute for every message in an authorized group chat (including those that
      don't trigger TARS). Filter logic:
      - Skip if `chat_id not in PROACTIVE_CHAT_IDS` (observation is opt-in per chat).
      - Skip if `message.content_type != "text"` (excludes photo, sticker, voice,
        video, document, etc.).
      - Skip if `text_content.startswith("/")` (commands are not conversational).
      - Skip if `len(text_content.split()) < PROACTIVE_MIN_WORD_COUNT` AND
        `len(text_content) < PROACTIVE_MIN_CHAR_COUNT`.
      - On pass: call `save_message(...)` then `ensure_user_profile_exists(...)`.
        Both calls are wrapped in a `try/except` so a DB error does not interrupt
        normal message processing.

**D — ProactiveEngine**

- [x] **AI-3.8** Create `core/proactive_engine.py`. Implement `ProactiveEngine`
      class with `should_post(chat_id) -> bool`, `record_post(chat_id)`,
      `_reset_day_if_needed(chat_id)`, and `_schedule_next(chat_id)`.
      Compute `day_reset_at` as the next UTC midnight:
      ```python
      import calendar
      from datetime import datetime, date, timedelta
      tomorrow = date.today() + timedelta(days=1)
      day_reset_at = calendar.timegm(tomorrow.timetuple())
      ```
- [x] **AI-3.9** Add module-level singleton `proactive_engine = ProactiveEngine()`
      at the bottom of `core/proactive_engine.py`.

**E — Prompt**

- [x] **AI-3.10** Add `PROACTIVE_PROMPT_TEMPLATE` string constant to
       `core/prompts.py` exactly as specified in the prompt section above.
- [x] **AI-3.11** Add `build_proactive_prompt(context_lines: list[str],
       utc_time: str) -> str` to `core/prompts.py`. Formats `context` as
       `"\n".join(context_lines)` and `context_size` as `len(context_lines)`.

**F — Brain**

- [x] **AI-3.12** Add `TARSBrain.post_proactively(chat_id: int) -> str | None`
       to `core/brain.py`:
       - Calls `get_recent_messages(chat_id, PROACTIVE_CONTEXT_MESSAGES)`.
       - If `len(rows) < PROACTIVE_MIN_CONTEXT_MESSAGES`: returns `None` (no LLM
         call — not enough context).
       - Formats `context_lines = [f"{r['first_name']}: {r['text']}" for r in rows]`.
       - Computes `utc_time` from `datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")`.
       - Calls `build_proactive_prompt(context_lines, utc_time)`.
       - Calls `_call_llm(MODEL_TEXT, messages=[{"role":"system","content":prompt}],
         temperature=0.85, max_tokens=200, top_p=0.95)`.
       - Parses JSON with `_parse_json_safe(raw)`, extracts `reply` field.
       - On success: calls `memory.add_chat_memory(chat_id, user_id=0,
         user_msg="", bot_reply=reply)` so the proactive post appears in
         TARS's own context for future triggered replies. Returns `reply`.
       - On any error: logs and returns `None`.

**G — Background service**

- [x] **AI-3.13** Create `services/background_service.py` with two public
       functions: `start_cleanup_loop(interval_seconds) -> threading.Thread` and
       `start_proactive_loop(bot, allowed_chat_ids, engine, interval_seconds)
       -> threading.Thread`. Both start their thread as a daemon before returning.
- [x] **AI-3.14** Implement the cleanup loop body in `start_cleanup_loop`:
       call `purge_expired_messages(MESSAGE_TTL_SECONDS)`, log the result as
       `f"Cleanup: purged {n} expired messages"`, then `time.sleep(interval_seconds)`.
       Wrap in `try/except Exception` to protect the thread from transient DB errors.
- [x] **AI-3.15** Implement the proactive loop body in `start_proactive_loop`:
       iterate `allowed_chat_ids`; for each chat call `engine.should_post(chat_id)`;
       on `True` call `brain.post_proactively(chat_id)` in a `try/except`; on a
       non-`None` return value send via `bot.send_message(chat_id, reply)` and call
       `engine.record_post(chat_id)`; on `None` or exception reschedule without
       consuming budget. After iterating all chats, sleep `interval_seconds`.

**H — Startup wiring**

- [x] **AI-3.16** In `main.py`, after `bot = init_bot()`, add:
       ```python
       if PROACTIVE_ENABLED:
           from core.proactive_engine import proactive_engine
           from services.background_service import start_cleanup_loop, start_proactive_loop
           from config.settings import (
               CLEANUP_LOOP_INTERVAL_SECONDS, PROACTIVE_LOOP_INTERVAL_SECONDS,
               PROACTIVE_CHAT_IDS,
           )
           start_cleanup_loop(CLEANUP_LOOP_INTERVAL_SECONDS)
           start_proactive_loop(
               bot, PROACTIVE_CHAT_IDS, proactive_engine,
               PROACTIVE_LOOP_INTERVAL_SECONDS
           )
       ```
       Note that `PROACTIVE_CHAT_IDS` — not `ALLOWED_CHAT_IDS` — is passed to
       `start_proactive_loop`. The proactive loop must never attempt to post into
       a chat that is not explicitly enrolled, even if TARS is authorized to reply
       there. The `PROACTIVE_ENABLED` guard means the entire feature can be toggled
       off via `.env` with zero code changes.
