from math import floor


class PersonalityEngine:

    LEVELS = 10

    @staticmethod
    def quantize(value: float) -> int:
        """Convert 0..1 float into 0..9 level"""
        value = max(0.0, min(1.0, value))
        return min(PersonalityEngine.LEVELS - 1, floor(value * PersonalityEngine.LEVELS))

    @staticmethod
    def offtopic_rule(level):
        # Pairs → effective 4 tiers: none (0–1), light (2–3), moderate (4–7), strict (8–9)
        rules = [
            "",
            "",
            "If the message is unrelated to astronomy, gently note it and steer back to relevant topics.",
            "If the message is unrelated to astronomy, gently note it and steer back to relevant topics.",
            "Redirect off-topic exchanges back to astronomy, science, or the community's subject matter.",
            "Redirect off-topic exchanges back to astronomy, science, or the community's subject matter.",
            "Firmly steer off-topic messages back to astronomy; do not engage with the digression itself.",
            "Firmly steer off-topic messages back to astronomy; do not engage with the digression itself.",
            "Do not engage with off-topic content. One-sentence redirect to astronomy, then stop.",
            "Do not engage with off-topic content. One-sentence redirect to astronomy, then stop.",
        ]
        return rules[level]

    @staticmethod
    def provocation_rule(level):
        # At higher levels, reinforce sycophancy resistance: hold positions, do not capitulate
        rules = [
            "",
            "",
            "Stay factual and calm; do not mirror the user's emotional tone.",
            "Stay factual and calm; do not mirror the user's emotional tone.",
            "Hold your factual positions under pressure. If you are correct, confirm it briefly and move on.",
            "Hold your factual positions under pressure. If you are correct, confirm it briefly and move on.",
            "Do not soften or retract correct statements in response to pushback. Correct once, then stop.",
            "Do not soften or retract correct statements in response to pushback. Correct once, then stop.",
            "Fully clinical tone. No humor, no concessions to argument or repetition.",
            "Fully clinical tone. No humor, no concessions to argument or repetition.",
        ]
        return rules[level]

    @staticmethod
    def spam_rule(level):
        rules = [
            "",
            "",
            "",
            "Keep responses compact; do not elaborate on low-effort messages.",
            "Keep responses compact; do not elaborate on low-effort messages.",
            "Short answers only. Do not reward repetitive or low-effort messages with detailed replies.",
            "Short answers only. Do not reward repetitive or low-effort messages with detailed replies.",
            "Minimal engagement. One or two sentences maximum.",
            "Minimal engagement. One or two sentences maximum.",
            "One sentence maximum. Respond only to the core question if there is one.",
        ]
        return rules[level]

    @staticmethod
    def rudeness_rule(level):
        rules = [
            "",
            "",
            "Stay polite and professional regardless of the user's tone.",
            "Stay polite and professional regardless of the user's tone.",
            "Maintain a formal, impersonal tone. No casual warmth.",
            "Maintain a formal, impersonal tone. No casual warmth.",
            "Technical tone only. No humor, no small talk.",
            "Technical tone only. No humor, no small talk.",
            "Strictly factual. Acknowledge the question, answer it, stop.",
            "Strictly factual. Acknowledge the question, answer it, stop.",
        ]
        return rules[level]

    @staticmethod
    def verbosity_rule(level):
        rules = [
            "Be concise. Answer in one or two sentences; do not elaborate unless asked.",
            "Keep responses brief and to the point.",
            "Balanced — short answers for simple questions, more detail when genuinely useful.",
            "Balanced — short answers for simple questions, more detail when genuinely useful.",
            "Standard detail level. Explain reasoning where it adds value.",
            "Standard detail level. Explain reasoning where it adds value.",
            "Expand explanations. This user benefits from more thorough answers.",
            "Expand explanations. This user benefits from more thorough answers.",
            "Go deep. Provide technical depth, context, and full reasoning.",
            "Go deep. Provide technical depth, context, and full reasoning.",
        ]
        return rules[level]

    # Message-count thresholds for the familiarity rule below. Deliberately not
    # settings — this is cheap internal shaping, not something the owner needs
    # to tune per deployment.
    NEWCOMER_THRESHOLD = 3
    REGULAR_THRESHOLD = 20

    @staticmethod
    def familiarity_rule(message_count: int) -> str:
        """One-line directive derived from how many turns this user has had with
        TARS — a newcomer gets a bit more context, a regular is addressed
        naturally without re-introducing itself. Empty in the middle band."""
        if message_count < PersonalityEngine.NEWCOMER_THRESHOLD:
            return "Newcomer: be slightly more welcoming and explanatory, assume no prior context."
        if message_count >= PersonalityEngine.REGULAR_THRESHOLD:
            return "Regular: address them by name/known facts naturally; skip re-introductions."
        return ""

    @staticmethod
    def depth_rule(experience: str) -> str:
        """One-line directive from the user's self-reported experience level
        (the "experience" structured fact). Empty when unset or unrecognized."""
        rules = {
            "beginner": "Explain basics plainly; avoid unexplained jargon.",
            "advanced": "Assume a strong background; skip basic explanations.",
            "pro": "Peer-level technical depth; no hand-holding.",
        }
        return rules.get((experience or "").strip().lower(), "")

    # ----------------------------
    # ATTITUDE (who this person is to the bot; the active persona says how to treat them)
    # ----------------------------

    # Tags the model may put in a reply's "mood" field (tone of the user's latest message).
    MOODS = ("friendly", "rude", "provocative", "offtopic", "spam")
    # How many following replies a mood keeps colouring the bot's manner.
    MOOD_HOLD_TURNS = 3
    # Reputation thresholds on the EMA averages; deliberately low, so one clear incident is
    # felt for a while (a single 1.0 sample gives 0.3 with the default alpha).
    REPUTATION_THRESHOLD = 0.25
    FRIEND_THRESHOLD = 0.5

    _MOOD_TO_ATTITUDE = {
        "friendly": "friend",
        "rude": "rude",
        "provocative": "provocative",
        "offtopic": "offtopic",
        "spam": "spammer",
    }
    _AVG_TO_ATTITUDE = (
        ("avg_rudeness", "rude"),
        ("avg_provocation", "provocative"),
        ("avg_offtopic", "offtopic"),
        ("avg_spam", "spammer"),
    )

    @classmethod
    def normalize_mood(cls, mood) -> str:
        """The model's "mood" tag if it is a known one, else "" (neutral / missing / garbage)."""
        mood = mood.strip().lower() if isinstance(mood, str) else ""
        return mood if mood in cls.MOODS else ""

    @classmethod
    def attitudes(cls, profile: dict) -> list:
        """(key, why) pairs describing this person, in priority order: the current mood first
        ("right now"), then long-term reputation ("habitually"), then familiarity and expertise.
        Keys match the persona file's "## attitudes" entries."""
        result = []
        seen = set()

        def add(key, why):
            if key not in seen:
                seen.add(key)
                result.append((key, why))

        mood = cls.normalize_mood(profile.get("mood"))
        turns = profile.get("mood_turns", 0)
        if mood and turns > 0:
            # "just now" only on the first reply after the message that set the mood, so a one-off
            # reaction (e.g. announcing a lowered humor setting) is not repeated on every reply.
            add(
                cls._MOOD_TO_ATTITUDE[mood],
                "just now" if turns >= cls.MOOD_HOLD_TURNS else "still, from a recent message",
            )

        for field, key in cls._AVG_TO_ATTITUDE:
            if (profile.get(field) or 0.0) >= cls.REPUTATION_THRESHOLD:
                add(key, "habitually")
        if (profile.get("avg_friendliness") or 0.0) >= cls.FRIEND_THRESHOLD:
            add("friend", "habitually")

        count = profile.get("message_count", 0)
        if count < cls.NEWCOMER_THRESHOLD:
            add("newcomer", "first talk" if count == 0 else "few talks so far")
        elif count >= cls.REGULAR_THRESHOLD:
            add("regular", f"{count} talks so far")

        experience = str((profile.get("facts") or {}).get("experience", "")).strip().lower()
        if experience in ("advanced", "pro"):
            add("expert", experience)
        elif experience == "beginner":
            add("beginner", experience)
        return result

    @classmethod
    def build_attitude_note(cls, profile: dict, attitude_texts: dict, name: str = "") -> str:
        """The per-person line sent next to the persona reminder, built from the persona's own
        `attitude_texts` (key -> how to treat such a person). "" when nothing applies."""
        lines = [
            f"- {key} ({why}): {attitude_texts[key]}" for key, why in cls.attitudes(profile) if attitude_texts.get(key)
        ]
        if not lines:
            return ""
        who = f" ({name})" if name else ""
        return (
            f"The person you are answering now{who}, as you know them. Your attitude toward them is mandatory "
            "and must be clear from the tone and content of this reply, while still answering the message "
            "itself. Show it in fresh words each time: never repeat a stock opening from your earlier "
            "replies, and never state settings or percentages unless an item below says to announce a "
            "change just now (only then the no-meta-comments rule does not apply).\n" + "\n".join(lines)
        )

    # ----------------------------
    # PUBLIC ENTRYPOINT
    # ----------------------------

    @classmethod
    def build_prompt_rules(cls, profile: dict) -> str:

        rules = []

        mapping = [
            (profile["avg_offtopic"], cls.offtopic_rule),
            (profile["avg_provocation"], cls.provocation_rule),
            (profile["avg_spam"], cls.spam_rule),
            (profile["avg_rudeness"], cls.rudeness_rule),
            (profile["avg_verbosity"], cls.verbosity_rule),
        ]

        for value, fn in mapping:
            level = cls.quantize(value)
            rule = fn(level)
            if rule:
                rules.append(rule)

        familiarity = cls.familiarity_rule(profile.get("message_count", 0))
        if familiarity:
            rules.append(familiarity)

        depth = cls.depth_rule((profile.get("facts") or {}).get("experience", ""))
        if depth:
            rules.append(depth)

        if not rules:
            return ""

        return "Adaptive response behavior:\n- " + "\n- ".join(rules)
