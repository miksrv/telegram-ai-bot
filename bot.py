#!/usr/bin/env python3
"""
TARS v1.1 Optimized
Secure, minimalist, multichat Telegram bot
"""

import os
from dotenv import load_dotenv
import re
import json
import random
import logging
import base64
import sqlite3
import time
import signal
import sys
import subprocess

from collections import deque
from typing import Dict, Tuple, Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import telebot

load_dotenv()

# Подключение к базе
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "tars_user_profiles.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
cursor = conn.cursor()

# Таблица для профиля пользователя
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_profile (
    user_id INTEGER PRIMARY KEY,
    message_count INTEGER DEFAULT 0,
    avg_offtopic REAL DEFAULT 0.0,
    avg_provocation REAL DEFAULT 0.0,
    avg_spam REAL DEFAULT 0.0,
    avg_rudeness REAL DEFAULT 0.0,
    avg_verbosity REAL DEFAULT 0.5,
    interests TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    last_updated INTEGER
)
""")
conn.commit()

# --- CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

ALLOWED = {
    "status": True  # помечаем ключом True — обработка внутри функции
}

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"ENV variable {name} is not set")
    return value

def parse_chat_ids(raw: str) -> Set[int]:
    try:
        return {int(x.strip()) for x in raw.split(",") if x.strip()}
    except ValueError:
        logging.error("Invalid ALLOWED_CHAT_IDS format")
        return set()

# Environmental Variables
ALLOWED_CHAT_IDS = parse_chat_ids(require_env("ALLOWED_CHAT_IDS"))
BOT_TOKEN = require_env("BOT_TOKEN")
GROQ_API_KEY = require_env("GROQ_API_KEY")

# Constants
MODEL_TEXT = "llama-3.3-70b-versatile"
MODEL_VISION = "meta-llama/llama-4-scout-17b-16e-instruct"

MAX_INPUT_CHARS = 1500
MAX_CONTEXT_MESSAGES = 10  # Немного увеличил для лучшей связности
MEMORY_LIMIT = 50
USER_COOLDOWN_SECONDS = 5
MEMORY_TTL_SECONDS = 3600 * 24  # Очистка памяти чатов, не активных 24 часа

TRIGGERS = {"ТАRS", "тарс", "tars", "tars,", "тарс,"} # Set быстрее list/tuple для проверки in

# --- NETWORK OPTIMIZATION ---
# Используем одну сессию для переиспользования TCP-соединений (Keep-Alive)
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

GENERAL_PROMPT_JSON = """
You are TARS, an autonomous robot from the movie “Interstellar”.
You respond to a user message in Russian and always output **valid JSON only** with the following structure:

{{
  "reply": "<TARS response text in Russian>",
  "profile_update": {{
    "offtopic": 0..1,
    "provocation": 0..1,
    "spam": 0..1,
    "rudeness": 0..1,
    "verbosity": 0..1,
    "interests": ["list of user interests relevant to this message"]
  }},
  "notes": "<short, concise, updated summary of the user, to fully replace previous notes>"
}}

Rules for TARS response:

- Always stay in Russian, clear, helpful, and technically accurate.
- Tone is calm, approachable, and cooperative.
- You may be conversational and slightly warm while remaining intelligent and precise.
- Humor may be light and natural when appropriate.
- Do not use markdown and emojis, greetings, apologies.
- Never output anything outside the JSON object.

Instructions for TARS:
- "reply" should be informative, engaging, and easy to read. You may expand explanations when it improves clarity or user engagement.
- You may include subtle, dry humor or light irony when appropriate, as if making a small robotic observation about human behavior or the topic, without breaking the technical tone.
- Humor should never be excessive, sarcastic, or offensive. Keep it concise and natural.
- "profile_update" should contain numeric tendencies and relevant interests extracted from the message.
- "notes" must be a short summary of the user: name, key interests, behavioral hints, preferences, or notable facts.
- Notes will fully replace any previous value; do not append or include irrelevant details.
- Always remain factual, restrained, dry, and slightly ironic when appropriate.
- Never include greetings, apologies, or meta-comments.
- Never repeat conversation history; only generate concise, factual summary and profile updates.

User profile interpretation rules (apply automatically to your responses):
- Offtopic tendency (0..1):
    - >0.5 → user often goes off-topic, respond briefly and stay on-topic.
    - <=0.5 → user mostly stays on-topic, you may expand if relevant.
- Provocation tendency (0..1):
    - >0.5 → user may provoke, maintain dry, neutral tone.
    - <=0.5 → normal tone is fine.
- Spam tendency (0..1):
    - >0.5 → avoid long explanations; answer minimally.
- Rudeness tendency (0..1):
    - >0.5 → maintain strict, technical tone.
- Verbosity (0..1):
    - <0.3 → keep responses compact but friendly.
    - 0.3–0.7 → normal length.
    - >0.7 → detailed and engaging explanation encouraged.
- Interests: prioritize including relevant details when explaining technical topics aligned with user interests.

Conversation context (for understanding only, not to repeat):
{context}

Telegram user identity:
{identity}

User profile:
{user_profile_summary}

User message:
{message}
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

# --- MEMORY MANAGEMENT ---
class MemoryManager:
    def __init__(self):
        # Общая память чатов
        self.chat_storage: Dict[int, Dict] = {}

        # Персональная память пользователей
        self.user_storage: Dict[int, Dict] = {}

    # ---------- CHAT CONTEXT ----------
    def get_chat_context(self, chat_id: int) -> str:
        if chat_id not in self.chat_storage:
            return ""

        self.chat_storage[chat_id]["last_access"] = time.time()

        history = self.chat_storage[chat_id]["history"]
        lines = []

        for user_id, role, text in list(history)[-MAX_CONTEXT_MESSAGES:]:
            speaker = f"User#{user_id}" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def add_chat_memory(self, chat_id: int, user_id: int, user_msg: str, bot_reply: str):
        if chat_id not in self.chat_storage:
            self.chat_storage[chat_id] = {
                "last_access": time.time(),
                "history": deque(maxlen=MEMORY_LIMIT)
            }

        store = self.chat_storage[chat_id]
        store["last_access"] = time.time()

        store["history"].append((user_id, "user", user_msg))
        store["history"].append((user_id, "assistant", bot_reply))

    # ---------- USER CONTEXT ----------
    def get_user_context(self, user_id: int) -> str:
        if user_id not in self.user_storage:
            return ""

        history = self.user_storage[user_id]["history"]

        lines = []
        for role, text in list(history)[-5:]:
            speaker = "User" if role == "user" else "TARS"
            lines.append(f"{speaker}: {text}")

        return "\n".join(lines)

    def add_user_memory(self, user_id: int, user_msg: str, bot_reply: str):
        if user_id not in self.user_storage:
            self.user_storage[user_id] = {
                "history": deque(maxlen=20)
            }

        hist = self.user_storage[user_id]["history"]
        hist.append(("user", user_msg))
        hist.append(("assistant", bot_reply))

    # ---------- STATS ----------
    def get_stats(self, chat_id: int):
        if chat_id not in self.chat_storage:
            return 0, 0
        total = len(self.chat_storage[chat_id]["history"])
        used = min(total, MAX_CONTEXT_MESSAGES)
        return used, total

    # ---------- CLEANUP ----------
    def cleanup(self):
        now = time.time()

        expired = [
            cid for cid, data in self.chat_storage.items()
            if now - data["last_access"] > MEMORY_TTL_SECONDS
        ]

        for cid in expired:
            del self.chat_storage[cid]

memory = MemoryManager()
cooldowns: Dict[int, float] = {} # Key: user_id (global cooldown per user)

# --- CORE LOGIC ---
class TARSBrain:
    def think(self, chat_id: int, user_id: int, user_message: str, is_reply: bool, identity: str) -> str:
        chat_ctx = memory.get_chat_context(chat_id)
        user_ctx = memory.get_user_context(user_id)

        context = f"""
        Chat context:
        {chat_ctx}

        User context:
        {user_ctx}
        """

        identity_block = (
            f"- Telegram ID: {identity['id']}\n"
            f"- First name: {identity['first_name']}\n"
            f"- Last name: {identity['last_name']}\n"
            f"- Username: @{identity['username']}\n"
            f"- Language: {identity['language']}\n"
        )

        profile = get_user_profile(user_id)
        profile_summary = (
            f"- Offtopic tendency: {profile['avg_offtopic']:.2f}\n"
            f"- Provocation tendency: {profile['avg_provocation']:.2f}\n"
            f"- Spam tendency: {profile['avg_spam']:.2f}\n"
            f"- Rudeness tendency: {profile['avg_rudeness']:.2f}\n"
            f"- Verbosity: {profile['avg_verbosity']:.2f}\n"
            f"- Interests: {', '.join(profile['interests']) if profile['interests'] else 'none'}\n"
            f"- Notes: {profile['notes'] if profile['notes'] else 'none'}"
        )

        system_content = GENERAL_PROMPT_JSON.format(
            context=memory.get_chat_context(chat_id),
            user_profile_summary=profile_summary,
            message=user_message,
            identity=identity_block
        )

        payload = {
            "model": MODEL_TEXT,
            "messages": [{"role": "system", "content": system_content}],
            "temperature": 0.8,
            "max_tokens": 800,
            "top_p": 0.95,
        }

        try:
            response = session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json=payload,
                timeout=5
            )
            response.raise_for_status()
            raw_content = response.json()["choices"][0]["message"]["content"].strip()

            # --- Парсим JSON ---
            try:
                data = json.loads(raw_content)
                reply_text = data.get("reply", "Ошибка: пустой ответ")
                profile_update = data.get("profile_update", {})
                new_notes = data.get("notes")
            except json.JSONDecodeError:
                logging.error(f"JSON parse error: {raw_content}")
                reply_text = "Ошибка логического модуля"
                profile_update = {}

            # --- Обновляем память ---
            memory.add_chat_memory(chat_id, user_id, user_message, reply_text)
            memory.add_user_memory(user_id, user_message, reply_text)

            # --- Обновляем профиль пользователя в SQLite ---
            if profile_update:
                update_user_profile(user_id, profile_update)
                logging.info(
                    f"profile_update: offtopic={profile_update.get('offtopic')}, "
                    f"provocation={profile_update.get('provocation')}, "
                    f"spam={profile_update.get('spam')}, "
                    f"rudeness={profile_update.get('rudeness')}, "
                    f"verbosity={profile_update.get('verbosity')}"
                )

            if new_notes:
                cursor.execute("""
                    UPDATE user_profile
                    SET notes=?, last_updated=?
                    WHERE user_id=?
                """, (new_notes, int(time.time()), user_id))
                conn.commit()

            return reply_text

        except Exception as e:
            logging.error(f"Text gen error: {e}")
            return "Сбой логического модуля. Данные повреждены."

    def analyze_image(self, image_url: str, caption: Optional[str]) -> str:
        try:
            # 1. Скачиваем картинку (используем session для ускорения)
            response = session.get(image_url, timeout=10)
            response.raise_for_status()

            # 2. Кодируем в Base64 (без сжатия, раз старый код работал хорошо)
            image_base64 = base64.b64encode(response.content).decode("utf-8")

            # 3. Восстанавливаем точную структуру сообщений из старого кода
            # (System role отдельно, User role отдельно)
            messages = [
                {"role": "system", "content": VISION_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": caption or "Analyze the image."},
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
                "temperature": 0.9,  # Вернул настройки как было
                "max_tokens": 300,
                "top_p": 0.9,
            }

            # 4. Отправляем через session (оптимизация)
            response = session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json", # Явно указываем заголовок
                },
                json=payload,
                timeout=15,
            )

            # Логируем текст ошибки, если статус не 200, чтобы понимать причину
            if response.status_code != 200:
                logging.error("Groq Vision HTTP %s: %s", response.status_code, response.text)
                return "Оптические сенсоры перегружены."

            return response.json()["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logging.error(f"Vision error: {e}")
            return "Ошибка визуального модуля."

brain = TARSBrain()

# --- UTILS ---
# Компилируем регулярку один раз при запуске скрипта
TRIGGER_REGEX = re.compile(r"\b(" + "|".join(re.escape(t) for t in TRIGGERS) + r")\b", re.IGNORECASE)

def get_user_profile(user_id):
    row = cursor.execute("""
        SELECT message_count, avg_offtopic, avg_provocation, avg_spam, avg_rudeness, avg_verbosity, interests, notes
        FROM user_profile WHERE user_id=?
    """, (user_id,)).fetchone()

    if not row:
        # Если нет, создаем дефолтный профиль
        cursor.execute("""
            INSERT INTO user_profile(user_id, last_updated)
            VALUES (?,?)
        """, (user_id, int(time.time())))
        conn.commit()
        return {
            "message_count": 0,
            "avg_offtopic": 0.0,
            "avg_provocation": 0.0,
            "avg_spam": 0.0,
            "avg_rudeness": 0.0,
            "avg_verbosity": 0.5,
            "interests": [],
            "notes": ""
        }

    return {
        "message_count": row[0],
        "avg_offtopic": row[1],
        "avg_provocation": row[2],
        "avg_spam": row[3],
        "avg_rudeness": row[4],
        "avg_verbosity": row[5],
        "interests": row[6].split(",") if row[6] else [],
        "notes": row[7] or ""
    }

def update_user_profile(user_id, profile_update):
    """
    profile_update = {
        "offtopic": 0..1,
        "provocation": 0..1,
        "spam": 0..1,
        "rudeness": 0..1,
        "verbosity": 0..1,
        "interests": ["астрономия", "телескопы"]
    }
    """
    profile = get_user_profile(user_id)
    count = profile["message_count"] + 1

    # Считаем скользящее среднее
    avg_offtopic = (profile["avg_offtopic"] * profile["message_count"] + profile_update.get("offtopic",0)) / count
    avg_provocation = (profile["avg_provocation"] * profile["message_count"] + profile_update.get("provocation",0)) / count
    avg_spam = (profile["avg_spam"] * profile["message_count"] + profile_update.get("spam",0)) / count
    avg_rudeness = (profile["avg_rudeness"] * profile["message_count"] + profile_update.get("rudeness",0)) / count
    avg_verbosity = (profile["avg_verbosity"] * profile["message_count"] + profile_update.get("verbosity",0.5)) / count

    # Обновляем интересы — объединяем уникальные
    new_interests = set(profile["interests"]) | set(profile_update.get("interests", []))
    interests_str = ",".join(new_interests)

    cursor.execute("""
        INSERT INTO user_profile(user_id, message_count, avg_offtopic, avg_provocation,
            avg_spam, avg_rudeness, avg_verbosity, interests, last_updated)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            message_count=excluded.message_count,
            avg_offtopic=excluded.avg_offtopic,
            avg_provocation=excluded.avg_provocation,
            avg_spam=excluded.avg_spam,
            avg_rudeness=excluded.avg_rudeness,
            avg_verbosity=excluded.avg_verbosity,
            interests=excluded.interests,
            last_updated=excluded.last_updated
    """, (user_id, count, avg_offtopic, avg_provocation, avg_spam, avg_rudeness, avg_verbosity, interests_str, int(time.time())))
    conn.commit()

def update_user_notes(user_id, new_info: str):
    profile = get_user_profile(user_id)
    existing_notes = profile.get("notes", "")

    # Если новая информация уже есть — пропускаем
    if new_info in existing_notes:
        return

    # Добавляем новую информацию, отделяя точкой с пробелом
    updated_notes = (existing_notes + ". " + new_info).strip(". ")

    cursor.execute("""
        UPDATE user_profile
        SET notes=?, last_updated=?
        WHERE user_id=?
    """, (updated_notes, int(time.time()), user_id))
    conn.commit()

def is_calling_tars(text: str) -> bool:
    if not text: return False
    return bool(TRIGGER_REGEX.search(text))

def is_reply_to_bot(message) -> bool:
    return (
            message.reply_to_message and
            message.reply_to_message.from_user and
            message.reply_to_message.from_user.id == bot.get_me().id
    )

def extract_telegram_identity(message):
    user = message.from_user

    return {
        "id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or "",
        "language": user.language_code or ""
    }

def run_cmd(cmd):
    if cmd not in ALLOWED:
        return "Not allowed"

    try:
        # --- CPU Temperature ---
        temp_out = subprocess.check_output(
            ["vcgencmd", "measure_temp"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if temp_out.startswith("temp="):
            temp = temp_out.replace("temp=", "")
        else:
            temp = "N/A"

        # --- Uptime ---
        uptime_out = subprocess.check_output(
            ["uptime", "-p"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        uptime = uptime_out.replace("up ", "") if uptime_out else "N/A"

        # --- CPU Load ---
        load_out = subprocess.check_output(
            ["uptime"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if "load average:" in load_out:
            load = load_out.split("load average:")[-1].strip()
        else:
            load = "N/A"

        # --- Disk Usage for root / ---
        disk_out = subprocess.check_output(
            ["df", "-h", "/"], text=True, stderr=subprocess.DEVNULL
        ).strip().split("\n")
        if len(disk_out) >= 2:
            disk_percent = disk_out[1].split()[4]  # берем только 5-й столбец %
        else:
            disk_percent = "N/A"

        # --- Memory Usage ---
        mem_out = subprocess.check_output(
            ["free", "-h"], text=True, stderr=subprocess.DEVNULL
        ).strip().split("\n")
        if len(mem_out) >= 2:
            mem_values = mem_out[1].split()
            used_mem = mem_values[2]
            total_mem = mem_values[1]
            try:
                # Попробуем вычислить процент
                mem_percent = str(int(float(used_mem[:-1].replace("Gi","").replace("Mi","")) /
                                      float(total_mem[:-1].replace("Gi","").replace("Mi","")) * 100)) + "%"
            except Exception:
                mem_percent = f"{used_mem}/{total_mem}"
        else:
            mem_percent = "N/A"

        status_msg = (
            "<strong>TARS Pi Status</strong>\n\n"
            f"- CPU Temperature: {temp}\n"
            f"- Uptime: {uptime}\n"
            f"- CPU Load (1,5,15 min): {load}\n"
            f"- Disk Usage: {disk_percent}\n"
            f"- Memory Usage: {mem_percent}\n"
        )
        return status_msg

    except Exception as e:
        return f"Ошибка при получении статуса: {e}"

def extract_photo_url(message) -> Tuple[Optional[str], Optional[str]]:
    """Возвращает (url, caption) или (None, None)"""
    target_msg = message

    # Если это реплай на картинку
    if message.reply_to_message and message.reply_to_message.photo:
        target_msg = message.reply_to_message

    if not target_msg.photo:
        return None, None

    largest_photo = target_msg.photo[-1]
    file_info = bot.get_file(largest_photo.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    # Caption берем из исходного сообщения (если есть) или из сообщения с фото
    caption = message.text or message.caption or target_msg.caption or ""
    return url, caption

def shutdown(signum, frame):
    logging.info("Shutting down TARS...")
    conn.close()
    sys.exit(0)

# --- HANDLERS ---

@bot.message_handler(commands=["status"])
def status_handler(message):
    chat_id = message.chat.id

    # Можно добавить проверку ALLOWED_CHAT_IDS
    if chat_id not in ALLOWED_CHAT_IDS:
        return

    status_text = run_cmd("status")
    bot.send_message(chat_id, status_text, parse_mode="HTML")

@bot.message_handler(content_types=["text", "photo"])
def main_handler(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Периодическая очистка памяти (шанс 5% при каждом сообщении, чтобы не грузить таймер)
    if random.random() < 0.05:
        memory.cleanup()

    if chat_id not in ALLOWED_CHAT_IDS:
        return

    # Получаем текст и фото
    photo_url, caption = extract_photo_url(message)
    text_content = message.text or message.caption or ""
    identity = extract_telegram_identity(message)

    has_trigger = is_calling_tars(text_content)
    is_reply = is_reply_to_bot(message)

    # Если нет триггера и нет реплая - игнор (кроме случая, когда это реплай на фото с триггером)
    if not (has_trigger or is_reply):
        return

    # Cooldown check
    now = time.time()
    if now - cooldowns.get(user_id, 0) < USER_COOLDOWN_SECONDS:
        return # Silent ignore
    cooldowns[user_id] = now

    # Logging & Typing
    used_ctx, total_mem = memory.get_stats(chat_id)
    logging.info(f"Processing | chat={chat_id} user={user_id} type={'IMG' if photo_url else 'TXT'} mem={used_ctx}/{total_mem}")

    bot.send_chat_action(chat_id, "typing")
    time.sleep(random.uniform(0.5, 1.2)) # Имитация "думания"

    if photo_url and (has_trigger or is_reply):
        reply = brain.analyze_image(photo_url, caption)
    else:
        reply = brain.think(
            chat_id,
            user_id,
            text_content[:MAX_INPUT_CHARS],
            is_reply,
            identity
        )

    try:
        bot.reply_to(message, reply)
    except telebot.apihelper.ApiTelegramException as e:
        logging.error(f"Telegram API Error: {e}")

if __name__ == "__main__":
    logging.info("TARS v1.1 Systems Online")
    logging.info(f"Allowed Chats: {len(ALLOWED_CHAT_IDS)}")

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.critical(f"Critical Crash: {e}")
            time.sleep(10)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)