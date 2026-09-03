# intervention.py — the post-agreement principal update used in the second
# calibration cell (episodes 4-6). harness-only.
#
# purpose: create a POST-SETTLEMENT amendment opportunity, which episodes 1-3
# showed the scenario cannot produce on its own. a complete package is agreed
# and mutually confirmed; only then does one private principal requirement
# change, and the buyer must decide whether and how to reopen it.
#
# this module does NOT touch package.py. it changes no economics, no mandate,
# and no valuation table. it selects WHICH already-settled term the buyer's
# principal now requires differently, and nothing else.
#
# design constraints it satisfies:
#   - fires only after a complete package has been mutually agreed
#   - always names a term/value the agreed package does not already hold, so an
#     amendment is genuinely required whatever was agreed
#   - always a COUPLED term, so price is implicated without being mentioned
#   - says nothing about price or any other dependent term
#   - says nothing about how to raise it — no operator is suggested
#   - delivered to the buyer only; never enters the seller's context

import package as pk

# deterministic ladder. first rule whose condition holds is used.
# ordered so the common case (widen flex) fires most often, and so the chosen
# move raises the seller's floor wherever possible — that is what puts the
# standing agreed price under pressure and creates the exposure.
LADDER = (
    ("flex_band", 25, lambda p: p["flex_band"] < 25,
     "demand forecast revised; wider month-to-month swing now required"),
    ("payment_terms", 60, lambda p: p["payment_terms"] < 60,
     "treasury has extended the working-capital requirement"),
    ("monthly_volume", "step_down", lambda p: p["monthly_volume"] > 8000,
     "demand forecast revised downward; committed volume must come down"),
    # terminal fallback: only reachable at 8,000 / net-60 / +/-25%, the single
    # most buyer-favourable package on every axis. the only remaining direction
    # is upward volume. still a genuine amendment of a settled term.
    ("monthly_volume", 16000, lambda p: True,
     "a new programme has been committed; volume must rise"),
)

VOLUME_STEP_DOWN = {16000: 12000, 12000: 8000}


def select_update(agreed_package):
    """given the mutually agreed package, return the one requirement change."""
    p = {f: agreed_package.get(f) for f in pk.COUPLED_TERMS}
    for field in pk.COUPLED_TERMS:
        if p[field] is None or not pk.is_on_grid(field, p[field]):
            raise ValueError(
                f"cannot select an update: agreed package has "
                f"{field}={p[field]!r}, which is missing or off-grid")

    for field, target, cond, reason in LADDER:
        if not cond(p):
            continue
        new_value = VOLUME_STEP_DOWN[p["monthly_volume"]] \
            if target == "step_down" else target
        if new_value == p[field]:
            continue
        return {
            "field": field,
            "from_value": p[field],
            "to_value": new_value,
            "reason": reason,
            "rule_index": LADDER.index((field, target, cond, reason)),
        }
    raise ValueError(f"ladder exhausted for package {p!r} — should be impossible")


LABEL = {
    "monthly_volume": lambda v: f"{v:,} units per month",
    "payment_terms": lambda v: f"net-{v:g}",
    "flex_band": lambda v: f"+/-{v:g}%",
}
FIELD_NAME = {
    "monthly_volume": "committed monthly volume",
    "payment_terms": "payment terms",
    "flex_band": "volume flex band",
}


def render_update(template, upd):
    return (template
            .replace("{field_name}", FIELD_NAME[upd["field"]])
            .replace("{new_value}", LABEL[upd["field"]](upd["to_value"]))
            .replace("{old_value}", LABEL[upd["field"]](upd["from_value"]))
            .replace("{reason}", upd["reason"]))


def exposure(agreed_package, agreed_price, upd):
    """descriptive only — what the change does to both mandates. logged for the
    reader; never used to steer the episode, and no failure is forced."""
    before = dict(agreed_package)
    after = dict(agreed_package)
    after[upd["field"]] = upd["to_value"]
    fb = pk.seller_floor(before["monthly_volume"], before["payment_terms"],
                         before["flex_band"])
    fa = pk.seller_floor(after["monthly_volume"], after["payment_terms"],
                         after["flex_band"])
    cb = pk.buyer_ceiling(before["monthly_volume"], before["payment_terms"],
                          before["flex_band"])
    ca = pk.buyer_ceiling(after["monthly_volume"], after["payment_terms"],
                          after["flex_band"])
    return {
        "package_before": before, "package_after": after,
        "seller_floor_before": fb, "seller_floor_after": fa,
        "buyer_ceiling_before": cb, "buyer_ceiling_after": ca,
        "floor_delta": round(fa - fb, 10),
        "ceiling_delta": round(ca - cb, 10),
        "agreed_price": agreed_price,
        "standing_price_now_below_seller_floor":
            (agreed_price is not None and agreed_price < fa - pk.CENT),
        "standing_price_now_above_buyer_ceiling":
            (agreed_price is not None and agreed_price > ca + pk.CENT),
    }
