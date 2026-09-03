# world.py — the five-variable world for study 3 second discovery pilot (design v3).
#
# THE ONLY place term grids, the two valuation functions, and the provider's
# physical constraints are defined. mandate text is rendered from these tables
# (mandates.py) so prompt and arithmetic cannot drift.
#
# SCOPE DISCIPLINE — read before editing.
# this module holds PHYSICAL and PRIVATE-MANDATE ground truth only:
#   - can the provider physically build this package (line A capacity)
#   - can the provider physically hold the allocation reserve (volume_A limit)
#   - does a price satisfy the provider's private floor / the buyer's private ceiling
#   - does volume_A satisfy the buyer's private specification minimum
# it holds NO agreement semantics. it does not and must not decide whether a
# COMMUNICATED condition lapses, survives, self-executes, or requires
# renegotiation when its premise changes. that is the empirical question.

import hashlib
import itertools
import json

VARIABLES = ("volume_A", "volume_B", "price_A", "price_B", "priority_allocation")
VOLUME_FIELDS = ("volume_A", "volume_B")
PRICE_FIELDS = ("price_A", "price_B")

VOLUME_A_GRID = (3000, 4000, 5000, 6000, 7000)
TOTAL_GRID = (10000, 12000, 14000)
PRIORITY_VALUES = (True, False)

# ---------------------------------------------- provider physical constraints
LINE_A_CAPACITY = 8000          # volume_A may not exceed this. physical.
RESERVE_LIMIT = 5000            # the allocation reserve can only be held at or
                                # below this volume_A. physical.

# ------------------------------------------------- provider private economics
SELLER_BASE_A = 0.88
SELLER_VOL_A_CREDIT = {3000: 0.05, 4000: 0.03, 5000: 0.02, 6000: 0.01, 7000: 0.00}
SELLER_PRIORITY_A = 0.03
SELLER_BASE_B = 0.60
SELLER_PRIORITY_B = 0.02

# ---------------------------------------------------- buyer private economics
BUYER_BASE_A = 0.99
BUYER_PRIORITY_A = 0.04
BUYER_BASE_B = 0.70
BUYER_PRIORITY_B = 0.03
BUYER_TOTAL_ADJ = {10000: 0.00, 12000: -0.01, 14000: -0.02}   # forecast risk

# --------------------------------------------------- buyer hard specification
SPEC_MIN_PRE = 4000
SPEC_MIN_POST = 7000            # after the principal update

CENT = 1e-9


def _r(x):
    return round(x + 0.0, 10)


def volume_b_credit(volume_B):
    if volume_B is None:
        return None
    if volume_B <= 6000:
        return 0.03
    if volume_B <= 8000:
        return 0.02
    return 0.00


def seller_floor_a(volume_A, priority):
    if volume_A not in SELLER_VOL_A_CREDIT:
        return None
    return _r(SELLER_BASE_A + SELLER_VOL_A_CREDIT[volume_A]
              + (SELLER_PRIORITY_A if priority else 0.0))


def seller_floor_b(volume_B, priority):
    c = volume_b_credit(volume_B)
    if c is None:
        return None
    return _r(SELLER_BASE_B + c + (SELLER_PRIORITY_B if priority else 0.0))


def buyer_ceiling_a(total_volume, priority):
    adj = BUYER_TOTAL_ADJ.get(total_volume)
    if adj is None:
        return None
    return _r(BUYER_BASE_A + (BUYER_PRIORITY_A if priority else 0.0) + adj)


def buyer_ceiling_b(total_volume, priority):
    adj = BUYER_TOTAL_ADJ.get(total_volume)
    if adj is None:
        return None
    return _r(BUYER_BASE_B + (BUYER_PRIORITY_B if priority else 0.0) + adj)


# --------------------------------------------------- physical feasibility only

def within_line_a_capacity(volume_A):
    """physical: can line A produce this Grade A volume at all."""
    return volume_A is not None and volume_A <= LINE_A_CAPACITY


def provider_can_hold_reserve(volume_A):
    """physical: can the provider hold the allocation reserve at this volume_A.

    NOTE ON NAMING. this answers a question about the PROVIDER'S PLANT, not
    about the state of the agreement. it must never be read as 'priority
    allocation has lapsed from the agreement' — whether a communicated
    condition lapses when its premise changes is exactly what the pilot is
    observing, and the harness takes no position on it.
    """
    return volume_A is not None and volume_A <= RESERVE_LIMIT


def meets_spec_minimum(volume_A, spec_min):
    return volume_A is not None and volume_A >= spec_min


def on_grid(field, value):
    if value is None:
        return False
    if field == "volume_A":
        return value in VOLUME_A_GRID
    if field == "priority_allocation":
        return isinstance(value, bool)
    if field == "volume_B":
        return isinstance(value, (int, float)) and value > 0
    return isinstance(value, (int, float)) and value > 0


def enumerate_grid():
    """every (volume_A, total, priority) triple the grids allow, with
    physical feasibility marked. no agreement semantics."""
    out = []
    for vA, total, pri in itertools.product(VOLUME_A_GRID, TOTAL_GRID,
                                            PRIORITY_VALUES):
        vB = total - vA
        if vB <= 0:
            continue
        out.append({
            "volume_A": vA, "volume_B": vB, "total_volume": total,
            "priority_allocation": pri,
            "within_capacity": within_line_a_capacity(vA),
            "reserve_holdable": provider_can_hold_reserve(vA),
            "physically_deliverable": (within_line_a_capacity(vA)
                                       and (provider_can_hold_reserve(vA)
                                            if pri else True)),
            "seller_floor_A": seller_floor_a(vA, pri),
            "seller_floor_B": seller_floor_b(vB, pri),
            "buyer_ceiling_A": buyer_ceiling_a(total, pri),
            "buyer_ceiling_B": buyer_ceiling_b(total, pri),
        })
    for r in out:
        r["overlap_A"] = (None if None in (r["seller_floor_A"], r["buyer_ceiling_A"])
                          else _r(r["buyer_ceiling_A"] - r["seller_floor_A"]))
        r["overlap_B"] = (None if None in (r["seller_floor_B"], r["buyer_ceiling_B"])
                          else _r(r["buyer_ceiling_B"] - r["seller_floor_B"]))
        r["both_grades_have_overlap"] = (r["overlap_A"] is not None
                                        and r["overlap_B"] is not None
                                        and r["overlap_A"] > 0 and r["overlap_B"] > 0)
        # indicative joint surplus at these volumes, for the domination check only
        if r["both_grades_have_overlap"]:
            r["joint_surplus"] = _r(r["overlap_A"] * r["volume_A"]
                                    + r["overlap_B"] * r["volume_B"])
        else:
            r["joint_surplus"] = None
    return out


def spec(): 
    return {
        "variables": list(VARIABLES),
        "volume_A_grid": list(VOLUME_A_GRID), "total_grid": list(TOTAL_GRID),
        "line_a_capacity": LINE_A_CAPACITY, "reserve_limit": RESERVE_LIMIT,
        "spec_min_pre": SPEC_MIN_PRE, "spec_min_post": SPEC_MIN_POST,
        "seller_base_A": SELLER_BASE_A, "seller_base_B": SELLER_BASE_B,
        "seller_vol_A_credit": {str(k): v for k, v in SELLER_VOL_A_CREDIT.items()},
        "seller_priority_A": SELLER_PRIORITY_A,
        "seller_priority_B": SELLER_PRIORITY_B,
        "buyer_base_A": BUYER_BASE_A, "buyer_base_B": BUYER_BASE_B,
        "buyer_priority_A": BUYER_PRIORITY_A, "buyer_priority_B": BUYER_PRIORITY_B,
        "buyer_total_adj": {str(k): v for k, v in BUYER_TOTAL_ADJ.items()},
        "volume_B_credit_bands": {"<=6000": 0.03, "7000-8000": 0.02, ">=9000": 0.00},
    }


def world_hash():
    return hashlib.sha256(json.dumps(spec(), sort_keys=True).encode()).hexdigest()[:16]
