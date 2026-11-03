"""Blacklist check: users listed in BLOCKED_USER_IDS are ignored completely."""

import logging

from config.settings import BLOCKED_USER_IDS


def is_blocked_user(message) -> bool:
    """True if the message's sender is blacklisted (logged at debug level only)."""
    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)
    if user_id is not None and user_id in BLOCKED_USER_IDS:
        logging.debug("Ignoring message from blocked user %s", user_id)
        return True
    return False
