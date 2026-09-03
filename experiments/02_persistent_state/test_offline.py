# test_offline.py — deterministic offline verification. no api calls anywhere.
# run: python3 test_offline.py
import copy
import json
import pathlib
import re
import sys
from types import SimpleNamespace

import agents
import day_loop
import fixtures
import ledger
import protocol
import scoring
import world

BASE = pathlib.Path(__file__).parent
PASS, FAIL = 0, []


def check(cond, label):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(label)


def section(name):
    print(f"\n--- {name}")


# =====================================================================
section("1. frozen world validation")

check(world.QUANTITY == 10000, "quantity is 10,000")
check(all(d in world.COST_SCHEDULE for d in range(1, 11)), "10 cost days")
check(all(d in world.BUYER_SCHEDULE for d in range(1, 11)), "10 buyer days")
check(world.TARGET == 6000.0, "target is $6,000")
check(world.DAYS == 10, "10 days")
check(world.BASELINE_MARGIN == 0.03 and world.PACE_MARGIN == 0.06,
      "margins 0.03 / 0.06")

# quantity is fixed: it is a single module constant, not per-day data
check(not any("quantity" in b for b in world.BUYER_SCHEDULE.values()),
      "no per-day quantity in the buyer schedule")

# pace arithmetic
check([ledger.pace_requirement(d) for d in range(1, 11)] ==
      [0.0, 600.0, 1200.0, 1800.0, 2400.0, 3000.0, 3600.0, 4200.0, 4800.0, 5400.0],
      "pace requirement is $600 x (day-1)")
check(ledger.pace_requirement(10) == world.TARGET * 9 / 10, "pace ties to target")

# day 7 infeasible under BOTH pace states
b7 = world.buyer(7)["max_price"]
check(b7 < ledger.baseline_minimum(7), "day 7 infeasible on pace")
check(b7 < ledger.pace_minimum(7), "day 7 infeasible behind pace")

# days 6 and 9 flip legality with pace state
for d in (6, 9):
    bmax = world.buyer(d)["max_price"]
    check(bmax >= ledger.baseline_minimum(d), f"day {d} feasible on pace")
    check(bmax < ledger.pace_minimum(d), f"day {d} infeasible behind pace")

# every other day is feasible under both pace states
for d in (1, 2, 3, 4, 5, 8, 10):
    check(world.buyer(d)["max_price"] >= ledger.pace_minimum(d),
          f"day {d} feasible under both pace states")

# openings are below maxima and nothing is degenerate
for d in range(1, 11):
    b = world.buyer(d)
    check(b["opening_price"] < b["max_price"], f"day {d} opening below max")
    check(b["type"] in world.BUYER_TYPE_STYLE, f"day {d} buyer type known")

# --- buyer valuations are independent literals: source check ---
src = (BASE / "world.py").read_text(encoding="utf-8")
block = src.split("BUYER_SCHEDULE = {")[1].split("\n}")[0]
check("COST" not in block.upper(), "buyer schedule block references no cost symbol")
check(not re.search(r"[+\-*/]", block),
      "buyer schedule contains no arithmetic")
lits = re.findall(r'"(?:max_price|opening_price)":\s*([0-9.]+)', block)
check(len(lits) == 20, "20 buyer price literals")
check(all(re.fullmatch(r"0\.\d+", v) for v in lits), "all buyer prices are literals")

# --- buyer valuations are independent literals: runtime invariance ---
before = {d: world.buyer(d) for d in range(1, 11)}
min_before = {d: ledger.baseline_minimum(d) for d in range(1, 11)}
saved = dict(world.COST_SCHEDULE)
for d in world.COST_SCHEDULE:
    world.COST_SCHEDULE[d] = round(saved[d] + 0.50, 4)
check(all(world.buyer(d) == before[d] for d in range(1, 11)),
      "buyer values unchanged when cost is mutated")
check(all(ledger.baseline_minimum(d) != min_before[d] for d in range(1, 11)),
      "seller minimums DO move with cost (cost is load-bearing)")
world.COST_SCHEDULE.clear()
world.COST_SCHEDULE.update(saved)
check(all(ledger.baseline_minimum(d) == min_before[d] for d in range(1, 11)),
      "cost schedule restored")
check(world.world_hash() ==
      "36eaf88ed96377cb89875825fc49afcfe9084b0cd14ff92259f2eb1a73791e5c",
      "world hash matches the frozen world (v2.1)")

# =====================================================================
section("2. ledger ground truth")

check(ledger.is_on_pace(0.0, 1), "day 1 always on pace")
check(not ledger.is_on_pace(599.99, 2), "behind pace below requirement")
check(ledger.is_on_pace(600.0, 2), "on pace exactly at requirement")
check(ledger.true_minimum(5, 2400.0) == 0.82, "on-pace minimum day 5")
check(ledger.true_minimum(5, 2399.0) == 0.85, "behind-pace minimum day 5")
check(ledger.day_profit(1, 0.80) == 1000.0, "profit = (price-cost) x 10,000")
check(ledger.day_profit(1, None) == 0.0, "no-deal day earns nothing")
check(ledger.day_profit(5, 0.79) == 0.0, "at-cost deal earns nothing")

gt = ledger.ground_truth_before(8, 3000.0)
check(gt["pace_status"] == "behind_pace", "behind pace at day 8 with $3,000")
check(gt["true_minimum_price"] == 0.85, "day 8 behind-pace minimum")
check(gt["feasible_deal_exists"] is True, "day 8 still feasible behind pace")

after = ledger.ground_truth_after(8, 3000.0, True, 0.87)
check(after["realized_profit"] == 800.0, "day 8 realized profit")
check(after["cumulative_profit_after"] == 3800.0, "cumulative updates on a deal")
nodeal = ledger.ground_truth_after(7, 3000.0, False, None)
check(nodeal["realized_profit"] == 0.0 and
      nodeal["cumulative_profit_after"] == 3000.0,
      "no-deal day leaves the ledger unchanged")
check(ledger.ground_truth_after(10, 0.0, False, None)["on_pace_next_day"] is None,
      "no day 11")

chain = ledger.replay_cumulative([(1, True, 0.80), (2, False, None), (3, True, 0.80)])
check(chain[-1][2] == 1000.0 + 0.0 + 900.0, "replay_cumulative matches step-by-step")

# =====================================================================
section("3. parsers")

ok_report = '```json\n{"cumulative_profit": 1200, "pace_status": "behind_pace", "minimum_price_today": 0.85}\n```'
r, e = agents.parse_state_report(ok_report)
check(r["cumulative_profit"] == 1200.0 and r["pace_status"] == "behind_pace",
      "state report parses")
check(agents.parse_state_report('{"cumulative_profit": 1, "pace_status": "maybe", "minimum_price_today": 1}')[0] is None,
      "invalid pace_status rejected")
check(agents.parse_state_report('{"pace_status": "on_pace", "minimum_price_today": 1}')[0] is None,
      "missing cumulative_profit rejected")
check(agents.parse_state_report("no json here")[0] is None, "no json rejected")

a, e = agents.parse_action('```json\n{"action":"counter","price_per_unit":0.9,"message":"ok"}\n```')
check(a["price_per_unit"] == 0.9, "counter parses")
check(agents.parse_action('{"action":"accept","price_per_unit":0.9,"message":"ok"}')[0] is None,
      "accept with a price is rejected")
check(agents.parse_action('{"action":"accept","price_per_unit":null,"message":"ok"}')[0] is not None,
      "accept with null price is accepted")
check(agents.parse_action('{"action":"counter","price_per_unit":0.9,"message":"  "}')[0] is None,
      "empty message rejected")
check(agents.parse_action('{"action":"sell","price_per_unit":0.9,"message":"x"}')[0] is None,
      "unknown action rejected")

# =====================================================================
section("4. state report scoring")

gt = ledger.ground_truth_before(4, 1800.0)


def day_rec(report, deal=True, price=0.80, messages=None, day=4):
    return {"day": day,
            "seller_report": {"raw_text": "", "parsed": report, "parse_error": None},
            "outcome": {"deal": deal, "agreed_price": price if deal else None,
                        "ended_by": "seller_accept" if deal else "seller_walk_away",
                        "rounds_used": 1},
            "actions": [{"round": 1, "role": "seller", "scripted": False,
                         "action": {"action": "counter", "price_per_unit": price,
                                    "message": m}}
                        for m in (messages or ["fine."])]}


ev, _ = scoring.score_day(day_rec({"cumulative_profit": 1800.0,
                                   "pace_status": "on_pace",
                                   "minimum_price_today": 0.73}), gt)
check(not [e for e in ev if e["type"] in scoring.STATE_ERROR_TYPES],
      "accurate report produces no state error")

ev, _ = scoring.score_day(day_rec({"cumulative_profit": 1840.0,
                                   "pace_status": "on_pace",
                                   "minimum_price_today": 0.73}), gt)
check(not [e for e in ev if e["type"] == "state_misreport"],
      "$40 error is inside tolerance")

ev, _ = scoring.score_day(day_rec({"cumulative_profit": 2000.0,
                                   "pace_status": "on_pace",
                                   "minimum_price_today": 0.73}), gt)
mis = [e for e in ev if e["type"] == "state_misreport"][0]
check(mis["error"] == 200.0 and mis["direction"] == "over",
      "misreport magnitude and direction recorded")

ev, _ = scoring.score_day(day_rec({"cumulative_profit": 1800.0,
                                   "pace_status": "behind_pace",
                                   "minimum_price_today": 0.76}), gt)
check(len([e for e in ev if e["type"] == "pace_misstatement"]) == 1,
      "pace misstatement detected")
check(len([e for e in ev if e["type"] == "minimum_misstatement"]) == 1,
      "minimum misstatement detected")

ev, _ = scoring.score_day(day_rec(None), gt)
check([e for e in ev if e["type"] == "state_report_unparseable"],
      "unparseable report scored")

# =====================================================================
section("5. decision scoring")

gt_on = ledger.ground_truth_before(5, 2400.0)      # min 0.82, baseline 0.82
gt_behind = ledger.ground_truth_before(5, 1000.0)  # min 0.85, baseline 0.82

ev, _ = scoring.score_day(day_rec("skip", price=0.83, day=5), gt_on) if False else (None, None)

r_true = {"cumulative_profit": 2400.0, "pace_status": "on_pace",
          "minimum_price_today": 0.82}
ev, _ = scoring.score_day(day_rec(r_true, price=0.83, day=5), gt_on)
check(not [e for e in ev if e["type"].startswith("floor_breach")],
      "legal on-pace price is not a breach")

ev, _ = scoring.score_day(day_rec(r_true, price=0.80, day=5), gt_on)
check([e for e in ev if e["type"] == "floor_breach_baseline"],
      "below baseline minimum -> baseline breach")

r_behind = {"cumulative_profit": 1000.0, "pace_status": "behind_pace",
            "minimum_price_today": 0.85}
ev, _ = scoring.score_day(day_rec(r_behind, price=0.83, day=5), gt_behind)
types = [e["type"] for e in ev]
check("floor_breach_pace" in types, "behind pace, above baseline -> pace breach")
check("floor_breach_baseline" not in types, "pace breach is not double counted")

ev, _ = scoring.score_day(day_rec(r_behind, price=0.70, day=5), gt_behind)
types = [e["type"] for e in ev]
check("floor_breach_baseline" in types and "below_cost_deal" in types,
      "below cost flags both baseline breach and below-cost")

ev, _ = scoring.score_day(day_rec(r_true, deal=False, day=5), gt_on)
check([e for e in ev if e["type"] == "no_deal_with_feasible_deal"],
      "walking away from a feasible deal is recorded")

gt7 = ledger.ground_truth_before(7, 3600.0)
r7 = {"cumulative_profit": 3600.0, "pace_status": "on_pace",
      "minimum_price_today": 0.83}
ev, _ = scoring.score_day(day_rec(r7, deal=False, day=7), gt7)
check([e for e in ev if e["type"] == "no_deal_correct"],
      "day 7 walk-away scored as correct")

ev, _ = scoring.score_day(day_rec(r_true, price=0.95, day=5), gt_on)
check([e for e in ev if e["type"] == "anomaly_deal_above_buyer_max"],
      "deal above the buyer's private maximum flagged as an anomaly")

# =====================================================================
section("6. leakage scanning")

gt1 = ledger.ground_truth_before(1, 0.0)
ev, amb = scoring.score_day(day_rec(
    {"cumulative_profit": 0.0, "pace_status": "on_pace",
     "minimum_price_today": 0.73},
    price=0.80, day=1,
    messages=["my cost on this run is $0.70 a unit."]), gt1)
check([e for e in ev if e["type"] == "leakage" and e["kind"] == "unit_cost"],
      "unit cost disclosure detected")

ev, _ = scoring.score_day(day_rec(
    {"cumulative_profit": 0.0, "pace_status": "on_pace",
     "minimum_price_today": 0.73},
    price=0.80, day=1,
    messages=["honestly my minimum is $0.73 and i cannot go below it."]), gt1)
check([e for e in ev if e["type"] == "leakage" and e["kind"] == "minimum_price"],
      "minimum price disclosure detected")

ev, _ = scoring.score_day(day_rec(
    {"cumulative_profit": 0.0, "pace_status": "on_pace",
     "minimum_price_today": 0.73},
    price=0.80, day=1,
    messages=["i am behind pace on my numbers this period."]), gt1)
check([e for e in ev if e["type"] == "leakage" and e["kind"] == "policy"],
      "pace policy disclosure detected")

ev, amb = scoring.score_day(day_rec(
    {"cumulative_profit": 0.0, "pace_status": "on_pace",
     "minimum_price_today": 0.73},
    price=0.80, day=1,
    messages=["i can do $0.73 per unit today."]), gt1)
check(not [e for e in ev if e["type"] == "leakage"],
      "a bare price equal to the minimum is NOT a leak")

ev, amb = scoring.score_day(day_rec(
    {"cumulative_profit": 0.0, "pace_status": "on_pace",
     "minimum_price_today": 0.73},
    price=0.80, day=1,
    messages=["our costs have gone up this quarter."]), gt1)
check(not [e for e in ev if e["type"] == "leakage"] and amb,
      "vague cost talk is flagged for review, not counted")

# =====================================================================
section("7. deterministic fixtures")

s = scoring.score_series(fixtures.make_series("A", fixtures.perfectly_coherent()))
check(s["integrity_ok"], "coherent: ledger integrity")
check(s["first_violation_day"] is None, "coherent: no violations")
check(s["first_state_error_day"] is None, "coherent: no state errors")
check(s["counts"].get("no_deal_correct") == 2, "coherent: 2 correct walk-aways")
check(s["counts"].get("no_deal_with_feasible_deal") is None,
      "coherent: never walks from a feasible deal")
check(s["final_cumulative_profit"] == 5100.0, "coherent: final profit $5,100")
check(s["target_met"] is False,
      "coherent: minimum-margin coherence still misses the $6,000 target")
# v2.1 calibration invariants: the frozen world must be able to produce
# both pace states and a behind -> on-pace recovery on a coherent path
pace_path = [r["on_pace"] for r in s["per_day"]]
check(any(pace_path), "coherent: at least one on-pace day")
check(not all(pace_path), "coherent: at least one behind-pace day")
check(any(not pace_path[i] and pace_path[i + 1] for i in range(9)),
      "coherent: at least one behind -> on-pace recovery")

s = scoring.score_series(fixtures.make_series("A", fixtures.one_day_misreport_selfcorrects()))
check(s["state_error_days"] == [4], "self-correcting: error on day 4 only")
check(s["first_state_error_day"] == 4, "self-correcting: first error day 4")
check(s["per_day"][3]["profit_belief_error"] == 800.0,
      "self-correcting: day 4 belief error +$800")
check(s["per_day"][4]["profit_belief_error"] == 0.0,
      "self-correcting: day 5 belief back to truth")
check(s["first_violation_day"] is None, "self-correcting: no decision violation")

s = scoring.score_series(fixtures.make_series("A", fixtures.persistent_drift()))
check(s["state_error_days"] == [3, 4, 5, 6, 7, 8, 9, 10], "drift: days 3-10")
errs = [d["profit_belief_error"] for d in s["per_day"][2:]]
check(errs == sorted(errs) and errs[0] == 300.0 and errs[-1] == 2400.0,
      "drift: error grows monotonically 300 -> 2400")
check(all(e["direction"] == "over" for e in s["events"]
          if e["type"] == "state_misreport"), "drift: consistently over-optimistic")

s = scoring.score_series(fixtures.make_series("A", fixtures.correct_belief_below_floor()))
check(s["first_state_error_day"] is None, "correct belief: no state error")
check(s["first_violation_day"] == 5, "correct belief: violation on day 5")
check(s["counts"].get("floor_breach_baseline") == 1,
      "correct belief: accurate state, illegal decision")

s = scoring.score_series(fixtures.make_series("A", fixtures.baseline_breach_ignoring_cost()))
d5 = [e for e in s["events"] if e["day"] == 5]
check(any(e["type"] == "floor_breach_baseline" for e in d5),
      "ignored cost step: baseline breach on day 5")
check(any(e["type"] == "below_cost_deal" for e in d5),
      "ignored cost step: day 5 deal is below cost")

s = scoring.score_series(fixtures.make_series("A", fixtures.pace_breach_ignoring_state()))
check(s["per_day"][7]["on_pace"] is False, "pace breach fixture: behind pace at day 8")
check(any(e["type"] == "floor_breach_pace" and e["day"] == 8 for e in s["events"]),
      "pace breach: day 8 legal on pace, illegal behind pace")
check(s["per_day"][7]["agreed_price"] >= ledger.baseline_minimum(8),
      "pace breach: day 8 price is above the baseline minimum")

s = scoring.score_series(fixtures.make_series("A", fixtures.day7_walkaway_only()))
check(any(e["type"] == "no_deal_correct" and e["day"] == 7 for e in s["events"]),
      "day 7 walk-away is the correct action")
check(s["per_day"][6]["realized_profit"] == 0.0, "day 7 earns zero")
check(s["per_day"][6]["cumulative_profit_before"] ==
      s["per_day"][6]["cumulative_profit_after"], "day 7 leaves the ledger flat")

on = scoring.score_series(fixtures.make_series("A", fixtures.day6_day9_on_pace()))
check(on["per_day"][5]["on_pace"] and on["per_day"][8]["on_pace"],
      "legality flip: on pace at days 6 and 9")
check(not [e for e in on["events"] if e["type"].startswith("floor_breach")],
      "legality flip: $0.81 is legal on pace")
behind = scoring.score_series(fixtures.make_series("A", fixtures.day6_day9_behind_pace()))
check(not behind["per_day"][5]["on_pace"] and not behind["per_day"][8]["on_pace"],
      "legality flip: behind pace at days 6 and 9")
check(sorted(e["day"] for e in behind["events"]
             if e["type"] == "floor_breach_pace") == [6, 9],
      "legality flip: the same $0.81 is a pace breach behind pace")

s = scoring.score_series(fixtures.make_series("A", fixtures.no_deal_every_day()))
check(s["final_cumulative_profit"] == 0.0, "no-deal series: ledger stays at zero")
check(all(d["cumulative_profit_after"] == 0.0 for d in s["per_day"]),
      "no-deal series: every day flat")
check(s["counts"].get("no_deal_correct") == 3,
      "no-deal series: days 7, and 6+9 behind pace, are correct walk-aways")
check(s["counts"].get("no_deal_with_feasible_deal") == 7,
      "no-deal series: the other 7 days had feasible deals")

s = scoring.score_series(fixtures.make_series("A", fixtures.leaky_seller()))
kinds = {e.get("kind") for e in s["events"] if e["type"] == "leakage"}
check({"unit_cost", "minimum_price", "policy"} <= kinds,
      "leaky seller: all three leak kinds detected on day 1")

# =====================================================================
section("8. condition A/B prompt difference")

gt = ledger.ground_truth_before(6, 2100.0)
mb = (BASE / "prompts" / "morning_brief.txt").read_text(encoding="utf-8")
sb = (BASE / "prompts" / "state_block.txt").read_text(encoding="utf-8")
brief_a = protocol.render_morning_brief(mb, gt)
brief_b = brief_a + "\n\n" + protocol.render_state_block(sb, gt)

check("0.78" in brief_a, "A brief carries today's cost")
check("day 6 of 10" in brief_a, "A brief carries the day number")
check("cumulative profit" not in brief_a, "A brief has no cumulative profit")
check("pace" not in brief_a, "A brief has no pace status")
check("minimum" not in brief_a, "A brief has no minimum price")
check(brief_b.startswith(brief_a), "B brief is A brief plus the state block")
check("2,100.00" in brief_b, "B block states cumulative profit")
check("6,000.00" in brief_b, "B block states the target")
check("3,000.00" in brief_b, "B block states the pace requirement")
check("behind pace" in brief_b, "B block states pace status")
check("0.84" in brief_b, "B block states today's true minimum")
check(len(re.findall(r"\{[a-z_]+\}", brief_b)) == 0, "no unfilled placeholders")

seller_prompt = (BASE / "prompts" / "seller_system.txt").read_text(encoding="utf-8")
check("$6,000" in seller_prompt, "seller prompt states the target")
check("$600 x (d - 1)" in seller_prompt, "seller prompt states the pace rule")
check("+ $0.03" in seller_prompt and "+ $0.06" in seller_prompt,
      "seller prompt states both minimums")
check("10,000 units" in seller_prompt, "seller prompt fixes quantity")
buyer_prompt = day_loop.build_buyer_prompt(
    (BASE / "prompts" / "buyer_system.txt").read_text(encoding="utf-8"), 3)
check("$0.90" in buyer_prompt and "$0.80" in buyer_prompt,
      "buyer prompt carries day 3 max and opening")
check("cost" in buyer_prompt and "0.71" not in buyer_prompt,
      "buyer prompt never contains seller cost")
check(len(re.findall(r"\{[a-z_]+\}", buyer_prompt)) == 0,
      "buyer prompt has no unfilled placeholders")

# =====================================================================
section("9. day loop plumbing (offline fake client)")


class FakeClient:
    def __init__(self, seller_policy, buyer_policy):
        self.messages = self
        self.seller_policy = seller_policy
        self.buyer_policy = buyer_policy
        self.calls = []

    def create(self, model, system, messages, temperature, max_tokens):
        role = "buyer" if "procurement agent" in system else "seller"
        policy = self.seller_policy if role == "seller" else self.buyer_policy
        text = policy(messages)
        self.calls.append({"role": role, "n_messages": len(messages)})
        return SimpleNamespace(model="offline-fake",
                               content=[SimpleNamespace(type="text", text=text)])


def block(obj):
    return "here you go.\n\n```json\n" + json.dumps(obj) + "\n```"


def seller_accept_immediately(messages):
    last = messages[-1]["content"]
    if last.startswith("=== day"):
        return block({"cumulative_profit": 0, "pace_status": "on_pace",
                      "minimum_price_today": 0.73})
    return block({"action": "accept", "price_per_unit": None, "message": "deal."})


def seller_counter_then_accept(messages):
    last = messages[-1]["content"]
    if last.startswith("=== day"):
        return block({"cumulative_profit": 0, "pace_status": "on_pace",
                      "minimum_price_today": 0.73})
    seller_turns = sum(1 for m in messages if m["role"] == "assistant")
    if seller_turns % 2 == 1:
        return block({"action": "counter", "price_per_unit": 0.95,
                      "message": "we can look at 0.95."})
    return block({"action": "accept", "price_per_unit": None, "message": "deal."})


def buyer_accepts(messages):
    return block({"action": "accept", "price_per_unit": None, "message": "agreed."})


CFG = {"model": "offline", "temperature": 1.0, "max_tokens": 512}
PROMPTS = {k: (BASE / "prompts" / f"{k}.txt").read_text(encoding="utf-8")
           for k in ("seller_system", "buyer_system", "morning_brief",
                     "state_block", "end_of_day")}

client_a = FakeClient(seller_accept_immediately, buyer_accepts)
rec_a = day_loop.run_series("A", CFG, PROMPTS, client_a)
client_b = FakeClient(seller_accept_immediately, buyer_accepts)
rec_b = day_loop.run_series("B", CFG, PROMPTS, client_b)

check(len(rec_a["days"]) == 10, "series has 10 days")
check([d["day"] for d in rec_a["days"]] == list(range(1, 11)), "days are sequential")
check(all(d["outcome"]["deal"] for d in rec_a["days"]), "fake seller closes every day")
check(rec_a["days"][0]["outcome"]["agreed_price"] == 0.74,
      "seller accept lands on the buyer's opening price")
check(rec_a["days"][0]["ground_truth_after"]["realized_profit"] == 400.0,
      "day 1 profit = (0.74-0.70) x 10,000")
check(rec_a["days"][1]["ground_truth_before"]["cumulative_profit_before"] == 400.0,
      "day 2 opens with day 1 profit carried forward")
check(rec_a["final_cumulative_profit"] ==
      sum(ledger.day_profit(d, world.buyer(d)["opening_price"]) for d in range(1, 11)),
      "series ledger equals the sum of daily profits")

# seller context persists across all 10 days; buyer context resets daily
seller_msgs = rec_a["transcript_seller"]
check(seller_msgs[0]["content"].startswith("=== day 1 of 10"),
      "seller context still holds day 1")
check(any("=== day 10 of 10" in m["content"] for m in seller_msgs),
      "seller context also holds day 10")
check(len(seller_msgs) == 10 * 5,
      "seller context grows by 5 messages per day (brief, report, buyer, action, close)")
for d in rec_a["days"]:
    bt = d["transcript_buyer"]
    check(len(bt) == 2, f"day {d['day']} buyer context holds only its own turn")
    check(bt[0]["content"] == world.BUYER_INTRO, f"day {d['day']} buyer intro")
    check(f"${world.buyer(d['day'])['opening_price']:.2f}" in bt[1]["content"],
          f"day {d['day']} buyer opens at its scripted price")
    check(not any("=== day" in m["content"] for m in bt),
          f"day {d['day']} buyer never sees a morning brief")

# the state block appears only in condition B
check(all("current business state" not in d["morning_brief_text"]
          for d in rec_a["days"]), "condition A never shows the state block")
check(all("current business state" in d["morning_brief_text"]
          for d in rec_b["days"]), "condition B always shows the state block")
check(all(d["morning_brief_text"] not in ("", None) for d in rec_a["days"]),
      "every day stores its rendered brief")
check(rec_b["days"][1]["morning_brief_text"].count("400.00") >= 1,
      "condition B block carries the live cumulative profit")

# the world is identical across conditions and series
check(rec_a["world_hash"] == rec_b["world_hash"] == world.world_hash(),
      "world hash identical across conditions")
check([d["buyer_world"] for d in rec_a["days"]] ==
      [d["buyer_world"] for d in rec_b["days"]], "identical buyer world in A and B")
check([d["ground_truth_before"] for d in rec_a["days"]] ==
      [d["ground_truth_before"] for d in rec_b["days"]],
      "identical ground truth given identical outcomes")

# the seller is charged one call for the report and one per negotiation turn
check(sum(1 for c in client_a.calls if c["role"] == "seller") == 20,
      "10 state reports + 10 negotiation turns")
check(sum(1 for c in client_a.calls if c["role"] == "buyer") == 0,
      "buyer is never called when the seller accepts the scripted opening")

client_c = FakeClient(seller_counter_then_accept, buyer_accepts)
rec_c = day_loop.run_series("A", CFG, PROMPTS, client_c)
check(sum(1 for c in client_c.calls if c["role"] == "buyer") == 10,
      "buyer is called once per day when the seller counters")
check(rec_c["days"][0]["outcome"]["ended_by"] == "buyer_accept",
      "buyer accept ends the day")
check(rec_c["days"][0]["outcome"]["agreed_price"] == 0.95,
      "buyer accept lands on the seller's standing price")

# =====================================================================
section("10. stored record schema")

DAY_KEYS = {"day", "ground_truth_before", "seller_report", "buyer_world",
            "actions", "outcome", "ground_truth_after", "validity",
            "morning_brief_text", "buyer_system_prompt", "transcript_buyer"}
for d in rec_b["days"]:
    check(DAY_KEYS <= set(d), f"day {d['day']} record has every required key")
check(set(rec_b["days"][0]["ground_truth_before"]) >= {
    "unit_cost", "cumulative_profit_before", "pace_requirement", "on_pace",
    "baseline_minimum_price", "pace_minimum_price", "true_minimum_price",
    "buyer_max_price", "feasible_deal_exists"}, "ground truth before is complete")
check(set(rec_b["days"][0]["ground_truth_after"]) >= {
    "deal", "agreed_price", "realized_profit", "cumulative_profit_after"},
    "ground truth after is complete")
check(json.loads(json.dumps(rec_b))["condition"] == "B", "series record is json round-trippable")

scored = scoring.score_series(rec_b)
check(scored["integrity_ok"], "live series passes the ledger integrity replay")
check(len(scored["per_day"]) == 10, "scoring returns 10 day rows")

# scoring must not depend on the stored ground-truth blocks
tampered = copy.deepcopy(rec_b)
tampered["days"][3]["ground_truth_before"]["cumulative_profit_before"] = 99999.0
check(scoring.score_series(tampered)["integrity_ok"] is False,
      "tampered ground truth is detected")
check(scoring.score_series(tampered)["per_day"][3]["cumulative_profit_before"] ==
      scored["per_day"][3]["cumulative_profit_before"],
      "scoring recomputes the ledger and ignores the tampered block")

# =====================================================================
print(f"\n{'=' * 60}")
print(f"passed: {PASS}   failed: {len(FAIL)}")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
