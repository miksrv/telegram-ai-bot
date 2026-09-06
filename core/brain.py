import base64
import json
import logging
from datetime import datetime

import requests

from config.settings import MAX_INPUT_CHARS, PROACTIVE_CONTEXT_MESSAGES, PROACTIVE_MIN_CONTEXT_MESSAGES
from core.llm import llm_engine
from core.llm.base import LLMEmptyResponseError
from core.memory import memory
from core.personality_engine import PersonalityEngine
from core.prompts import (
    build_general_system_prompt,
    build_proactive_prompt,
    build_proactive_reply_prompt,
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
# Shared HTTP session (connection reuse) — for downloading Telegram photo
# bytes in analyze_image(); unrelated to the LLM provider calls, which go
# through core.llm.llm_engine.
# --------------------------------------------------

session = requests.Session()

# User-facing fallbacks. Kept as constants so handlers/tests can compare
# against them and so the wording lives in exactly one place.
LLM_FAILURE_REPLY = "Сбой логического модуля. Пожалуйста, попробуйте позже."
LLM_BAD_RESPONSE_REPLY = "Ошибка ответа логического модуля"
LLM_REFUSAL_REPLY = "Логический модуль отклонил этот запрос. Попробуйте переформулировать вопрос."
VISION_FAILURE_REPLY = "Ошибка визуального модуля"


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
                "text",
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

        except LLMEmptyResponseError as e:
            # The API answered fine but the model produced no text — almost always a
            # refusal/content filter on this particular message. Not a bot fault, so
            # no stack trace and no "try again later": the same input would refuse again.
            logging.warning(f"LLM refused/empty completion (chat={chat_id} user={user_id}): {e}")
            return LLM_REFUSAL_REPLY

        except Exception as e:
            logging.exception(f"Text gen error: {e}")
            return LLM_FAILURE_REPLY

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
                "vision",
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

        except LLMEmptyResponseError as e:
            logging.warning(f"Vision model refused/empty completion (chat={chat_id} user={user_id}): {e}")
            return LLM_REFUSAL_REPLY

        except Exception as e:
            logging.exception(f"Vision error: {e}")
            return VISION_FAILURE_REPLY

    # --------------------------------------------------
    # Core LLM response processing (shared logic for text and vision)
    # --------------------------------------------------
    def _process_llm_response(
        self,
        kind,
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
            kind,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        )

        data = self._parse_json_safe(raw)
        if not isinstance(data, dict) or not data:
            return None, LLM_BAD_RESPONSE_REPLY

        # The model occasionally returns `"reply": null` or a non-string value
        # despite the schema in the prompt — treat anything but real text as empty.
        reply = data.get("reply")
        reply = reply.strip() if isinstance(reply, str) else ""
        if not reply:
            logging.error(f"LLM returned empty reply field: {raw}")
            return None, LLM_BAD_RESPONSE_REPLY

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
    # LLM call abstraction (for both text and vision) — delegates to the
    # active core.llm provider. `kind` is "text" or "vision", not a literal
    # model name; the provider resolves its own model per role.
    # --------------------------------------------------
    def _call_llm(self, kind, messages, temperature, max_tokens, top_p, json_mode=True):
        return llm_engine.complete(
            messages,
            kind=kind,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            json_mode=json_mode,
        )

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
                "text",
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
    # PROACTIVE DIRECT REPLY (once-daily, targets one specific message)
    # --------------------------------------------------
    def post_proactive_reply(self, chat_id: int, target_text: str, target_author: str):
        """
        Generates a direct reply to a specific past message. The caller (the
        proactive engine) already picked the target message via SQL/Python, so
        this spends exactly one LLM call — none are spent on target selection.

        Returns the reply string on success, or None if there is not enough
        context or if the LLM call fails.
        """
        try:
            rows = get_recent_messages(chat_id, PROACTIVE_CONTEXT_MESSAGES)
            if len(rows) < PROACTIVE_MIN_CONTEXT_MESSAGES:
                return None

            context_lines = [f"{r['first_name']}: {r['text']}" for r in rows]
            utc_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            prompt = build_proactive_reply_prompt(context_lines, target_author, target_text, utc_time)

            raw = self._call_llm(
                "text",
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
            logging.exception(f"post_proactive_reply error (chat={chat_id}): {e}")
            return None

    # --------------------------------------------------
    # Robust JSON parsing (handles common model formatting issues)
    # --------------------------------------------------
    def _parse_json_safe(self, raw):
        """Parses the model's JSON output, tolerating stray text around the object.

        Never raises: a completely unparseable payload returns None so the caller
        can report a clean "bad response" instead of a generic module failure.
        """
        if not isinstance(raw, str) or not raw.strip():
            logging.error(f"Unrecoverable JSON (empty/non-text payload): {raw!r}")
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Fallback: model wrapped the object in prose/markdown fences — cut out the
        # outermost {...} and try again.
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass

        logging.error(f"Unrecoverable JSON: {raw}")
        return None


# Singleton brain instance
brain = TARSBrain()
