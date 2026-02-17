"""
TARS database module.
All user profile logic is centralized.
"""

import sqlite3
import time
import logging
from typing import Dict, Any
from config.settings import DB_PATH

# ==========================================================
# DATABASE CONNECTION
# ==========================================================

def get_connection() -> sqlite3.Connection:
    """Singleton connection к SQLite"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    return conn


conn = get_connection()
cursor = conn.cursor()


# ==========================================================
# TABLE INITIALIZATION
# ==========================================================

cursor.execute("""
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

conn.commit()


# ==========================================================
# USER PROFILE OPERATIONS
# ==========================================================

def get_user_profile(user_id: int, identity: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Returns a user profile dictionary.
    If there is no record, a default one is created.
    Optionally updates identity info (first_name, last_name, username)
    """
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
# CLEANUP
# ==========================================================

def close_connection():
    """Close the connection upon termination"""
    try:
        conn.close()
    except Exception as e:
        logging.error(f"Error closing DB: {e}")
