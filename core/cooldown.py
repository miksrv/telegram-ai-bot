import time
from typing import Dict, Deque
from collections import deque

from config.settings import USER_COOLDOWN_SECONDS, RATE_LIMIT_COUNT, RATE_LIMIT_WINDOW, RATE_LIMIT_PENALTY


class CooldownManager:
    """
    Advanced rate limiter.

    Features:
    ----------
    1) Classic cooldown:
        USER_COOLDOWN_SECONDS between messages

    2) Sliding window rate limit:
        Max RATE_LIMIT_COUNT messages per RATE_LIMIT_WINDOW seconds

        If exceeded:
            user receives penalty cooldown (RATE_LIMIT_PENALTY)

    Designed for easy future extension:
        - per chat cooldown
        - per command cooldown
        - Redis backend
        - persistent storage
    """

    def __init__(self):
        # Last accepted message timestamp (classic cooldown)
        self._last_action: Dict[int, float] = {}

        # Sliding window message timestamps
        self._windows: Dict[int, Deque[float]] = {}

        # Penalty lock timestamps
        self._penalty_until: Dict[int, float] = {}

    # --------------------------------------------------
    # Check if user is allowed to perform action
    # --------------------------------------------------
    def allowed(self, user_id: int) -> bool:
        now = time.time()

        # ----- Check penalty cooldown -----
        penalty = self._penalty_until.get(user_id)
        if penalty and now < penalty:
            return False

        # ----- Classic cooldown -----
        last = self._last_action.get(user_id, 0)
        if now - last < USER_COOLDOWN_SECONDS:
            return False

        # ----- Sliding window rate limiting -----
        window = self._windows.setdefault(user_id, deque())

        # Remove timestamps outside window
        while window and now - window[0] > RATE_LIMIT_WINDOW:
            window.popleft()

        # If limit exceeded → apply penalty
        if len(window) >= RATE_LIMIT_COUNT:
            self._penalty_until[user_id] = now + RATE_LIMIT_PENALTY
            return False

        # Record accepted action
        window.append(now)
        self._last_action[user_id] = now
        return True

    # --------------------------------------------------
    # Forcefully set cooldown
    # --------------------------------------------------
    def set(self, user_id: int):
        """
        Forces classic cooldown reset.
        """
        self._last_action[user_id] = time.time()

    # --------------------------------------------------
    # Cleanup old records
    # --------------------------------------------------
    def cleanup(self):
        """
        Removes stale entries to prevent memory growth.

        Should be called periodically.
        """

        now = time.time()
        expire_window = RATE_LIMIT_WINDOW * 3
        expire_cooldown = USER_COOLDOWN_SECONDS * 3

        # Clean classic cooldowns
        for uid in list(self._last_action.keys()):
            if now - self._last_action[uid] > expire_cooldown:
                del self._last_action[uid]

        # Clean windows
        for uid in list(self._windows.keys()):
            window = self._windows[uid]

            while window and now - window[0] > expire_window:
                window.popleft()

            if not window:
                del self._windows[uid]

        # Clean penalties
        for uid in list(self._penalty_until.keys()):
            if now > self._penalty_until[uid]:
                del self._penalty_until[uid]

    # --------------------------------------------------
    # Debug stats
    # --------------------------------------------------
    def size(self) -> int:
        return len(self._last_action)


# Singleton instance
cooldowns = CooldownManager()
