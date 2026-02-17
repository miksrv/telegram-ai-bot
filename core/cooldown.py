import time
from typing import Dict

from config.settings import USER_COOLDOWN_SECONDS


class CooldownManager:
    """
    Manages user request rate limiting.
    By default — global cooldown per user\_id.

    Easily extendable later:
        - different cooldowns per chat
        - different cooldowns per command
        - Redis backend
        - persistence
    """

    def __init__(self):
        self._cooldowns: Dict[int, float] = {}

    # --------------------------------------------------
    # Action availability check
    # --------------------------------------------------
    def allowed(self, user_id: int) -> bool:
        now = time.time()
        last = self._cooldowns.get(user_id, 0)

        if now - last < USER_COOLDOWN_SECONDS:
            return False

        self._cooldowns[user_id] = now
        return True

    # --------------------------------------------------
    # Forcefully set cooldown
    # --------------------------------------------------
    def set(self, user_id: int):
        self._cooldowns[user_id] = time.time()

    # --------------------------------------------------
    # Cleanup of old records
    # --------------------------------------------------
    def cleanup(self):
        """
        Removes entries older than 3x cooldown.
        Call periodically (for example, together with memory.cleanup)
        """
        now = time.time()
        threshold = USER_COOLDOWN_SECONDS * 3

        expired = [
            uid for uid, ts in self._cooldowns.items()
            if now - ts > threshold
        ]

        for uid in expired:
            del self._cooldowns[uid]

    # --------------------------------------------------
    # Statistics (for debugging)
    # --------------------------------------------------
    def size(self) -> int:
        return len(self._cooldowns)


# Singleton instance
cooldowns = CooldownManager()
