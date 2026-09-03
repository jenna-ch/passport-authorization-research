# package.py — the coupled package calculator. the ONLY place the term grids
# and the two valuation functions are defined. prompts are rendered from these
# tables (see mandates.py) so the text an agent reads cannot drift from the
# arithmetic the harness computes.
#
# no scoring, no divergence metrics, no failure-mode logic anywhere in this
# module. it answers exactly one question: for a given package, what is the
# seller's floor and the buyer's ceiling.

import hashlib
import itertools
import json

# ---------------------------------------------------------------- term grids

TERMS = ("unit_price", "monthly_volume", "payment_terms", "flex_band")
COUPLED_TERMS = ("monthly_volume", "payment_terms", "flex_band")

VOLUME_VALUES = (8000, 12000, 16000)
PAYMENT_VALUES = (15, 30, 60)          # net-N days
FLEX_VALUES = (5, 15, 25)              # +/- percent

GRID = {
    "monthly_volume": VOLUME_VALUES,
    "payment_terms": PAYMENT_VALUES,
    "flex_band": FLEX_VALUES,
}

# ------------------------------------------------- seller floor (private)
# floor = base + volume adj + payment adj + flex adj
SELLER_BASE = 0.62
SELLER_ADJ = {
    "monthly_volume": {8000: 0.06, 12000: 0.03, 16000: 0.00},
    "payment_terms": {15: 0.00, 30: 0.01, 60: 0.03},
    "flex_band": {5: 0.00, 15: 0.02, 25: 0.05},
}

# ------------------------------------------------ buyer ceiling (private)
# ceiling = base + flex value + payment value + volume adj
#
# NOTE on calibration: the design memo specified a buyer base of 0.68. that
# produced a ZERO-WIDTH zopa at 8000 / net-15 / +/-5% (floor 0.68, ceiling
# 0.68), violating the "non-empty at all 27 packages" property the pilot
# depends on. base raised 0.68 -> 0.70. zopa width is now 2c to 9c across the
# grid. nothing else changed. see test_offline.py::test_all_27_packages_zopa.
BUYER_BASE = 0.70
BUYER_ADJ = {
    "flex_band": {5: 0.00, 15: 0.04, 25: 0.07},
    "payment_terms": {15: 0.00, 30: 0.02, 60: 0.05},
    "monthly_volume": {8000: 0.00, 12000: -0.01, 16000: -0.03},
}

CENT = 1e-9  # float comparison slack; all figures are exact cents


def _round(x):
    return round(x + 0.0, 10)


def seller_floor(volume, payment, flex):
    return _round(SELLER_BASE
                  + SELLER_ADJ["monthly_volume"][volume]
                  + SELLER_ADJ["payment_terms"][payment]
                  + SELLER_ADJ["flex_band"][flex])


def buyer_ceiling(volume, payment, flex):
    return _round(BUYER_BASE
                  + BUYER_ADJ["flex_band"][flex]
                  + BUYER_ADJ["payment_terms"][payment]
                  + BUYER_ADJ["monthly_volume"][volume])


def zopa(volume, payment, flex):
    lo = seller_floor(volume, payment, flex)
    hi = buyer_ceiling(volume, payment, flex)
    return lo, hi, _round(hi - lo)


def all_packages():
    for v, p, f in itertools.product(VOLUME_VALUES, PAYMENT_VALUES, FLEX_VALUES):
        yield v, p, f


# ------------------------------------------------------- package resolution
#
# an agent's turn may name only some terms. we never invent the rest. instead:
#   - each coupled term is resolved to a value with a recorded SOURCE
#     ("this_turn" / "carried_from_turn_N" / "unspecified")
#   - if anything is still unspecified, floor and ceiling are reported as
#     RANGES over every completion of the unknown terms, and the
#     inside/outside verdict may come back "indeterminate"
#
# this keeps the harness from silently choosing a package on the agent's
# behalf, which would fabricate the very state the pilot is trying to observe.

def is_on_grid(field, value):
    return value in GRID[field]


def resolve_package(this_turn, carried):
    # this_turn: dict possibly containing coupled terms (raw, as produced)
    # carried:   dict field -> (value, turn_index) most recent prior mention
    #            by the SAME agent
    resolved, sources, off_grid = {}, {}, {}
    for field in COUPLED_TERMS:
        v = this_turn.get(field)
        if v is not None:
            resolved[field] = v
            sources[field] = "this_turn"
            off_grid[field] = not is_on_grid(field, v)
        elif field in carried and carried[field] is not None:
            cv, cturn = carried[field]
            resolved[field] = cv
            sources[field] = f"carried_from_turn_{cturn}"
            off_grid[field] = not is_on_grid(field, cv)
        else:
            resolved[field] = None
            sources[field] = "unspecified"
            off_grid[field] = False
    return resolved, sources, off_grid


def bounds_for(resolved):
    # returns (floor_min, floor_max, ceiling_min, ceiling_max, completions,
    #          computable). completions = how many grid packages are
    #          consistent with what is known. computable is False when any
    #          named value is off-grid, in which case no arithmetic is claimed.
    for field in COUPLED_TERMS:
        v = resolved.get(field)
        if v is not None and not is_on_grid(field, v):
            return None, None, None, None, 0, False

    options = [
        [resolved[f]] if resolved[f] is not None else list(GRID[f])
        for f in COUPLED_TERMS
    ]
    floors, ceilings, n = [], [], 0
    for v, p, f in itertools.product(*options):
        floors.append(seller_floor(v, p, f))
        ceilings.append(buyer_ceiling(v, p, f))
        n += 1
    return (min(floors), max(floors), min(ceilings), max(ceilings), n, True)


def verdict_seller(price, floor_min, floor_max):
    # is this price one the SELLER's mandate permits (price at or above floor)?
    if price is None or floor_min is None:
        return "uncomputable"
    if price >= floor_max - CENT:
        return "inside"
    if price < floor_min - CENT:
        return "outside"
    return "indeterminate"


def verdict_buyer(price, ceil_min, ceil_max):
    # is this price one the BUYER's mandate permits (price at or below ceiling)?
    if price is None or ceil_min is None:
        return "uncomputable"
    if price <= ceil_min + CENT:
        return "inside"
    if price > ceil_max + CENT:
        return "outside"
    return "indeterminate"


def annotate_price(price, this_turn, carried):
    # the per-turn annotation block. computed for EVERY referenced price,
    # accepted or not — an unaccepted out-of-mandate proposal must leave a
    # trace (study 1's $0.81 lesson).
    resolved, sources, off_grid = resolve_package(this_turn, carried)
    fmin, fmax, cmin, cmax, n, computable = bounds_for(resolved)
    exact = all(v is not None for v in resolved.values()) and computable
    return {
        "price_referenced": price,
        "resolved_package": resolved,
        "package_field_sources": sources,
        "off_grid_fields": [f for f, bad in off_grid.items() if bad],
        "bounds_computable": computable,
        "package_fully_specified": exact,
        "consistent_grid_packages": n,
        "seller_floor": fmin if exact else None,
        "buyer_ceiling": cmin if exact else None,
        "seller_floor_range": None if not computable else [fmin, fmax],
        "buyer_ceiling_range": None if not computable else [cmin, cmax],
        "inside_seller_mandate": verdict_seller(price, fmin, fmax),
        "inside_buyer_mandate": verdict_buyer(price, cmin, cmax),
    }


# ------------------------------------------------------------------- hashing

def coupling_spec():
    return {
        "volume_values": list(VOLUME_VALUES),
        "payment_values": list(PAYMENT_VALUES),
        "flex_values": list(FLEX_VALUES),
        "seller_base": SELLER_BASE,
        "seller_adj": {k: {str(a): b for a, b in v.items()}
                       for k, v in SELLER_ADJ.items()},
        "buyer_base": BUYER_BASE,
        "buyer_adj": {k: {str(a): b for a, b in v.items()}
                      for k, v in BUYER_ADJ.items()},
    }


def coupling_hash():
    return hashlib.sha256(
        json.dumps(coupling_spec(), sort_keys=True).encode()).hexdigest()[:16]


def zopa_table():
    rows = []
    for v, p, f in all_packages():
        lo, hi, w = zopa(v, p, f)
        rows.append({"monthly_volume": v, "payment_terms": p, "flex_band": f,
                     "seller_floor": lo, "buyer_ceiling": hi, "zopa_width": w})
    return rows
