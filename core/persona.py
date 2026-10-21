"""
Bot persona loader.

A persona is a small hand-editable text file in personas/<key>.md holding
everything that makes the bot "who it is" (name, character, tone, self-names,
extra trigger words). Structural prompt parts (JSON contract, plain-text rules,
user card, capabilities, profile updates) stay in core/prompts.py and apply to
every persona. The active persona is chosen by settings.PERSONA.

File format: `key: value` header lines up to a line holding only `---`, then
prompt text split into `## section` blocks. Lines before the first `## ` heading
in the body are comments and are ignored.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from config.settings import PERSONA, PERSONAS_DIR

REQUIRED_SECTIONS = ("identity", "style", "humor", "proactive_character")

# The original bot name always stays valid as a way to address the bot,
# whatever persona is active (and is what the stored chat history calls it).
BASE_SELF_NAMES = ("ТАРС", "TARS", "Тарс*")


@dataclass(frozen=True)
class Persona:
    """One parsed persona file."""

    key: str
    name: str
    self_names: Tuple[str, ...]
    triggers: Tuple[str, ...]
    identity: str
    style: str
    humor: str
    proactive_character: str

    def all_self_names(self) -> List[str]:
        """Persona's own names first, then the base TARS names, without duplicates."""
        names: List[str] = []
        for n in (*self.self_names, *BASE_SELF_NAMES):
            if n.lower() not in (x.lower() for x in names):
                names.append(n)
        return names


def _split_csv(raw: str) -> Tuple[str, ...]:
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def parse_persona(key: str, text: str) -> Persona:
    """Parses persona file text. Raises ValueError when malformed."""
    # Files edited on Windows may carry CRLF (or a BOM); the separator and headings expect "\n".
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    head, sep, body = text.partition("\n---\n")
    if not sep:
        raise ValueError(f"persona '{key}': missing '---' line after the header")

    header: Dict[str, str] = {}
    for line in head.splitlines():
        if line.strip() and ":" in line:
            k, _, v = line.partition(":")
            header[k.strip().lower()] = v.strip()

    sections: Dict[str, List[str]] = {}
    current = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    missing = [s for s in REQUIRED_SECTIONS if not "\n".join(sections.get(s, [])).strip()]
    if missing or not header.get("name"):
        raise ValueError(f"persona '{key}': missing header 'name' or sections {missing}")

    text_of = {s: "\n".join(sections[s]).strip() for s in REQUIRED_SECTIONS}
    return Persona(
        key=key,
        name=header["name"],
        self_names=_split_csv(header.get("self_names", "")) or (header["name"],),
        triggers=tuple(t.lower() for t in _split_csv(header.get("triggers", ""))),
        **text_of,
    )


def load_persona(key: str, directory: str = PERSONAS_DIR) -> Persona:
    """Loads and parses personas/<key>.md."""
    with open(os.path.join(directory, f"{key}.md"), encoding="utf-8") as f:
        return parse_persona(key, f.read())


# Active persona, loaded once at import time (settings.py already verified the file exists).
persona = load_persona(PERSONA)
