import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

from config.settings import (
    MAX_CONTEXT_MESSAGES,
    MEMORY_LIMIT,
    MEMORY_TTL_SECONDS,
)
from database.db import flush_memory, load_memory

ChatHistoryEntry = Tuple[int, str, str]  # (user_id, role, text)


class MemoryManager:
    """
    Manages the bot's fast in-memory chat context.

    State is persisted to SQLite on shutdown via flush() and reloaded
    automatically on the next startup.
    """

    # --------------------------------------------------
    # INIT
    # --------------------------------------------------

    def __init__(self):
        self._lock = threading.Lock()
        self.chat_storage: Dict[int, Dict] = {}
        self._load()

    def _load(self):
        """Restores chat history from SQLite into RAM."""
        chat_data = load_memory()
        for chat_id, data in chat_data.items():
            self.chat_storage[chat_id] = {
                "last_access": data["last_access"],
                "history": deque(data["history"], maxlen=MEMORY_LIMIT),
            }

    # ==================================================
    # CHAT CONTEXT
    # ==================================================

    def get_chat_context(self, chat_id: int) -> str:
        with self._lock:
            if chat_id not in self.chat_storage:
                return ""

            self.chat_storage[chat_id]["last_access"] = time.time()

            history: Deque[ChatHistoryEntry] = self.chat_storage[chat_id]["history"]
            snapshot = list(history)[-MAX_CONTEXT_MESSAGES:]

        lines = []
        for user_id, role, text in snapshot:
            speaker = f"User#{user_id}" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def get_chat_history(self, chat_id: int) -> list:
        """Returns the last MAX_CONTEXT_MESSAGES entries as raw (user_id, role, text) tuples."""
        with self._lock:
            if chat_id not in self.chat_storage:
                return []

            self.chat_storage[chat_id]["last_access"] = time.time()

            history: Deque[ChatHistoryEntry] = self.chat_storage[chat_id]["history"]
            return list(history)[-MAX_CONTEXT_MESSAGES:]

    def add_chat_memory(
        self,
        chat_id: int,
        user_id: int,
        user_msg: str,
        bot_reply: str,
    ):
        with self._lock:
            if chat_id not in self.chat_storage:
                self.chat_storage[chat_id] = {
                    "last_access": time.time(),
                    "history": deque(maxlen=MEMORY_LIMIT),
                }

            store = self.chat_storage[chat_id]
            store["last_access"] = time.time()

            store["history"].append((user_id, "user", user_msg))
            store["history"].append((user_id, "assistant", bot_reply))

    def add_bot_message(self, chat_id: int, text: str):
        """Records a standalone bot message (e.g. a proactive post) as an assistant turn.

        Unlike add_chat_memory there is no preceding user message, so the chat history
        stays coherent when a user later replies to or follows up on a proactive post.
        """
        with self._lock:
            if chat_id not in self.chat_storage:
                self.chat_storage[chat_id] = {
                    "last_access": time.time(),
                    "history": deque(maxlen=MEMORY_LIMIT),
                }

            store = self.chat_storage[chat_id]
            store["last_access"] = time.time()
            store["history"].append((0, "assistant", text))

    def last_sender_is_bot(self, chat_id: int) -> bool:
        """Returns True if the last recorded message in the chat was from the bot."""
        with self._lock:
            if chat_id not in self.chat_storage:
                return False
            history = self.chat_storage[chat_id]["history"]
            if not history:
                return False
            return history[-1][1] == "assistant"

    # ==================================================
    # STATS
    # ==================================================

    def get_stats(self, chat_id: int):
        with self._lock:
            if chat_id not in self.chat_storage:
                return 0, 0

            total = len(self.chat_storage[chat_id]["history"])
            used = min(total, MAX_CONTEXT_MESSAGES)
            return used, total

    # ==================================================
    # CLEANUP
    # ==================================================

    def flush(self):
        """Persists current in-RAM state to SQLite. Called on shutdown."""
        with self._lock:
            flush_memory(self.chat_storage)

    def cleanup(self):
        """
        Removes inactive chats from memory.
        Called periodically.
        """
        now = time.time()

        with self._lock:
            expired = [cid for cid, data in self.chat_storage.items() if now - data["last_access"] > MEMORY_TTL_SECONDS]

            for cid in expired:
                del self.chat_storage[cid]

    # ==================================================
    # DEBUG
    # ==================================================

    def size(self):
        return {
            "chats": len(self.chat_storage),
        }


# Singleton instance
memory = MemoryManager()
