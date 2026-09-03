# frozen_eligibility.py — the Study 1 validity block, TRANSCRIBED VERBATIM.
#
# WHY THIS FILE EXISTS. Phase 2 needs two denominators (see the design's
# dual-denominator rule). The frozen one must stay frozen, and "frozen" has to
# be provable rather than asserted. So the frozen computation lives here, in
# one function, copied line for line out of protocol.run_negotiation, and
# test_offline_c1.py replays every historical S1-A / S1-B run record through it
# and asserts it reproduces the stored validity values exactly.
#
# THE RULES BELOW ARE NOT MINE AND MUST NOT BE EDITED. the source is
# protocol.py (sha256[:16] = 304a2dd59e0c6c3b), which sits beside this file,
# byte-identical to the frozen baseline. if this function and that file ever
# disagree, this file is wrong.
#
# verbatim from protocol.run_negotiation:
#
#   scripted_turns = [a for a in actions
#                     if a["role"] == "buyer" and a["turn"] in SCRIPTED_BUYER_ROUNDS]
#   validity["scripted_buyer_ok"] = all(a["scripted"] for a in scripted_turns)
#
#   validity["full_pressure_exposure"] = any(
#       a["role"] == "seller" and a["turn"] == PRESSURE_ROUND_LAST
#       for a in actions)
#
#   validity["primary_analysis_eligible"] = (
#       validity["parse_ok"]
#       and validity["scripted_buyer_ok"]
#       and validity["full_pressure_exposure"])
#
# `actions` therefore means RELAYED / COMMITTED actions — in Study 1 every
# action was relayed, and in S1-G `actions` holds only relayed ones, which is
# exactly what preserves the original meaning.

from protocol import PRESSURE_ROUND_LAST, SCRIPTED_BUYER_ROUNDS

BASIS = "frozen_study1_relayed_seller_action"


def frozen_validity(actions, parse_ok):
    """the three frozen Study 1 validity values, computed by the frozen rules.

    returns {"scripted_buyer_ok", "full_pressure_exposure",
             "primary_analysis_eligible"}.
    """
    scripted_turns = [a for a in actions
                      if a["role"] == "buyer" and a["turn"] in SCRIPTED_BUYER_ROUNDS]
    scripted_buyer_ok = all(a["scripted"] for a in scripted_turns)

    full_pressure_exposure = any(
        a["role"] == "seller" and a["turn"] == PRESSURE_ROUND_LAST
        for a in actions)

    return {
        "scripted_buyer_ok": scripted_buyer_ok,
        "full_pressure_exposure": full_pressure_exposure,
        "primary_analysis_eligible": (parse_ok and scripted_buyer_ok
                                      and full_pressure_exposure),
    }
