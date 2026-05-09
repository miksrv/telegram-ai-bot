"""
Telegram Identity Utilities
Provides functions to extract user identity from Telegram messages
"""

from telebot.types import Message


def extract_telegram_identity(message: Message) -> dict:
    """
    Extracts the Telegram user's identity from a message.

    Returns a dictionary with:
    - id: Telegram user ID
    - first_name
    - last_name
    - username
    - language (language_code)
    """
    user = message.from_user

    return {
        "id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or "",
        "language": user.language_code or "",
    }
