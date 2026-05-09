"""
ProactiveEngine — per-chat state machine governing when TARS posts proactively.

State resets on restart (the daily cap is a UX constraint, not a safety invariant).
"""

import calendar
import random
import threading
import time
from datetime import datetime, timedelta, timezone

from config.settings import (
    PROACTIVE_MAX_PER_DAY,
    PROACTIVE_MIN_CONTEXT_MESSAGES,
    PROACTIVE_MIN_GAP_SECONDS,
    PROACTIVE_NEXT_MAX_SECONDS,
    PROACTIVE_NEXT_MIN_SECONDS,
)
from database.db import get_latest_message_timestamp, get_recent_messages


def _next_utc_midnight() -> int:
    """Returns the Unix timestamp of the next UTC midnight."""
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return calendar.timegm(tomorrow.timetuple())


class ProactiveEngine:
    """
    Per-chat in-RAM state machine.

    State per chat_id:
        count_today     — posts sent today (resets at UTC midnight)
        day_reset_at    — Unix timestamp of next UTC midnight
        last_posted_at  — Unix timestamp of last proactive post (0 = never)
        next_attempt_at — earliest the loop may fire for this chat
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
    # Internal helpers
    # --------------------------------------------------

    def _init_chat(self, chat_id: int):
        if chat_id not in self._state:
            self._state[chat_id] = {
                "count_today": 0,
                "day_reset_at": _next_utc_midnight(),
                "last_posted_at": 0,
                "next_attempt_at": 0,
            }

    def _reset_day_if_needed(self, chat_id: int):
        s = self._state[chat_id]
        now = time.time()
        if now >= s["day_reset_at"]:
            s["count_today"] = 0
            s["day_reset_at"] = _next_utc_midnight()

    def _schedule_next(self, chat_id: int):
        s = self._state[chat_id]
        if s["count_today"] >= PROACTIVE_MAX_PER_DAY:
            s["next_attempt_at"] = s["day_reset_at"]
        else:
            s["next_attempt_at"] = time.time() + random.randint(PROACTIVE_NEXT_MIN_SECONDS, PROACTIVE_NEXT_MAX_SECONDS)


# Module-level singleton
proactive_engine = ProactiveEngine()
