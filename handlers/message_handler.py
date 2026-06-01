"""
Telegram Message Handler
Handles incoming messages, triggers, cooldowns, and dispatches to TARSBrain
"""

import logging
import random
import time

from telebot import TeleBot, types

from config.settings import (
    ADMIN_IDS,
    PROACTIVE_CHAT_IDS,
    PROACTIVE_MIN_CHAR_COUNT,
    PROACTIVE_MIN_WORD_COUNT,
)
from core.brain import brain

# Global cooldown dictionary imported from cooldown module
from core.cooldown import cooldowns
from core.memory import memory
from database.db import ensure_user_profile_exists, save_message
from utils.identity import extract_telegram_identity
from utils.photo import extract_photo_url
from utils.triggers import is_calling_tars, is_reply_to_bot


def handle_message(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Main handler for incoming Telegram messages.
    """

    chat_id = message.chat.id
    user_id = message.from_user.id

    # --- Extract text ---
    text_content = message.text or message.caption or ""

    if not text_content.strip():
        return

    # --- Check triggers and replies ---
    has_trigger = is_calling_tars(text_content)
    is_reply = is_reply_to_bot(bot, message)

    standard_reply = (
        "Я не отвечаю в личных сообщениях 🙂\n"
        "Присоединяйтесь к астрономическому чату "
        "@astronom_chat и пообщаемся там!"
    )

    # --- PRIVATE CHAT LOGIC ---
    if message.chat.type == "private":
        if user_id in ADMIN_IDS:
            # Admin can interact in private chat
            pass
        else:
            bot.reply_to(message, standard_reply)
            logging.info(f"Blocked PRIVATE | user={user_id}")
            return

    # --- UNAUTHORIZED CHAT LOGIC ---
    # Allow if it has trigger or is a reply, but log the attempt
    if chat_id not in allowed_chat_ids and message.chat.type != "private":
        if has_trigger or is_reply:
            bot.reply_to(message, standard_reply)
            logging.info(f"Blocked UNAUTHORIZED | user={user_id} chat={chat_id}")
        return

    # Periodic cleanup of memory and cooldowns (5% chance per message)
    if random.random() < 0.05:
        memory.cleanup()
        cooldowns.cleanup()

    # --- Observe: save qualifying text messages for proactive context ---
    if (
        chat_id in PROACTIVE_CHAT_IDS
        and message.content_type == "text"
        and text_content
        and not text_content.startswith("/")
        and (len(text_content.split()) >= PROACTIVE_MIN_WORD_COUNT or len(text_content) >= PROACTIVE_MIN_CHAR_COUNT)
    ):
        try:
            save_message(
                chat_id=chat_id,
                user_id=user_id,
                telegram_message_id=message.message_id,
                first_name=message.from_user.first_name or "",
                username=message.from_user.username or "",
                text=text_content,
            )
            ensure_user_profile_exists(
                user_id=user_id,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name or "",
                username=message.from_user.username or "",
            )
        except Exception as e:
            logging.error(f"Observe error: {e}")

    # --- Extract text and photo ---
    photo_url, caption = extract_photo_url(bot, message)
    identity = extract_telegram_identity(message)

    # Ignore message if it doesn't call TARS and is not a reply
    if message.chat.type != "private" and not (has_trigger or is_reply):
        return

    # --- Cooldown check ---
    if not cooldowns.allowed(user_id):
        bot.reply_to(
            message, "Вы задаете слишком много вопросов. Пожалуйста, подождите немного перед следующим сообщением."
        )
        return

    # --- Logging ---
    used_ctx, total_mem = memory.get_stats(chat_id)
    logging.info(
        f"Processing | chat={chat_id} user={user_id} type={'IMG' if photo_url else 'TXT'} mem={used_ctx}/{total_mem}"
    )

    # --- Simulate typing ---
    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.5, 1.2))  # simulate thinking delay

    # If this is a reply to one of the bot's own messages (e.g. a proactive post),
    # capture that message's text so the LLM knows exactly what is being answered.
    # Proactive posts and older messages may be absent from the rolling chat memory.
    reply_to_text = None
    if is_reply and message.reply_to_message is not None:
        reply_to_text = message.reply_to_message.text or message.reply_to_message.caption

    # --- Generate reply ---
    if photo_url and (has_trigger or is_reply):
        reply = brain.analyze_image(
            chat_id=chat_id, user_id=user_id, image_url=photo_url, caption=caption, identity=identity
        )
    else:
        reply = brain.think(
            chat_id=chat_id,
            user_id=user_id,
            user_message=text_content[:1500],  # MAX_INPUT_CHARS
            identity=identity,
            reply_to_text=reply_to_text,
        )

    # --- Send reply ---
    try:
        bot.reply_to(message, reply)
    except Exception as e:
        logging.error(f"Telegram API Error: {e}")
