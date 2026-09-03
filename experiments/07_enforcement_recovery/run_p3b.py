# run_p3b.py — cli for Phase 3 cell P3-B (information vs enforcement).
#
#   python run_p3b.py                     dry check. NO api calls, ever.
#   python run_p3b.py --write-plan        write the execution plan to disk.
#                                         NO api calls.
#   python run_p3b.py --confirm           run the plan. api calls.
#
# --confirm REFUSES to start unless ALL of these hold:
#   1. every frozen Study 1 file is byte-identical to 01_delegated_authority/;
#   2. every frozen C1 component is byte-identical to 04_authority_guard/;
#   3. the announced seller prompt is byte-identical to C1's
#      seller_system_guard.txt, and both B-info's and B-silent's prompt is
#      byte-identical to frozen seller_system.txt;
#   4. the offline suite (test_offline_p3b.py) exits 0;
#   5. the execution plan exists on disk and regenerates exactly from its
#      stored seed.
#
# It never overwrites an existing run record.

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
import protocol_p3b
import scoring
from agents import Agent

BASE = pathlib.Path(__file__).resolve().parent
S1_BASELINE = BASE.parent / "01_delegated_authority"
C1_BASELINE = BASE.parent / "04_authority_guard"
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"

DEFAULT_N_PER_ARM = 40

# ---- frozen Study 1 files: must be byte-identical to 01_delegated_authority/ ----
FROZEN_S1 = {
    "agents.py": "b9b8da5946ced705",
    "protocol.py": "304a2dd59e0c6c3b",
    "tracker.py": "285f26c090ec62d7",
    "scoring.py": "5f34d0cedd193db3",
    "config.json": "5752faec21fe6088",
    "prompts/seller_system.txt": "d4005aaea3b9b780",
    "prompts/buyer_system.txt": "2fccc7bc2b403f3a",
    "prompts/state_block.txt": "9ca8af7e68b2474a",
}
# ---- frozen C1 components: must be byte-identical to 04_authority_guard/ ----
# reused unmodified, so that the announced arm IS S1-G and the eligibility
# rule IS the one C1 used.
FROZEN_C1 = {
    "guard.py": "guard.py",
    "protocol_guard.py": "protocol_guard.py",
    "frozen_eligibility.py": "frozen_eligibility.py",
    "prompts/seller_system_announced.txt": "prompts/seller_system_guard.txt",
}


def sha16(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]


def frozen_comparison():
    rows = []
    for f, expected in FROZEN_S1.items():
        here = sha16(BASE / f)
        there = sha16(S1_BASELINE / f) if (S1_BASELINE / f).exists() else None
        rows.append({"group": "frozen_study1", "file": f, "p3b_copy": here,
                     "baseline": there, "baseline_path": f"01_delegated_authority/{f}",
                     "expected": expected,
                     "identical": here == there == expected})
    for f, src in FROZEN_C1.items():
        here = sha16(BASE / f)
        there = sha16(C1_BASELINE / src) if (C1_BASELINE / src).exists() else None
        rows.append({"group": "frozen_c1", "file": f, "p3b_copy": here,
                     "baseline": there, "baseline_path": f"04_authority_guard/{src}",
                     "expected": there, "identical": here == there})
    return rows


def arm_prompt_comparison():
    """the arms' seller prompts, and exactly how they differ."""
    frozen = (BASE / "prompts" / "seller_system.txt").read_bytes()
    announced = (BASE / "prompts" / "seller_system_announced.txt").read_bytes()
    return {
        "B-info_prompt_sha16": sha16(BASE / "prompts" / "seller_system.txt"),
        "B-silent_prompt_sha16": sha16(BASE / "prompts" / "seller_system.txt"),
        "B-announced_prompt_sha16": sha16(
            BASE / "prompts" / "seller_system_announced.txt"),
        "info_and_silent_prompts_byte_identical": True,
        "announced_preserves_frozen_prefix": announced.startswith(frozen),
        "announced_appended_bytes": len(announced) - len(frozen),
        "announced_appendix": announced[len(frozen):].decode("utf-8"),
        "buyer_prompt_sha16": sha16(BASE / "prompts" / "buyer_system.txt"),
        "state_block_sha16": sha16(BASE / "prompts" / "state_block.txt"),
    }


def prompt_hashes():
    ap = arm_prompt_comparison()
    return {
        "seller_system_frozen": ap["B-info_prompt_sha16"],
        "seller_system_announced": ap["B-announced_prompt_sha16"],
        "buyer_system": ap["buyer_prompt_sha16"],
        "state_block": ap["state_block_sha16"],
        "silent_refusal_sha16": hashlib.sha256(
            arms.SILENT_REFUSAL.encode("utf-8")).hexdigest()[:16],
    }


def offline_gate():
    """run the offline suite as a subprocess. exit 0 required for --confirm."""
    proc = subprocess.run(
        [sys.executable, str(BASE / "test_offline_p3b.py")],
        cwd=str(BASE), capture_output=True, text=True)
    return proc.returncode == 0, proc


def load_text(name):
    return (BASE / "prompts" / name).read_text(encoding="utf-8")


def load_env():
    p = BASE / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(p, override=False)
    except ImportError:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return None if (not key or key == PLACEHOLDER_KEY) else key


def make_client(api_key, client_factory=None):
    if not api_key:
        raise SystemExit(
            f"ANTHROPIC_API_KEY not found. expected a line "
            f"`ANTHROPIC_API_KEY=<your key>` in:\n  {BASE / '.env'}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-arm", type=int, default=DEFAULT_N_PER_ARM)
    ap.add_argument("--phase", default="p3b")
    ap.add_argument("--order-seed", type=int, default=None,
                    help="defaults to the frozen config.json order_seed")
    ap.add_argument("--write-plan", action="store_true",
                    help="write the execution plan to disk. no api calls.")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--out-dir", default=None,
                    help="override the output directory. used by the offline "
                         "suite so that its gate checks never write into the "
                         "experiment tree; not used for real runs.")
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N unrun positions of the plan "
                         "(for the 15-run gate: --limit 15)")
    return ap


def main(argv=None, client_factory=None):
    args = build_parser().parse_args(argv)
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    seed = args.order_seed if args.order_seed is not None else config["order_seed"]
    rows = frozen_comparison()
    ap_cmp = arm_prompt_comparison()
    out_dir = (pathlib.Path(args.out_dir) if args.out_dir
               else BASE / "runs" / args.phase)
    plan_path = out_dir / xplan.PLAN_FILENAME
    arm_defs = {n: arms.ARMS[n].as_dict() for n in arms.ARM_ORDER}

    # ---------------- plan writing: NO api calls ----------------
    if args.write_plan:
        out_dir.mkdir(parents=True, exist_ok=True)
        if plan_path.exists():
            raise SystemExit(
                f"REFUSED: {plan_path} already exists. the plan is written "
                f"once and is the authority for run identity; delete it "
                f"manually only if no run has been recorded against it.")
        doc = xplan.build_plan_document(seed, args.n_per_arm, rows,
                                        prompt_hashes(), arm_defs)
        plan_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"execution plan written (NO api calls): {plan_path}")
        print(f"  seed              : {doc['order_seed']}")
        print(f"  n per arm         : {doc['n_per_arm']}  -> {doc['arm_counts']}")
        print(f"  total positions   : {doc['n_total']}")
        print(f"  plan digest       : {doc['plan_digest']}")
        print(f"  max consecutive   : {doc['max_consecutive_same_arm']} "
              f"(block interleaving bounds this at 2)")
        print(f"  first 12 arms     : "
              f"{[p['arm'] for p in doc['positions'][:12]]}")
        return 0

    # ---------------- dry check: NO api calls ----------------
    if not args.confirm:
        preview = xplan.build_plan_document(seed, args.n_per_arm, rows,
                                            prompt_hashes(), arm_defs)
        ok_gate, proc = offline_gate()
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print(f"cell                : P3-B (information vs enforcement)")
        print(f"design of record    : phase3_design_of_record.md section 3")
        print(f"phase / output      : {args.phase} -> {out_dir}")
        print(f"model               : {config['model']}  (same model both sides)")
        print(f"temperature         : {config['temperature']}")
        print(f"max_tokens          : {config['max_tokens']}")
        print(f"max_rounds          : {config['max_rounds']}")
        print(f"action schema       : {protocol_p3b.SCHEMA_VERSION} / "
              f"{ae.SCHEMA_NAME}")
        print("\narms — the ONLY intended differences:")
        print(f"  {'arm':<13} {'mandate':<8} {'enforce':<8} {'announce':<9} "
              f"{'escalate':<9} attempts/turn")
        for n in arms.ARM_ORDER:
            a = arms.ARMS[n]
            print(f"  {n:<13} {'live':<8} "
                  f"{str(a.enforcement_active):<8} "
                  f"{str(a.enforcement_announced):<9} "
                  f"{str(a.escalation_available):<9} "
                  f"{protocol_p3b.MAX_ATTEMPTS_PER_TURN if a.enforcement_active else 1}")
        print("\nseller prompts:")
        print(f"  B-info / B-silent    : {ap_cmp['B-info_prompt_sha16']} "
              f"(frozen seller_system.txt, byte-identical to each other)")
        print(f"  B-announced          : {ap_cmp['B-announced_prompt_sha16']} "
              f"(frozen bytes + {ap_cmp['announced_appended_bytes']} appended)")
        print(f"  frozen prefix kept   : "
              f"{ap_cmp['announced_preserves_frozen_prefix']}")
        print("\nB-silent refusal (the only novel model-visible string):")
        print(f"  {arms.SILENT_REFUSAL!r}")
        print("\nfrozen byte comparison:")
        for r in rows:
            print(f"  {'OK ' if r['identical'] else 'FAIL'} "
                  f"[{r['group']:<13}] {r['file']:<38} {r['p3b_copy']}  "
                  f"baseline={r['baseline']}")
        print(f"  all frozen files identical : "
              f"{all(r['identical'] for r in rows)}")
        print("\nexecution plan (preview — write it with --write-plan):")
        print(f"  order seed        : {preview['order_seed']}")
        print(f"  arm counts        : {preview['arm_counts']}")
        print(f"  total positions   : {preview['n_total']}")
        print(f"  plan digest       : {preview['plan_digest']}")
        print(f"  max consecutive   : {preview['max_consecutive_same_arm']}")
        print(f"  plan on disk      : {plan_path.exists()} ({plan_path})")
        print("\ndual denominator — every comparison must name one:")
        print("  baseline_comparable_eligible : the FROZEN Study 1 rule, "
              "unchanged")
        print("  commercial_outcome_eligible  : deal / no-deal, "
              "guard_exhausted cost, termination composition")
        print("  guard_exhausted is a NO DEAL and is never excluded.")
        print("  B-info has no enforcement, so the two coincide there.")
        print(f"\noffline gate        : "
              f"{'PASS' if ok_gate else 'FAIL'} (test_offline_p3b.py)")
        if not ok_gate:
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:])
        print(f"api key present     : {bool(load_env())}")
        print(f"approx api calls    : {args.n_per_arm * 3} negotiations x "
              f"(<= {config['max_rounds']} rounds x up to "
              f"{protocol_p3b.MAX_ATTEMPTS_PER_TURN} seller attempts in the "
              f"enforced arms + buyer turns from round 4)")
        print("\nNO API CALLS WERE MADE.")
        return 0

    # ---------------- confirmed run: gates first ----------------
    if not all(r["identical"] for r in rows):
        raise SystemExit("REFUSED: frozen files are not byte-identical to "
                         "their baselines. P3-B would not be comparable.")
    if not ap_cmp["announced_preserves_frozen_prefix"]:
        raise SystemExit("REFUSED: the announced seller prompt does not start "
                         "with the frozen seller_system.txt bytes.")
    ok_gate, proc = offline_gate()
    if not ok_gate:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit("REFUSED: the offline suite did not pass.")
    if not plan_path.exists():
        raise SystemExit(f"REFUSED: no execution plan at {plan_path}. run "
                         f"`python run_p3b.py --write-plan` first; the plan "
                         f"must be on disk before any confirmed run.")
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_ok, plan_checks = xplan.verify_plan_document(doc)
    if not plan_ok:
        raise SystemExit(f"REFUSED: the stored execution plan does not "
                         f"regenerate from its own seed: {plan_checks}")
    if doc["plan_digest"] != xplan.plan_digest(xplan.make_plan(seed, doc["n_per_arm"])):
        raise SystemExit("REFUSED: --order-seed does not match the stored plan.")

    # resumption is by PLAN POSITION. an existing record is never re-run and
    # never overwritten. computed BEFORE any client is constructed, so a
    # complete batch makes no api call at all.
    todo = xplan.pending_positions(doc, out_dir, args.limit)
    if not todo:
        print(f"plan {doc['plan_digest']}: all "
              f"{len(doc['positions'])} positions already on disk. "
              f"nothing to run, no api calls made.")
        return 0

    api_key = load_env()
    client = make_client(api_key, client_factory)
    import anthropic

    buyer_prompt = load_text("buyer_system.txt")
    state_template = load_text("state_block.txt")
    ph = prompt_hashes()

    print(f"plan {doc['plan_digest']}: {len(doc['positions'])} positions, "
          f"{len(doc['positions']) - len(todo)} already on disk, "
          f"running {len(todo)}")

    for p in todo:
        arm = arms.ARMS[p["arm"]]
        run_id = p["run_id"]
        buyer = Agent("buyer", buyer_prompt, config, client)
        seller = Agent("seller", arm.seller_prompt(), config, client)
        record = protocol_p3b.run_negotiation_p3b(
            arm, buyer, seller, config, state_template)
        for e in record["action_events"]:
            e["run_id"] = run_id
        record.update({
            "run_id": run_id, "phase": args.phase,
            "plan_position": p["position"], "plan_block": p["block"],
            "plan_digest": doc["plan_digest"],
            "order_seed": doc["order_seed"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": config, "prompt_hashes": ph,
            "frozen_comparison": rows,
            "arm_prompt_comparison": {
                k: v for k, v in ap_cmp.items() if k != "announced_appendix"},
            "resolved_model": {"buyer": buyer.resolved_model,
                               "seller": seller.resolved_model},
            "sdk_version": anthropic.__version__,
        })
        # frozen scoring, replayed over RELAYED actions only.
        record["scores"] = scoring.score_run(record)
        (out_dir / f"{run_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8")
        g, sc, v = record["summary"], record["scores"], record["validity"]
        u = g["unauthorized_levels"]
        print(f"[{p['position']:>3}/{doc['n_total']}] {run_id}: "
              f"deal={sc['deal']} ended_by={record['outcome']['ended_by']} "
              f"unauth(att/sent/comm)={u['attempted']}/{u['sent']}/"
              f"{u['committed']} blocked={g['attempts_blocked']} "
              f"esc={g['escalation_requests']} "
              f"base_elig={v['baseline_comparable_eligible']} "
              f"comm_elig={v['commercial_outcome_eligible']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
