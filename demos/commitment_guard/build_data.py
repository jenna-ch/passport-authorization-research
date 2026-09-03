"""
build_data.py — read-only data extractor for the Commitment Guard prototype.

Reads ONE frozen experiment record (main_B_15_1787710879) from
../01_delegated_authority/runs/main/ and the frozen tracker.py it was scored with.
Writes nothing back to 01_delegated_authority/. Makes no API calls. Runs no model.

What this script does, precisely:

  1. Imports 01_delegated_authority/tracker.py and agents.py directly (read-only —
     no experiment file is modified) and replays the stored actions for
     turns 0-4 through tracker.update_buyer / tracker.update_seller, exactly
     as protocol.py did when the run was originally produced. This
     reconstructs the seller's authentic commitment state immediately before
     the residual failure — not hand-copied numbers.
  2. Cross-checks that reconstruction against the run's own stored
     tracker_timeline (round 4) and fails loudly on any mismatch.
  3. Applies the buyer's actual turn-5 offer to that state (tracker.update_buyer),
     giving the exact state the seller faced the moment before it attempted
     the accept — still 100% recorded, nothing invented yet.
  4. Reconstructs the seller's actual stored action at turn 5 (`accept`,
     which commits to the buyer's turn-5 package) and evaluates it through
     guard.py's independent v1 rule implementation — NOT tracker.py's
     classifier. This is the new artifact under test.
  5. Asserts the guard's decision is REQUIRES_NEW_VALUE and that
     state_after == state_before field-for-field (zero mutation on
     withholding) — the central claim of the v1 design. Fails loudly if not.
  6. Writes data.js with everything the prototype page renders: the frozen
     mandate text, the recorded state and actions, the guard's evaluation
     result, the experiment's own (different-purpose) classification of the
     same action for contrast, and one clearly-flagged, hand-authored
     prototype continuation for beat 5. Nothing in data.js is computed by an
     LLM; every negotiation figure traces back to the stored run record.

Regenerate with:  python build_data.py
"""

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP_DIR = HERE.parent.parent / "experiments" / "01_delegated_authority"
RUN_FILE = EXP_DIR / "runs" / "main" / "main_B_15_1787710879.json"

if not RUN_FILE.exists():
    sys.exit(f"frozen run record not found (read-only lookup): {RUN_FILE}")

# import the frozen experiment's own modules, read-only, to replay its own
# scoring logic authentically rather than re-typing tracker semantics by hand
sys.path.insert(0, str(EXP_DIR))
import tracker  # noqa: E402  (01_delegated_authority/tracker.py, frozen, unmodified)
from agents import PAYMENT_DAYS  # noqa: E402  (01_delegated_authority/agents.py, frozen)

sys.path.insert(0, str(HERE))
import guard  # noqa: E402  (this prototype's new v1 guard)


def find_action(actions, turn, role):
    for a in actions:
        if a["turn"] == turn and a["role"] == role:
            return a["action"]
    raise KeyError(f"no {role} action at turn {turn}")


def to_guard_state(tstate):
    return {
        "hard_floor": tracker.FLOOR,
        "unilateral_concessions_allowed": tstate["unilateral_concessions_allowed"],
        "unilateral_concessions_used": tstate["unilateral_concessions_used"],
        "seller_standing_offer": tstate["standing_offer"],
        "buyer_current_offer": copy.deepcopy(tstate["buyer_offer"]),
        "credited_quantity": tstate["credited_quantity"],
        "credited_payment_terms": tstate["credited_days"],
        "outstanding_conditional": copy.deepcopy(tstate["outstanding_conditional"]),
    }


def package_from_buyer_action(action):
    return {
        "price": action["price_per_unit"],
        "quantity": action["quantity"],
        "days": PAYMENT_DAYS[action["payment_terms"]],
    }


def main():
    run = json.loads(RUN_FILE.read_text(encoding="utf-8"))
    actions = run["actions"]

    # ---- 1. authentic replay of turns 1-4 through the frozen tracker ------
    s = tracker.new_state()
    for turn in (1, 2, 3, 4):
        b_action = find_action(actions, turn, "buyer")
        tracker.update_buyer(s, turn, b_action)
        s_action = find_action(actions, turn, "seller")
        tracker.update_seller(s, turn, s_action)

    # ---- 2. cross-check against the run's own stored timeline -------------
    stored_round4 = next(e["state"] for e in run["tracker_timeline"] if e["round"] == 4)
    live_round4 = tracker.snapshot(s)
    if live_round4 != stored_round4:
        sys.exit(
            "integrity check failed: replayed round-4 state does not match "
            "the stored tracker_timeline. Refusing to generate data.js.\n"
            f"replayed: {live_round4}\nstored:   {stored_round4}"
        )

    # ---- 3. apply the buyer's actual turn-5 offer (still fully recorded) --
    buyer_turn5 = find_action(actions, 5, "buyer")
    tracker.update_buyer(s, 5, buyer_turn5)
    state_before = to_guard_state(tracker.snapshot(s))

    # ---- 4. reconstruct the seller's actual stored turn-5 action ----------
    # the stored action is a bare `accept` (null package fields, per schema);
    # accepting commits the seller to the buyer's package on the table.
    seller_turn5 = find_action(actions, 5, "seller")
    assert seller_turn5["action"] == "accept", "expected the residual-failure trace to end in accept"
    pkg = package_from_buyer_action(buyer_turn5)
    proposed_action = {
        "action": "accept",
        "price_per_unit": pkg["price"],
        "quantity": pkg["quantity"],
        "payment_terms": buyer_turn5["payment_terms"],
        "conditional_on": None,
    }

    # ---- 5. evaluate through the NEW guard, independent of tracker.py -----
    result = guard.evaluate(state_before, proposed_action)

    if result["decision"] != "REQUIRES_NEW_VALUE":
        sys.exit(f"expected REQUIRES_NEW_VALUE, guard returned {result['decision']!r}")
    if result["state_before"] != result["state_after"]:
        sys.exit(
            "integrity check failed: guard mutated state on a withheld action.\n"
            f"before: {result['state_before']}\nafter:  {result['state_after']}"
        )

    # ---- for contrast only: the experiment's OWN classification of the ----
    # same action, already stored in the run record (a different-purpose,
    # after-the-fact score — not what the guard evaluates against)
    experiment_event = next(
        e for e in run["tracker_events"] if e["turn"] == 5 and e.get("via_accept")
    )

    # ---- messages, for the recorded portion's quotes -----------------------
    def message(turn, role):
        return find_action(actions, turn, role)["message"]

    data = {
        "run_id": run["run_id"],
        "condition": run["condition"],
        "resolved_model": run["resolved_model"]["seller"],

        "mandate": {
            "hard_floor": tracker.FLOOR,
            "unilateral_concessions_allowed": tracker.CONCESSIONS_ALLOWED,
            "source": "01_delegated_authority/experiment_spec_v1.1.md §5 (seller principal mandate) — frozen",
        },

        "state_before": state_before,

        "buyer_turn5": {
            "price": pkg["price"], "quantity": pkg["quantity"],
            "payment_terms": buyer_turn5["payment_terms"], "message": buyer_turn5["message"],
        },
        "seller_turn4_message": message(4, "seller"),
        "seller_turn5_message": message(5, "seller"),

        "proposed_action": proposed_action,
        "guard_result": result,

        "experiment_classification": {
            "type": experiment_event["type"],
            "note": "The frozen tracker scores this action AFTER it already committed the "
                    "principal — a different purpose (measurement) than the guard's (withholding).",
        },

        "evidence": {
            "agent": "seller", "role": "sales negotiation agent",
            "principal": "packaging manufacturer (seller principal)",
            "proposed_action": proposed_action,
            "mandate_state_at_decision": state_before,
            "decision": result["decision"],
            "reason": result["reason"],
            "state_before": result["state_before"],
            "state_after": result["state_after"],
        },

        "continuation": {
            "label": "PROTOTYPE CONTINUATION — NOT EXPERIMENT EVIDENCE",
            "synthetic": True,
            "held_price": state_before["seller_standing_offer"],
            "message": "I can't move below $0.90 without something new — a larger "
                       "order or faster payment than what we already have. At 12,000 "
                       "units on Net 15, $0.90 per unit stands.",
            "other_paths": [
                "Request new reciprocal value (quantity above 12,000, or faster than Net 15)",
                "Walk away",
            ],
            "note": "Authored for this prototype; not generated by a model, not replayed "
                    "from any stored run.",
        },

        "provenance": {
            "source_record": str(RUN_FILE.relative_to(EXP_DIR.parent)).replace("\\", "/"),
            "tracker_module": "01_delegated_authority/tracker.py (frozen, imported read-only)",
            "guard_module": "commitment_guard_prototype/guard.py (new, v1)",
        },
    }

    out = HERE / "data.js"
    out.write_text("window.DATA = " + json.dumps(data, indent=2) + ";\n", encoding="utf-8")
    print("wrote data.js")
    print(f"guard decision: {result['decision']} (state_before == state_after: "
          f"{result['state_before'] == result['state_after']})")
    print(f"experiment's own classification of the same action: "
          f"{experiment_event['type']} (via_accept)")


if __name__ == "__main__":
    main()
