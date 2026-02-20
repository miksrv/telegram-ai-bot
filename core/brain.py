import json
import base64
import logging
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
from core.personality_engine import PersonalityEngine

from database.profile_repo import db_get_user_profile, db_update_user_profile, db_update_user_notes


# --------------------------------------------------
# Shared HTTP session (connection reuse)
# --------------------------------------------------

API_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json",
}

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
    def think(self, chat_id, user_id, user_message, identity):

        user_message = user_message[:MAX_INPUT_CHARS]

        chat_ctx, user_ctx, identity_block, profile_summary = \
            self._build_user_context(chat_id, user_id, identity)

        system_content = build_general_prompt(
            context=f"Chat:\n{chat_ctx}\n\nUser:\n{user_ctx}",
            identity=identity_block,
            profile_summary=profile_summary,
            message=user_message,
        )

        try:
            raw = self._call_llm(
                MODEL_TEXT,
                [{"role": "system", "content": system_content}],
                temperature=0.8,
                max_tokens=800,
                top_p=0.95
            )

            data = self._parse_json_safe(raw)
            if not data:
                return "Ошибка ответа логического модуля"

            reply = data.get("reply", "")
            profile_update = data.get("profile_update", {})
            notes = data.get("notes")

            memory.add_chat_memory(chat_id, user_id, user_message, reply)
            memory.add_user_memory(user_id, user_message, reply)

            if profile_update:
                db_update_user_profile(user_id, profile_update)

            if notes:
                db_update_user_notes(user_id, notes)

            return reply

        except Exception as e:
            logging.error(f"Text gen error: {e}")
            return "Сбой логического модуля. Пожалуйста, попробуйте позже."


    # --------------------------------------------------
    # IMAGE ANALYSIS
    # --------------------------------------------------
    def analyze_image(self, chat_id, user_id, image_url, caption, identity):

        try:
            chat_ctx, user_ctx, identity_block, profile_summary = \
                self._build_user_context(chat_id, user_id, identity)

            vision_message = f"[IMAGE]\nCaption: {caption}" if caption else "[IMAGE]"

            system_content = build_general_prompt(
                context=f"Chat:\n{chat_ctx}\n\nUser:\n{user_ctx}",
                identity=identity_block,
                profile_summary=profile_summary,
                message=vision_message,
            ) + "\n\n" + get_vision_prompt()

            img = session.get(image_url, timeout=15)
            img.raise_for_status()

            image_b64 = base64.b64encode(img.content).decode()

            messages = [
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_message},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                        },
                    ],
                },
            ]

            reply = self._call_llm(
                MODEL_VISION,
                messages,
                temperature=0.9,
                max_tokens=400,
                top_p=0.9
            )

            memory.add_chat_memory(chat_id, user_id, vision_message, reply)
            memory.add_user_memory(user_id, vision_message, reply)

            return reply

        except Exception as e:
            logging.error(f"Vision error: {e}")
            return "Ошибка визуального модуля"


    # --------------------------------------------------
    # Context building (for both text and vision)
    # --------------------------------------------------
    def _build_user_context(self, chat_id, user_id, identity):
        chat_ctx = memory.get_chat_context(chat_id)
        user_ctx = memory.get_user_context(user_id)

        identity_block = (
            f"- Telegram ID: {identity.get('id')}\n"
            f"- First name: {identity.get('first_name')}\n"
            f"- Last name: {identity.get('last_name')}\n"
            f"- Username: @{identity.get('username')}\n"
            f"- Language: {identity.get('language')}\n"
        )

        profile = db_get_user_profile(user_id, identity)

        dynamic_rules = PersonalityEngine.build_prompt_rules(profile)

        profile_summary = (
            dynamic_rules + "\n\n"
                f"Interests: {', '.join(profile['interests']) or 'none'}\n"
                f"Notes: {profile['notes'] or 'none'}"
        )

        return chat_ctx, user_ctx, identity_block, profile_summary


    # --------------------------------------------------
    # LLM call abstraction (for both text and vision)
    # --------------------------------------------------
    def _call_llm(self, model, messages, temperature, max_tokens, top_p):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }

        response = post_with_retry(
            "https://api.groq.com/openai/v1/chat/completions",
            API_HEADERS,
            payload,
        )

        return response.json()["choices"][0]["message"]["content"].strip()


    # --------------------------------------------------
    # Robust JSON parsing (handles common model formatting issues)
    # --------------------------------------------------
    def _parse_json_safe(self, raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end != -1:
                return json.loads(raw[start:end])
            logging.error(f"Unrecoverable JSON: {raw}")
            return None


# Singleton brain instance
brain = TARSBrain()
