import json
import base64
import logging
from typing import Optional
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import (
    MODEL_TEXT,
    MODEL_VISION,
    GROQ_API_KEY,
    MAX_INPUT_CHARS,
)

from core.memory import memory
from core.prompts import build_general_prompt, get_vision_prompt

from database.profile_repo import db_get_user_profile, db_update_user_profile, db_update_user_notes


# --------------------------------------------------
# Shared HTTP session (connection reuse)
# --------------------------------------------------

session = requests.Session()

# Configure retry strategy for transient network errors
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
)

session.mount("https://", HTTPAdapter(max_retries=retries))

# ------------------------------------------------
# Helper function for API calls with retry logic
# ------------------------------------------------

def post_with_retry(url, headers, payload, retries=3):
    for attempt in range(retries):
        try:
            response = session.post(
                url,
                headers=headers,
                json=payload,
                timeout=(5, 60),
            )

            response.raise_for_status()
            return response

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:

            logging.warning(f"API retry {attempt+1}/{retries}: {e}")

            if attempt == retries - 1:
                raise

            time.sleep(2 ** attempt)  # exponential backoff


# ==================================================
# TARS Brain
# ==================================================

class TARSBrain:

    # --------------------------------------------------
    # TEXT THINKING
    # --------------------------------------------------
    def think(self, chat_id, user_id, user_message, identity: dict) -> str:
        """
        Main reasoning pipeline:
        - Build context
        - Call LLM
        - Parse JSON
        - Update memory + profile
        """

        # Prevent prompt overflow
        user_message = user_message[:MAX_INPUT_CHARS]

        # Retrieve contextual memory
        chat_ctx = memory.get_chat_context(chat_id)
        user_ctx = memory.get_user_context(user_id)

        # Safely construct identity block
        identity_block = (
            f"- Telegram ID: {identity.get('id')}\n"
            f"- First name: {identity.get('first_name')}\n"
            f"- Last name: {identity.get('last_name')}\n"
            f"- Username: @{identity.get('username')}\n"
            f"- Language: {identity.get('language')}\n"
        )

        # Fetch profile from DB
        profile = db_get_user_profile(user_id, identity)

        profile_summary = (
            f"- Offtopic tendency: {profile['avg_offtopic']:.2f}\n"
            f"- Provocation tendency: {profile['avg_provocation']:.2f}\n"
            f"- Spam tendency: {profile['avg_spam']:.2f}\n"
            f"- Rudeness tendency: {profile['avg_rudeness']:.2f}\n"
            f"- Verbosity: {profile['avg_verbosity']:.2f}\n"
            f"- Interests: {', '.join(profile['interests']) if profile['interests'] else 'none'}\n"
            f"- Notes: {profile['notes'] or 'none'}"
        )

        # Build centralized system prompt
        system_content = build_general_prompt(
            context=f"Chat:\n{chat_ctx}\n\nUser:\n{user_ctx}",
            identity=identity_block,
            profile_summary=profile_summary,
            message=user_message,
        )

        payload = {
            "model": MODEL_TEXT,
            "messages": [{"role": "system", "content": system_content}],
            "temperature": 0.8,
            "max_tokens": 800,
            "top_p": 0.95,
        }

        try:
            response = post_with_retry(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
            )

            response.raise_for_status()

            raw = response.json()["choices"][0]["message"]["content"].strip()

            # ---------------- JSON SAFE PARSING ----------------
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # Attempt to salvage JSON if model wrapped text
                start = raw.find("{")
                end = raw.rfind("}") + 1
                if start != -1 and end != -1:
                    data = json.loads(raw[start:end])
                else:
                    logging.error(f"Unrecoverable JSON: {raw}")
                    return "Ошибка логического модуля"

            reply = data.get("reply", "Ошибка: пустой ответ")
            profile_update = data.get("profile_update", {})
            notes = data.get("notes")

            # ---- Memory update
            memory.add_chat_memory(chat_id, user_id, user_message, reply)
            memory.add_user_memory(user_id, user_message, reply)

            # ---- Profile update
            if profile_update:
                db_update_user_profile(user_id, profile_update)

            if notes:
                db_update_user_notes(user_id, notes)

            return reply

        except Exception as e:
            logging.error(f"Text gen error: {e}")
            return "Сбой логического модуля"


    # --------------------------------------------------
    # IMAGE ANALYSIS
    # --------------------------------------------------
    def analyze_image(self, image_url: str, caption: Optional[str]) -> str:
        """
        Download image and send to vision model
        """

        try:
            img = session.get(image_url, timeout=10)
            img.raise_for_status()

            image_b64 = base64.b64encode(img.content).decode()

            messages = [
                {
                    "role": "system",
                    "content": get_vision_prompt(),  # call builder
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": caption or "Analyze image"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        },
                    ],
                },
            ]

            payload = {
                "model": MODEL_VISION,
                "messages": messages,
                "temperature": 0.9,
                "max_tokens": 300,
                "top_p": 0.9,
            }

            response = post_with_retry(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code != 200:
                logging.error(response.text)
                return "Оптические сенсоры перегружены"

            return response.json()["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logging.error(f"Vision error: {e}")
            return "Ошибка визуального модуля"

# Singleton brain instance
brain = TARSBrain()
