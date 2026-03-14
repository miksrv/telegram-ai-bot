import time
from collections import deque
from typing import Dict, Deque, Tuple

from config.settings import (
    MAX_CONTEXT_MESSAGES,
    MEMORY_LIMIT,
    MEMORY_TTL_SECONDS,
)


ChatHistoryEntry = Tuple[int, str, str]   # (user_id, role, text)
UserHistoryEntry = Tuple[str, str]        # (role, text)


class MemoryManager:
    """
    Manages the bot's fast in-memory storage.

    Divided into:
        - Chat memory (chat context)
        - User memory (personal short context)

    No persistence — RAM only.
    """

    # --------------------------------------------------
    # INIT
    # --------------------------------------------------

    def __init__(self):
        self.chat_storage: Dict[int, Dict] = {}
        self.user_storage: Dict[int, Dict] = {}

    # ==================================================
    # CHAT CONTEXT
    # ==================================================

    def get_chat_context(self, chat_id: int) -> str:
        if chat_id not in self.chat_storage:
            return ""

        self.chat_storage[chat_id]["last_access"] = time.time()

        history: Deque[ChatHistoryEntry] = self.chat_storage[chat_id]["history"]

        lines = []
        for user_id, role, text in list(history)[-MAX_CONTEXT_MESSAGES:]:
            speaker = f"User#{user_id}" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def add_chat_memory(
            self,
            chat_id: int,
            user_id: int,
            user_msg: str,
            bot_reply: str,
    ):
        if chat_id not in self.chat_storage:
            self.chat_storage[chat_id] = {
                "last_access": time.time(),
                "history": deque(maxlen=MEMORY_LIMIT),
            }

        store = self.chat_storage[chat_id]
        store["last_access"] = time.time()

        store["history"].append((user_id, "user", user_msg))
        store["history"].append((user_id, "assistant", bot_reply))

    # ==================================================
    # USER CONTEXT
    # ==================================================

    def get_user_context(self, user_id: int) -> str:
        if user_id not in self.user_storage:
            return ""

        self.user_storage[user_id]["last_access"] = time.time()

        history: Deque[UserHistoryEntry] = self.user_storage[user_id]["history"]

        lines = []
        for role, text in list(history)[-5:]:
            speaker = "User" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def add_user_memory(
            self,
            user_id: int,
            user_msg: str,
            bot_reply: str,
    ):
        if user_id not in self.user_storage:
            self.user_storage[user_id] = {
                "last_access": time.time(),
                "history": deque(maxlen=20),
            }

        hist: Deque[UserHistoryEntry] = self.user_storage[user_id]["history"]

        self.user_storage[user_id]["last_access"] = time.time()

        hist.append(("user", user_msg))
        hist.append(("assistant", bot_reply))

    # ==================================================
    # STATS
    # ==================================================

    def get_stats(self, chat_id: int):
        if chat_id not in self.chat_storage:
            return 0, 0

        total = len(self.chat_storage[chat_id]["history"])
        used = min(total, MAX_CONTEXT_MESSAGES)
        return used, total

    # ==================================================
    # CLEANUP
    # ==================================================

    def cleanup(self):
        """
        Removes inactive chats from memory.
        Called periodically.
        """
        now = time.time()

        expired = [
            cid for cid, data in self.chat_storage.items()
            if now - data["last_access"] > MEMORY_TTL_SECONDS
        ]

        for cid in expired:
            del self.chat_storage[cid]

        expired_users = [
            uid for uid, data in self.user_storage.items()
            if now - data.get("last_access", 0) > MEMORY_TTL_SECONDS
        ]

        for uid in expired_users:
            del self.user_storage[uid]

    # ==================================================
    # DEBUG
    # ==================================================

    def size(self):
        return {
            "chats": len(self.chat_storage),
            "users": len(self.user_storage),
        }


# Singleton instance
memory = MemoryManager()
