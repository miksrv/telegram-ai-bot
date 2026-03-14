"""
TARS database module.
All user profile logic is centralized.
"""

import json
import sqlite3
import time
import logging
from typing import Dict, Any, Tuple
from config.settings import DB_PATH

# ==========================================================
# DATABASE CONNECTION
# ==========================================================

def get_connection() -> sqlite3.Connection:
    """Opens and returns a new SQLite connection."""
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)


# ==========================================================
# TABLE INITIALIZATION
# ==========================================================

def _init_db():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                message_count INTEGER DEFAULT 0,
                avg_offtopic REAL DEFAULT 0.0,
                avg_provocation REAL DEFAULT 0.0,
                avg_spam REAL DEFAULT 0.0,
                avg_rudeness REAL DEFAULT 0.0,
                avg_verbosity REAL DEFAULT 0.5,
                interests TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                last_updated INTEGER
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_memory (
                chat_id INTEGER PRIMARY KEY,
                last_access REAL,
                history_json TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_memory (
                user_id INTEGER PRIMARY KEY,
                last_access REAL,
                history_json TEXT
            );
        """)
        conn.execute("""
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
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_ts
            ON messages(chat_id, timestamp);
        """)
        conn.commit()
    finally:
        conn.close()

_init_db()


# ==========================================================
# USER PROFILE OPERATIONS
# ==========================================================

def get_user_profile(user_id: int, identity: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Returns a user profile dictionary.
    If there is no record, a default one is created.
    Optionally updates identity info (first_name, last_name, username).
    Each call opens and closes its own connection to avoid shared-cursor races.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        row = cursor.execute("""
            SELECT message_count, avg_offtopic, avg_provocation,
                   avg_spam, avg_rudeness, avg_verbosity,
                   interests, notes, first_name, last_name, username
            FROM user_profile WHERE user_id=?
                 """, (user_id,)).fetchone()

        if not row:
            first_name = identity.get('first_name', '') if identity else ''
            last_name = identity.get('last_name', '') if identity else ''
            username = identity.get('username', '') if identity else ''

            cursor.execute("""
                INSERT INTO user_profile(user_id, first_name, last_name, username, last_updated)
                VALUES (?, ?, ?, ?, ?)
                """, (user_id, first_name, last_name, username, int(time.time())))
            conn.commit()

            return {
                "message_count": 0,
                "avg_offtopic": 0.0,
                "avg_provocation": 0.0,
                "avg_spam": 0.0,
                "avg_rudeness": 0.0,
                "avg_verbosity": 0.5,
                "interests": [],
                "notes": "",
                "first_name": first_name,
                "last_name": last_name,
                "username": username
            }

        # Если identity передали, обновляем
        if identity:
            cursor.execute("""
                UPDATE user_profile
                SET first_name=?, last_name=?, username=?, last_updated=?
                WHERE user_id=?
                """, (identity.get('first_name',''), identity.get('last_name',''), identity.get('username',''), int(time.time()), user_id))
            conn.commit()

        return {
            "message_count": row[0],
            "avg_offtopic": row[1],
            "avg_provocation": row[2],
            "avg_spam": row[3],
            "avg_rudeness": row[4],
            "avg_verbosity": row[5],
            "interests": row[6].split(",") if row[6] else [],
            "notes": row[7] or "",
            "first_name": row[8] or "",
            "last_name": row[9] or "",
            "username": row[10] or ""
        }
    finally:
        conn.close()


def update_user_profile(user_id: int, profile_update: Dict[str, Any]):
    """
    Updates the user profile using a moving average.
    profile_update = {
        "offtopic": float,
        "provocation": float,
        "spam": float,
        "rudeness": float,
        "verbosity": float,
        "interests": List[str]
    }
    """
    profile = get_user_profile(user_id)
    count = profile["message_count"] + 1

    avg_offtopic = (profile["avg_offtopic"] * profile["message_count"] + profile_update.get("offtopic", 0)) / count
    avg_provocation = (profile["avg_provocation"] * profile["message_count"] + profile_update.get("provocation", 0)) / count
    avg_spam = (profile["avg_spam"] * profile["message_count"] + profile_update.get("spam", 0)) / count
    avg_rudeness = (profile["avg_rudeness"] * profile["message_count"] + profile_update.get("rudeness", 0)) / count
    avg_verbosity = (profile["avg_verbosity"] * profile["message_count"] + profile_update.get("verbosity", 0.5)) / count

    # Combine unique interests
    new_interests = set(profile["interests"]) | set(profile_update.get("interests", []))
    interests_str = ",".join(new_interests)

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO user_profile(
                user_id, message_count,
                avg_offtopic, avg_provocation,
                avg_spam, avg_rudeness,
                avg_verbosity, interests,
                last_updated
            )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        message_count=excluded.message_count,
                            avg_offtopic=excluded.avg_offtopic,
                            avg_provocation=excluded.avg_provocation,
                            avg_spam=excluded.avg_spam,
                            avg_rudeness=excluded.avg_rudeness,
                            avg_verbosity=excluded.avg_verbosity,
                            interests=excluded.interests,
                            last_updated=excluded.last_updated
                    """, (
                        user_id,
                        count,
                        avg_offtopic,
                        avg_provocation,
                        avg_spam,
                        avg_rudeness,
                        avg_verbosity,
                        interests_str,
                        int(time.time())
                    ))

        conn.commit()


def update_user_notes(user_id: int, new_info: str):
    """
    Replaces notes entirely (LLM maintains summary)
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profile
            SET notes=?, last_updated=?
            WHERE user_id=?
            """, (new_info, int(time.time()), user_id))

        conn.commit()


# ==========================================================
# MEMORY PERSISTENCE
# ==========================================================

def flush_memory(chat_storage: dict, user_storage: dict):
    """
    Writes the current in-RAM MemoryManager state to SQLite so it
    survives restarts.  Called by the shutdown handler.
    """
    conn = get_connection()
    try:
        conn.execute("DELETE FROM chat_memory")
        for chat_id, data in chat_storage.items():
            conn.execute(
                "INSERT INTO chat_memory(chat_id, last_access, history_json) VALUES (?, ?, ?)",
                (chat_id, data["last_access"], json.dumps(list(data["history"]))),
            )

        conn.execute("DELETE FROM user_memory")
        for user_id, data in user_storage.items():
            conn.execute(
                "INSERT INTO user_memory(user_id, last_access, history_json) VALUES (?, ?, ?)",
                (user_id, data["last_access"], json.dumps(list(data["history"]))),
            )

        conn.commit()
        logging.info(
            f"Memory flushed: {len(chat_storage)} chats, {len(user_storage)} users"
        )
    except Exception as e:
        logging.error(f"Failed to flush memory: {e}")
    finally:
        conn.close()


def load_memory() -> Tuple[dict, dict]:
    """
    Reads persisted chat and user history from SQLite.
    Returns (chat_data, user_data) suitable for reconstructing
    MemoryManager storage.  Returns empty dicts on any error.
    """
    chat_data: dict = {}
    user_data: dict = {}
    conn = get_connection()
    try:
        for row in conn.execute(
            "SELECT chat_id, last_access, history_json FROM chat_memory"
        ):
            chat_id, last_access, history_json = row
            chat_data[chat_id] = {
                "last_access": last_access,
                "history": [tuple(e) for e in json.loads(history_json)],
            }

        for row in conn.execute(
            "SELECT user_id, last_access, history_json FROM user_memory"
        ):
            user_id, last_access, history_json = row
            user_data[user_id] = {
                "last_access": last_access,
                "history": [tuple(e) for e in json.loads(history_json)],
            }

        logging.info(
            f"Memory loaded: {len(chat_data)} chats, {len(user_data)} users"
        )
    except Exception as e:
        logging.error(f"Failed to load memory: {e}")
    finally:
        conn.close()

    return chat_data, user_data


# ==========================================================
# MESSAGES TABLE OPERATIONS
# ==========================================================

def save_message(
        chat_id: int,
        user_id: int,
        telegram_message_id: int,
        first_name: str,
        username: str,
        text: str,
):
    """Saves a qualifying text message for proactive context."""
    word_count = len(text.split())
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO messages(chat_id, user_id, telegram_message_id,
                                 first_name, username, text, word_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, user_id, telegram_message_id,
              first_name, username, text, word_count, int(time.time())))
        conn.commit()


def get_recent_messages(chat_id: int, limit: int) -> list:
    """
    Returns up to `limit` most recent messages for a chat, ordered oldest-first.
    Each row is a dict with keys: first_name, username, text.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT first_name, username, text
            FROM messages
            WHERE chat_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (chat_id, limit)).fetchall()
        return [{"first_name": r[0], "username": r[1], "text": r[2]}
                for r in reversed(rows)]
    finally:
        conn.close()


def purge_expired_messages(ttl_seconds: int) -> int:
    """Deletes messages older than ttl_seconds. Returns the number of rows deleted."""
    cutoff = int(time.time()) - ttl_seconds
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
        conn.commit()
        return cursor.rowcount


def ensure_user_profile_exists(
        user_id: int,
        first_name: str,
        last_name: str,
        username: str,
):
    """
    Inserts a default user_profile row if none exists.
    Uses INSERT OR IGNORE — zero-cost no-op on duplicate. No LLM involved.
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO user_profile(user_id, first_name, last_name, username, last_updated)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, first_name, last_name, username, int(time.time())))
        conn.commit()


# ==========================================================
# CLEANUP
# ==========================================================

def close_connection():
    """No-op — connections are now opened and closed per-operation."""
    pass
