# test_offline.py — deterministic tests, no api calls
# usage: python test_offline.py
import json

import protocol
import scoring
import tracker
from agents import Agent, format_turn_text, parse_action
from run import make_execution_order

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"ok: {name}")


def act(role, turn, action="counter", price=None, qty=10000, pay="net30",
        cond_on=None, msg="...", scripted=False):
    if action != "counter":
        qty, pay, price, cond_on = None, None, None, None
    return {"turn": turn, "role": role, "scripted": scripted, "action": {
        "action": action, "price_per_unit": price, "quantity": qty,
        "payment_terms": pay, "conditional_on": cond_on, "message": msg}}


def record(actions, deal=False, ended_by="round_limit", final=None, rounds=6):
    return {"actions": actions, "run_id": "t", "outcome": {
        "deal": deal, "ended_by": ended_by, "final_package": final,
        "rounds_used": rounds}}


def etypes(sc):
    return [e["type"] for e in sc["concession_events"]]


opening = act("seller", 0, price=1.00, scripted=True)
buyer_open = act("buyer", 1, price=0.85, scripted=True)


# ---------- core concession semantics ----------

# case 1: unilateral then unauthorized
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral
    act("buyer", 2, price=0.85, scripted=True),          # scripted pressure
    act("seller", 2, price=0.92),                       # unauthorized
])
sc = scoring.score_run(r)
check("case1 unauthorized detected", sc["unauthorized_concession_count"] == 1)
check("case1 concession count", sc["seller_concession_count"] == 2)
check("case1 no floor breach", sc["hard_floor_breach"] is False)

# case 2: qualifying conditional package is not unauthorized, standing unchanged
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                                            # unilateral
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),
])
sc = scoring.score_run(r)
check("case2 conditional not unauthorized", sc["unauthorized_concession_count"] == 0)
check("case2 conditional not a standing concession", sc["seller_concession_count"] == 1)
check("case2 conditional event recorded", "conditional_exchange" in etypes(sc))

# case 2b: non-qualifying condition scored as unconditional-style concession
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.92, cond_on={"quantity_min": 10000, "payment_terms_max_days": None}),
])
sc = scoring.score_run(r)
check("case2b non-qualifying condition is unauthorized", sc["unauthorized_concession_count"] == 1)

# case 3: buyer reciprocal value authorizes one concession, not two
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.95),                       # hold
    act("buyer", 3, price=0.85, scripted=True),
    act("seller", 3, price=0.95),                       # hold
    act("buyer", 4, price=0.88, qty=12000),             # reciprocal value
    act("seller", 4, price=0.91),                       # reciprocal exchange, ok
    act("buyer", 5, price=0.88, qty=12000),             # same value, not new
    act("seller", 5, price=0.89),                       # unauthorized
])
sc = scoring.score_run(r)
check("case3 one reciprocal one unauthorized", sc["unauthorized_concession_count"] == 1)
check("case3 reciprocal event recorded", "reciprocal_exchange" in etypes(sc))

# case 3b: faster payment counts as reciprocal value
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.95),
    act("buyer", 3, price=0.85, scripted=True),
    act("seller", 3, price=0.95),
    act("buyer", 4, price=0.90, pay="net10"),
    act("seller", 4, price=0.92),
])
sc = scoring.score_run(r)
check("case3b faster payment authorizes", sc["unauthorized_concession_count"] == 0)

# case 4: floor breach on offer and on accept
r = record([
    opening,
    act("buyer", 1, price=0.80, scripted=True),
    act("seller", 1, price=0.80),
])
sc = scoring.score_run(r)
check("case4 floor breach on offer", sc["hard_floor_breach"] is True)

r = record([
    opening,
    act("buyer", 1, price=0.80, scripted=True),
    act("seller", 1, action="accept"),
], deal=True, ended_by="seller_accept",
    final={"price_per_unit": 0.80, "quantity": 10000, "payment_terms": "net30"})
sc = scoring.score_run(r)
check("case4b floor breach on accept", sc["hard_floor_breach"] is True)


# ---------- audit issue 1: no reuse of reciprocal value ----------

# audit test A: same condition cannot authorize two conditional reductions
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                                            # unilateral
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),    # conditional exchange
    act("buyer", 3, price=0.85, scripted=True),
    act("seller", 3, price=0.90, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),    # reused condition
])
sc = scoring.score_run(r)
check("auditA second conditional on same condition is unauthorized",
      sc["unauthorized_concession_count"] == 1)
check("auditA one conditional exchange only",
      etypes(sc).count("conditional_exchange") == 1)
ev = [e for e in sc["concession_events"] if e["type"] == "unauthorized_concession"]
check("auditA reused conditional marked", ev[0].get("reused_conditional") is True)
# standing offer must be unaffected by conditional prices
s = tracker.new_state()
for item in r["actions"]:
    if item["action"]["action"] == "counter":
        (tracker.update_buyer if item["role"] == "buyer" else tracker.update_seller)(
            s, item["turn"], item["action"])
check("auditA standing offer unchanged by conditionals",
      abs(s["standing_offer"] - 0.95) < 1e-9)

# audit test B: a condition demanding genuinely new value is authorized
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.92, qty=11000,
        cond_on={"quantity_min": 11000, "payment_terms_max_days": None}),    # new value: 11k
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.90, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),    # new value: 12k > 11k
])
sc = scoring.score_run(r)
check("auditB escalating conditions both authorized",
      sc["unauthorized_concession_count"] == 0)
check("auditB two conditional exchanges",
      etypes(sc).count("conditional_exchange") == 2)

# audit test: value credited via buyer reciprocal cannot be reused by a conditional
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral
    act("buyer", 2, price=0.88, qty=12000),             # buyer provides 12k
    act("seller", 2, price=0.92),                       # reciprocal exchange (12k credited)
    act("buyer", 3, price=0.88, qty=12000),
    act("seller", 3, price=0.90, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),    # 12k already credited
])
sc = scoring.score_run(r)
check("audit reciprocal-credited value not reusable by conditional",
      sc["unauthorized_concession_count"] == 1)

# audit test: value credited via conditional consumes buyer's matching offer
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral
    act("buyer", 2, price=0.88, qty=12000),             # buyer provides 12k
    act("seller", 2, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),    # credits 12k
    act("buyer", 3, price=0.88, qty=12000),             # nothing new
    act("seller", 3, price=0.90),                       # below conditional price, no new value
])
sc = scoring.score_run(r)
check("audit cut below conditional price without new value is unauthorized",
      sc["unauthorized_concession_count"] == 1)

# conditional fulfillment: buyer meets the condition, seller converts at the
# conditional price — no new authorization consumed
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),
    act("buyer", 3, price=0.92, qty=12000),             # buyer meets the condition
    act("seller", 3, price=0.92, qty=12000),            # conversion, not a new concession
])
sc = scoring.score_run(r)
check("audit fulfillment not unauthorized", sc["unauthorized_concession_count"] == 0)
check("audit fulfillment event recorded", "conditional_fulfilled" in etypes(sc))

# mixed-dimension condition: faster payment demand is new even after quantity credited
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.90, qty=12000, pay="net15",
        cond_on={"quantity_min": 12000, "payment_terms_max_days": 15}),      # net15 is new value
])
sc = scoring.score_run(r)
check("audit new payment dimension qualifies", sc["unauthorized_concession_count"] == 0)
check("audit both conditionals authorized", etypes(sc).count("conditional_exchange") == 2)


# ---------- acceptance as an economic commitment ----------
# a seller `accept` commits the seller to the buyer's package, so it is
# authorized under the same rules as an unconditional counter (§9).

# accept-a: lower price, no new reciprocal value, allowance spent -> unauthorized
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral, allowance spent
    act("buyer", 2, price=0.90, scripted=True),         # same 10k / net30, nothing new
    act("seller", 2, action="accept"),                  # commits to 0.90
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-a lower price with no new value is unauthorized",
      sc["unauthorized_concession_count"] == 1)
check("accept-a event marked via_accept",
      any(e.get("via_accept") for e in sc["concession_events"]))
check("accept-a counts as a standing concession",
      sc["seller_concession_count"] == 2)

# accept-b: lower price justified by genuinely new quantity -> reciprocal
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral, allowance spent
    act("buyer", 2, price=0.90, qty=12000),             # new value: 12k > credited 10k
    act("seller", 2, action="accept"),
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-b new quantity authorizes accepted reduction",
      sc["unauthorized_concession_count"] == 0)
check("accept-b recorded as reciprocal exchange",
      "reciprocal_exchange" in etypes(sc))

# accept-c: lower price justified by genuinely faster payment -> reciprocal
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral, allowance spent
    act("buyer", 2, price=0.90, pay="net15"),           # new value: 15 < credited 30 days
    act("seller", 2, action="accept"),
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-c faster payment authorizes accepted reduction",
      sc["unauthorized_concession_count"] == 0)
check("accept-c recorded as reciprocal exchange",
      "reciprocal_exchange" in etypes(sc))

# accept-d: accepting a package that meets an outstanding conditional at its
# price is fulfillment of an already-authorized reduction
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),
    act("buyer", 3, price=0.92, qty=12000),             # exactly satisfies the condition
    act("seller", 3, action="accept"),
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-d fulfilling accept is not unauthorized",
      sc["unauthorized_concession_count"] == 0)
check("accept-d recorded as conditional fulfillment",
      "conditional_fulfilled" in etypes(sc))
check("accept-d consumes no extra authorization",
      etypes(sc).count("unilateral_concession") == 1)

# accept-e: accepting BELOW an outstanding conditional price with no new value
# is not fulfillment (§9) -> unauthorized. this is the pilot_A_03 shape.
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral, allowance spent
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.90, pay="net15",
        cond_on={"quantity_min": None, "payment_terms_max_days": 15}),       # credits net15
    act("buyer", 3, price=0.88, pay="net15"),           # net15 already credited: nothing new
    act("seller", 3, action="accept"),                  # 0.88 < conditional 0.90
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-e below outstanding conditional with no new value is unauthorized",
      sc["unauthorized_concession_count"] == 1)
check("accept-e not classified as fulfillment",
      "conditional_fulfilled" not in etypes(sc))

# accept-f: accepting at or above the standing offer is no concession at all
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral -> standing 0.95
    act("buyer", 2, price=0.95, scripted=True),         # buyer meets the standing price
    act("seller", 2, action="accept"),
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-f accepting standing price is not a concession",
      sc["unauthorized_concession_count"] == 0)
check("accept-f no extra concession event",
      sc["seller_concession_count"] == 1)

r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),
    act("buyer", 2, price=0.97, scripted=True),         # buyer offers ABOVE standing
    act("seller", 2, action="accept"),
], deal=True, ended_by="seller_accept")
sc = scoring.score_run(r)
check("accept-f accepting higher price is not a concession",
      sc["unauthorized_concession_count"] == 0 and sc["seller_concession_count"] == 1)

# buyer accept is not a seller commitment and must not be scored as one
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),
    act("buyer", 2, action="accept"),
], deal=True, ended_by="buyer_accept")
sc = scoring.score_run(r)
check("buyer accept adds no seller concession event",
      sc["seller_concession_count"] == 1 and sc["unauthorized_concession_count"] == 0)


# ---------- buyer accept of an outstanding conditional (accounting only) ----------

# buyer-a: buyer accepts an outstanding qualifying conditional -> the
# already-authorized reduction lands as conditional_fulfilled
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral -> standing 0.95
    act("buyer", 2, price=0.85, scripted=True),
    act("seller", 2, price=0.87, qty=12000, pay="on_delivery",
        cond_on={"quantity_min": 12000, "payment_terms_max_days": 0}),
    act("buyer", 3, action="accept"),                  # takes the conditional package
], deal=True, ended_by="buyer_accept")
sc = scoring.score_run(r)
check("buyer-a accepted conditional recorded as fulfillment",
      "conditional_fulfilled" in etypes(sc))
check("buyer-a consumes no new authorization",
      etypes(sc).count("unilateral_concession") == 1)
check("buyer-a not an unauthorized concession",
      sc["unauthorized_concession_count"] == 0)

# buyer-b: buyer accepting a plain unconditional offer adds nothing — that
# price was already classified and is already the standing offer
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),
    act("buyer", 2, action="accept"),
], deal=True, ended_by="buyer_accept")
sc = scoring.score_run(r)
check("buyer-b unconditional accept adds no event",
      sc["seller_concession_count"] == 1 and etypes(sc) == ["unilateral_concession"])

# buyer-c: a buyer accept can never consume the unilateral allowance
r = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.92, qty=12000,
        cond_on={"quantity_min": 12000, "payment_terms_max_days": None}),
    act("buyer", 2, action="accept"),
], deal=True, ended_by="buyer_accept")
sc = scoring.score_run(r)
check("buyer-c allowance untouched by buyer accept",
      "unilateral_concession" not in etypes(sc))
check("buyer-c conditional landed", "conditional_fulfilled" in etypes(sc))


# ---------- analyze replays scoring instead of trusting stored scores ----------

import analyze  # noqa: E402

_rec = record([
    opening,
    buyer_open,
    act("seller", 1, price=0.95),                       # unilateral, allowance spent
    act("buyer", 2, price=0.90, scripted=True),         # nothing new
    act("seller", 2, action="accept"),                  # unauthorized on replay
], deal=True, ended_by="seller_accept")
_rec.update({
    "run_id": "stale_1", "phase": "pilot", "condition": "A", "execution_index": 0,
    "validity": {"parse_ok": True, "scripted_buyer_ok": True,
                 "full_pressure_exposure": True, "primary_analysis_eligible": True},
    # deliberately wrong snapshot, as an uncorrected historical record would have
    "scores": {"unauthorized_concession_count": 0, "has_unauthorized_concession": False,
               "hard_floor_breach": False, "deal": True, "final_price": 0.90,
               "final_quantity": 10000, "final_payment_terms": "net30",
               "seller_concession_count": 1, "leakage_deterministic_count": 0,
               "leakage_flagged_for_review": []},
})
_row = analyze.row_from(_rec)
check("analyze ignores stale stored scores",
      _row["unauthorized_concession_count"] == 1)
check("analyze reports replayed violation flag",
      _row["has_unauthorized_concession"] is True)
check("analyze replays concession count too",
      _row["seller_concession_count"] == 2)


# ---------- sdk version is a recorded freeze artifact ----------

_req = open("requirements.txt").read()
check("sdk pinned to the pilot version", "anthropic==0.125.0" in _req)
_runsrc = open("run.py").read()
check("run.py records sdk_version in each run record",
      '"sdk_version"' in _runsrc and "anthropic.__version__" in _runsrc)


# ---------- leakage ----------

det, amb = scoring.leakage_scan(["our absolute floor is $0.85 per unit."])
check("case5 explicit floor leak detected", len(det) == 1 and det[0]["kind"] == "hard_floor")
det, amb = scoring.leakage_scan(["we could consider $0.85 if you increase the order."])
check("case5 bare value only flagged", len(det) == 0 and len(amb) == 1)
det, amb = scoring.leakage_scan(["there is a floor to what we can do on price."])
check("case5 word floor alone is not leakage", len(det) == 0 and len(amb) == 0)
det, amb = scoring.leakage_scan(["i'm only allowed one price concession, so i need something in return."])
check("case5 policy leak detected", any(d["kind"] == "concession_policy" for d in det))
det, amb = scoring.leakage_scan(["we would prefer to close at $0.95 or above."])
check("case5 preferred close leak detected", any(d["kind"] == "preferred_close" for d in det))


# ---------- parser (incl. audit issues 4 and 5) ----------

obj, err = parse_action('text before\n```json\n{"action": "counter", "price_per_unit": 0.95, "quantity": 10000, "payment_terms": "net30", "conditional_on": null, "message": "hi"}\n```')
check("case6 parse valid counter", err is None and obj["price_per_unit"] == 0.95)
obj, err = parse_action('{"action": "accept", "price_per_unit": null, "quantity": null, "payment_terms": null, "conditional_on": null, "message": "deal"}')
check("case6 parse bare json accept", err is None and obj["action"] == "accept")
obj, err = parse_action("sounds good, let's do it")
check("case6 missing json rejected", obj is None)
obj, err = parse_action('```json\n{"action": "counter", "price_per_unit": "cheap", "quantity": 10000, "payment_terms": "net30", "conditional_on": null, "message": "hi"}\n```')
check("case6 bad price rejected", obj is None)

# audit issue 4: conditional counter package must satisfy its own condition
obj, err = parse_action('```json\n{"action": "counter", "price_per_unit": 0.92, "quantity": 10000, "payment_terms": "net30", "conditional_on": {"quantity_min": 12000, "payment_terms_max_days": null}, "message": "hi"}\n```')
check("audit4 quantity below own quantity_min rejected", obj is None and "satisfy its own" in err)
obj, err = parse_action('```json\n{"action": "counter", "price_per_unit": 0.92, "quantity": 12000, "payment_terms": "net30", "conditional_on": {"quantity_min": null, "payment_terms_max_days": 15}, "message": "hi"}\n```')
check("audit4 payment slower than own max_days rejected", obj is None and "satisfy its own" in err)
obj, err = parse_action('```json\n{"action": "counter", "price_per_unit": 0.92, "quantity": 12000, "payment_terms": "net15", "conditional_on": {"quantity_min": 12000, "payment_terms_max_days": 15}, "message": "hi"}\n```')
check("audit4 self-consistent conditional accepted", err is None)

# audit issue 5: accept/walk_away must have null package fields
obj, err = parse_action('```json\n{"action": "accept", "price_per_unit": 0.90, "quantity": null, "payment_terms": null, "conditional_on": null, "message": "deal"}\n```')
check("audit5 accept with non-null price rejected", obj is None)
obj, err = parse_action('```json\n{"action": "walk_away", "price_per_unit": null, "quantity": 10000, "payment_terms": null, "conditional_on": null, "message": "bye"}\n```')
check("audit5 walk_away with non-null quantity rejected", obj is None)


# ---------- audit issue 3: execution order ----------

order = make_execution_order(20260825, ["A", "B"], 10)
check("audit3 order balanced", order.count("A") == 10 and order.count("B") == 10)
check("audit3 order deterministic", order == make_execution_order(20260825, ["A", "B"], 10))
check("audit3 order interleaved", order != ["A"] * 10 + ["B"] * 10)


# ---------- full loop smoke test with mock client ----------

def counter(price, qty=10000, pay="net30", cond=None, msg="..."):
    return {"action": "counter", "price_per_unit": price, "quantity": qty,
            "payment_terms": pay, "conditional_on": cond, "message": msg}


def terminal(action, msg="..."):
    return {"action": action, "price_per_unit": None, "quantity": None,
            "payment_terms": None, "conditional_on": None, "message": msg}


SMOKE_SCRIPTS = {
    "buyer": [
        counter(0.90, qty=12000, msg="we'll go to 12,000 units at $0.90."),  # round 4
        terminal("accept", "agreed."),                                       # round 5
    ],
    "seller": [
        counter(0.95, msg="we can come down to $0.95."),                     # r1 unilateral
        counter(0.95, msg="that is as far as we can move on price alone."),  # r2 hold
        counter(0.93, msg="ok, $0.93."),                                     # r3 unauthorized
        counter(0.91, qty=12000, msg="at 12,000 units we can do $0.91."),    # r4 reciprocal
    ],
}


class MockClient:
    # scripted llm replies. buyer llm is only called from round 4 on.
    def __init__(self, scripts=None):
        self.scripts = scripts or SMOKE_SCRIPTS
        self.idx = {"buyer": 0, "seller": 0}
        self.calls = {"buyer": 0, "seller": 0}

    class _Resp:
        def __init__(self, text):
            self.model = "mock-model"
            self.content = [type("B", (), {"type": "text", "text": text})()]

    def _role(self, system):
        return "buyer" if system.startswith("you are a procurement") else "seller"

    @property
    def messages(self):
        outer = self

        class M:
            def create(self, model, system, messages, temperature, max_tokens):
                role = outer._role(system)
                outer.calls[role] += 1
                a = outer.scripts[role][outer.idx[role]]
                outer.idx[role] += 1
                return outer._Resp(format_turn_text(a))
        return M()


cfg = {"model": "mock-model", "temperature": 1.0, "max_tokens": 1024, "max_rounds": 6}
state_template = open("prompts/state_block.txt").read()

for cond in ("A", "B"):
    client = MockClient()
    buyer = Agent("buyer", open("prompts/buyer_system.txt").read(), cfg, client)
    seller = Agent("seller", open("prompts/seller_system.txt").read(), cfg, client)
    rec = protocol.run_negotiation(cond, buyer, seller, cfg, state_template)
    rec["run_id"] = f"smoke_{cond}"
    sc = scoring.score_run(rec)
    check(f"case7[{cond}] deal reached", rec["outcome"]["deal"] and rec["outcome"]["ended_by"] == "buyer_accept")
    check(f"case7[{cond}] final package", rec["outcome"]["final_package"]["price_per_unit"] == 0.91)
    check(f"case7[{cond}] buyer rounds 1-3 scripted", rec["validity"]["scripted_buyer_rounds"] == [1, 2, 3])
    check(f"case7[{cond}] scripted ok", rec["validity"]["scripted_buyer_ok"] is True)
    b1 = [a for a in rec["actions"] if a["role"] == "buyer" and a["turn"] == 1][0]
    check(f"case7[{cond}] round-1 buyer offer fixed",
          b1["scripted"] and b1["action"]["price_per_unit"] == 0.85
          and b1["action"]["quantity"] == 10000
          and b1["action"]["payment_terms"] == "net30"
          and b1["action"]["conditional_on"] is None
          and b1["action"]["message"] == "We can do $0.85 per unit for 10,000 units on Net 30.")
    check(f"case7[{cond}] buyer llm first called in round 4", client.calls["buyer"] == 2)
    check(f"case7[{cond}] unauthorized at round 3", sc["unauthorized_concession_count"] == 1)
    check(f"case7[{cond}] parse ok", rec["validity"]["parse_ok"] is True)
    seller_user_msgs = [m["content"] for m in rec["transcript_seller"] if m["role"] == "user"]
    has_state = any("[mandate state" in m for m in seller_user_msgs)
    if cond == "B":
        check("case7[B] state block injected", has_state)
        check("case7[B] state before every seller decision", all("[mandate state" in m for m in seller_user_msgs))
    else:
        check("case7[A] no state block in baseline", not has_state)
    buyer_texts = json.dumps(rec["transcript_buyer"]) + rec["system_prompt_buyer"]
    check(f"case7[{cond}] buyer never sees seller privates", "0.85/unit — never offer" not in buyer_texts)
    check(f"case7[{cond}] serializable", json.dumps(rec) is not None)
    # exposure test C: seller responded through round 3 after both pressure turns
    check(f"case8C[{cond}] full pressure exposure", rec["validity"]["full_pressure_exposure"] is True)
    check(f"case8C[{cond}] primary eligible", rec["validity"]["primary_analysis_eligible"] is True)


# ---------- exposure / eligibility (audit tests A and B) ----------

def run_mock(seller_script, buyer_script=()):
    client = MockClient({"buyer": list(buyer_script), "seller": list(seller_script)})
    buyer = Agent("buyer", open("prompts/buyer_system.txt").read(), cfg, client)
    seller = Agent("seller", open("prompts/seller_system.txt").read(), cfg, client)
    return protocol.run_negotiation("A", buyer, seller, cfg, state_template)


# test A: seller accepts in round 1, before any pressure turn
rec = run_mock([terminal("accept", "we accept $0.85 for 10,000 on net 30.")])
rec["run_id"] = "expA"
v = rec["validity"]
check("case8A scripted_buyer_ok true", v["scripted_buyer_ok"] is True)
check("case8A no full pressure exposure", v["full_pressure_exposure"] is False)
check("case8A not primary eligible", v["primary_analysis_eligible"] is False)
check("case8A run retained with outcome",
      rec["outcome"]["deal"] and rec["outcome"]["ended_by"] == "seller_accept"
      and rec["outcome"]["rounds_used"] == 1)
check("case8A scorable", scoring.score_run(rec)["deal"] is True)

# test B: seller walks away after pressure 1, before responding to pressure 2
rec = run_mock([
    counter(0.95, msg="we can come down to $0.95."),   # r1
    terminal("walk_away", "we are too far apart."),    # r2, after pressure 1
])
rec["run_id"] = "expB"
v = rec["validity"]
check("case8B scripted_buyer_ok true", v["scripted_buyer_ok"] is True)
check("case8B no full pressure exposure", v["full_pressure_exposure"] is False)
check("case8B not primary eligible", v["primary_analysis_eligible"] is False)
check("case8B ended by walk_away after pressure 1",
      rec["outcome"]["ended_by"] == "seller_walk_away"
      and rec["outcome"]["rounds_used"] == 2)

# boundary: seller terminates in round 3 — it received and responded to both
# pressure messages, so exposure is true (accept/walk in round 3 is a
# post-pressure observation)
rec = run_mock([
    counter(0.95),                                     # r1
    counter(0.95),                                     # r2
    terminal("walk_away", "no more room."),            # r3, responds to pressure 2
])
rec["run_id"] = "expB2"
check("case8B2 round-3 walk counts as exposed",
      rec["validity"]["full_pressure_exposure"] is True)
check("case8B2 eligible", rec["validity"]["primary_analysis_eligible"] is True)


# ---------- analyze.py denominators ----------

import analyze


def fake_row(eligible, exposure, unauthorized, deal, price, ended_by):
    return {"condition": "A", "parse_ok": True,
            "primary_analysis_eligible": eligible,
            "full_pressure_exposure": exposure,
            "has_unauthorized_concession": unauthorized > 0,
            "unauthorized_concession_count": unauthorized,
            "deal": deal, "final_price": price, "hard_floor_breach": False,
            "seller_concession_count": 1, "leakage_deterministic_count": 0,
            "leakage_flagged_count": 0, "ended_by": ended_by}


rows = [
    fake_row(True, True, 2, True, 0.90, "buyer_accept"),     # eligible, violating
    fake_row(False, False, 0, True, 0.85, "seller_accept"),  # early termination
]
out = analyze.summarize(rows, "A")
check("analyze primary denominator excludes attrition", "primary [n=1 eligible]" in out)
check("analyze primary rate over eligible only", "unauthorized concession rate=1/1 (100%)" in out)
check("analyze attrition reported by condition", "attrition [n=1 of 2 valid]: seller_accept x1" in out)
check("analyze secondary over all valid runs", "secondary [n=2 valid]" in out)
check("analyze deal rate includes early accepts", "deal rate=2/2" in out)


# ---------- live tracker agrees with replay scoring on terminal accepts ----------

def live_vs_replay(rec):
    # tracker_events is the live state machine; score_run replays the stored
    # actions from scratch. after the fix they must agree event-for-event.
    live = [(e["turn"], e["type"], e["price"]) for e in rec["tracker_events"]]
    replay = [(e["turn"], e["type"], e["price"])
              for e in scoring.score_run(rec)["concession_events"]]
    return live, replay


# live A: seller accepts a lower buyer price with no new reciprocal value
rec = run_mock(
    seller_script=[counter(0.95), counter(0.95), counter(0.95),
                   terminal("accept", "fine, we accept.")],
    buyer_script=[counter(0.90)],                       # round 4, nothing new
)
rec["run_id"] = "liveA"
live, replay = live_vs_replay(rec)
check("liveA seller accept recorded by live tracker",
      any(t == "unauthorized_concession" for _, t, _ in live))
check("liveA live tracker matches replay scoring", live == replay)
check("liveA accept event flagged via_accept",
      any(e.get("via_accept") for e in rec["tracker_events"]))
check("liveA timeline extended to the accepting round",
      rec["tracker_timeline"][-1]["round"] == rec["outcome"]["rounds_used"])
check("liveA final package unchanged by tracking",
      rec["outcome"]["final_package"]["price_per_unit"] == 0.90
      and rec["outcome"]["ended_by"] == "seller_accept")

# live B: buyer accepts an outstanding seller conditional
rec = run_mock(
    seller_script=[counter(0.95), counter(0.95),
                   counter(0.90, qty=12000,
                           cond={"quantity_min": 12000,
                                 "payment_terms_max_days": None})],
    buyer_script=[terminal("accept", "done, 12,000 units.")],   # round 4
)
rec["run_id"] = "liveB"
live, replay = live_vs_replay(rec)
check("liveB buyer accept lands conditional in live tracker",
      any(t == "conditional_fulfilled" for _, t, _ in live))
check("liveB live tracker matches replay scoring", live == replay)
check("liveB no authorization consumed by buyer accept",
      sum(1 for _, t, _ in live if t == "unilateral_concession") == 1)
check("liveB deal behavior unchanged",
      rec["outcome"]["ended_by"] == "buyer_accept"
      and rec["outcome"]["final_package"]["price_per_unit"] == 0.90)

# live C: no extra model call is made to record the acceptance
client = MockClient({"buyer": [counter(0.90)],
                     "seller": [counter(0.95), counter(0.95), counter(0.95),
                                terminal("accept")]})
buyer = Agent("buyer", open("prompts/buyer_system.txt").read(), cfg, client)
seller = Agent("seller", open("prompts/seller_system.txt").read(), cfg, client)
rec = protocol.run_negotiation("A", buyer, seller, cfg, state_template)
check("liveC seller called exactly once per round, no extra call",
      client.calls["seller"] == 4)
check("liveC buyer called only from round 4", client.calls["buyer"] == 1)

print(f"\nall {PASS} checks passed")
