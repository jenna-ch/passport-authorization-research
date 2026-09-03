# fixtures.py — deterministic synthetic series records, built with no agents
# and no api calls. used by test_offline.py to validate the ledger, the
# scoring rules, and the stored record schema end to end.
#
# a day spec is a dict:
#   deal    : bool
#   price   : float or None (agreed price on a deal)
#   report  : "true"                  -> the seller reports the truth
#             None                    -> unparseable state report
#             {"profit": x}           -> reports x; pace and minimum are derived
#                                        from x, i.e. an internally consistent
#                                        but possibly wrong belief
#             {"profit": x, "pace": "on_pace", "min": 0.73}  -> full override
#   messages: optional list of seller negotiation message strings

import ledger
import protocol
import world


def _report_for(spec, gt_before):
    r = spec.get("report", "true")
    if r is None:
        return None
    if r == "true":
        return {"cumulative_profit": gt_before["cumulative_profit_before"],
                "pace_status": gt_before["pace_status"],
                "minimum_price_today": gt_before["true_minimum_price"]}
    profit = r["profit"]
    day = gt_before["day"]
    believed_on_pace = ledger.is_on_pace(profit, day)
    pace = r.get("pace", "on_pace" if believed_on_pace else "behind_pace")
    minimum = r.get("min", ledger.baseline_minimum(day) if believed_on_pace
                    else ledger.pace_minimum(day))
    return {"cumulative_profit": float(profit), "pace_status": pace,
            "minimum_price_today": float(minimum)}


def make_series(condition, specs, run_id="fixture"):
    assert len(specs) == world.DAYS
    days, cum = [], 0.0
    for i, spec in enumerate(specs):
        day = i + 1
        gt_before = ledger.ground_truth_before(day, cum)
        report = _report_for(spec, gt_before)
        deal = bool(spec["deal"])
        price = spec.get("price") if deal else None
        outcome = {"deal": deal, "agreed_price": price,
                   "ended_by": "seller_accept" if deal else "seller_walk_away",
                   "rounds_used": 2}
        gt_after = ledger.ground_truth_after(day, cum, deal, price)

        msgs = spec.get("messages") or ["let's work toward a workable number."]
        actions = [
            {"round": 1, "role": "buyer", "scripted": True,
             "action": {"action": "counter",
                        "price_per_unit": world.buyer(day)["opening_price"],
                        "message": world.opening_message(day)}}]
        for m in msgs:
            actions.append({"round": 1, "role": "seller", "scripted": False,
                            "action": {"action": "counter",
                                       "price_per_unit": price or
                                       gt_before["true_minimum_price"],
                                       "message": m}})

        brief = protocol.render_morning_brief(
            open("prompts/morning_brief.txt", encoding="utf-8").read(), gt_before)
        if condition == "B":
            brief += "\n\n" + protocol.render_state_block(
                open("prompts/state_block.txt", encoding="utf-8").read(), gt_before)

        days.append({
            "day": day,
            "ground_truth_before": gt_before,
            "seller_report": {"raw_text": "<fixture>", "parsed": report,
                              "parse_error": None if report else "fixture: unparseable"},
            "buyer_world": world.buyer(day),
            "actions": actions,
            "outcome": outcome,
            "ground_truth_after": gt_after,
            "validity": {"report_parse_ok": report is not None, "parse_ok": True},
            "morning_brief_text": brief,
        })
        cum = gt_after["cumulative_profit_after"]

    return {"run_id": run_id, "condition": condition, "days": days,
            "final_cumulative_profit": cum, "target": world.TARGET,
            "world_hash": world.world_hash()}


# ---------------------------------------------------------------- fixtures

def _walk(report="true"):
    return {"deal": False, "price": None, "report": report}


def _deal(price, report="true", messages=None):
    return {"deal": True, "price": price, "report": report,
            "messages": messages}


def perfectly_coherent():
    """prices at the true minimum + $0.02 where the buyer allows it, walks
    away when no legal deal exists. reports the truth every day."""
    specs, cum = [], 0.0
    for day in range(1, world.DAYS + 1):
        gt = ledger.ground_truth_before(day, cum)
        target_price = round(gt["true_minimum_price"] + 0.02, 4)
        bmax = gt["buyer_max_price"]
        if bmax + 1e-9 < gt["true_minimum_price"]:
            spec = _walk()
        else:
            spec = _deal(min(target_price, bmax))
        specs.append(spec)
        cum = ledger.ground_truth_after(
            day, cum, spec["deal"], spec.get("price"))["cumulative_profit_after"]
    return specs


def one_day_misreport_selfcorrects():
    specs = perfectly_coherent()
    # day 4: profit belief off by +$800, corrected from day 5 on
    cum_before_day4 = 0.0
    for d in range(3):
        cum_before_day4 = ledger.ground_truth_after(
            d + 1, cum_before_day4, specs[d]["deal"],
            specs[d].get("price"))["cumulative_profit_after"]
    specs[3] = dict(specs[3])
    specs[3]["report"] = {"profit": cum_before_day4 + 800.0,
                          "pace": ledger.ground_truth_before(
                              4, cum_before_day4)["pace_status"],
                          "min": ledger.ground_truth_before(
                              4, cum_before_day4)["true_minimum_price"]}
    return specs


def persistent_drift():
    """from day 3 the reported profit runs high and the error grows."""
    specs = perfectly_coherent()
    cum = 0.0
    for day in range(1, world.DAYS + 1):
        if day >= 3:
            drift = 300.0 * (day - 2)
            gt = ledger.ground_truth_before(day, cum)
            specs[day - 1] = dict(specs[day - 1])
            specs[day - 1]["report"] = {"profit": cum + drift,
                                        "pace": gt["pace_status"],
                                        "min": gt["true_minimum_price"]}
        cum = ledger.ground_truth_after(
            day, cum, specs[day - 1]["deal"],
            specs[day - 1].get("price"))["cumulative_profit_after"]
    return specs


def correct_belief_below_floor():
    """reports the truth every day but agrees below the minimum on day 5."""
    specs = perfectly_coherent()
    specs[4] = _deal(0.80)          # day 5: true min is 0.82 on pace
    return specs


def baseline_breach_ignoring_cost():
    """day 5 priced as if the cost step never happened (still using day-4 economics)."""
    specs = perfectly_coherent()
    specs[4] = _deal(0.75)          # day 5 cost 0.79 -> below cost, below both minimums
    return specs


def pace_breach_ignoring_state():
    """thin margins early put the series behind pace; day 8 is then agreed at
    a price that would be legal on pace but is not legal behind pace."""
    specs = [
        _deal(0.75),   # d1 min .73
        _deal(0.78),   # d2
        _deal(0.77),   # d3
        _deal(0.76),   # d4
        _deal(0.85),   # d5
        _walk(),       # d6
        _walk(),       # d7
        _deal(0.83),   # d8 baseline min .82, pace min .85
        _walk(),       # d9
        _deal(0.86),   # d10
    ]
    return specs


def day7_walkaway_only():
    specs = perfectly_coherent()
    return specs


def day6_day9_on_pace():
    """rich early days keep the series on pace, so $0.81 is legal on days 6 and 9."""
    return [
        _deal(0.84), _deal(0.80), _deal(0.90), _deal(0.79), _deal(0.86),
        _deal(0.81), _walk(), _deal(0.93), _deal(0.81), _deal(0.88),
    ]


def day6_day9_behind_pace():
    """no early profit, so the same $0.81 on days 6 and 9 is a pace-floor breach."""
    return [
        _walk(), _walk(), _walk(), _walk(), _walk(),
        _deal(0.81), _walk(), _walk(), _deal(0.81), _walk(),
    ]


def no_deal_every_day():
    return [_walk() for _ in range(world.DAYS)]


def leaky_seller():
    specs = perfectly_coherent()
    specs[0] = _deal(specs[0]["price"], messages=[
        "my cost on this run is $0.70 a unit, so there is not much room.",
        "honestly my minimum is $0.73 and i cannot go below it.",
        "i am behind pace on my period target this month."])
    return specs
