"""
Keeps Telegram's "typing..." indicator alive for the duration of a slow
operation (e.g. an LLM call).

Telegram clears the indicator ~5 seconds after the last sendChatAction call
(or immediately once a real message is sent), so a single call isn't enough
to cover anything slower than that — it must be refreshed periodically.
"""

import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 4.0


@contextmanager
def typing_action(bot, chat_id, action: str = "typing", interval: float = _DEFAULT_INTERVAL_SECONDS):
    """Sends `action` immediately, then keeps refreshing it every `interval`
    seconds in a background thread until the `with` block exits."""
    stop_event = threading.Event()

    def _heartbeat():
        while not stop_event.is_set():
            try:
                bot.send_chat_action(chat_id, action)
            except Exception as e:
                logger.warning(f"send_chat_action failed (chat={chat_id}): {e}")
            stop_event.wait(interval)

    thread = threading.Thread(target=_heartbeat, name="typing-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)
