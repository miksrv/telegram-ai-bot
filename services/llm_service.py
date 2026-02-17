"""
LLM Service
Handles communication with text and vision LLM models via Groq API
"""

import base64
import logging
import requests

from config.settings import GROQ_API_KEY, MODEL_TEXT, MODEL_VISION
from core.prompts import build_general_prompt, get_vision_prompt

# Reuse a single session for connection pooling
session = requests.Session()


def generate_text_reply(
        context: str,
        identity: str,
        profile_summary: str,
        message: str,
        max_tokens: int = 800
) -> str:
    """
    Builds the system prompt and sends a text request to Groq LLM.
    """

    # Build final system prompt using centralized prompt builder
    system_content = build_general_prompt(
        context=context,
        identity=identity,
        profile_summary=profile_summary,
        message=message,
    )

    payload = {
        "model": MODEL_TEXT,
        "messages": [{"role": "system", "content": system_content}],
        "temperature": 0.8,
        "max_tokens": max_tokens,
        "top_p": 0.95,
    }

    try:
        response = session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logging.error(f"Text LLM error: {e}")
        return "LLM text module failure."


def generate_image_reply(image_bytes: bytes, caption: str = "") -> str:
    """
    Sends an image + caption to Groq Vision LLM and returns the assistant's reply.
    """

    try:
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        messages = [
            {
                "role": "system",
                "content": get_vision_prompt(),  # ← IMPORTANT: call the function
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": caption or "Analyze the image."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        },
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

        response = session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )

        if response.status_code != 200:
            logging.error("Vision LLM HTTP %s: %s", response.status_code, response.text)
            return "Vision module overloaded."

        return response.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logging.error(f"Vision LLM error: {e}")
        return "Vision LLM module failure."
