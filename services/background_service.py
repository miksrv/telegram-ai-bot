"""
Background Service
Hosts the cleanup and proactive posting daemon threads.
Neither loop blocks the Telegram polling thread.
"""

import logging
import threading
import time

from config.settings import MESSAGE_TTL_SECONDS, PROACTIVE_REPLY_ENABLED
from core.brain import brain
from core.memory import memory
from database.db import mark_message_replied, purge_expired_messages

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
                logger.exception(f"Cleanup loop error: {e}")

            # Periodically persist in-RAM chat memory so it survives a crash or
            # hard kill, not just a graceful shutdown. flush() is idempotent.
            try:
                memory.flush()
            except Exception as e:
                logger.exception(f"Periodic memory flush error: {e}")

            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="cleanup-loop", daemon=True)
    t.start()
    logger.info(f"Cleanup loop started (interval={interval_seconds}s)")
    return t


def _try_proactive_reply(bot, engine, chat_id: int, candidate: dict):
    """Generates and sends the once-daily direct reply to `candidate`, a message
    dict from ProactiveEngine.should_post_reply (id, telegram_message_id,
    first_name, username, text). Isolated in its own try/except so a failure
    reschedules via reschedule_reply_failed, not the general post's reschedule_failed.
    """
    try:
        reply = brain.post_proactive_reply(
            chat_id,
            target_text=candidate["text"],
            target_author=candidate["first_name"] or candidate["username"] or "участник чата",
        )

        if not reply:
            engine.reschedule_reply_failed(chat_id)
            logger.warning(f"Proactive reply skipped (no content) for chat={chat_id}")
            return

        bot.send_message(chat_id, reply, reply_to_message_id=candidate["telegram_message_id"])
        memory.add_bot_message(chat_id, reply)
        mark_message_replied(candidate["id"])
        engine.record_reply(chat_id)
        logger.info(f"Proactive reply sent to chat={chat_id} (message_id={candidate['telegram_message_id']})")

    except Exception as e:
        logger.exception(f"Proactive reply error (chat={chat_id}): {e}")
        try:
            engine.reschedule_reply_failed(chat_id)
        except Exception:
            pass


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
                    if engine.should_post(chat_id):
                        reply = brain.post_proactively(chat_id)

                        if reply:
                            bot.send_message(chat_id, reply)
                            # Record the proactive post in chat memory so that follow-ups
                            # and replies to it have the right context (avoids hallucination).
                            memory.add_bot_message(chat_id, reply)
                            engine.record_post(chat_id)
                            logger.info(f"Proactive post sent to chat={chat_id}")
                        else:
                            engine.reschedule_failed(chat_id)
                            logger.warning(f"Proactive post skipped (no content) for chat={chat_id}")
                        continue

                    if not PROACTIVE_REPLY_ENABLED:
                        continue

                    candidate = engine.should_post_reply(chat_id)
                    if not candidate:
                        continue

                    _try_proactive_reply(bot, engine, chat_id, candidate)

                except Exception as e:
                    logger.exception(f"Proactive loop error (chat={chat_id}): {e}")
                    try:
                        engine.reschedule_failed(chat_id)
                    except Exception:
                        pass

            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="proactive-loop", daemon=True)
    t.start()
    logger.info(f"Proactive loop started (interval={interval_seconds}s, " f"chats={len(allowed_chat_ids)})")
    return t
