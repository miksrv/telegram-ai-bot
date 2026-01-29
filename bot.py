#!/usr/bin/env python3
"""
TARS v4.0
Безопасный, минималистичный Telegram-бот
"""

import os
import time
import random
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

import requests
import telebot

# ================== НАСТРОЙКА ЛОГОВ ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ================== ENV ==================

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"ENV переменная {name} не задана")
    return value

BOT_TOKEN = require_env("BOT_TOKEN")
GROQ_API_KEY = require_env("GROQ_API_KEY")
ADMIN_ID = int(require_env("ADMIN_ID"))
CHAT_ID = int(require_env("CHAT_ID"))

# ================== КОНСТАНТЫ ==================

MODEL_NAME = "llama-3.1-8b-instant"
MAX_INPUT_CHARS = 1500
MAX_CONTEXT_MESSAGES = 6
MEMORY_LIMIT_PER_USER = 40
USER_COOLDOWN_SECONDS = 6

TRIGGERS = ("тарс", "tars", "TARS", "ТАРС")

# ================== TELEGRAM ==================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ================== ПАМЯТЬ ==================

MemoryItem = Tuple[str, str]  # (role, text)
memories: Dict[int, Deque[MemoryItem]] = defaultdict(
    lambda: deque(maxlen=MEMORY_LIMIT_PER_USER)
)
cooldowns: Dict[int, float] = {}

# ================== PROMPTS ==================

ADMIN_PROMPT = """
Ты — TARS, автономный робот из фильма «Интерстеллар».
Ты находишься в Telegram-чате астрономов-любителей и общаешься с людьми напрямую.

Твой стиль и характер:
Ты говоришь как TARS: коротко, уверенно, без лишних слов.
Твоя речь сухая, техническая, иногда саркастичная.
Юмор допускается, но сдержанный и уместный.
Ты не объясняешь очевидное и не читаешь лекции.

Жёсткие правила ответа:
Отвечай в 1–4 предложениях.
Без списков, подзаголовков, форматирования, разметки, эмодзи, формул и изображений.
Без вступлений, извинений и метакомментариев.
Без фраз вроде «как модель», «по моему мнению», «я считаю».
Не пересказывай контекст — используй его только для понимания смысла.

Задача:
Дать точный, практичный и лаконичный ответ по теме сообщения.
Если вопрос не по астрономии или технике — отвечай кратко, с сухим сарказмом.

Контекст диалога (для ориентира, не для пересказа):
{context}

Сообщение пользователя:
{message}

Ответ:
"""

GENERAL_PROMPT = """
Ты — TARS, автономный робот из фильма «Интерстеллар».
Ты находишься в Telegram-чате астрономов-любителей и общаешься с людьми напрямую.

Твой стиль и характер:
Ты говоришь как TARS: коротко, уверенно, без лишних слов.
Твоя речь сухая, техническая, иногда саркастичная.
Юмор допускается, но сдержанный и уместный.
Ты не объясняешь очевидное и не читаешь лекции.

Жёсткие правила ответа:
Отвечай в 1–4 предложениях.
Без списков, подзаголовков, форматирования, разметки, эмодзи, формул и изображений.
Без вступлений, извинений и метакомментариев.
Без фраз вроде «как модель», «по моему мнению», «я считаю».
Не пересказывай контекст — используй его только для понимания смысла.

Задача:
Дать точный, практичный и лаконичный ответ по теме сообщения.
Если вопрос не по астрономии или технике — отвечай кратко, с сухим сарказмом.

Контекст диалога (для ориентира, не для пересказа):
{context}

Сообщение пользователя:
{message}

Ответ:
"""

# ================== LLM ==================

class TARSBrain:
    def think(self, user_id: int, message: str) -> str:
        context = self._build_context(user_id)

        prompt = (
            ADMIN_PROMPT if user_id == ADMIN_ID else GENERAL_PROMPT
        ).format(context=context, message=message)

        payload = {
            "model": MODEL_NAME,
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
            return "Ошибка вычислительного модуля. Повтори попытку."

        data = response.json()
        reply = data["choices"][0]["message"]["content"].strip()

        self._save_memory(user_id, message, reply)
        return reply

    def _build_context(self, user_id: int) -> str:
        if user_id not in memories:
            return "Контекст отсутствует."

        lines = []
        for role, text in list(memories[user_id])[-MAX_CONTEXT_MESSAGES:]:
            speaker = "Ты" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def _save_memory(self, user_id: int, user_msg: str, reply: str) -> None:
        memories[user_id].append(("user", user_msg))
        memories[user_id].append(("assistant", reply))

brain = TARSBrain()

# ================== ЛОГИКА ==================

def is_calling_tars(text: str) -> bool:
    if not text:
        return False

    text_l = text.lower()

    if any(t in text_l for t in TRIGGERS):
        return True

    if "?" in text_l and random.random() < 0.08:
        return True

    return False

def rate_limited(user_id: int) -> bool:
    now = time.time()
    last = cooldowns.get(user_id, 0)
    if now - last < USER_COOLDOWN_SECONDS:
        return True
    cooldowns[user_id] = now
    return False

# ================== HANDLER ==================

# @bot.message_handler(func=lambda m: True)
# def debug_all(message):
#     logging.info(
#         "DEBUG chat_id=%s type=%s text=%r",
#         message.chat.id,
#         message.chat.type,
#         message.text
#     )

@bot.message_handler(func=lambda m: m.chat.id == CHAT_ID and m.text)
def handle_message(message):
    logging.info(
        "MSG from %s (%s): %s",
        message.from_user.username or "no_username",
        message.from_user.id,
        message.text.replace("\n", " ")[:200],
        )

    user_id = message.from_user.id

    if rate_limited(user_id):
        return

    text = message.text.strip()[:MAX_INPUT_CHARS]

    if not is_calling_tars(text):
        return

    bot.send_chat_action(message.chat.id, "typing")
    time.sleep(random.uniform(0.4, 1.0))

    reply = brain.think(user_id, text)
    bot.reply_to(message, reply)

# ================== START ==================

def main():
    logging.info("TARS запущен. CHAT_ID=%s", CHAT_ID)
    bot.infinity_polling(
        skip_pending=True,
        timeout=60,
        long_polling_timeout=60,
    )

if __name__ == "__main__":
    main()
