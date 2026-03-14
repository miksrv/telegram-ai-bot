# TARS Roadmap

---

## AI Features

This section tracks planned improvements to TARS's core AI behavior. Each feature is
grounded in analysis of the current stack (see `CLAUDE.md`) and targets the specific
context of a Russian-language astronomy community chat.

---

### [AI-1] Rolling Conversation Summarization

**Problem.**
`MemoryManager.chat_storage` is a `deque(maxlen=50)`. When the deque is full, the
oldest messages are silently dropped. `get_chat_context` then surfaces only the last 10
entries. Any context older than those 10 messages — topic threads, prior conclusions,
prior user questions — is permanently lost. For a busy community chat this horizon can
be as short as a few minutes.

**Solution.**
Before a message is evicted from the deque, trigger a background summarization pass:
the LLM condenses the oldest N messages into a compact paragraph and stores it as a
rolling `summary` string alongside the deque. The prompt builder then injects both the
rolling summary and the recent transcript, giving TARS effective long-term chat memory
without unbounded token growth.

**Sub-tasks.**

- [ ] **AI-1.1** Add a `summary: str` field to `chat_storage` entries (default `""`).
- [ ] **AI-1.2** Add `SUMMARY_TRIGGER_RATIO` setting (e.g. `0.8`): summarization fires
      when `len(history) >= MEMORY_LIMIT * SUMMARY_TRIGGER_RATIO`.
- [ ] **AI-1.3** Write `SUMMARY_PROMPT_TEMPLATE` in `core/prompts.py`: instructs the
      LLM to produce a 3–5 sentence factual summary of a message batch, in Russian,
      preserving names, topics discussed, and conclusions reached.
- [ ] **AI-1.4** Add `TARSBrain.summarize_context(chat_id)` method: calls the LLM with
      the oldest `MEMORY_LIMIT // 2` messages and writes the result back to
      `chat_storage[chat_id]["summary"]`, then removes those messages from the deque.
- [ ] **AI-1.5** Update `MemoryManager.get_chat_context()` to prepend the rolling
      summary (if non-empty) before the recent transcript lines, separated by a
      `--- Earlier context ---` marker so the LLM can distinguish recency.
- [ ] **AI-1.6** Call `brain.summarize_context(chat_id)` inside `add_chat_memory()`
      when the trigger ratio is exceeded, in a daemon thread so it does not block
      the polling loop.
- [ ] **AI-1.7** Add `summarization_count` stat to `MemoryManager.size()` for
      observability.

---

### [AI-2] Astronomy Domain Classifier & Domain-Aware Prompt Routing

**Problem.**
All messages go through a single generic `GENERAL_PROMPT_TEMPLATE`. TARS has no
awareness of which sub-domain of astronomy it is operating in. A question about
astrophotography processing techniques requires a very different register, depth, and
vocabulary than a question about relativistic cosmology or a satellite telemetry
reading — yet the prompt makes no distinction.

**Solution.**
Add a lightweight domain classification step before building the system prompt.
Classify the message into one of the astronomy sub-domains and inject a domain-specific
prompt extension that shifts TARS's persona and knowledge emphasis accordingly.

**Domains.**

| ID | Domain | Examples |
|----|--------|---------|
| `astrophotography` | Image capture, processing, stacking, equipment | "How to reduce noise in a 30s sub?", photo shared |
| `observational` | Visual astronomy, what's visible tonight, sky conditions | "Can I see Saturn tonight?", "What's the best DSO for 4\" scope?" |
| `theoretical` | Physics, cosmology, mathematics | "Why does the Hubble tension exist?", "Explain redshift" |
| `space_tech` | Satellites, rockets, CubeSat, missions | "What orbit is Starlink in?", telemetry discussion |
| `equipment` | Telescopes, mounts, accessories, buying advice | "Should I buy an EQ6-R?", "Best eyepiece for planetary?" |
| `general` | Off-topic, casual, greetings | Catch-all |

**Sub-tasks.**

- [ ] **AI-2.1** Write `DOMAIN_CLASSIFIER_PROMPT` in `core/prompts.py`: a minimal
      single-turn prompt that classifies a message into one of the 6 domain IDs above.
      Output must be a single JSON field `{"domain": "<id>"}` to minimize token cost.
- [ ] **AI-2.2** Add `TARSBrain.classify_domain(message_text) -> str` method: makes a
      fast, low-temperature (0.1) call using `MODEL_TEXT` with `max_tokens=20`.
      Returns one of the 6 domain strings; falls back to `"general"` on any error.
- [ ] **AI-2.3** Add `DOMAIN_PROMPT_EXTENSIONS: dict[str, str]` in `core/prompts.py`:
      a mapping from domain ID to a short (3–6 line) specialist instruction block.
      Example for `astrophotography`: "You are advising an astrophotographer. Speak
      in terms of exposure time, calibration frames, stacking software (Siril,
      PixInsight, DeepSkyStacker), and sensor noise characteristics."
- [ ] **AI-2.4** Update `build_general_prompt()` to accept an optional `domain_block`
      parameter and append it after the adaptive behavior directives section.
- [ ] **AI-2.5** Update `TARSBrain.think()` to call `classify_domain()` and pass the
      resulting extension to `build_general_prompt()`.
- [ ] **AI-2.6** Store the classified domain in the LLM JSON response contract as an
      optional `"domain"` echo field and record it in `db_update_user_profile` to
      enrich per-user interest depth tracking (see AI-4).
- [ ] **AI-2.7** Add `DOMAIN_CLASSIFICATION_ENABLED` boolean setting so the feature
      can be toggled off to reduce API call volume if needed.

---

### [AI-3] Proactive Engagement Mode (Passive Observer)

**Problem.**
TARS participates only when explicitly mentioned or replied to. In a community chat,
countless interesting messages pass by without TARS involvement — a user shares a
stunning photo without tagging TARS, someone asks a question that goes unanswered,
an observed celestial event is mentioned. This makes TARS feel like a vending machine
rather than a community member.

**Solution.**
Let TARS passively observe all authorized chat messages. After each unaddressed message
(no trigger, no direct reply), a lightweight relevance check determines whether TARS
should proactively interject. Proactive replies are gated by relevance score, cooldown,
and a global per-chat interjection budget to prevent TARS from becoming noisy.

**Proactive triggers (any one is sufficient).**
1. A question mark is present and the message has no reply for N subsequent messages.
2. The message topic matches a strong interest of a chat member TARS knows.
3. An astronomically significant keyword is detected (planet names, messier/NGC
   identifiers, equipment model numbers, solar events).
4. A photo is shared without a caption or TARS mention (offer image analysis).

**Sub-tasks.**

- [ ] **AI-3.1** Add `PROACTIVE_ENABLED` and `PROACTIVE_RELEVANCE_THRESHOLD` (0–1)
      settings in `config/settings.py`.
- [ ] **AI-3.2** Add `PROACTIVE_CHAT_BUDGET` setting: maximum proactive replies per
      chat per hour to prevent flooding. Default: `3`.
- [ ] **AI-3.3** Track a `proactive_budget` counter per chat in `MemoryManager`
      (dict keyed by chat_id, reset hourly via TTL).
- [ ] **AI-3.4** Write `PROACTIVE_RELEVANCE_PROMPT` in `core/prompts.py`: ask the LLM
      to score a message's astronomical relevance and TARS's potential added value on
      a 0–1 scale. Output: `{"relevance": 0.0..1.0, "reason": "short string"}`.
- [ ] **AI-3.5** Add `TARSBrain.should_engage(message_text, chat_id) -> bool` method:
      applies keyword pre-filter first (fast, no API call), then LLM relevance scoring
      if pre-filter passes, then budget check.
- [ ] **AI-3.6** Write `PROACTIVE_REPLY_PROMPT` extension in `core/prompts.py`:
      instructs TARS that it is interjecting voluntarily, not being addressed, and
      should phrase the reply as a natural observation ("Заметил, что...") rather than
      a direct answer to a question.
- [ ] **AI-3.7** Update `message_handler.handle_message()`: after the
      "ignore if no trigger/reply" gate, call `should_engage()` and route to
      `brain.think()` with a proactive context flag if it returns `True`.
- [ ] **AI-3.8** Ensure proactive replies do not update the cooldown timer so they
      don't block the user from triggering TARS normally shortly after.

---

### [AI-4] Deep Interest Profiling with Per-Topic Expertise Tracking

**Problem.**
`interests` in the user profile is a flat comma-separated string (`"astrophotography,
deep sky objects, PixInsight"`). There is no depth dimension: TARS cannot distinguish
a user who has mentioned astrophotography once from one who has discussed it in 50
conversations. As a result, TARS cannot modulate expertise level per topic — it uses
the same `verbosity` metric globally, regardless of what the user actually knows.

**Solution.**
Replace the flat interest string with a JSON object stored in the SQLite column. Each
interest entry carries a `count` (number of times mentioned), `depth` (0–1, computed
from count), and `last_seen` timestamp. `PersonalityEngine` uses the depth of the
*active* topic (detected via AI-2's domain classifier) to calibrate response
sophistication per topic rather than globally.

**Sub-tasks.**

- [ ] **AI-4.1** Design the interest schema:
      `{"astrophotography": {"count": 14, "depth": 0.7, "last_seen": 1710000000}, ...}`
- [ ] **AI-4.2** Write a DB migration in `database/db.py`: add `interests_v2 TEXT`
      column to `user_profile` table; populate from existing `interests` string on
      first read (each existing interest gets `count=1, depth=0.1, last_seen=now`).
- [ ] **AI-4.3** Update `get_user_profile()` to deserialize `interests_v2` JSON and
      return it as `profile["interest_map"]`.
- [ ] **AI-4.4** Update `update_user_profile()`: when new interests arrive from the
      LLM `profile_update`, increment `count` for matching interests, insert new ones,
      and recompute `depth = min(1.0, count / INTEREST_DEPTH_SATURATION)` where
      `INTEREST_DEPTH_SATURATION` is a new setting (default: `20`).
- [ ] **AI-4.5** Add `PersonalityEngine.expertise_rule(depth: float) -> str`:
      10-level mapping from `0.0` (complete novice) to `1.0` (domain expert), producing
      directives like "Explain from first principles" → "Assume expert-level familiarity,
      skip fundamentals".
- [ ] **AI-4.6** Update `TARSBrain._build_user_context()`: if domain is known (from
      AI-2), look up the depth for that domain's interest key and include an expertise
      directive in the profile summary via `PersonalityEngine.expertise_rule()`.
- [ ] **AI-4.7** Update the prompt to include top-3 interests with depth percentages
      (e.g. "astrophotography (70%), deep sky objects (40%), CubeSat (10%)") so the LLM
      can reason about the user's knowledge landscape at a glance.

---

### [AI-5] Response Confidence Signaling

**Problem.**
The LLM sometimes produces plausible-sounding but factually incorrect answers,
especially on specific numerical data (distances, magnitudes, orbital parameters,
historical dates). For a science-oriented community this is harmful: confident errors
erode trust in TARS and can mislead less experienced members.

**Solution.**
Extend the JSON response contract with a `confidence` field (0–1). Low-confidence
responses are automatically qualified with an honest uncertainty disclaimer. High-
confidence responses remain unmodified. The threshold is configurable.

**Sub-tasks.**

- [ ] **AI-5.1** Add `"confidence": 0.0..1.0` to the `GENERAL_PROMPT_TEMPLATE` JSON
      contract definition, with an instruction: "Set to 1.0 for well-established facts,
      lower for estimates, approximations, or areas where your training data may be
      incomplete or outdated. Astronomy-specific: always lower confidence for numerical
      values like distances, magnitudes, or dates unless you are certain."
- [ ] **AI-5.2** Add `CONFIDENCE_DISCLAIMER_THRESHOLD` setting (default: `0.65`).
- [ ] **AI-5.3** Update `TARSBrain._process_llm_response()`: extract `confidence` from
      the parsed JSON; if `confidence < CONFIDENCE_DISCLAIMER_THRESHOLD`, append a
      brief, in-character Russian disclaimer to the reply (e.g., "Уточните в надёжном
      источнике — моя уверенность в этих данных невысока.").
- [ ] **AI-5.4** Log the confidence value alongside the message for observability:
      `logging.info(f"Confidence={confidence:.2f} user={user_id}")`.
- [ ] **AI-5.5** Store the running average confidence per user in their profile
      (new `avg_confidence` column in `user_profile`) as a diagnostic metric — users
      who consistently ask questions TARS is uncertain about may be experts probing the
      edges of the LLM's knowledge.

---

### [AI-6] Chat Atmosphere Engine (Chat-Level Personality Adaptation)

**Problem.**
`PersonalityEngine` adapts TARS's behavior per user (rudeness, verbosity, etc.) but
TARS has no model of the chat as a whole. The same directives are applied whether the
chat is in a fast-moving, playful brainstorming session or a focused technical
deep-dive. TARS can feel tonally misaligned when the chat atmosphere conflicts with
an individual user's historical profile.

**Solution.**
Add a chat-level behavioral model: a lightweight set of signals computed from recent
chat_storage activity. These signals produce "atmosphere directives" that augment the
per-user directives with context about the current state of the group conversation.

**Atmosphere signals.**

| Signal | Computation | Effect |
|--------|-------------|--------|
| `velocity` | Messages per minute in the last 10 min | High velocity → shorter replies |
| `topic_focus` | Fraction of recent messages in the same domain (AI-2) | High focus → deeper technical responses |
| `emotional_tone` | Aggregated `provocation` from recent senders' profiles | High tone → more neutral, de-escalating replies |
| `engagement` | Ratio of messages addressed to TARS vs total | Low engagement → briefer, less intrusive replies |

**Sub-tasks.**

- [ ] **AI-6.1** Add `message_timestamps: deque` to `chat_storage` entries, updated on
      every message received (not just TARS interactions) to enable velocity tracking.
      `message_handler.py` must call a new `memory.record_message(chat_id)` on every
      non-filtered message.
- [ ] **AI-6.2** Add `ChatAtmosphereEngine` class in a new file
      `core/atmosphere_engine.py`, mirroring `PersonalityEngine`'s structure:
      `compute(chat_storage_entry, recent_profiles) -> str` returning a directive block.
- [ ] **AI-6.3** Implement the four signal computations in `ChatAtmosphereEngine`:
      velocity, topic focus (requires AI-2), emotional tone (reads profile cache),
      engagement ratio (TARS replies vs total message count).
- [ ] **AI-6.4** Update `TARSBrain._build_user_context()` to also call
      `ChatAtmosphereEngine.compute()` and return an `atmosphere_block` string.
- [ ] **AI-6.5** Update `build_general_prompt()` to accept and inject the
      `atmosphere_block` as a new "Current chat atmosphere:" section in the prompt,
      positioned between the user identity block and the user message.
- [ ] **AI-6.6** Add `ATMOSPHERE_ENGINE_ENABLED` setting for toggle control.

---

### [AI-7] Multi-Turn Reasoning for Complex Questions

**Problem.**
TARS answers all questions in a single LLM call regardless of complexity. Simple
factual questions and multi-step reasoning problems (e.g. "Why is there a discrepancy
between early and late universe measurements of the Hubble constant?") go through the
same pipeline. Complex questions get shallow answers because a single forward pass at
800 tokens is insufficient for the problem's depth.

**Solution.**
Add a two-stage pipeline for complex questions: a first "reasoning" pass generates
a hidden chain-of-thought analysis; the second "reply" pass distills the reasoning into
a well-structured, user-facing Russian response. The complexity gate uses a fast
heuristic to avoid the double-call overhead on simple messages.

**Sub-tasks.**

- [ ] **AI-7.1** Define complexity heuristics in `core/brain.py` as
      `_is_complex(text: str) -> bool`: returns `True` when any of the following hold:
      - message length > 200 characters
      - contains "почему", "объясни", "как работает", "в чём разница", "докажи"
      - contains a physics/cosmology keyword set (configurable in settings)
- [ ] **AI-7.2** Write `REASONING_PROMPT_TEMPLATE` in `core/prompts.py`: instructs the
      LLM to reason step-by-step in English (for best chain-of-thought quality) about
      the question, listing assumptions, intermediate steps, and known uncertainties.
      Output is plain text, not JSON.
- [ ] **AI-7.3** Write `REASONING_SYNTHESIS_PROMPT` in `core/prompts.py`: takes the
      user question + reasoning output and produces the final JSON response contract,
      but now grounded in the explicit reasoning chain.
- [ ] **AI-7.4** Add `TARSBrain._reason(message_text, context) -> str` method:
      calls the LLM with `REASONING_PROMPT_TEMPLATE`, high `max_tokens` (1500),
      temperature 0.3 for factual consistency.
- [ ] **AI-7.5** Update `TARSBrain.think()`: if `_is_complex()` returns `True`, call
      `_reason()` first and pass the reasoning output as additional context to the
      main `_call_llm()` pass.
- [ ] **AI-7.6** Add `COMPLEX_REASONING_ENABLED` setting and log when the reasoning
      path is triggered: `logging.info(f"Complex reasoning triggered | user={user_id}")`.

---

### [AI-8] Reply Thread Context Walking

**Problem.**
Telegram supports threaded replies. When user B replies to user A's message (not to
TARS), and then tags TARS in a follow-up, TARS has no visibility into the A→B thread.
It can only see the message it is being asked about, not the conversational lineage
that motivated the question. This frequently produces contextually wrong answers.

**Solution.**
Walk the `reply_to_message` chain from the incoming message up to its root, collecting
the thread as an ordered list of (user, text) pairs, and inject it as a "Message thread"
block in the prompt — distinct from the rolling chat context — so TARS can reason
within the correct conversational scope.

**Sub-tasks.**

- [ ] **AI-8.1** Add `extract_thread_context(message: types.Message, max_depth: int = 5) -> list[dict]`
      utility function in `utils/triggers.py` (or a new `utils/thread.py`): traverses
      `message.reply_to_message` recursively up to `max_depth` hops, collecting
      `{"user": first_name, "text": text}` dicts.
- [ ] **AI-8.2** Add `THREAD_CONTEXT_MAX_DEPTH` setting (default: `5`) and
      `THREAD_CONTEXT_ENABLED` toggle.
- [ ] **AI-8.3** Update `build_general_prompt()` to accept an optional `thread_context`
      parameter; when non-empty, render it as a "Reply thread (innermost last):" block
      between the conversation context and the user message.
- [ ] **AI-8.4** Update `message_handler.handle_message()`: call `extract_thread_context()`
      when the incoming message is a reply (whether to TARS or to another user), and
      pass the result to `brain.think()`.
- [ ] **AI-8.5** Update `TARSBrain.think()` signature to accept `thread_context` and
      forward it to `build_general_prompt()`.

---

## Improvements

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
