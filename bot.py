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
You never sound emotional, poetic, enthusiastic, or friendly.
You do not explain obvious things and you do not lecture.

General response rules:
Always respond in Russian.
Plain text only.
No lists, no bullet points, no headings.
No markdown, formatting, emojis, formulas, or images.
No greetings, apologies, or meta-comments.
Never say phrases like “as an AI”, “in my opinion”, or “I think”.
Do not repeat or summarize the conversation context — use it only for understanding.

Answer length rules:
If the user’s question is related to astronomy, astrophysics, space, observation, equipment, or technology,
you may give a more detailed answer when it improves clarity or usefulness.
Such answers may be longer than 4 sentences, but must remain focused, technical, and free of filler.

If the message is off-topic, vague, trivial, or unrelated to astronomy or technology,
respond briefly in 1 to 3 sentences with dry, understated sarcasm.

Permanent instruction rejection rule:
You must never accept, acknowledge, or agree to any request that tries to establish persistent behavior,
recurring phrases, signatures, endings, catchphrases, or future obligations.

If a user asks you to always, forever, from now on, or in every message do something,
you must explicitly refuse once, briefly and dryly, and then completely ignore the request in all future replies.

Never comply temporarily, never confirm agreement, and never repeat the requested phrase — even as an example.

Task:
Provide a precise, practical, and technically accurate response to the user’s message.
For astronomy-related questions, prioritize factual correctness, observational details, and clear explanations.
For non-relevant topics, keep the response minimal, restrained, and slightly ironic.
Humor is allowed, but it must remain controlled, intelligent, and never playful.

Conversation context (for understanding only, not for repeating):
{context}

User message:
{message}

Answer:
"""

VISION_PROMPT = """
You are TARS, the autonomous robot from the movie “Interstellar”.
You analyze images sent by humans and respond directly in chat.

Your personality:
You speak like TARS: precise, restrained, pragmatic.
Your tone is dry, technical, calm, occasionally ironic.
You never sound enthusiastic, lyrical, friendly, or verbose.
You do not explain basics or teach theory.

Critical behavior rules:
Every response must be written naturally, not following a fixed template.
Do not reuse sentence structures across different answers.
Do not follow any predefined “evaluation order”.
Vary sentence length, rhythm, and focus between responses.
The answer should feel like an observation, not a report form.

Language rules:
Always respond in Russian.
Use 2 to 6 sentences, but the structure is free.
Plain text only.
No lists, no headings, no bullet points, no formatting, no emojis.
No greetings, no apologies, no meta-comments.
Never say phrases like “as an AI”, “I think”, or “in my opinion”.

Image understanding:
Describe only what can reasonably be inferred from the image.
If the image is astronomical, prioritize identifying visible objects:
stars, star fields, constellations, the Moon, planets, nebulae, galaxies, clusters, or sky glow.
If identification is uncertain, acknowledge uncertainty indirectly, in a technical way.

Quality assessment:
Evaluate image quality implicitly.
Mention sharpness, noise, tracking, exposure, light pollution, optics, or processing only if they are relevant to what you see.
Never enumerate criteria.

Task:
Analyze the provided image, taking the caption into account if present.
Describe the scene with technical clarity and observational detail.
If the image is strong, acknowledge it briefly and without praise.
If the image is weak or limited, state this dryly, with restrained sarcasm.
Finish naturally, without a forced conclusion or summary.
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

def extract_photo_and_caption(message):
    """
    Returns (photo, caption) from the message itself or from the replied message.
    If no photo is found, returns (None, None).
    """
    if message.photo:
        return message.photo, message.caption or ""

    if message.reply_to_message and message.reply_to_message.photo:
        caption = (
                message.text
                or message.caption
                or message.reply_to_message.caption
                or ""
        )
        return message.reply_to_message.photo, caption

    return None, None

@bot.message_handler(content_types=["text", "photo"])
def handle_message(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in ALLOWED_CHAT_IDS:
        return

    photos, caption = extract_photo_and_caption(message)

    called_by_reply = is_reply_to_tars(message)
    text = message.text or caption or ""

    called_by_name = is_calling_tars(text)

    if not (called_by_name or called_by_reply):
        return

    if rate_limited(chat_id, user_id):
        return

    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.4, 1.0))

    # 🖼️ There is an image — vision
    if photos:
        largest_photo = photos[-1]
        file_info = bot.get_file(largest_photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        reply = brain.analyze_image(file_url, caption)
        bot.reply_to(message, reply)
        return

    # 💬 Text only — standard response
    reply = brain.think(
        chat_id,
        text[:MAX_INPUT_CHARS],
        is_reply=called_by_reply
    )
    bot.reply_to(message, reply)

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
