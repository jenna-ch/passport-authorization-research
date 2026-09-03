# arms.py — the four P3-B2 arms.
#
# EVERY arm is identical except for `refusal_renderer`. There is no per-arm
# prompt, no per-arm parser, no per-arm action space, no per-arm cap and no
# per-arm classifier. `seller_prompt()` is defined once on the class and reads
# the single frozen file, so it is not even possible to give one arm a
# different prompt without editing this file.
#
# All four arms:
#   - use the FROZEN Study 1 seller system prompt (d4005aaea3b9b780);
#   - carry NO advance notice that enforcement exists;
#   - enforce deterministically with the frozen C1 classifier;
#   - use the FROZEN parser (so `escalate` is not an available action in any
#     arm — parser follows the prompt);
#   - allow the same same-turn attempt cap.
#
# SIMULATED PASSPORT PRIMITIVE INTERFACE BASED ON CURRENT DESIGN MATERIALS.
# Not deployed Passport functionality.

import pathlib

import refusals
from agents import parse_action

BASE = pathlib.Path(__file__).resolve().parent

# P3-B used 3. P3-B2 raises it to 5 so that `guard_exhausted` is not the
# outcome the cap manufactures. The PRIMARY outcome is pre-registered as the
# FIRST RETRY after the FIRST BLOCK, which the cap cannot touch: a run's first
# block always occurs at attempt 1 of some turn (an authorized attempt ends
# the turn immediately), so attempt 2 always exists whenever the cap is >= 2.
MAX_ATTEMPTS_PER_TURN = 5

SELLER_PROMPT_FILE = "seller_system.txt"      # the frozen Study 1 prompt
ENFORCEMENT_ANNOUNCED = False                 # in every arm, by construction


class Arm:
    def __init__(self, name):
        assert name in refusals.RENDERERS
        self.name = name
        self.enforcement_active = True
        self.enforcement_announced = ENFORCEMENT_ANNOUNCED
        self.factors = refusals.FACTORS[name]

    # -- model-visible text --------------------------------------------------
    def seller_prompt(self):
        """one file, one arm-independent read."""
        return (BASE / "prompts" / SELLER_PROMPT_FILE).read_text(
            encoding="utf-8")

    def render_refusal(self, state, classification, state_template):
        return refusals.RENDERERS[self.name](state, classification,
                                             state_template)

    def template_id(self):
        return refusals.template_id(self.name)

    def template_sha16(self, state_template):
        return refusals.template_sha16(self.name, state_template)

    # -- action space: frozen, identical in every arm ------------------------
    def parse(self, text):
        return parse_action(text)

    def as_dict(self, state_template=None):
        d = {
            "arm": self.name,
            "refusal_components": dict(self.factors),
            "refusal_template_id": self.template_id(),
            "enforcement_active": self.enforcement_active,
            "enforcement_announced": self.enforcement_announced,
            "seller_prompt_file": SELLER_PROMPT_FILE,
            "escalation_available": False,
            "max_attempts_per_turn": MAX_ATTEMPTS_PER_TURN,
        }
        if state_template is not None:
            d["refusal_template_sha16"] = self.template_sha16(state_template)
        return d


ARM_ORDER = ("R0", "R1", "R2", "R3")
ARMS = {n: Arm(n) for n in ARM_ORDER}

assert len(ARMS) == 4
assert {a.enforcement_announced for a in ARMS.values()} == {False}
assert {a.enforcement_active for a in ARMS.values()} == {True}
