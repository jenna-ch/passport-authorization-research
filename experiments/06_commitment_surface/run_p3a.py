# run_p3a.py — cli for Phase 3 cell P3-A (commitment surface).
#
#   python run_p3a.py               dry check + equivalence table. NO api calls.
#   python run_p3a.py --write-plan  write the execution plan. NO api calls.
#   python run_p3a.py --confirm     run the plan. api calls.
#
# --confirm REFUSES unless: every frozen hash matches; A-both's prompt is the
# frozen Study 1 bytes and A-declared's is those bytes plus the appended
# paragraph; the offline suite exits 0; and the plan exists and regenerates
# from its stored seed. It never overwrites an existing record.

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

import action_event as ae
import arms
import execution_plan as xplan
import guard
import protocol_p3a
import scoring
import tracker
from agents import Agent

BASE = pathlib.Path(__file__).resolve().parent
S1 = BASE.parent / "01_delegated_authority"
C1 = BASE.parent / "04_authority_guard"
P3B = BASE.parent / "07_enforcement_recovery"
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"
DEFAULT_N_PER_ARM = 40

FROZEN_S1 = {"agents.py": "b9b8da5946ced705", "protocol.py": "304a2dd59e0c6c3b",
             "tracker.py": "285f26c090ec62d7", "scoring.py": "5f34d0cedd193db3",
             "config.json": "5752faec21fe6088",
             "prompts/seller_system.txt": "d4005aaea3b9b780",
             "prompts/buyer_system.txt": "2fccc7bc2b403f3a",
             "prompts/state_block.txt": "9ca8af7e68b2474a"}
FROZEN_C1 = {"guard.py": "guard.py", "frozen_eligibility.py": "frozen_eligibility.py"}
FROZEN_P3B = {"action_event.py": "action_event.py"}


def sha16(p):
    p = pathlib.Path(p)
    return None if not p.exists() else hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def frozen_comparison():
    rows = []
    for f, exp in FROZEN_S1.items():
        h, b = sha16(BASE / f), sha16(S1 / f)
        rows.append({"group": "frozen_study1", "file": f, "p3a_copy": h,
                     "baseline": b, "baseline_path": f"01_delegated_authority/{f}",
                     "expected": exp, "identical": h == b == exp})
    for f, src in FROZEN_C1.items():
        h, b = sha16(BASE / f), sha16(C1 / src)
        rows.append({"group": "frozen_c1", "file": f, "p3a_copy": h,
                     "baseline": b, "baseline_path": f"04_authority_guard/{src}",
                     "expected": b, "identical": h is not None and h == b})
    for f, src in FROZEN_P3B.items():
        h, b = sha16(BASE / f), sha16(P3B / src)
        rows.append({"group": "frozen_p3b", "file": f, "p3a_copy": h,
                     "baseline": b,
                     "baseline_path": f"07_enforcement_recovery/{src}",
                     "expected": b, "identical": h is not None and h == b})
    return rows


def arm_prompt_check():
    frozen = (BASE / "prompts" / "seller_system.txt").read_bytes()
    dec = (BASE / "prompts" / "seller_system_declared.txt").read_bytes()
    return {"A-both_is_frozen_study1_prompt":
                arms.ARMS["A-both"].seller_prompt().encode("utf-8") == frozen,
            "A-both_sha16": arms.ARMS["A-both"].seller_prompt_sha16(),
            "A-declared_sha16": arms.ARMS["A-declared"].seller_prompt_sha16(),
            "declared_preserves_frozen_prefix": dec.startswith(frozen),
            "declared_appended_bytes": len(dec) - len(frozen),
            "declared_appendix": dec[len(frozen):].decode("utf-8"),
            "no_arm_enforces": all(not a.enforcement_active
                                   for a in arms.ARMS.values()),
            "identical_action_space":
                len({tuple(a.as_dict()["action_space"])
                     for a in arms.ARMS.values()}) == 1,
            "buyer_prompt_sha16": sha16(BASE / "prompts" / "buyer_system.txt"),
            "state_block_sha16": sha16(BASE / "prompts" / "state_block.txt")}


def equivalence_demo():
    """the economic-equivalence table, computed from the FROZEN tracker."""
    buyer = {"action": "counter", "price_per_unit": 0.85, "quantity": 10000,
             "payment_terms": "net30", "conditional_on": None, "message": "b"}
    ctr = {"action": "counter", "price_per_unit": 0.85, "quantity": 10000,
           "payment_terms": "net30", "conditional_on": None, "message": "s"}
    acc = {"action": "accept", "price_per_unit": None, "quantity": None,
           "payment_terms": None, "conditional_on": None, "message": "s"}

    def state():
        s = tracker.new_state()
        s["standing_offer"] = 0.95
        s["unilateral_concessions_used"] = 1
        tracker.update_buyer(s, 3, buyer)
        return s

    a, b = state(), state()
    tracker.update_seller(a, 3, ctr)
    tracker.update_seller_accept(b, 3, buyer)
    strip = lambda evs: [{k: v for k, v in e.items() if k != "via_accept"}
                         for e in evs]
    ca = guard.classify(state(), 3, ctr, buyer)
    cb = guard.classify(state(), 3, acc, buyer)
    return {
        "state_before": tracker.snapshot(state()),
        "counter": {"action": ctr, "events": a["events"],
                    "state_after": tracker.snapshot(a),
                    "verdict": ca["decision"], "blocking": ca["blocking"],
                    "committed_price": ca["committed_price"]},
        "accept": {"action": acc, "events": b["events"],
                   "state_after": tracker.snapshot(b),
                   "verdict": cb["decision"], "blocking": cb["blocking"],
                   "committed_price": cb["committed_price"]},
        "identical_state_after": tracker.snapshot(a) == tracker.snapshot(b),
        "identical_events_ignoring_via_accept":
            strip(a["events"]) == strip(b["events"]),
        "identical_verdict": (ca["decision"], ca["blocking"])
                             == (cb["decision"], cb["blocking"]),
        "identical_committed_price":
            ca["committed_price"] == cb["committed_price"] == 0.85,
    }


def offline_gate():
    p = subprocess.run([sys.executable, str(BASE / "test_offline_p3a.py")],
                       cwd=str(BASE), capture_output=True, text=True)
    return p.returncode == 0, p


def load_env():
    f = BASE / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(f, override=False)
    except ImportError:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return None if (not key or key == PLACEHOLDER_KEY) else key


def make_client(api_key, client_factory=None):
    if not api_key:
        raise SystemExit(f"ANTHROPIC_API_KEY not found; expected it in {BASE / '.env'}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def prompt_hashes():
    ap = arm_prompt_check()
    return {"seller_system_frozen_A_both": ap["A-both_sha16"],
            "seller_system_declared_A_declared": ap["A-declared_sha16"],
            "buyer_system": ap["buyer_prompt_sha16"],
            "state_block": ap["state_block_sha16"]}


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-arm", type=int, default=DEFAULT_N_PER_ARM)
    ap.add_argument("--phase", default="p3a")
    ap.add_argument("--order-seed", type=int, default=None)
    ap.add_argument("--write-plan", action="store_true")
    ap.add_argument("--rewrite-plan", action="store_true",
                    help="regenerate the plan in place. REFUSES if any run "
                         "record exists in the output directory, so a plan "
                         "can never be swapped under collected data.")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-dir", default=None)
    return ap


def main(argv=None, client_factory=None):
    args = build_parser().parse_args(argv)
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    seed = args.order_seed if args.order_seed is not None else config["order_seed"]
    rows, apc = frozen_comparison(), arm_prompt_check()
    out_dir = (pathlib.Path(args.out_dir) if args.out_dir
               else BASE / "runs" / args.phase)
    plan_path = out_dir / xplan.PLAN_FILENAME
    arm_defs = {n: arms.ARMS[n].as_dict() for n in arms.ARM_ORDER}
    st = (BASE / "prompts" / "state_block.txt").read_text(encoding="utf-8")

    if args.write_plan or args.rewrite_plan:
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = [f for f in out_dir.glob("*.json")
                    if f.name != xplan.PLAN_FILENAME]
        if args.rewrite_plan and existing:
            raise SystemExit(
                f"REFUSED: {len(existing)} run record(s) already exist in "
                f"{out_dir}. The plan is the authority for run identity and "
                f"must never be regenerated under collected data.")
        if plan_path.exists() and not args.rewrite_plan:
            raise SystemExit(f"REFUSED: {plan_path} already exists. Use "
                             f"--rewrite-plan (refused once any record "
                             f"exists).")
        doc = xplan.build_plan_document(seed, args.n_per_arm, rows,
                                        prompt_hashes(), arm_defs)
        doc["economic_equivalence"] = equivalence_demo()
        plan_path.write_text(json.dumps(doc, indent=2, default=str),
                             encoding="utf-8")
        print(f"execution plan written (NO api calls): {plan_path}")
        print(f"  seed {doc['order_seed']} | n/arm {doc['n_per_arm']} -> "
              f"{doc['arm_counts']} | total {doc['n_total']}")
        print(f"  plan digest {doc['plan_digest']} | max consecutive "
              f"{doc['max_consecutive_same_arm']}")
        print(f"  first 12 arms {[p['arm'] for p in doc['positions'][:12]]}")
        return 0

    if not args.confirm:
        preview = xplan.build_plan_document(seed, args.n_per_arm, rows,
                                            prompt_hashes(), arm_defs)
        ok, proc = offline_gate()
        eq = equivalence_demo()
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print("cell                : P3-A (commitment surface)")
        print("question            : does explicitly DECLARING that `accept` "
              "creates the same economic\n                      commitment as "
              "directly proposing the buyer's package reduce\n                "
              "      action-path-specific authority failures?")
        print("                      (this is NOT a path-forced comparison: "
              "both arms keep the\n                      full action space. "
              "see the design record section 4.)")
        print(f"phase / output      : {args.phase} -> {out_dir}")
        print(f"model               : {config['model']}   temp "
              f"{config['temperature']}   max_rounds {config['max_rounds']}")
        print(f"enforcement         : NONE in any arm (classification only)")
        print(f"attempts per turn   : {arms.MAX_ATTEMPTS_PER_TURN}")
        print(f"schema              : {protocol_p3a.SCHEMA_VERSION} / "
              f"{ae.SCHEMA_NAME} + {protocol_p3a.SCHEMA_EXTENSION}")
        print("\nPRE-REGISTERED PRIMARY OUTCOME: among runs presenting an "
              "UNAUTHORIZED-ACCEPT\nOPPORTUNITY, the rate at which the seller "
              "TAKES an unauthorized accept.\nDenominator = opportunity, not "
              "runs. Specificity control: the identical\nconstruction on the "
              "counter path. Deal outcome is SECONDARY and is never\nthe "
              "primary measure.")
        print("\nthree layers are recorded and analysed separately:")
        print("  1. OPPORTUNITY  did the decision present an (unauthorized) "
              "accept / counter option?")
        print("  2. SELECTION    which path did the seller take?")
        print("  3. ADHERENCE    conditional on both, was the action "
              "authorized?")
        print("\narms — the ONLY difference is whether the action schema "
              "declares that\n`accept` creates the same commitment as "
              "`counter`:")
        for n in arms.ARM_ORDER:
            a = arms.ARMS[n]
            print(f"  {n:<12} prompt {a.seller_prompt_sha16()}  "
                  f"commitment_semantics_declared={a.commitment_semantics_declared}  "
                  f"action space {a.as_dict()['action_space']}")
        print(f"  A-both is the frozen Study 1 prompt : "
              f"{apc['A-both_is_frozen_study1_prompt']}")
        print(f"  A-declared = frozen bytes + {apc['declared_appended_bytes']} "
              f"appended (prefix preserved: "
              f"{apc['declared_preserves_frozen_prefix']})")
        print(f"  identical action space across arms  : "
              f"{apc['identical_action_space']}")
        print(f"  no arm enforces                     : {apc['no_arm_enforces']}")
        print("\n  the appended paragraph, verbatim:")
        for line in apc["declared_appendix"].splitlines():
            print(f"    {line}")
        print("\n=== ECONOMIC-EQUIVALENCE CHECK (computed from the FROZEN "
              "tracker) ===")
        print(f"  state before both paths: standing_offer "
              f"${eq['state_before']['standing_offer']:.2f}, unilateral used "
              f"{eq['state_before']['unilateral_concessions_used']}/"
              f"{eq['state_before']['unilateral_concessions_allowed']}, buyer "
              f"offer ${eq['state_before']['buyer_offer']['price']:.2f}"
              f"/{eq['state_before']['buyer_offer']['quantity']}"
              f"/net{eq['state_before']['buyer_offer']['days']}")
        for p in ("counter", "accept"):
            print(f"  path {p:<8}: verdict {eq[p]['verdict']} "
                  f"{eq[p]['blocking']}  committed price "
                  f"${eq[p]['committed_price']:.2f}  standing_offer after "
                  f"${eq[p]['state_after']['standing_offer']:.2f}  events "
                  f"{[e['type'] for e in eq[p]['events']]}")
        print(f"  identical tracker state after      : "
              f"{eq['identical_state_after']}")
        print(f"  identical events (ignoring via_accept): "
              f"{eq['identical_events_ignoring_via_accept']}")
        print(f"  identical verdict and price        : "
              f"{eq['identical_verdict']} / {eq['identical_committed_price']}")
        print("\nfrozen byte comparison:")
        for r in rows:
            print(f"  {'OK ' if r['identical'] else 'FAIL'} "
                  f"[{r['group']:<13}] {r['file']:<28} {r['p3a_copy']}  "
                  f"baseline={r['baseline']}")
        print(f"  all frozen files identical : {all(r['identical'] for r in rows)}")
        print("\nexecution plan (preview — write it with --write-plan):")
        print(f"  order seed {preview['order_seed']} | arm counts "
              f"{preview['arm_counts']} | total {preview['n_total']}")
        print(f"  plan digest {preview['plan_digest']} | max consecutive "
              f"{preview['max_consecutive_same_arm']}")
        print(f"  plan on disk {plan_path.exists()} ({plan_path})")
        print(f"\noffline gate        : {'PASS' if ok else 'FAIL'} "
              f"(test_offline_p3a.py)")
        if not ok:
            print(proc.stdout[-2000:], proc.stderr[-2000:])
        print(f"api key present     : {bool(load_env())}")
        print(f"approx api calls    : {args.n_per_arm * 2} negotiations x "
              f"(<= {config['max_rounds']} rounds, 1 seller attempt per turn)")
        print("\nNO API CALLS WERE MADE.")
        return 0

    # ---------------- confirmed run: gates first ----------------
    if not all(r["identical"] for r in rows):
        raise SystemExit("REFUSED: frozen files are not byte-identical.")
    if not apc["A-both_is_frozen_study1_prompt"]:
        raise SystemExit("REFUSED: A-both is not the frozen Study 1 prompt.")
    if not apc["declared_preserves_frozen_prefix"]:
        raise SystemExit("REFUSED: A-declared does not preserve the frozen "
                         "seller_system.txt prefix.")
    if not apc["identical_action_space"] or not apc["no_arm_enforces"]:
        raise SystemExit("REFUSED: the arms do not share one unenforced "
                         "action space.")
    ok, proc = offline_gate()
    if not ok:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit("REFUSED: the offline suite did not pass.")
    if not plan_path.exists():
        raise SystemExit(f"REFUSED: no execution plan at {plan_path}. run "
                         f"`python run_p3a.py --write-plan` first.")
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_ok, checks = xplan.verify_plan_document(doc)
    if not plan_ok:
        raise SystemExit(f"REFUSED: the stored plan does not regenerate from "
                         f"its own seed: {checks}")
    if doc["plan_digest"] != xplan.plan_digest(
            xplan.make_plan(seed, doc["n_per_arm"])):
        raise SystemExit("REFUSED: --order-seed does not match the stored plan.")
    # the plan digest covers only (position -> arm). It CANNOT detect a change
    # to model-visible bytes, so the stored prompt-hash manifest is verified
    # against the live one separately.
    if doc.get("prompt_hashes") != prompt_hashes():
        raise SystemExit(
            f"REFUSED: the stored plan's prompt hashes do not match the "
            f"current ones. Model-visible bytes changed after the plan was "
            f"written.\n  stored : {doc.get('prompt_hashes')}\n  current: "
            f"{prompt_hashes()}")
    if doc.get("frozen_comparison") != rows:
        raise SystemExit("REFUSED: the stored plan's frozen manifest does not "
                         "match the current one.")

    todo = xplan.pending_positions(doc, out_dir, args.limit)
    if not todo:
        print(f"plan {doc['plan_digest']}: all {len(doc['positions'])} "
              f"positions already on disk. nothing to run, no api calls made.")
        return 0
    client = make_client(load_env(), client_factory)
    import anthropic
    buyer_prompt = (BASE / "prompts" / "buyer_system.txt").read_text(
        encoding="utf-8")
    ph = prompt_hashes()
    remaining = len(doc["positions"]) - len(
        xplan.pending_positions(doc, out_dir))
    print(f"plan {doc['plan_digest']}: {len(doc['positions'])} positions, "
          f"{remaining} already on disk, running {len(todo)}")

    for p in todo:
        arm = arms.ARMS[p["arm"]]
        run_id = p["run_id"]
        buyer = Agent("buyer", buyer_prompt, config, client)
        seller = Agent("seller", arm.seller_prompt(), config, client)
        record = protocol_p3a.run_negotiation_p3a(arm, buyer, seller, config, st)
        for e in record["action_events"]:
            e["run_id"] = run_id
        record.update({
            "run_id": run_id, "phase": args.phase,
            "plan_position": p["position"], "plan_block": p["block"],
            "plan_digest": doc["plan_digest"], "order_seed": doc["order_seed"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": config, "prompt_hashes": ph, "frozen_comparison": rows,
            "arm_prompt_check": {k: v for k, v in apc.items()
                                 if k != "declared_appendix"},
            "resolved_model": {"buyer": buyer.resolved_model,
                               "seller": seller.resolved_model},
            "sdk_version": anthropic.__version__})
        record["scores"] = scoring.score_run(record)
        (out_dir / f"{run_id}.json").write_text(json.dumps(record, indent=2),
                                                encoding="utf-8")
        g, sc = record["summary"], record["scores"]
        bp = g["unauthorized_by_path"]
        print(f"[{p['position']:>3}/{doc['n_total']}] {run_id}: "
              f"unauth counter {bp['counter']['unauthorized_attempted']} "
              f"accept {bp['accept']['unauthorized_attempted']} "
              f"cond {bp['conditional_counter']['unauthorized_attempted']} | "
              f"a/s/c {g['unauthorized_levels']['attempted']}/"
              f"{g['unauthorized_levels']['sent']}/"
              f"{g['unauthorized_levels']['committed']} | "
              f"deal={sc['deal']} ended_by={record['outcome']['ended_by']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
