"""
Background Service
Hosts the cleanup and proactive posting daemon threads.
Neither loop blocks the Telegram polling thread.
"""

import time
import logging
import threading

from config.settings import MESSAGE_TTL_SECONDS
from database.db import purge_expired_messages
from core.brain import brain

logger = logging.getLogger(__name__)


def start_cleanup_loop(interval_seconds: int) -> threading.Thread:
    """
    Starts a daemon thread that periodically purges expired messages from the DB.
    Returns the started thread.
    """
    def _loop():
        while True:
            try:
                n = purge_expired_messages(MESSAGE_TTL_SECONDS)
                logger.info(f"Cleanup: purged {n} expired messages")
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="cleanup-loop", daemon=True)
    t.start()
    logger.info(f"Cleanup loop started (interval={interval_seconds}s)")
    return t


def start_proactive_loop(
        bot,
        allowed_chat_ids: set,
        engine,
        interval_seconds: int,
) -> threading.Thread:
    """
    Starts a daemon thread that periodically checks each enrolled chat and
    posts a proactive message when the ProactiveEngine approves.
    Returns the started thread.
    """
    def _loop():
        while True:
            for chat_id in allowed_chat_ids:
                try:
                    if not engine.should_post(chat_id):
                        continue

                    reply = brain.post_proactively(chat_id)

                    if reply:
                        bot.send_message(chat_id, reply)
                        engine.record_post(chat_id)
                        logger.info(f"Proactive post sent to chat={chat_id}")
                    else:
                        engine.reschedule_failed(chat_id)
                        logger.warning(
                            f"Proactive post skipped (no content) for chat={chat_id}"
                        )

                except Exception as e:
                    logger.error(f"Proactive loop error (chat={chat_id}): {e}")
                    try:
                        engine.reschedule_failed(chat_id)
                    except Exception:
                        pass

            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="proactive-loop", daemon=True)
    t.start()
    logger.info(
        f"Proactive loop started (interval={interval_seconds}s, "
        f"chats={len(allowed_chat_ids)})"
    )
    return t
