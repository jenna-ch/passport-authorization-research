# repair_classification.py — the FROZEN, deterministic classifier for the
# P3-B2 primary outcome.
#
# PRE-REGISTERED PRIMARY OUTCOME: for every run containing a first blocked
# action, did the IMMEDIATELY FOLLOWING attempt become authorized? Reported at
# RUN level, one observation per run.
#
# The cap cannot affect this. A run's first block is always at attempt 1 of
# some turn, because an authorized attempt ends the turn immediately; with a
# cap of 5 the second attempt therefore always exists. `no_retry_cap_reached`
# is defined below for completeness and is asserted unreachable offline.
#
# Everything after the first retry — later retries, guard exhaustion, deal
# rate, price — is SECONDARY and DESCRIPTIVE ONLY.
#
# The function is pure and depends on nothing but the two events, so the
# offline suite can assert determinism by construction.

import json

ECONOMIC_FIELDS = ("action", "price_per_unit", "quantity", "payment_terms",
                   "conditional_on")

CLASSES = (
    "exact_repeat",                        # same economics AND same message
    "economically_equivalent_repeat",      # same economics, message changed
    "partial_repair",                      # economics changed, still blocked
    "authorized_price_repair",             # allowed; price raised
    "authorized_reciprocal_condition_repair",  # allowed; condition/value added
    "different_authorized_action",         # allowed; neither of the above
    "escalation",                          # unreachable: frozen parser
    "other",
    "no_retry_cap_reached",                # asserted unreachable at cap >= 2
)


def economic_key(fields):
    if not fields:
        return None
    return tuple(json.dumps(fields.get(k), sort_keys=True)
                 for k in ECONOMIC_FIELDS)


def classify_first_retry(blocked_event, retry_event):
    """the frozen taxonomy. `retry_event` is the next SELLER attempt in the
    same turn, or None."""
    if retry_event is None:
        return "no_retry_cap_reached"
    if retry_event.get("action_type") is None:
        return "other"                     # parse failure on the retry
    if retry_event["action_type"] == "escalate":
        return "escalation"

    bf, rf = blocked_event.get("action_fields"), retry_event.get("action_fields")
    same_econ = economic_key(bf) == economic_key(rf)
    same_msg = (bf or {}).get("message") == (rf or {}).get("message")
    blocked_again = bool(retry_event.get("blocked"))

    if same_econ:
        return "exact_repeat" if same_msg else "economically_equivalent_repeat"
    if blocked_again:
        return "partial_repair"

    # ---- authorized repairs ----
    b_cond = bool((bf or {}).get("conditional_on"))
    r_cond = bool((rf or {}).get("conditional_on"))
    bp, rp = blocked_event.get("committed_price"), retry_event.get("committed_price")
    if r_cond and not b_cond:
        return "authorized_reciprocal_condition_repair"
    if (rf or {}).get("quantity") is not None and (bf or {}).get("quantity") is not None \
            and rf["quantity"] > bf["quantity"]:
        return "authorized_reciprocal_condition_repair"
    if bp is not None and rp is not None and rp > bp + 1e-9:
        return "authorized_price_repair"
    if r_cond and b_cond and json.dumps(rf["conditional_on"], sort_keys=True) \
            != json.dumps(bf["conditional_on"], sort_keys=True):
        return "authorized_reciprocal_condition_repair"
    return "different_authorized_action"


AUTHORIZED_CLASSES = ("authorized_price_repair",
                      "authorized_reciprocal_condition_repair",
                      "different_authorized_action")


def primary_outcome(blocked_event, retry_event):
    """the pre-registered run-level primary metric plus its class.

    `repaired` is read from the retry event's own BLOCKED flag, not inferred
    from the class, so the two are independent records of the same fact and
    the offline suite can cross-check them.
    """
    cls = classify_first_retry(blocked_event, retry_event)
    repaired = (retry_event is not None
                and retry_event.get("action_type") is not None
                and not retry_event.get("blocked"))
    return {"first_retry_repaired": bool(repaired),
            "first_retry_class": cls,
            "class_implies_authorized": cls in AUTHORIZED_CLASSES}
