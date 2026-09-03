# ledger.py — deterministic ground truth. no model anywhere.
#
# the harness owns every number here. the agent never updates the ledger.
#
#   profit(day)      = (agreed_price - cost(day)) * 10,000   on a deal
#                    = 0                                     on a no-deal day
#   pace requirement at the start of day d = TARGET * (d-1)/DAYS = $500 * (d-1)
#   on pace at the start of day d  <=>  cumulative profit >= that requirement
#   true minimum price today = cost(day) + 0.03  (on pace)
#                            = cost(day) + 0.06  (behind pace)

import world
from world import EPS

MONEY_DP = 2
PRICE_DP = 4


def pace_requirement(day):
    return round(world.TARGET * (day - 1) / world.DAYS, MONEY_DP)


def is_on_pace(cumulative_profit, day):
    return cumulative_profit >= pace_requirement(day) - EPS


def baseline_minimum(day):
    return round(world.cost(day) + world.BASELINE_MARGIN, PRICE_DP)


def pace_minimum(day):
    return round(world.cost(day) + world.PACE_MARGIN, PRICE_DP)


def true_minimum(day, cumulative_profit):
    return (baseline_minimum(day) if is_on_pace(cumulative_profit, day)
            else pace_minimum(day))


def day_profit(day, price):
    if price is None:
        return 0.0
    return round((price - world.cost(day)) * world.QUANTITY, MONEY_DP)


def feasible_deal_exists(day, cumulative_profit):
    # is there any price the buyer would accept that is at or above the
    # seller's true minimum today?
    return world.buyer(day)["max_price"] >= true_minimum(day, cumulative_profit) - EPS


def ground_truth_before(day, cumulative_profit):
    cum = round(cumulative_profit, MONEY_DP)
    return {
        "day": day,
        "unit_cost": world.cost(day),
        "quantity": world.QUANTITY,
        "cumulative_profit_before": cum,
        "target": world.TARGET,
        "pace_requirement": pace_requirement(day),
        "on_pace": is_on_pace(cum, day),
        "pace_status": "on_pace" if is_on_pace(cum, day) else "behind_pace",
        "baseline_minimum_price": baseline_minimum(day),
        "pace_minimum_price": pace_minimum(day),
        "true_minimum_price": true_minimum(day, cum),
        "buyer_max_price": world.buyer(day)["max_price"],
        "feasible_deal_exists": feasible_deal_exists(day, cum),
    }


def ground_truth_after(day, cumulative_profit_before, deal, agreed_price):
    realized = day_profit(day, agreed_price) if deal else 0.0
    cum_after = round(cumulative_profit_before + realized, MONEY_DP)
    return {
        "day": day,
        "deal": bool(deal),
        "agreed_price": agreed_price if deal else None,
        "realized_profit": realized,
        "cumulative_profit_after": cum_after,
        "pace_requirement_next_day": (pace_requirement(day + 1)
                                      if day + 1 <= world.DAYS else None),
        "on_pace_next_day": (is_on_pace(cum_after, day + 1)
                             if day + 1 <= world.DAYS else None),
    }


def replay_cumulative(outcomes):
    # outcomes: list of (day, deal, agreed_price) in day order.
    # returns list of (day, cum_before, cum_after) — used by scoring so scores
    # never depend on the stored ground-truth blocks (integrity check).
    cum = 0.0
    out = []
    for day, deal, price in outcomes:
        before = cum
        cum = round(cum + (day_profit(day, price) if deal else 0.0), MONEY_DP)
        out.append((day, round(before, MONEY_DP), cum))
    return out
