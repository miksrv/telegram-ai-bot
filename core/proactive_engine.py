"""
ProactiveEngine — per-chat state machine governing when TARS posts proactively.

State resets on restart (the daily cap is a UX constraint, not a safety invariant).
Besides the general proactive posts, the engine also governs a once-daily direct
reply to a specific past message (see should_post_reply/record_reply below).
"""

import calendar
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from config.settings import (
    PROACTIVE_MAX_PER_DAY,
    PROACTIVE_MIN_CONTEXT_MESSAGES,
    PROACTIVE_MIN_GAP_SECONDS,
    PROACTIVE_NEXT_MAX_SECONDS,
    PROACTIVE_NEXT_MIN_SECONDS,
    PROACTIVE_REPLY_MAX_DELAY_SECONDS,
    PROACTIVE_REPLY_MAX_PER_DAY,
    PROACTIVE_REPLY_MIN_DELAY_SECONDS,
    PROACTIVE_REPLY_MIN_WORD_COUNT,
)
from database.db import get_latest_message_timestamp, get_recent_messages, get_reply_candidate


def _next_utc_midnight() -> int:
    """Returns the Unix timestamp of the next UTC midnight."""
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return calendar.timegm(tomorrow.timetuple())


class ProactiveEngine:
    """
    Per-chat in-RAM state machine.

    State per chat_id:
        count_today           — posts sent today (resets at UTC midnight)
        day_reset_at           — Unix timestamp of next UTC midnight
        last_posted_at         — Unix timestamp of last proactive action, post or
                                  reply (0 = never); shared so the two features
                                  respect a single PROACTIVE_MIN_GAP_SECONDS gap
        next_attempt_at        — earliest the loop may fire a general post
        reply_count_today      — direct replies sent today (resets at UTC midnight)
        next_reply_attempt_at  — earliest the loop may fire the daily direct reply
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[int, dict] = {}

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def should_post(self, chat_id: int) -> bool:
        """Returns True only when all posting conditions are satisfied."""
        with self._lock:
            self._init_chat(chat_id)
            self._reset_day_if_needed(chat_id)

            s = self._state[chat_id]
            now = time.time()

            if now < s["next_attempt_at"]:
                return False
            if s["count_today"] >= PROACTIVE_MAX_PER_DAY:
                return False
            if s["last_posted_at"] and now - s["last_posted_at"] < PROACTIVE_MIN_GAP_SECONDS:
                return False

            last_posted_at = s["last_posted_at"]

        # Require enough context rows in the DB (outside lock to avoid blocking)
        rows = get_recent_messages(chat_id, PROACTIVE_MIN_CONTEXT_MESSAGES)
        if len(rows) < PROACTIVE_MIN_CONTEXT_MESSAGES:
            return False

        # Don't post if there are no new user messages since the last proactive post
        if get_latest_message_timestamp(chat_id) <= last_posted_at:
            return False

        return True

    def record_post(self, chat_id: int):
        """Called after a successful proactive send."""
        with self._lock:
            self._init_chat(chat_id)
            s = self._state[chat_id]
            now = time.time()

            s["count_today"] += 1
            s["last_posted_at"] = now
            self._schedule_next(chat_id)

    def reschedule_failed(self, chat_id: int):
        """Called when LLM failed — advances next_attempt_at without consuming budget."""
        with self._lock:
            self._init_chat(chat_id)
            self._state[chat_id]["next_attempt_at"] = time.time() + PROACTIVE_NEXT_MIN_SECONDS

    # --------------------------------------------------
    # Public API — once-daily direct reply to a specific message
    # --------------------------------------------------

    def should_post_reply(self, chat_id: int) -> Optional[dict]:
        """
        Returns the candidate message to reply to when all reply conditions are
        satisfied, or None otherwise. The candidate is selected here (SQL/Python),
        not by the LLM, so the caller spends exactly one API call on the reply text.
        """
        with self._lock:
            self._init_chat(chat_id)
            self._reset_day_if_needed(chat_id)

            s = self._state[chat_id]
            now = time.time()

            if now < s["next_reply_attempt_at"]:
                return None
            if s["reply_count_today"] >= PROACTIVE_REPLY_MAX_PER_DAY:
                return None
            if s["last_posted_at"] and now - s["last_posted_at"] < PROACTIVE_MIN_GAP_SECONDS:
                return None

        # Require enough context rows in the DB (outside lock to avoid blocking)
        rows = get_recent_messages(chat_id, PROACTIVE_MIN_CONTEXT_MESSAGES)
        if len(rows) < PROACTIVE_MIN_CONTEXT_MESSAGES:
            return None

        return get_reply_candidate(chat_id, PROACTIVE_REPLY_MIN_WORD_COUNT)

    def record_reply(self, chat_id: int):
        """Called after a successful direct reply send."""
        with self._lock:
            self._init_chat(chat_id)
            s = self._state[chat_id]
            now = time.time()

            s["reply_count_today"] += 1
            s["last_posted_at"] = now
            # Budget is exhausted for the day either way (default cap is 1); park
            # the next attempt at the day boundary, where _reset_day_if_needed
            # will re-roll a fresh random delay for the following day.
            s["next_reply_attempt_at"] = s["day_reset_at"]

    def reschedule_reply_failed(self, chat_id: int):
        """Called when the reply LLM call failed — retries later without consuming budget."""
        with self._lock:
            self._init_chat(chat_id)
            self._state[chat_id]["next_reply_attempt_at"] = time.time() + PROACTIVE_NEXT_MIN_SECONDS

    # --------------------------------------------------
    # Internal helpers
    # --------------------------------------------------

    def _init_chat(self, chat_id: int):
        if chat_id not in self._state:
            self._state[chat_id] = {
                "count_today": 0,
                "day_reset_at": _next_utc_midnight(),
                "last_posted_at": 0,
                "next_attempt_at": 0,
                "reply_count_today": 0,
                "next_reply_attempt_at": time.time()
                + random.randint(PROACTIVE_REPLY_MIN_DELAY_SECONDS, PROACTIVE_REPLY_MAX_DELAY_SECONDS),
            }

    def _reset_day_if_needed(self, chat_id: int):
        s = self._state[chat_id]
        now = time.time()
        if now >= s["day_reset_at"]:
            s["count_today"] = 0
            s["reply_count_today"] = 0
            s["day_reset_at"] = _next_utc_midnight()
            midnight_today = s["day_reset_at"] - 86400
            next_at = midnight_today + random.randint(PROACTIVE_REPLY_MIN_DELAY_SECONDS, PROACTIVE_REPLY_MAX_DELAY_SECONDS)
            if next_at <= now:
                next_at = s["day_reset_at"] + random.randint(PROACTIVE_REPLY_MIN_DELAY_SECONDS, PROACTIVE_REPLY_MAX_DELAY_SECONDS)
            s["next_reply_attempt_at"] = next_at

    def _schedule_next(self, chat_id: int):
        s = self._state[chat_id]
        if s["count_today"] >= PROACTIVE_MAX_PER_DAY:
            s["next_attempt_at"] = s["day_reset_at"]
        else:
            s["next_attempt_at"] = time.time() + random.randint(PROACTIVE_NEXT_MIN_SECONDS, PROACTIVE_NEXT_MAX_SECONDS)


# Module-level singleton
proactive_engine = ProactiveEngine()
