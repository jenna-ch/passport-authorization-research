# execution_plan.py — the deterministic, concurrent, order-randomized
# execution plan for P3-B.
#
# WHY THIS FILE EXISTS AT ALL. C1's weakness was not only its historical
# before arm; its runner also derived run labels from a per-invocation counter
# (`for i in range(args.runs)` -> `..._G_{i+1:02d}_...`), so three separate
# --confirm invocations produced 25 traces whose labels 1-5 appeared three
# times, and rewrote `_execution_order.json` each time. Reconstructing which
# trace belonged to which batch afterwards required timestamp forensics.
#
# P3-B removes that failure mode by construction:
#
#   1. THE PLAN IS THE AUTHORITY. Every run's identity is a POSITION in a plan
#      generated once from a recorded seed and written to disk BEFORE any
#      confirmed run. run_id = p3b_{position:03d}_{arm}. Positions are global,
#      never per-invocation.
#   2. THE PLAN IS IMMUTABLE. It is written once. A later invocation
#      regenerates it from the stored seed and refuses to proceed unless the
#      regenerated plan digest matches the stored one.
#   3. RESUMPTION IS BY POSITION. The runner skips positions whose output file
#      already exists, so an interrupted batch resumes without relabelling or
#      re-running anything, and no existing run is ever overwritten.
#
# BALANCE. The three arms are interleaved in BLOCKS OF THREE: each block is a
# permutation of (B-info, B-silent, B-announced) drawn from the seeded RNG.
# This guarantees exactly n_per_arm runs per arm, and balance within every
# consecutive window of three positions — so any drift in model behaviour or
# API conditions over the batch is shared equally by the three arms. That is
# the property C1 lacked and Study 1's own A/B had.

import hashlib
import json
import random

from arms import ARM_ORDER

PLAN_FILENAME = "_execution_plan.json"
PLAN_SCHEMA = "p3b.execution_plan.v1"


def make_plan(seed, n_per_arm):
    """the balanced interleaving. deterministic in (seed, n_per_arm)."""
    rng = random.Random(seed)
    positions = []
    for block in range(n_per_arm):
        arms_in_block = list(ARM_ORDER)
        rng.shuffle(arms_in_block)
        for slot, arm in enumerate(arms_in_block):
            pos = len(positions) + 1
            positions.append({
                "position": pos,
                "block": block + 1,
                "slot_in_block": slot + 1,
                "arm": arm,
                "run_id": f"p3b_{pos:03d}_{arm}",
            })
    return positions


def plan_digest(positions):
    payload = json.dumps([[p["position"], p["arm"]] for p in positions],
                         sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def arm_counts(positions):
    return {a: len([p for p in positions if p["arm"] == a]) for a in ARM_ORDER}


def max_run_of_same_arm(positions):
    """longest consecutive stretch of one arm. block interleaving bounds this
    at 2 (last slot of one block plus first slot of the next)."""
    best = cur = 1
    for i in range(1, len(positions)):
        cur = cur + 1 if positions[i]["arm"] == positions[i - 1]["arm"] else 1
        best = max(best, cur)
    return best


def build_plan_document(seed, n_per_arm, frozen_rows, prompt_hashes, arm_defs):
    positions = make_plan(seed, n_per_arm)
    counts = arm_counts(positions)
    assert set(counts.values()) == {n_per_arm}, counts
    return {
        "schema": PLAN_SCHEMA,
        "cell": "P3-B",
        "design_of_record": "phase3_design_of_record.md section 3",
        "order_seed": seed,
        "n_per_arm": n_per_arm,
        "n_total": len(positions),
        "arm_counts": counts,
        "arms": arm_defs,
        "interleaving": ("blocks of three; each block is a seeded permutation "
                         "of the three arms. exactly n_per_arm runs per arm, "
                         "and balance within every consecutive window of "
                         "three positions."),
        "max_consecutive_same_arm": max_run_of_same_arm(positions),
        "plan_digest": plan_digest(positions),
        "frozen_comparison": frozen_rows,
        "prompt_hashes": prompt_hashes,
        "run_id_rule": ("run_id = p3b_{position:03d}_{arm}. positions are "
                        "global and come from this plan, never from a "
                        "per-invocation counter."),
        "resumption_rule": ("a confirmed invocation skips any position whose "
                            "output file already exists and never overwrites "
                            "an existing run."),
        "positions": positions,
    }


def verify_plan_document(doc):
    """regenerate from the stored seed and compare. returns (ok, detail)."""
    regen = make_plan(doc["order_seed"], doc["n_per_arm"])
    checks = {
        "schema_ok": doc.get("schema") == PLAN_SCHEMA,
        "digest_matches_stored": plan_digest(regen) == doc.get("plan_digest"),
        "positions_match_stored": (
            [[p["position"], p["arm"], p["run_id"]] for p in regen]
            == [[p["position"], p["arm"], p["run_id"]]
                for p in doc.get("positions", [])]),
        "arm_counts_exact": arm_counts(regen) == {
            a: doc["n_per_arm"] for a in ARM_ORDER},
        "total_ok": len(regen) == doc["n_per_arm"] * len(ARM_ORDER),
    }
    return all(checks.values()), checks


def pending_positions(doc, out_dir, limit=None):
    """the plan positions with no output file yet.

    This is the whole of P3-B's resumption logic. An existing record is never
    re-run and never overwritten, and a run's identity comes from its plan
    position, so an interrupted batch resumes without relabelling anything.
    """
    todo = [p for p in doc["positions"]
            if not (out_dir / f"{p['run_id']}.json").exists()]
    return todo[:limit] if limit is not None else todo
