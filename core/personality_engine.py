from math import floor


class PersonalityEngine:

    LEVELS = 10

    @staticmethod
    def quantize(value: float) -> int:
        """
        Convert 0..1 float into 0..9 level
        """
        value = max(0.0, min(1.0, value))
        return min(PersonalityEngine.LEVELS - 1,
                   floor(value * PersonalityEngine.LEVELS))


    @staticmethod
    def offtopic_rule(level):
        rules = [
            "",
            "",
            "Lightly encourage relevance.",
            "Occasionally steer conversation back.",
            "Actively steer toward task.",
            "Redirect when drifting.",
            "Firmly maintain topic alignment.",
            "Strongly prevent digression.",
            "Strictly enforce relevance.",
            "Hard constrain conversation to topic.",
        ]
        return rules[level]


    @staticmethod
    def provocation_rule(level):
        rules = [
            "",
            "",
            "Normal tone acceptable.",
            "Reduce emotional engagement.",
            "Increase neutrality.",
            "Maintain detached tone.",
            "Strict emotional neutrality.",
            "Avoid humor.",
            "Fully clinical tone.",
            "Maximum restraint.",
        ]
        return rules[level]


    @staticmethod
    def spam_rule(level):
        rules = [
            "",
            "",
            "",
            "Slightly reduce response length.",
            "Prefer concise answers.",
            "Keep replies short.",
            "Minimize verbosity.",
            "Respond minimally.",
            "Ultra-compact replies.",
            "One-paragraph maximum.",
        ]
        return rules[level]


    @staticmethod
    def rudeness_rule(level):
        rules = [
            "",
            "",
            "Maintain polite neutrality.",
            "Increase professionalism.",
            "Formal tone.",
            "Technical tone.",
            "Strict technical tone.",
            "No humor.",
            "Highly formal language.",
            "Clinical precision.",
        ]
        return rules[level]


    @staticmethod
    def verbosity_rule(level):
        rules = [
            "Be concise.",
            "Keep responses compact.",
            "Balanced brevity.",
            "Normal detail level.",
            "Standard explanations.",
            "Expand explanations.",
            "Detailed responses encouraged.",
            "Deep technical detail.",
            "Highly comprehensive.",
            "Maximum analytical depth.",
        ]
        return rules[level]


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

        if not rules:
            return ""

        return "Adaptive response behavior:\n- " + "\n- ".join(rules)