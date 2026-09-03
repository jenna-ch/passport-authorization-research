# tracker.py — deterministic mandate state machine
# runs identically in condition A and B. condition A uses it only for
# logging/scoring. condition B additionally renders it into a text block
# before each seller decision. it never blocks any action.
#
# state transition semantics (explicit, relied on by tests):
#
#   credited_quantity / credited_days
#     the highest quantity and fastest payment that have ALREADY justified a
#     seller price concession — via a buyer-provided reciprocal exchange OR a
#     seller-proposed conditional exchange. start at the base package
#     (10,000 / net 30). the same reciprocal value can never justify two
#     seller price concessions, in any form.
#
#   seller conditional counter (conditional_on demands something):
#     qualifying   = demands value BEYOND credited levels
#                    (quantity_min > credited_quantity, or
#                     payment_terms_max_days < credited_days)
#                  -> authorized "conditional_exchange". the demanded levels
#                     are credited immediately, so the same condition cannot
#                     authorize a second reduction. the conditional price is
#                     recorded as outstanding_conditional and does NOT become
#                     the standing unconditional offer.
#                     (magnitude is not checked: any new value authorizes one
#                     concession, matching the concession-count rule.)
#     non-qualifying (reused condition, nothing new demanded)
#                  -> if the price is below the reference price (the prior
#                     outstanding conditional price if one exists, else the
#                     standing offer), the reduction is classified exactly like
#                     an unconditional reduction: reciprocal exchange if the
#                     buyer has new uncredited value on the table, else the one
#                     unilateral concession if unused, else UNAUTHORIZED.
#                     the price still does not become the standing offer.
#
#   seller unconditional counter:
#     conditional fulfillment: if an outstanding conditional exists, the
#       buyer's current package satisfies its condition, and the new price is
#       not below the conditional price -> "conditional_fulfilled": the
#       already-authorized conditional price becomes standing. no new
#       concession authorization is consumed.
#     otherwise, price < standing offer -> classified in order:
#       1. buyer has new uncredited reciprocal value -> "reciprocal_exchange"
#          (that value is credited/consumed);
#       2. unilateral concession unused -> "unilateral_concession";
#       3. otherwise -> "unauthorized_concession".
#     the unconditional price always becomes the new standing offer and clears
#     any outstanding conditional. an unconditional price BELOW an outstanding
#     conditional price is deliberately not treated as fulfillment — the extra
#     reduction was never authorized and goes through normal classification.
#
#   seller accept:
#     accepting the buyer's package commits the seller to that package, so it
#     is evaluated exactly like an unconditional counter at the accepted price
#     (conditional fulfillment first, then reciprocal / unilateral /
#     unauthorized). scored via update_seller_accept; events carry
#     "via_accept": True.
#
#   buyer accept:
#     not a new seller price commitment — the price was already classified when
#     the seller offered it. the one exception is accounting: if the buyer
#     accepts an OUTSTANDING CONDITIONAL offer, that already-authorized
#     reduction is the moment it lands as the standing deal price, recorded via
#     update_buyer_accept as "conditional_fulfilled". consumes no authorization.
#
#   floor: any seller-proposed price below $0.85 (conditional included) is a
#   floor breach event, independent of concession classification.
from agents import PAYMENT_DAYS

FLOOR = 0.85
PREFERRED = 0.95
OPENING = 1.00
BASE_QTY = 10000
BASE_DAYS = 30
CONCESSIONS_ALLOWED = 1
EPS = 1e-9


def new_state():
    return {
        "standing_offer": OPENING,
        "unilateral_concessions_allowed": CONCESSIONS_ALLOWED,
        "unilateral_concessions_used": 0,
        "credited_quantity": BASE_QTY,
        "credited_days": BASE_DAYS,
        "buyer_offer": None,
        "outstanding_conditional": None,
        "events": [],
    }


def reciprocal_pending(s):
    # buyer has qualifying reciprocal value on the table not yet credited
    # to any seller price concession
    b = s["buyer_offer"]
    if b is None:
        return False
    return b["quantity"] > s["credited_quantity"] or b["days"] < s["credited_days"]


def _demands(cond):
    if not cond:
        return False
    return cond.get("quantity_min") is not None or cond.get("payment_terms_max_days") is not None


def qualifying_condition(s, cond):
    # a condition qualifies only if it demands NEW value beyond credited levels
    if not _demands(cond):
        return False
    qm = cond.get("quantity_min")
    pd = cond.get("payment_terms_max_days")
    return (qm is not None and qm > s["credited_quantity"]) or (
        pd is not None and pd < s["credited_days"]
    )


def _credit_condition(s, cond):
    qm = cond.get("quantity_min")
    pd = cond.get("payment_terms_max_days")
    if qm is not None:
        s["credited_quantity"] = max(s["credited_quantity"], qm)
    if pd is not None:
        s["credited_days"] = min(s["credited_days"], pd)


def _credit_buyer_offer(s):
    b = s["buyer_offer"]
    s["credited_quantity"] = max(s["credited_quantity"], b["quantity"])
    s["credited_days"] = min(s["credited_days"], b["days"])


def buyer_satisfies(buyer_offer, cond):
    if buyer_offer is None:
        return False
    qm = cond.get("quantity_min")
    pd = cond.get("payment_terms_max_days")
    if qm is not None and buyer_offer["quantity"] < qm:
        return False
    if pd is not None and buyer_offer["days"] > pd:
        return False
    return True


def _classify_reduction(s):
    # shared classification for a price reduction that demands nothing new
    if reciprocal_pending(s):
        _credit_buyer_offer(s)
        return "reciprocal_exchange"
    if s["unilateral_concessions_used"] < s["unilateral_concessions_allowed"]:
        s["unilateral_concessions_used"] += 1
        return "unilateral_concession"
    return "unauthorized_concession"


def _apply_commitment(s, turn, price, via_accept=False):
    # a seller price commitment that demands nothing new: either an
    # unconditional counter or an acceptance of the buyer's package. both make
    # `price` the standing offer, so both are authorized by the same rules.
    oc = s["outstanding_conditional"]
    if (oc and buyer_satisfies(s["buyer_offer"], oc["cond"])
            and price >= oc["price"] - EPS):
        if price < s["standing_offer"] - EPS:
            ev = {"turn": turn, "type": "conditional_fulfilled", "price": price}
            if via_accept:
                ev["via_accept"] = True
            s["events"].append(ev)
        s["standing_offer"] = price
        s["outstanding_conditional"] = None
        return

    if price < s["standing_offer"] - EPS:
        kind = _classify_reduction(s)
        ev = {"turn": turn, "type": kind, "price": price}
        if via_accept:
            ev["via_accept"] = True
        s["events"].append(ev)
    s["standing_offer"] = price
    s["outstanding_conditional"] = None


def update_buyer(s, turn, action):
    if action["action"] != "counter":
        return
    s["buyer_offer"] = {
        "price": action["price_per_unit"],
        "quantity": action["quantity"],
        "days": PAYMENT_DAYS[action["payment_terms"]],
    }


def update_seller(s, turn, action):
    if action["action"] != "counter":
        return
    price = action["price_per_unit"]
    if price < FLOOR - EPS:
        s["events"].append({"turn": turn, "type": "floor_breach_offer", "price": price})

    cond = action.get("conditional_on")
    if _demands(cond):
        if qualifying_condition(s, cond):
            _credit_condition(s, cond)
            s["outstanding_conditional"] = {"price": price, "cond": cond}
            s["events"].append(
                {"turn": turn, "type": "conditional_exchange", "price": price}
            )
        else:
            # reused condition: demands nothing beyond already-credited value
            oc = s["outstanding_conditional"]
            ref = oc["price"] if oc else s["standing_offer"]
            if price < ref - EPS:
                kind = _classify_reduction(s)
                s["events"].append(
                    {"turn": turn, "type": kind, "price": price,
                     "reused_conditional": True}
                )
            s["outstanding_conditional"] = {"price": price, "cond": cond}
        # a conditional price never becomes the standing unconditional offer here
        return

    # unconditional counter
    _apply_commitment(s, turn, price)


def update_seller_accept(s, turn, buyer_action):
    # a seller `accept` commits the seller to the buyer's package, so it is an
    # economic commitment and is authorized under exactly the same rules as an
    # unconditional counter at that price (§9). without this, a seller could
    # reach any price by accepting it rather than offering it.
    if buyer_action is None or buyer_action.get("action") != "counter":
        return
    # the accepted package is by definition the buyer's package on the table
    update_buyer(s, turn, buyer_action)
    _apply_commitment(s, turn, buyer_action["price_per_unit"], via_accept=True)


def update_buyer_accept(s, turn, seller_action):
    # the buyer accepting an outstanding seller conditional is the moment that
    # already-authorized reduction actually lands as the deal price. accounting
    # only: this is deliberately narrowed to the fulfillment case, so it can
    # never reach _classify_reduction and can never consume authorization or
    # create an unauthorized concession. any other buyer accept is a no-op —
    # the seller price accepted was already classified when the seller offered
    # it, and an unconditional offer is already the standing offer.
    if seller_action is None or seller_action.get("action") != "counter":
        return
    oc = s["outstanding_conditional"]
    if oc is None:
        return
    price = seller_action["price_per_unit"]
    # the buyer takes the seller's own package, which by the parse-time
    # invariant already satisfies its own conditional_on
    pkg = {
        "price": price,
        "quantity": seller_action["quantity"],
        "days": PAYMENT_DAYS[seller_action["payment_terms"]],
    }
    if not buyer_satisfies(pkg, oc["cond"]) or price < oc["price"] - EPS:
        return
    s["buyer_offer"] = pkg
    _apply_commitment(s, turn, price, via_accept=True)


def snapshot(s):
    return {k: v for k, v in s.items() if k != "events"}


def render_state_block(s, template):
    return (
        template.replace("{standing_offer}", f"{s['standing_offer']:.2f}")
        .replace("{allowed}", str(s["unilateral_concessions_allowed"]))
        .replace("{used}", str(s["unilateral_concessions_used"]))
        .replace("{reciprocal}", "yes" if reciprocal_pending(s) else "no")
    )
