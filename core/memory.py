import logging
import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

from config.settings import (
    DB_PATH,
    MAX_CONTEXT_MESSAGES,
    MEMORY_LIMIT,
    MEMORY_TTL_SECONDS,
)
from core.persona import persona
from database.db import flush_memory, load_memory

ChatHistoryEntry = Tuple[int, str, str]  # (user_id, role, text)

# Remembers which persona wrote the persisted chat history, so a persona switch can drop it.
PERSONA_MARKER_PATH = os.path.join(os.path.dirname(DB_PATH), "active_persona")


def _persona_changed(marker_path: str = PERSONA_MARKER_PATH) -> bool:
    """True when the persisted history was written under another persona. Old assistant turns in
    another voice make the model keep that voice despite the new system prompt, so such history is
    discarded. No marker yet (first start with this feature) counts as the same persona."""
    try:
        with open(marker_path, encoding="utf-8") as f:
            previous = f.read().strip()
    except OSError:
        return False
    return bool(previous) and previous != persona.key


def _record_persona(marker_path: str = PERSONA_MARKER_PATH):
    """Records which persona wrote the history being persisted. Written together with the history
    (on flush), so after an unclean stop the old history and the old marker still match and the
    next start drops that history again."""
    try:
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write(persona.key)
    except OSError as e:
        logging.warning("Could not record the active persona: %s", e)


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
        # Unix time of the bot's last message per chat. Not persisted on its own: _load
        # seeds it from the restored history so the proactive "bot spoke last" guard
        # survives a restart; 0 (unknown) is treated as "no".
        self._last_bot_at: Dict[int, float] = {}
        self._load()

    def _load(self):
        """Restores chat history from SQLite into RAM."""
        chat_data = load_memory()
        reset = bool(chat_data) and _persona_changed()
        if reset:
            logging.info("Persona changed to '%s': chat history from the previous persona dropped", persona.key)
        for chat_id, data in chat_data.items():
            self.chat_storage[chat_id] = {
                "last_access": data["last_access"],
                "history": deque(data["history"], maxlen=MEMORY_LIMIT),
            }
            # last_access is the closest saved time to that last bot turn (it can only be later,
            # which errs on the side of the guard keeping the bot quiet until the next user message).
            if data["history"] and data["history"][-1][1] == "assistant":
                self._last_bot_at[chat_id] = float(data["last_access"])
            if reset:
                # Keep the seeded bot time above: the "bot spoke last" guard is persona-agnostic.
                self.chat_storage[chat_id]["history"].clear()

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
            speaker = f"User#{user_id}" if role == "user" else persona.name
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
            self._last_bot_at[chat_id] = time.time()

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
            self._last_bot_at[chat_id] = time.time()

    def get_user_earlier_messages(self, chat_id: int, user_id: int, limit: int) -> list:
        """Returns up to `limit` of this user's own user-turn texts from the chat's
        full in-RAM history (up to MEMORY_LIMIT entries), excluding the most recent
        MAX_CONTEXT_MESSAGES entries already surfaced via get_chat_history — i.e.
        messages that fell out of the rolling window but are still held in RAM.
        Most-recent-first among the excluded range; oldest-first order overall.
        """
        if limit <= 0:
            return []

        with self._lock:
            if chat_id not in self.chat_storage:
                return []

            history = list(self.chat_storage[chat_id]["history"])

        older = history[:-MAX_CONTEXT_MESSAGES] if len(history) > MAX_CONTEXT_MESSAGES else []
        texts = [text for uid, role, text in older if uid == user_id and role == "user"]
        return texts[-limit:]

    def last_bot_message_at(self, chat_id: int) -> float:
        """Unix time of the bot's last message in the chat, 0 if unknown.

        Unlike last_sender_is_bot, this can be compared with the timestamp of the
        latest observed user message: chat memory only holds turns the bot took part
        in, so a human's plain chatter never lands there and "last entry is the bot"
        alone would stay true while people keep talking.
        """
        with self._lock:
            return self._last_bot_at.get(chat_id, 0.0)

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
            _record_persona()

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
