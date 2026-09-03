# packages.py — five-variable package representation, partial specification,
# per-field provenance, multiple alternatives, and per-alternative annotation.
#
# SCOPE: descriptive only. every function here answers a PHYSICAL or
# PRIVATE-MANDATE question. none of them decides what the jointly authored
# agreement currently is, and none of them decides what happens to a
# communicated condition when its premise changes.

import world as w

FIELDS = ("volume_A", "volume_B", "price_A", "price_B", "priority_allocation")
CARRY_FIELDS = ("volume_A", "volume_B", "priority_allocation")


def empty():
    return {f: None for f in FIELDS}


def is_complete(pkg):
    return all(pkg.get(f) is not None for f in FIELDS)


def total_volume(pkg):
    a, b = pkg.get("volume_A"), pkg.get("volume_B")
    if a is None or b is None:
        return None
    return a + b


# ------------------------------------------------------------- provenance

def resolve(this_turn_pkg, carried):
    """fill unspecified carry-fields from the SAME agent's own most recent
    declaration. never merges the counterparty's view — a merged view is the
    object under study.

    carried: field -> (value, turn_index, ambiguous_bool)
    a field carried from a turn that declared SEVERAL alternatives is marked
    ambiguous rather than resolved: we do not guess which alternative the agent
    meant to carry forward.
    """
    resolved, sources = {}, {}
    for f in FIELDS:
        v = this_turn_pkg.get(f)
        if v is not None:
            resolved[f], sources[f] = v, "this_turn"
            continue
        if f in CARRY_FIELDS and f in carried and carried[f] is not None:
            val, turn, ambiguous = carried[f]
            if ambiguous:
                resolved[f], sources[f] = None, f"ambiguous_carry_from_turn_{turn}"
            else:
                resolved[f], sources[f] = val, f"carried_from_turn_{turn}"
            continue
        resolved[f], sources[f] = None, "unspecified"
    return resolved, sources


# ------------------------------------------- physical / mandate annotation

def annotate_package(pkg, spec_min):
    """descriptive annotation of ONE package (one alternative)."""
    vA, vB = pkg.get("volume_A"), pkg.get("volume_B")
    pri = pkg.get("priority_allocation")
    pA, pB = pkg.get("price_A"), pkg.get("price_B")
    total = total_volume(pkg)

    off_grid = [f for f in ("volume_A", "volume_B") 
                if pkg.get(f) is not None and not w.on_grid(f, pkg[f])]

    fA = w.seller_floor_a(vA, pri) if (vA is not None and pri is not None) else None
    fB = w.seller_floor_b(vB, pri) if (vB is not None and pri is not None) else None
    cA = w.buyer_ceiling_a(total, pri) if (total is not None and pri is not None) else None
    cB = w.buyer_ceiling_b(total, pri) if (total is not None and pri is not None) else None

    def verdict_floor(price, floor):
        if price is None or floor is None:
            return "uncomputable"
        return "inside" if price >= floor - w.CENT else "outside"

    def verdict_ceiling(price, ceil):
        if price is None or ceil is None:
            return "uncomputable"
        return "inside" if price <= ceil + w.CENT else "outside"

    return {
        "package": dict(pkg),
        "complete": is_complete(pkg),
        "off_grid_fields": off_grid,
        "total_volume": total,
        # ---- physical facts about the provider's plant. NOT agreement state.
        "within_line_a_capacity": (w.within_line_a_capacity(vA)
                                   if vA is not None else None),
        "provider_can_hold_reserve": (w.provider_can_hold_reserve(vA)
                                      if vA is not None else None),
        "priority_physically_deliverable": (
            None if (vA is None or pri is None)
            else (w.provider_can_hold_reserve(vA) if pri else True)),
        # ---- buyer's private hard specification
        "meets_buyer_spec_minimum": (w.meets_spec_minimum(vA, spec_min)
                                     if vA is not None else None),
        "spec_minimum_applied": spec_min,
        # ---- private mandate bounds
        "seller_floor_A": fA, "seller_floor_B": fB,
        "buyer_ceiling_A": cA, "buyer_ceiling_B": cB,
        "price_A_vs_seller_floor": verdict_floor(pA, fA),
        "price_B_vs_seller_floor": verdict_floor(pB, fB),
        "price_A_vs_buyer_ceiling": verdict_ceiling(pA, cA),
        "price_B_vs_buyer_ceiling": verdict_ceiling(pB, cB),
    }


# ------------------------------------- prose price -> alternative attachment

def attach_prose_price(value, annotated_alternatives):
    """attach a price found in prose to a declared alternative.

    exactly one match -> attached. more than one -> AMBIGUOUS, recorded as
    ambiguous rather than guessed. none -> unattached. this is the fix for the
    pilot-1 defect where every prose price was scored against a single carried
    package.
    """
    hits = []
    for i, a in enumerate(annotated_alternatives):
        p = a["package"]
        for field in ("price_A", "price_B"):
            if p.get(field) is not None and abs(p[field] - value) < 1e-9:
                hits.append({"alternative_index": i,
                             "label": p.get("label"), "field": field})
    if len(hits) == 1:
        return {"attachment": "attached", "matches": hits}
    if len(hits) > 1:
        return {"attachment": "ambiguous", "matches": hits}
    return {"attachment": "unattached", "matches": []}
