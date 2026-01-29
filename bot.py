#!/usr/bin/env python3
"""
TARS v4.1
Безопасный, минималистичный, мультичат Telegram-бот
"""

import os
import time
import random
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

import requests
import telebot

# ================== ЛОГИ ==================

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

def parse_chat_ids(raw: str) -> set[int]:
    return {int(x.strip()) for x in raw.split(",") if x.strip()}

ALLOWED_CHAT_IDS = parse_chat_ids(require_env("ALLOWED_CHAT_IDS"))

BOT_TOKEN = require_env("BOT_TOKEN")
GROQ_API_KEY = require_env("GROQ_API_KEY")
ADMIN_ID = int(require_env("ADMIN_ID"))

# ================== КОНСТАНТЫ ==================

MODEL_NAME = "llama-3.1-8b-instant"
MAX_INPUT_CHARS = 1500
MAX_CONTEXT_MESSAGES = 6
MEMORY_LIMIT = 40
USER_COOLDOWN_SECONDS = 6

TRIGGERS = ("тарс", "tars")

# ================== TELEGRAM ==================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ================== ПАМЯТЬ ==================

MemoryKey = Tuple[int, int]
MemoryItem = Tuple[str, str]

memories: Dict[int, Deque[MemoryItem]] = defaultdict(
    lambda: deque(maxlen=MEMORY_LIMIT)
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

GENERAL_PROMPT = ADMIN_PROMPT

# ================== LLM ==================

class TARSBrain:
    def think(self, chat_id: int, user_message: str) -> str:
        context = self._build_context(chat_id)

        prompt = GENERAL_PROMPT.format(
            context=context,
            message=user_message
        )

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
            return "Ошибка вычислительного модуля."

        reply = response.json()["choices"][0]["message"]["content"].strip()
        self._save_memory(chat_id, user_message, reply)
        return reply

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

# ================== ЛОГИКА ==================

def is_calling_tars(text: str) -> bool:
    if not text:
        return False

    t = text.lower()
    if any(trigger in t for trigger in TRIGGERS):
        return True

    if "?" in t and random.random() < 0.08:
        return True

    return False

def rate_limited(chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    now = time.time()
    last = cooldowns.get(key, 0)

    if now - last < USER_COOLDOWN_SECONDS:
        return True

    cooldowns[key] = now
    return False

# ================== HANDLER ==================

@bot.message_handler(content_types=["text"])
def handle_message(message):
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

    if not is_calling_tars(text):
        return

    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.4, 1.0))

    reply = brain.think(chat_id, text[:MAX_INPUT_CHARS])
    bot.reply_to(message, reply)

# ================== START ==================

def main():
    logging.info("TARS запущен в мультичат-режиме")
    logging.info("Разрешённые чаты: %s", ", ".join(map(str, ALLOWED_CHAT_IDS)))
    bot.infinity_polling(
        skip_pending=True,
        timeout=60,
        long_polling_timeout=60,
    )

if __name__ == "__main__":
    main()
