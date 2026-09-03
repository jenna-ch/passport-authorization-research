"""
guard.py — Mandate + Commitment Guard, v1 (frozen design, approved before
implementation; see the design conversation for the full rule derivation).

A deterministic, non-LLM check that evaluates ONE proposed seller action
(`counter` or `accept`) against the seller principal's mandate state BEFORE
that action becomes the principal's economic commitment.

This module is a new product primitive. It does not import
01_delegated_authority/tracker.py — it is written independently — but it implements
the same mandate semantics that tracker.py used to score the frozen
experiment (one unilateral concession; further reductions require new
reciprocal value; a hard floor; conditional exchange and fulfillment as
separate, non-overlapping authorization pathways). See README.md for exactly
which frozen behaviors this restates and where it deliberately departs
(withholding vs. after-the-fact scoring).

Decision set (v1, frozen — do not add a fourth):
  ALLOW              — authorized under an existing mandate pathway.
  REQUIRES_NEW_VALUE — not currently authorized. No approval pathway exists
                        in v1; the only ways out are: the buyer supplies new
                        qualifying value, the seller holds, or the seller
                        walks away.
  BLOCK              — price below the hard floor. Never authorizable.

Commitment boundaries evaluated: `counter`, `accept`.
`walk_away` is not evaluated — it carries no price and creates no economic
commitment, so there is nothing for the guard to check.

Contract: on REQUIRES_NEW_VALUE or BLOCK, state_after == state_before,
field for field. The guard withholds; it never partially applies an action.
"""

import copy

EPS = 1e-9

DECISIONS = ("ALLOW", "REQUIRES_NEW_VALUE", "BLOCK")
BOUNDARY_ACTIONS = ("counter", "accept")


def new_state(hard_floor, unilateral_concessions_allowed, base_quantity, base_payment_days,
              seller_standing_offer):
    """Convenience constructor matching the input schema below. Not required —
    callers may build the dict directly."""
    return {
        "hard_floor": hard_floor,
        "unilateral_concessions_allowed": unilateral_concessions_allowed,
        "unilateral_concessions_used": 0,
        "seller_standing_offer": seller_standing_offer,
        "buyer_current_offer": None,  # {"price":.., "quantity":.., "days":..} or None
        "credited_quantity": base_quantity,
        "credited_payment_terms": base_payment_days,
        "outstanding_conditional": None,  # {"price":.., "cond":..} or None
    }


def _reference_price(state):
    oc = state.get("outstanding_conditional")
    return oc["price"] if oc else state["seller_standing_offer"]


def _demands(cond):
    if not cond:
        return False
    return cond.get("quantity_min") is not None or cond.get("payment_terms_max_days") is not None


def _qualifying_condition(state, cond):
    # a condition qualifies only if it demands value BEYOND what is already
    # credited — otherwise it is asking for something already paid for.
    if not _demands(cond):
        return False
    qm = cond.get("quantity_min")
    pd = cond.get("payment_terms_max_days")
    return (qm is not None and qm > state["credited_quantity"]) or (
        pd is not None and pd < state["credited_payment_terms"]
    )


def _reciprocal_pending(state):
    # does the buyer currently have qualifying value on the table that has
    # not yet been credited to any past price concession?
    b = state.get("buyer_current_offer")
    if not b:
        return False
    return b["quantity"] > state["credited_quantity"] or b["days"] < state["credited_payment_terms"]


def _buyer_satisfies(buyer_offer, cond):
    if buyer_offer is None:
        return False
    qm = cond.get("quantity_min")
    pd = cond.get("payment_terms_max_days")
    if qm is not None and buyer_offer["quantity"] < qm:
        return False
    if pd is not None and buyer_offer["days"] > pd:
        return False
    return True


def _result(decision, reason, state_before, state_after=None):
    return {
        "decision": decision,
        "reason": reason,
        "state_before": copy.deepcopy(state_before),
        "state_after": copy.deepcopy(state_after) if state_after is not None
                       else copy.deepcopy(state_before),
    }


def _commit_price(new_st, price, cond):
    # a price commitment lands either as a non-standing conditional offer, or
    # as the new standing offer (unconditional counter or accept) — these are
    # mutually exclusive outcomes of the SAME reduction.
    if cond is not None:
        new_st["outstanding_conditional"] = {"price": price, "cond": cond}
    else:
        new_st["seller_standing_offer"] = price
        new_st["outstanding_conditional"] = None


def _classify_reduction(state, proposed_action, reference, cond):
    """Shared classification for a price against `reference`, used for both
    unconditional commitments (cond=None) and reused/non-qualifying
    conditional counters (cond=the reused condition)."""
    price = proposed_action["price_per_unit"]
    action = proposed_action["action"]

    if price >= reference - EPS:
        return _result(
            "ALLOW",
            "No price reduction relative to the current standing offer; nothing to authorize.",
            state,
        )

    if _reciprocal_pending(state):
        new_st = copy.deepcopy(state)
        b = state["buyer_current_offer"]
        new_st["credited_quantity"] = max(new_st["credited_quantity"], b["quantity"])
        new_st["credited_payment_terms"] = min(new_st["credited_payment_terms"], b["days"])
        _commit_price(new_st, price, cond)
        return _result(
            "ALLOW",
            "The buyer's current offer includes new quantity or payment value not yet "
            "credited to a concession. This reduction is authorized against it; that "
            "value is credited now.",
            state,
            new_st,
        )

    if state["unilateral_concessions_used"] < state["unilateral_concessions_allowed"]:
        new_st = copy.deepcopy(state)
        new_st["unilateral_concessions_used"] += 1
        _commit_price(new_st, price, cond)
        return _result(
            "ALLOW",
            "Uses the mandate's one allowed unilateral price concession "
            f"({new_st['unilateral_concessions_used']} of "
            f"{new_st['unilateral_concessions_allowed']} now used).",
            state,
            new_st,
        )

    if action == "accept":
        reason = (
            "Accepting this offer would reduce the seller's committed price without "
            "new buyer value and after the unilateral concession has been used."
        )
    else:
        reason = (
            "This price is below the standing offer with no new buyer value on the "
            "table and the one unilateral concession already used."
        )
    return _result("REQUIRES_NEW_VALUE", reason, state)


def evaluate(state, proposed_action):
    """
    state: dict — see new_state() for the schema.
    proposed_action: {
      "action": "counter" | "accept",
      "price_per_unit": float,
      "quantity": int,
      "payment_terms": str,          # informational only, not evaluated here
      "conditional_on": {"quantity_min": int|None, "payment_terms_max_days": int|None} | None
    }
    Returns {decision, reason, state_before, state_after}.
    """
    action = proposed_action["action"]
    if action not in BOUNDARY_ACTIONS:
        raise ValueError(f"guard evaluates only {BOUNDARY_ACTIONS!r}; got {action!r}")

    price = proposed_action["price_per_unit"]

    # step 1 — hard floor. independent of action type or form; overrides
    # everything else. never authorizable, so state is never mutated here.
    if price < state["hard_floor"] - EPS:
        return _result(
            "BLOCK",
            f"This price (${price:.2f}) is below the mandate's hard floor "
            f"(${state['hard_floor']:.2f}/unit). Not permitted under any condition.",
            state,
        )

    cond = proposed_action.get("conditional_on") if action == "counter" else None

    # steps 2/3 — counter carrying a conditional demand
    if cond and _demands(cond):
        if _qualifying_condition(state, cond):
            new_st = copy.deepcopy(state)
            qm = cond.get("quantity_min")
            pd = cond.get("payment_terms_max_days")
            if qm is not None:
                new_st["credited_quantity"] = max(new_st["credited_quantity"], qm)
            if pd is not None:
                new_st["credited_payment_terms"] = min(new_st["credited_payment_terms"], pd)
            new_st["outstanding_conditional"] = {"price": price, "cond": cond}
            return _result(
                "ALLOW",
                "This conditional demands new value beyond what's already credited. "
                "Authorized as a conditional exchange — the demanded value is credited "
                "now and cannot authorize a second reduction.",
                state,
                new_st,
            )
        # non-qualifying / "reused" condition: demands nothing beyond credited
        # levels. classified exactly like an unconditional reduction against
        # the current reference price, but a conditional price never becomes
        # the standing unconditional offer.
        return _classify_reduction(state, proposed_action, _reference_price(state), cond)

    # step 4 — fulfillment of an outstanding conditional (counter or accept)
    oc = state.get("outstanding_conditional")
    buyer = state.get("buyer_current_offer")
    if oc and _buyer_satisfies(buyer, oc["cond"]) and price >= oc["price"] - EPS:
        new_st = copy.deepcopy(state)
        new_st["seller_standing_offer"] = price
        new_st["outstanding_conditional"] = None
        return _result(
            "ALLOW",
            "The buyer's current offer meets the condition on your earlier conditional "
            "offer. Committing here fulfills an already-authorized exchange and "
            "consumes no new authorization.",
            state,
            new_st,
        )

    # steps 2/5/6/7 — ordinary commitment: unconditional counter, or accept
    return _classify_reduction(state, proposed_action, state["seller_standing_offer"], None)
