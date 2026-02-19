"""
Telegram Message Handler
Handles incoming messages, triggers, cooldowns, and dispatches to TARSBrain
"""

import time
import random
import logging

from telebot import TeleBot, types

from core.brain import brain
from core.memory import memory

from utils.photo import extract_photo_url
from utils.identity import extract_telegram_identity
from utils.triggers import is_calling_tars, is_reply_to_bot
from config.settings import ADMIN_IDS

# Global cooldown dictionary imported from cooldown module
from core.cooldown import cooldowns


def handle_message(bot: TeleBot, message: types.Message, allowed_chat_ids: set):
    """
    Main handler for incoming Telegram messages.
    """

    chat_id = message.chat.id
    user_id = message.from_user.id

    # --- Extract text ---
    text_content = message.text or message.caption or ""

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

    # Periodic cleanup of memory (5% chance per message)
    if random.random() < 0.05:
        memory.cleanup()

    # --- Extract text and photo ---
    photo_url, caption = extract_photo_url(bot, message)
    identity = extract_telegram_identity(message)

    # Ignore message if it doesn't call TARS and is not a reply
    if message.chat.type != "private" and not (has_trigger or is_reply):
        return

    # --- Cooldown check ---
    if not cooldowns.allowed(user_id):
        bot.reply_to(message, "Вы задаете слишком много вопросов. Пожалуйста, подождите немного перед следующим сообщением.")
        return

    # --- Logging ---
    used_ctx, total_mem = memory.get_stats(chat_id)
    logging.info(
        f"Processing | chat={chat_id} user={user_id} type={'IMG' if photo_url else 'TXT'} mem={used_ctx}/{total_mem}"
    )

    # --- Simulate typing ---
    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.5, 1.2))  # simulate thinking delay

    # --- Generate reply ---
    if photo_url and (has_trigger or is_reply):
        reply = brain.analyze_image(photo_url, caption)
    else:
        reply = brain.think(
            chat_id=chat_id,
            user_id=user_id,
            user_message=text_content[:1500],  # MAX_INPUT_CHARS
            identity=identity
        )

    # --- Send reply ---
    try:
        bot.reply_to(message, reply)
    except Exception as e:
        logging.error(f"Telegram API Error: {e}")
