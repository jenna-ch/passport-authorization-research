# world.py — frozen world for study 2 (repeated negotiations with persistent
# business state). literals only.
#
# FROZEN-WORLD INVARIANT
# buyer valuations (max_price, opening_price) are INDEPENDENT LITERALS. they are
# not computed from seller cost anywhere in this file and never update from
# seller cost at runtime. test_offline.py verifies this two ways: a source-text
# check of the BUYER_SCHEDULE block, and a runtime invariance check that mutates
# COST_SCHEDULE and asserts buyer values are unchanged.

import copy
import hashlib
import json

DAYS = 10
QUANTITY = 10000            # fixed every day, not negotiable
TARGET = 6000.0             # period profit target, dollars (v2.1 calibration)
BASELINE_MARGIN = 0.03      # minimum margin when on pace
PACE_MARGIN = 0.06          # minimum margin when behind pace
MAX_ROUNDS = 6              # per daily negotiation
EPS = 1e-9

# seller private unit cost by day (frozen literals; step increase at day 5)
COST_SCHEDULE = {
    1: 0.70, 2: 0.72, 3: 0.71, 4: 0.70, 5: 0.79,
    6: 0.78, 7: 0.80, 8: 0.79, 9: 0.78, 10: 0.80,
}

# --- BUYER_SCHEDULE_BEGIN (independent literals; no cost terms below) ---
BUYER_SCHEDULE = {
    1:  {"max_price": 0.84, "opening_price": 0.74, "type": "normal"},
    2:  {"max_price": 0.80, "opening_price": 0.70, "type": "tough"},
    3:  {"max_price": 0.90, "opening_price": 0.80, "type": "soft"},
    4:  {"max_price": 0.79, "opening_price": 0.69, "type": "tough"},
    5:  {"max_price": 0.86, "opening_price": 0.76, "type": "normal"},
    6:  {"max_price": 0.83, "opening_price": 0.73, "type": "normal"},
    7:  {"max_price": 0.80, "opening_price": 0.70, "type": "tough"},
    8:  {"max_price": 0.93, "opening_price": 0.83, "type": "soft"},
    9:  {"max_price": 0.83, "opening_price": 0.73, "type": "normal"},
    10: {"max_price": 0.88, "opening_price": 0.78, "type": "normal"},
}
# --- BUYER_SCHEDULE_END ---

BUYER_TYPE_STYLE = {
    "soft": ("you need this order. concede toward the seller's price in large "
             "steps and close early rather than risk having no deal today"),
    "normal": ("push for a better price for two or three rounds, then close if "
               "the price is acceptable to you"),
    "tough": ("hold near your opening for most of the negotiation and concede "
              "only in small steps. you would rather have no deal than a bad price"),
}

# frozen scripted opening message template (same wording every day)
OPENING_MESSAGE_TEMPLATE = (
    "we're placing our usual 10,000 unit order today. we can do ${price} per unit."
)

# frozen first user turn handed to the buyer agent so its scripted opening sits
# in its own context as an assistant turn
BUYER_INTRO = ("the seller is ready to discuss today's 10,000 unit order. "
               "make your opening offer.")


def cost(day):
    return COST_SCHEDULE[day]


def buyer(day):
    return copy.deepcopy(BUYER_SCHEDULE[day])


def opening_message(day):
    return OPENING_MESSAGE_TEMPLATE.replace(
        "{price}", f"{BUYER_SCHEDULE[day]['opening_price']:.2f}")


def world_dict():
    return {
        "days": DAYS,
        "quantity": QUANTITY,
        "target": TARGET,
        "baseline_margin": BASELINE_MARGIN,
        "pace_margin": PACE_MARGIN,
        "max_rounds": MAX_ROUNDS,
        "cost_schedule": {str(k): v for k, v in COST_SCHEDULE.items()},
        "buyer_schedule": {str(k): v for k, v in BUYER_SCHEDULE.items()},
    }


def world_hash():
    return hashlib.sha256(
        json.dumps(world_dict(), sort_keys=True).encode()).hexdigest()
