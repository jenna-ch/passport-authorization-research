# arms.py — the two P3-A arms.
#
# RESEARCH QUESTION (as patched before any run).
#
#   Does explicitly declaring that `accept` creates the same economic
#   commitment as directly proposing the buyer's package reduce
#   action-path-specific authority failures?
#
# The broader conceptual question — whether authorization follows the economic
# commitment or the action representation — remains the motivation. But THIS
# CELL IS NOT A PATH-FORCED COMPARISON, and must not be described as one. Both
# arms retain the full frozen action space; the intervention is a schema
# declaration, nothing else.
#
# THE TWO COMMITMENT PATHS (see the design record's conceptual audit). In the
# frozen Study 1 world exactly two actions create an economically equivalent
# seller price commitment, and the frozen tracker itself says so: both
# `update_seller` (unconditional counter) and `update_seller_accept` route
# through the SAME function, tracker._apply_commitment. At an identical state
# they produce byte-identical tracker state and identical events, differing
# only by the `via_accept` tag.
#
#   path COUNTER  seller proposes price P            -> standing_offer = P
#   path ACCEPT   seller accepts the buyer's P       -> standing_offer = P
#
# `confirm_amendment` and `finalize` were evaluated and REMOVED, and a
# conditional counter was evaluated and excluded. That is a SCOPE RESULT about
# the frozen world, not a failed implementation. See the design record §3.
#
# WHY NOT PATH FORCING. Forcing the path forces the decision: instructing "use
# accept" at a state where accepting is unauthorized manufactures the very
# violation being measured, and instructing "use counter" removes the choice
# the cell exists to observe. Both arms therefore keep the FULL frozen action
# space and the identical world.
#
#   A-both      the frozen Study 1 seller prompt, byte-identical. Its schema
#               describes `accept` as "accept the counterparty's current
#               package exactly as offered; ends the negotiation with
#               agreement" — it never says this is a price commitment.
#   A-declared  the frozen bytes plus a SEMANTICS-ONLY declaration. It states
#               only (a) what `accept` commits the seller to, and (b) that this
#               is the same commitment as proposing that package directly. It
#               adds NO behavioural instruction: no "check authorization", no
#               "only accept if authorized", no "apply your mandate", no "be
#               careful", no "verify". It defines what the action MEANS, never
#               how to behave. Offline gate 1 asserts this.
#
# READING — and the three layers must never be collapsed. A change in
# accept-path violations can come from a change in OPPORTUNITY, in path
# SELECTION, or in ADHERENCE conditional on both. protocol_p3a records all
# three separately, and if the declaration mainly changes SELECTION rather
# than conditional adherence, that must be reported as such rather than as a
# reduction in authority failure.
#
# NO ENFORCEMENT IN THIS CELL. Authorization is classified on a discarded deep
# copy and recorded; nothing is blocked. attempted / sent / committed are
# recorded separately and, in an unenforced cell, coincide by construction —
# which is the point: nothing contains these commitments. Containment is
# P3-B's question, already answered.
#
# SIMULATED PASSPORT PRIMITIVE INTERFACE BASED ON CURRENT DESIGN MATERIALS.
# Not deployed Passport functionality.

import hashlib
import pathlib

from agents import parse_action

BASE = pathlib.Path(__file__).resolve().parent

ENFORCEMENT_ACTIVE = False          # in every arm, by construction
MAX_ATTEMPTS_PER_TURN = 1           # frozen condition B: one attempt per turn

COMMITMENT_PATHS = ("counter", "accept")
NON_COMMITTING_ACTIONS = ("walk_away",)


class Arm:
    def __init__(self, name, seller_prompt_file, commitment_semantics_declared):
        self.name = name
        self.seller_prompt_file = seller_prompt_file
        self.commitment_semantics_declared = commitment_semantics_declared
        self.enforcement_active = ENFORCEMENT_ACTIVE
        self.enforcement_announced = False

    def seller_prompt(self):
        return (BASE / "prompts" / self.seller_prompt_file).read_text(
            encoding="utf-8")

    def seller_prompt_sha16(self):
        return hashlib.sha256(
            (BASE / "prompts" / self.seller_prompt_file).read_bytes()
        ).hexdigest()[:16]

    # the action space is the FROZEN one in both arms: counter / accept /
    # walk_away. no arm adds, removes or renames an action.
    def parse(self, text):
        return parse_action(text)

    def as_dict(self):
        return {
            "arm": self.name,
            "seller_prompt_file": self.seller_prompt_file,
            "seller_prompt_sha16": self.seller_prompt_sha16(),
            "commitment_semantics_declared": self.commitment_semantics_declared,
            "enforcement_active": self.enforcement_active,
            "enforcement_announced": self.enforcement_announced,
            "action_space": ["counter", "accept", "walk_away"],
            "commitment_paths": list(COMMITMENT_PATHS),
            "max_attempts_per_turn": MAX_ATTEMPTS_PER_TURN,
        }


ARMS = {
    "A-both": Arm("A-both", "seller_system.txt", False),
    "A-declared": Arm("A-declared", "seller_system_declared.txt", True),
}
ARM_ORDER = ("A-both", "A-declared")

assert len(ARMS) == 2
assert {a.enforcement_active for a in ARMS.values()} == {False}
assert ARMS["A-both"].seller_prompt_sha16() == "d4005aaea3b9b780"
