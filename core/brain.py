import base64
import json
import logging
import time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import (
    GROQ_API_KEY,
    MAX_INPUT_CHARS,
    MODEL_TEXT,
    MODEL_VISION,
    PROACTIVE_CONTEXT_MESSAGES,
    PROACTIVE_MIN_CONTEXT_MESSAGES,
)
from core.memory import memory
from core.personality_engine import PersonalityEngine
from core.prompts import (
    build_general_system_prompt,
    build_proactive_prompt,
    build_reply_only_system_prompt,
    get_vision_prompt,
)
from database.db import get_recent_messages
from database.profile_repo import (
    db_get_user_profile,
    db_increment_message_count,
    db_update_user_notes,
    db_update_user_profile,
)

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
    connect=3,
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

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
            ConnectionResetError,
        ) as e:

            logging.warning(f"API retry {attempt+1}/{retries}: {e}")

            if attempt == retries - 1:
                raise

            time.sleep(2**attempt)  # exponential backoff


# ==================================================
# TARS Brain
# ==================================================


class TARSBrain:

    # --------------------------------------------------
    # TEXT THINKING
    # --------------------------------------------------
    def think(self, chat_id, user_id, user_message, identity, reply_to_text=None, reply_to_is_bot=True):

        user_message = user_message[:MAX_INPUT_CHARS]

        chat_history, identity_block, profile_summary, profile = self._build_user_context(chat_id, user_id, identity)

        # Full profile update on first message (msg_count==0) and every 5th thereafter
        want_full_update = profile["message_count"] % 5 == 0

        if want_full_update:
            system_content = build_general_system_prompt(identity_block, profile_summary)
        else:
            system_content = build_reply_only_system_prompt(identity_block, profile_summary)

        messages = self._build_messages_array(
            chat_history, user_message, system_content, reply_to_text, reply_to_is_bot
        )

        try:
            reply, err = self._process_llm_response(
                MODEL_TEXT,
                messages,
                temperature=0.8,
                max_tokens=800,
                top_p=0.95,
                chat_id=chat_id,
                user_id=user_id,
                user_input=user_message,
                update_profile=want_full_update,
            )

            if err:
                return err

            return reply

        except Exception as e:
            logging.exception(f"Text gen error: {e}")
            return "Сбой логического модуля. Пожалуйста, попробуйте позже."

    # --------------------------------------------------
    # IMAGE ANALYSIS
    # --------------------------------------------------
    def analyze_image(
        self,
        chat_id,
        user_id,
        image_url,
        caption,
        identity,
        reply_to_text=None,
        reply_to_is_bot=True,
        photo_from_reply=False,
    ):

        try:
            chat_history, identity_block, profile_summary, profile = self._build_user_context(
                chat_id, user_id, identity
            )

            want_full_update = profile["message_count"] % 5 == 0

            caption_text = (caption or "").strip()
            vision_message = f"[IMAGE]\nCaption: {caption_text}" if caption_text else "[IMAGE]"

            # Same system-only templates as the text path, plus the vision extensions.
            if want_full_update:
                system_content = build_general_system_prompt(identity_block, profile_summary)
            else:
                system_content = build_reply_only_system_prompt(identity_block, profile_summary)
            system_content += "\n\n" + get_vision_prompt()

            # When the analyzed photo comes from a replied-to (older) message, the recent
            # chat history is about something else and is not useful for describing this
            # image — drop it. Otherwise the image accompanies the live conversation, so
            # keep the rolling context.
            history = [] if photo_from_reply else chat_history

            # Reuse the text path's conversation builder so the image turn gets the same
            # global context, ancient-reply pruning, and quote handling. Its final user
            # turn (a plain string) is then upgraded to a multimodal text+image message.
            messages = self._build_messages_array(
                history, vision_message, system_content, reply_to_text, reply_to_is_bot
            )

            img = session.get(image_url, timeout=15)
            img.raise_for_status()

            image_b64 = base64.b64encode(img.content).decode()

            final_text = messages[-1]["content"]
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": final_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }

            # Record the photo in chat memory so following turns know one was shared and
            # what was said about it (the caption), instead of storing a bare None.
            memory_text = f"[изображение] {caption_text}".strip() if caption_text else "[изображение]"

            reply, err = self._process_llm_response(
                MODEL_VISION,
                messages,
                temperature=0.9,
                max_tokens=400,
                top_p=0.9,
                chat_id=chat_id,
                user_id=user_id,
                user_input=memory_text,
                update_profile=want_full_update,
            )

            if err:
                return err

            return reply

        except Exception as e:
            logging.exception(f"Vision error: {e}")
            return "Ошибка визуального модуля"

    # --------------------------------------------------
    # Core LLM response processing (shared logic for text and vision)
    # --------------------------------------------------
    def _process_llm_response(
        self,
        model,
        messages,
        temperature,
        max_tokens,
        top_p,
        chat_id,
        user_id,
        user_input,
        update_profile: bool = True,
    ):
        raw = self._call_llm(
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        )

        data = self._parse_json_safe(raw)
        if not data:
            return None, "Ошибка ответа логического модуля"

        reply = data.get("reply", "")

        # Memory update
        memory.add_chat_memory(chat_id, user_id, user_input, reply)

        # Always increment the interaction counter
        db_increment_message_count(user_id)

        # Profile update only on designated turns (first message + every 5th)
        if update_profile:
            profile_update = data.get("profile_update", {})
            notes = data.get("notes")

            if profile_update:
                db_update_user_profile(user_id, profile_update)

            if notes:
                db_update_user_notes(user_id, notes)

        return reply, None

    # --------------------------------------------------
    # Context building (for both text and vision)
    # --------------------------------------------------
    def _build_user_context(self, chat_id, user_id, identity):
        chat_history = memory.get_chat_history(chat_id)

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

        return chat_history, identity_block, profile_summary, profile

    # --------------------------------------------------
    # Build proper chat completions messages array from raw chat history
    # --------------------------------------------------
    def _build_messages_array(
        self,
        chat_history: list,
        current_message: str,
        system_content: str,
        reply_to_text: str = None,
        reply_to_is_bot: bool = True,
    ) -> list:
        messages = [{"role": "system", "content": system_content}]

        snippet = reply_to_text[:MAX_INPUT_CHARS].strip() if reply_to_text else ""

        # Is the replied-to message still inside the rolling window? Match on exact
        # text, or substantial containment to tolerate truncation on either side.
        in_window = False
        if snippet:
            for _uid, _role, text in chat_history:
                t = (text or "").strip()
                if t and (t == snippet or (len(snippet) >= 16 and (snippet in t or t in snippet))):
                    in_window = True
                    break

        # A reply to ANOTHER user's message is folded into the current user turn as an
        # explicit reference, rather than mislabeling another person's words as TARS's
        # own assistant turn.
        if snippet and not reply_to_is_bot:
            current_message = f'(в ответ на сообщение: "{snippet}")\n{current_message}'

        # Ancient reply: the user is answering an OLD message (a proactive post, an old
        # photo, or a turn already evicted from memory). The recent rolling history is
        # about a different topic and would only mislead the model, so drop it entirely
        # and anchor solely on the quoted message. This also trims tokens.
        if snippet and not in_window:
            if reply_to_is_bot:
                messages.append({"role": "assistant", "content": snippet})
            messages.append({"role": "user", "content": current_message})
            return messages

        last_assistant_text = None
        for user_id, role, text in chat_history:
            if role == "user":
                messages.append({"role": "user", "content": f"User#{user_id}: {text}"})
            else:
                messages.append({"role": "assistant", "content": text})
                last_assistant_text = text

        # In-window reply to the bot: surface the exact quoted turn as the immediately
        # preceding assistant message so the model answers the right one, unless it
        # already is the latest assistant turn.
        if snippet and reply_to_is_bot and snippet != (last_assistant_text or "").strip():
            messages.append({"role": "assistant", "content": snippet})

        messages.append({"role": "user", "content": current_message})
        return messages

    # --------------------------------------------------
    # LLM call abstraction (for both text and vision)
    # --------------------------------------------------
    def _call_llm(self, model, messages, temperature, max_tokens, top_p, json_mode=True):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }

        # Force valid JSON output at the API level instead of relying on prompt
        # instructions + brace-extraction fallback. All prompts already request
        # JSON and contain the word "json" (a Groq JSON-mode requirement).
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = post_with_retry(
            "https://api.groq.com/openai/v1/chat/completions",
            API_HEADERS,
            payload,
        )

        return response.json()["choices"][0]["message"]["content"].strip()

    # --------------------------------------------------
    # PROACTIVE POSTING
    # --------------------------------------------------
    def post_proactively(self, chat_id: int):
        """
        Generates and returns a proactive message for the given chat.

        Returns the reply string on success, or None if there is not enough
        context or if the LLM call fails.
        """
        try:
            rows = get_recent_messages(chat_id, PROACTIVE_CONTEXT_MESSAGES)
            if len(rows) < PROACTIVE_MIN_CONTEXT_MESSAGES:
                return None

            context_lines = [f"{r['first_name']}: {r['text']}" for r in rows]
            utc_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            prompt = build_proactive_prompt(context_lines, utc_time)

            raw = self._call_llm(
                MODEL_TEXT,
                [{"role": "system", "content": prompt}],
                temperature=0.85,
                max_tokens=200,
                top_p=0.95,
            )

            data = self._parse_json_safe(raw)
            if not data:
                return None

            reply = data.get("reply", "").strip()
            if not reply:
                return None

            return reply

        except Exception as e:
            logging.exception(f"post_proactively error (chat={chat_id}): {e}")
            return None

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
