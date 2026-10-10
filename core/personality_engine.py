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
