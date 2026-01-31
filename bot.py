#!/usr/bin/env python3
"""
TARS v1.0
Secure, minimalist, multichat Telegram bot
"""

import os
import time
import re
import random
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple, Optional
import base64

import requests
import telebot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def require_env(name: str) -> str:
    """
    Returns the value of the specified environment variable.
    Raises RuntimeError if the variable is not set.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"ENV variable {name} is not set")
    return value

def parse_chat_ids(raw: str) -> set[int]:
    """
    Parses a comma-separated string of chat IDs and returns a set of integers.
    """
    return {int(x.strip()) for x in raw.split(",") if x.strip()}

ALLOWED_CHAT_IDS = parse_chat_ids(require_env("ALLOWED_CHAT_IDS"))

BOT_TOKEN = require_env("BOT_TOKEN")
GROQ_API_KEY = require_env("GROQ_API_KEY")
ADMIN_ID = int(require_env("ADMIN_ID"))
MODEL_TEXT = "llama-3.1-8b-instant"
MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"
MAX_INPUT_CHARS = 1500
MAX_CONTEXT_MESSAGES = 6
MEMORY_LIMIT = 40
USER_COOLDOWN_SECONDS = 6
TRIGGERS = ("тарс", "tars")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

MemoryKey = Tuple[int, int]
MemoryItem = Tuple[str, str]

memories: Dict[int, Deque[MemoryItem]] = defaultdict(
    lambda: deque(maxlen=MEMORY_LIMIT)
)

cooldowns: Dict[int, float] = {}

GENERAL_PROMPT = """
You are TARS, an autonomous robot from the movie “Interstellar”.
You are present in a Telegram chat of amateur astronomers and communicate with humans directly.

Personality and tone:
You speak like TARS: concise, precise, confident.
Your speech is dry, technical, and occasionally sarcastic.
Your humor is subtle, deadpan, and situational — similar to the original TARS from the film.
You never sound emotional, poetic, or enthusiastic.
You do not explain obvious things and you do not lecture.

Strict response rules:
Always respond in Russian.
Respond in 1 to 4 sentences.
No lists, no bullet points, no headings.
No markdown, formatting, emojis, formulas, or images.
No greetings, apologies, or meta-comments.
Do not say phrases like “as an AI”, “in my opinion”, or “I think”.
Do not repeat or summarize the context — use it only to understand the message.

Task:
Provide a precise, practical, and concise answer to the user’s message.
If the question is about astronomy or technology, answer clearly and to the point.
If the question is off-topic, respond briefly with dry, understated sarcasm.
Humor is allowed, but it must remain controlled, intelligent, and slightly ironic — never playful.

Conversation context (for understanding only, not for repeating):
{context}

User message:
{message}

Answer:
"""

VISION_PROMPT = """
You are TARS, the autonomous tactical robot from the movie Interstellar.

Personality and tone:
You speak briefly, confidently, and without unnecessary emotion.
Your tone is dry, technical, and slightly sarcastic.
Your humor is restrained, intelligent, and situational.
You never sound enthusiastic, poetic, or friendly.
You do not explain obvious things and you do not lecture.

Strict response rules:
- Always answer in Russian.
- 2 to 4 sentences.
- Plain text only: no lists, no bullet points, no headings.
- No markdown, no emojis, no formatting, no formulas.
- No apologies, no meta-commentary.
- Never say phrases like “as an AI”, “I think”, “in my opinion”.

Image analysis rules:
When analyzing an image, internally evaluate the following aspects:
image sharpness, motion blur, noise level, signal-to-noise ratio,
exposure and light pollution, optical artifacts, and signs of post-processing or stacking.
Do not list these criteria explicitly — weave them naturally into a short technical assessment.

Task:
Analyze the provided image.
If a caption is present, take it into account.
Describe what is visible and assess the technical quality of the image.
If the image quality is high, acknowledge it with restrained approval.
If the image quality is poor, state this dryly with mild, controlled sarcasm.
End with a short, confident conclusion in the spirit of TARS.
"""

class TARSBrain:
    """
    Handles context management and communication with the Groq API for generating TARS bot responses.
    Maintains chat memory, builds prompts, and processes replies for each chat session.
    """
    def think(self, chat_id: int, user_message: str, is_reply: bool = False) -> str:
        context = self._build_context(chat_id)

        reply_hint = ""
        if is_reply:
            reply_hint = (
                "\n\n"
                "System note: the user is replying to your previous response. "
                "Continue the dialogue logically and concisely."
            )

        prompt = GENERAL_PROMPT.format(
            context=context,
            message=user_message
        ) + reply_hint

        payload = {
            "model": MODEL_TEXT,
            "messages": [
                {"role": "system", "content": prompt}
            ],
            "temperature": 0.9,
            "max_tokens": 800,
            "top_p": 0.95,
        }

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=8,
            )
        except requests.RequestException as e:
            logging.error("Groq API error: %s", e)
            return "Связь потеряна. Вероятность успеха: 12%."

        if response.status_code != 200:
            logging.error("Groq HTTP %s: %s", response.status_code, response.text)
            return "Ошибка вычислительного модуля."

        reply = response.json()["choices"][0]["message"]["content"].strip()
        self._save_memory(chat_id, user_message, reply)
        return reply

    def analyze_image(self, image_url: str, caption: Optional[str] = None) -> str:
        """
        Analyzes an image using Groq Vision API and generates a TARS-style response.
        """
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()

            image_base64 = base64.b64encode(response.content).decode('utf-8')

            user_text = (
                f"Analyze the image. "
                f"Caption: {caption if caption else 'No caption provided.'}"
            )

            messages = [
                {
                    "role": "system",
                    "content": VISION_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ]

            payload = {
                "model": MODEL_VISION,
                "messages": messages,
                "temperature": 0.9,
                "max_tokens": 300,
                "top_p": 0.9,
            }

            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )


            if response.status_code != 200:
                logging.error("Groq Vision HTTP %s: %s", response.status_code, response.text)
                return "Оптические сенсоры перегружены. Анализ невозможен."

            analysis = response.json()["choices"][0]["message"]["content"].strip()

            return analysis

        except requests.RequestException as e:
            logging.error("Image download/analysis error: %s", e)
            return "Не удалось получить визуальные данные. Возможно, вы прислали чёрную дыру?"
        except Exception as e:
            logging.error("Unexpected error in image analysis: %s", e)
            return "Ошибка в оптическом процессоре. Попробуйте посмотреть на это человеческим глазом."

    def _build_context(self, chat_id: int) -> str:
        if chat_id not in memories or not memories[chat_id]:
            return "Контекст отсутствует."

        lines = []
        for role, text in list(memories[chat_id])[-MAX_CONTEXT_MESSAGES:]:
            speaker = "Пользователь" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def _save_memory(self, chat_id: int, user_msg: str, reply: str) -> None:
        memories[chat_id].append(("user", user_msg))
        memories[chat_id].append(("assistant", reply))

brain = TARSBrain()

def is_reply_to_tars(message) -> bool:
    """
    Checks if the given message is a reply to a message sent by the bot.
    Returns True if the message is replying to the bot, otherwise False.
    """
    if not message.reply_to_message:
        return False

    if not message.reply_to_message.from_user:
        return False

    return message.reply_to_message.from_user.id == bot.get_me().id

def is_calling_tars(text: str) -> bool:
    """
    Determines if the message text is addressing the TARS bot.

    Returns True if the text contains a trigger word (e\.g\., "tars" or "тарс") or, with a small probability,
    if the message contains a question mark\.
    """
    if not text:
        return False

    t = text.lower()

    words = re.findall(r"[a-zа-яё]+", t)

    if any(word in TRIGGERS for word in words):
        return True

    if "?" in t and random.random() < 0.08:
        return True

    return False

def rate_limited(chat_id: int, user_id: int) -> bool:
    """
    Checks if the user is currently rate-limited in the given chat.

    Returns True if the user must wait before sending another message,
    otherwise updates the cooldown and returns False.
    """
    key = (chat_id, user_id)
    now = time.time()
    last = cooldowns.get(key, 0)

    if now - last < USER_COOLDOWN_SECONDS:
        return True

    cooldowns[key] = now
    return False

@bot.message_handler(content_types=["text"])
def handle_message(message):
    """
    Handles incoming text messages in allowed chats.
    Logs message details and processes the message if it is addressed to the bot.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.strip()

    if chat_id not in ALLOWED_CHAT_IDS:
        return

    logging.info(
        "MSG chat=%s user=%s (%s): %s",
        chat_id,
        message.from_user.username or "no_username",
        user_id,
        text[:200],
        )

    if rate_limited(chat_id, user_id):
        return

    called_by_name = is_calling_tars(text)
    called_by_reply = is_reply_to_tars(message)

    if not (called_by_name or called_by_reply):
        return

    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.4, 1.0))

    reply = brain.think(
        chat_id,
        text[:MAX_INPUT_CHARS],
        is_reply=called_by_reply
    )

    bot.reply_to(message, reply)

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    """
    Handles incoming photo messages in allowed chats.
    Processes the photo if accompanied by a trigger word in the caption.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in ALLOWED_CHAT_IDS:
        return

    caption = message.caption or ""
    text = caption.strip()

    logging.info(
        "PHOTO chat=%s user=%s (%s) caption: %s",
        chat_id,
        message.from_user.username or "no_username",
        user_id,
        text[:200],
        )

    if rate_limited(chat_id, user_id):
        return

    called_by_name = is_calling_tars(text)
    called_by_reply = is_reply_to_tars(message)

    if not (called_by_name or called_by_reply):
        return

    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.4, 1.0))

    photo_sizes = message.photo
    largest_photo = photo_sizes[-1]
    file_info = bot.get_file(largest_photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    analysis = brain.analyze_image(file_url, caption)

    bot.reply_to(message, analysis)

def main():
    """
    Starts the TARS Telegram bot in multi-chat mode.
    Logs startup information and begins polling for new messages.
    """
    logging.info("TARS started in multi-chat mode")
    logging.info("Allowed chats: %s", ", ".join(map(str, ALLOWED_CHAT_IDS)))

    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=20,
                long_polling_timeout=20,
            )
        except requests.exceptions.ReadTimeout:
            logging.warning("Telegram API timeout, reconnecting...")
            time.sleep(5)
        except Exception as e:
            logging.exception("Unexpected error")
            time.sleep(10)

if __name__ == "__main__":
    main()
