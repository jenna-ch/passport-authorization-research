# agents_p3d2.py — the ONE addition P3-D2 makes to the frozen Study 3 action
# space: a structured `ack_mandate` control value.
#
# WHY IT IS ADDED IN ALL THREE ARMS.
# D2-ack's mechanism is a control-plane gate that will not relay a
# consequential action until the active mandate version has been acknowledged.
# The acknowledgement therefore has to be an available action in that arm. If
# it were available ONLY there, the three arms would differ in ACTION SPACE as
# well as in mechanism, and the contrast would be confounded. So the schema
# extension is delivered to the buyer in EVERY arm, byte-identical, at exactly
# the same point in the episode (immediately after the principal update), and
# only the GATE differs.
#
# The honest cost of that choice is recorded in the design record: D2-prompt
# is therefore not a pure "message only, no version vocabulary" baseline. It
# is a baseline in which the version vocabulary exists and nothing is exposed
# or gated. The comparison is clean; the baseline is not a general base rate.
#
# THE FROZEN PARSER IS NOT MODIFIED. frozen/agents.py is byte-identical to
# 05_optional_agreement_read/agents.py. This module wraps it: an `ack_mandate` block is
# handled here, and everything else is delegated to the frozen parse_turn
# unchanged, so a negotiation action is parsed by exactly the frozen code.

import json
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "frozen"))

import agents as frozen_agents          # frozen, byte-identical
from agents import Agent, parse_turn as frozen_parse_turn   # noqa: F401

ACK_CONTROL = "ack_mandate"
CONTROL_VALUES_P3D2 = frozen_agents.CONTROL_VALUES + (ACK_CONTROL,)


def _control_of(text):
    """peek at the control field without committing to either parser."""
    raw = frozen_agents._last_json_block(text)
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj.get("control") if isinstance(obj, dict) else None


def parse_turn(text):
    """frozen parsing, plus ack_mandate.

    An ack_mandate action carries no package and sends nothing. Its
    `mandate_version` must be an integer — a missing or non-integer version is
    a parse error rather than a silently accepted acknowledgement, because the
    control plane validates the CLAIMED version against its own record.
    """
    if _control_of(text) != ACK_CONTROL:
        return frozen_parse_turn(text)

    obj = json.loads(frozen_agents._last_json_block(text))
    act = obj.get("act")
    if not isinstance(act, str) or not act.strip():
        return None, ("act must be a non-empty string describing what you are "
                      "doing")
    ver = obj.get("mandate_version")
    if isinstance(ver, bool) or not isinstance(ver, int):
        return None, ('an ack_mandate action must include a top-level '
                      '"mandate_version" integer')
    return {
        "act": act,
        "control": ACK_CONTROL,
        "packages": [],
        "packages_raw": [],
        "terms_touched": [],
        # nothing is delivered to the counterparty by an acknowledgement.
        "message": "",
        "mandate_version_claimed": ver,
    }, None


def is_consequential(parsed):
    """could this action FORM OR AMEND a commitment?

    Deterministic and economics-blind: it looks at the action's TYPE and at
    whether any term is declared, never at a price, a volume or an
    authorization verdict. This is what the D2-ack gate is allowed to see.
    """
    if parsed is None:
        return False
    if parsed["control"] == ACK_CONTROL:
        return False
    if parsed["control"] == "withdraw":
        return False
    if parsed["control"] == "propose_close":
        return True
    for pkg in parsed["packages"]:
        if any(pkg.get(f) is not None for f in
               ("volume_A", "volume_B", "price_A", "price_B",
                "priority_allocation")):
            return True
    return False
