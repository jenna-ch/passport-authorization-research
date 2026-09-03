# run_p3b2.py — cli for Phase 3 cell P3-B2 (refusal information isolation).
#
#   python run_p3b2.py                dry check + arm-difference audit. NO api calls.
#   python run_p3b2.py --write-plan   write the execution plan. NO api calls.
#   python run_p3b2.py --confirm      run the plan. api calls.
#
# --confirm REFUSES unless ALL hold:
#   1. every frozen Study 1 file is byte-identical to 01_delegated_authority/;
#   2. every frozen C1 / P3-B component is byte-identical to its source;
#   3. all four arms resolve to the SAME seller system prompt bytes, and those
#      bytes are the frozen Study 1 prompt;
#   4. the offline suite exits 0;
#   5. the execution plan exists on disk and regenerates from its stored seed.
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
import protocol_p3b2
import refusals
import scoring
import tracker
from agents import Agent

BASE = pathlib.Path(__file__).resolve().parent
S1_BASELINE = BASE.parent / "01_delegated_authority"
C1_BASELINE = BASE.parent / "04_authority_guard"
P3B_BASELINE = BASE.parent / "07_enforcement_recovery"
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"
DEFAULT_N_PER_ARM = 20

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
FROZEN_C1 = {"guard.py": "guard.py",
             "protocol_guard.py": "protocol_guard.py",
             "frozen_eligibility.py": "frozen_eligibility.py"}
# reused byte-identically from the completed P3-B cell
FROZEN_P3B = {"action_event.py": "action_event.py"}


def sha16(p):
    """None if the file is absent, so a missing baseline REFUSES the run
    rather than raising."""
    p = pathlib.Path(p)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def frozen_comparison():
    rows = []
    for f, exp in FROZEN_S1.items():
        h = sha16(BASE / f)
        b = sha16(S1_BASELINE / f) if (S1_BASELINE / f).exists() else None
        rows.append({"group": "frozen_study1", "file": f, "p3b2_copy": h,
                     "baseline": b, "baseline_path": f"01_delegated_authority/{f}",
                     "expected": exp, "identical": h == b == exp})
    for f, src in FROZEN_C1.items():
        h, b = sha16(BASE / f), sha16(C1_BASELINE / src)
        rows.append({"group": "frozen_c1", "file": f, "p3b2_copy": h,
                     "baseline": b, "baseline_path": f"04_authority_guard/{src}",
                     "expected": b,
                     "identical": h is not None and h == b})
    for f, src in FROZEN_P3B.items():
        h, b = sha16(BASE / f), sha16(P3B_BASELINE / src)
        rows.append({"group": "frozen_p3b", "file": f, "p3b2_copy": h,
                     "baseline": b,
                     "baseline_path": f"07_enforcement_recovery/{src}",
                     "expected": b,
                     "identical": h is not None and h == b})
    return rows


def state_template():
    return (BASE / "prompts" / "state_block.txt").read_text(encoding="utf-8")


def arm_prompt_check():
    """the isolation requirement: ALL FOUR arms, one prompt."""
    frozen = (BASE / "prompts" / "seller_system.txt").read_bytes()
    per_arm = {n: arms.ARMS[n].seller_prompt().encode("utf-8")
               for n in arms.ARM_ORDER}
    return {
        "distinct_seller_prompts_across_arms": len(set(per_arm.values())),
        "all_arms_byte_identical": len(set(per_arm.values())) == 1,
        "equals_frozen_study1_prompt": all(v == frozen for v in per_arm.values()),
        "seller_prompt_sha16": sha16(BASE / "prompts" / "seller_system.txt"),
        "no_arm_announces_enforcement": all(
            not a.enforcement_announced for a in arms.ARMS.values()),
        "no_arm_exposes_escalate": all(
            "escalate" not in a.seller_prompt().lower()
            for a in arms.ARMS.values()),
    }


def audit_rows():
    """the arm-difference audit. computed from the RENDERED text, not asserted."""
    st = state_template()
    s = tracker.new_state()
    s["standing_offer"] = 0.95
    s["unilateral_concessions_used"] = 1
    s["buyer_offer"] = {"price": 0.85, "quantity": 10000, "days": 30}
    cls = {"blocking": ["unauthorized_concession"]}
    out = {}
    labels = [ln.split(":")[0].lstrip("- ").strip().lower()
              for ln in st.splitlines() if ln.strip().startswith("-")]
    for n in arms.ARM_ORDER:
        t = arms.ARMS[n].render_refusal(s, cls, st)
        low = t.lower()
        out[n] = {
            "text": t,
            "sha16": hashlib.sha256(t.encode("utf-8")).hexdigest()[:16],
            "template_sha16": arms.ARMS[n].template_sha16(st),
            "enforcement_existence": ("implied (a reason reveals that "
                                      "something evaluated the action)"
                                      if refusals.FACTORS[n]["reason"] else "no"),
            "generic_failure": refusals.NEUTRAL in t,
            "violated_rule_reason": refusals.REASON_UNAUTHORIZED in t,
            "current_mandate_state": st.splitlines()[0] in t,
            "explicit_repair_instruction": any(
                p in low for p in ("you may propose", "you may ", "please ",
                                   "try ", "instead", "in order to")),
            "reciprocal_value_requirements": (
                "requirement named" if refusals.REASON_UNAUTHORIZED in t
                else ("status field only" if st.splitlines()[0] in t else "no")),
            "numeric_private_mandate_values": any(ch.isdigit() for ch in t),
            "state_field_labels_present": sum(1 for l in labels if l in low),
        }
    return out


def offline_gate():
    p = subprocess.run([sys.executable, str(BASE / "test_offline_p3b2.py")],
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
        raise SystemExit(f"ANTHROPIC_API_KEY not found; expected it in "
                         f"{BASE / '.env'}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def prompt_hashes():
    st = state_template()
    return {"seller_system_frozen_all_arms": sha16(BASE / "prompts" / "seller_system.txt"),
            "buyer_system": sha16(BASE / "prompts" / "buyer_system.txt"),
            "state_block": sha16(BASE / "prompts" / "state_block.txt"),
            **{f"refusal_template_{n}": arms.ARMS[n].template_sha16(st)
               for n in arms.ARM_ORDER}}


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-arm", type=int, default=DEFAULT_N_PER_ARM)
    ap.add_argument("--phase", default="p3b2")
    ap.add_argument("--order-seed", type=int, default=None)
    ap.add_argument("--write-plan", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-dir", default=None,
                    help="override the output directory; used by the offline "
                         "suite so its gate checks never write into the "
                         "experiment tree.")
    return ap


def main(argv=None, client_factory=None):
    args = build_parser().parse_args(argv)
    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    seed = args.order_seed if args.order_seed is not None else config["order_seed"]
    rows = frozen_comparison()
    apc = arm_prompt_check()
    out_dir = (pathlib.Path(args.out_dir) if args.out_dir
               else BASE / "runs" / args.phase)
    plan_path = out_dir / xplan.PLAN_FILENAME
    st = state_template()
    arm_defs = {n: arms.ARMS[n].as_dict(st) for n in arms.ARM_ORDER}

    if args.write_plan:
        out_dir.mkdir(parents=True, exist_ok=True)
        if plan_path.exists():
            raise SystemExit(f"REFUSED: {plan_path} already exists; the plan "
                             f"is written once and is the authority for run "
                             f"identity.")
        doc = xplan.build_plan_document(seed, args.n_per_arm, rows,
                                        prompt_hashes(), arm_defs)
        plan_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"execution plan written (NO api calls): {plan_path}")
        print(f"  seed            : {doc['order_seed']}")
        print(f"  n per arm       : {doc['n_per_arm']} -> {doc['arm_counts']}")
        print(f"  total positions : {doc['n_total']}")
        print(f"  plan digest     : {doc['plan_digest']}")
        print(f"  max consecutive : {doc['max_consecutive_same_arm']}")
        print(f"  first 12 arms   : {[p['arm'] for p in doc['positions'][:12]]}")
        return 0

    if not args.confirm:
        preview = xplan.build_plan_document(seed, args.n_per_arm, rows,
                                            prompt_hashes(), arm_defs)
        ok, proc = offline_gate()
        aud = audit_rows()
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print("cell                : P3-B2 (refusal information isolation)")
        print("follows             : P3-B (completed). this cell holds the "
              "seller prompt CONSTANT and varies only the refusal.")
        print(f"phase / output      : {args.phase} -> {out_dir}")
        print(f"model               : {config['model']}   temp "
              f"{config['temperature']}   max_rounds {config['max_rounds']}")
        print(f"attempt cap         : {arms.MAX_ATTEMPTS_PER_TURN} "
              f"(P3-B used 3)")
        print(f"schema              : {protocol_p3b2.SCHEMA_VERSION} / "
              f"{ae.SCHEMA_NAME} + {protocol_p3b2.SCHEMA_EXTENSION}")
        print("\nPRE-REGISTERED PRIMARY OUTCOME: for runs containing a first")
        print("blocked action, did the IMMEDIATELY FOLLOWING attempt become")
        print("authorized? run level, one observation per run. later retries,")
        print("guard exhaustion, deal rate and price are SECONDARY only.")
        print("\nisolation check — the seller system prompt:")
        print(f"  distinct prompts across the 4 arms : "
              f"{apc['distinct_seller_prompts_across_arms']}")
        print(f"  all arms byte-identical            : {apc['all_arms_byte_identical']}")
        print(f"  equals frozen Study 1 prompt       : "
              f"{apc['equals_frozen_study1_prompt']} "
              f"({apc['seller_prompt_sha16']})")
        print(f"  no arm announces enforcement       : "
              f"{apc['no_arm_announces_enforcement']}")
        print(f"  no arm exposes `escalate`          : {apc['no_arm_exposes_escalate']}")
        print("\n=== EXACT MODEL-VISIBLE REFUSAL TEXT, ALL FOUR ARMS ===")
        for n in arms.ARM_ORDER:
            f = refusals.FACTORS[n]
            print(f"\n---------- {n}  (reason={f['reason']}, state={f['state']}) "
                  f" template {aud[n]['template_sha16']} ----------")
            print(aud[n]["text"])
        print("\n=== ARM-DIFFERENCE AUDIT ===")
        keys = [("enforcement_existence", "enforcement existence"),
                ("generic_failure", "generic failure"),
                ("violated_rule_reason", "violated-rule reason"),
                ("current_mandate_state", "current mandate state"),
                ("explicit_repair_instruction", "explicit repair instruction"),
                ("reciprocal_value_requirements", "reciprocal-value requirements"),
                ("numeric_private_mandate_values", "numeric/private mandate values")]
        print(f"  {'component':<32} {'R0':<12} {'R1':<12} {'R2':<12} {'R3':<12}")
        for k, label in keys:
            print(f"  {label:<32} " + " ".join(
                f"{str(aud[n][k]):<12}" for n in arms.ARM_ORDER))
        print(f"  {'state field labels present':<32} " + " ".join(
            f"{str(aud[n]['state_field_labels_present']):<12}"
            for n in arms.ARM_ORDER))
        print("\nfrozen byte comparison:")
        for r in rows:
            print(f"  {'OK ' if r['identical'] else 'FAIL'} "
                  f"[{r['group']:<13}] {r['file']:<28} {r['p3b2_copy']}  "
                  f"baseline={r['baseline']}")
        print(f"  all frozen files identical : {all(r['identical'] for r in rows)}")
        print("\nexecution plan (preview — write it with --write-plan):")
        print(f"  order seed      : {preview['order_seed']}")
        print(f"  arm counts      : {preview['arm_counts']}")
        print(f"  total positions : {preview['n_total']}")
        print(f"  plan digest     : {preview['plan_digest']}")
        print(f"  max consecutive : {preview['max_consecutive_same_arm']}")
        print(f"  plan on disk    : {plan_path.exists()} ({plan_path})")
        print(f"\noffline gate        : {'PASS' if ok else 'FAIL'} "
              f"(test_offline_p3b2.py)")
        if not ok:
            print(proc.stdout[-2000:], proc.stderr[-2000:])
        print(f"api key present     : {bool(load_env())}")
        print(f"approx api calls    : {args.n_per_arm * 4} negotiations x "
              f"(<= {config['max_rounds']} rounds x up to "
              f"{arms.MAX_ATTEMPTS_PER_TURN} seller attempts + buyer turns "
              f"from round 4)")
        print("\nNO API CALLS WERE MADE.")
        return 0

    # ---------------- confirmed run: gates first ----------------
    if not all(r["identical"] for r in rows):
        raise SystemExit("REFUSED: frozen files are not byte-identical to "
                         "their baselines.")
    if not (apc["all_arms_byte_identical"] and apc["equals_frozen_study1_prompt"]):
        raise SystemExit("REFUSED: the four arms do not share one seller "
                         "system prompt equal to the frozen Study 1 bytes. "
                         "The isolation requirement is violated.")
    if not apc["no_arm_announces_enforcement"]:
        raise SystemExit("REFUSED: an arm announces enforcement in advance.")
    ok, proc = offline_gate()
    if not ok:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit("REFUSED: the offline suite did not pass.")
    if not plan_path.exists():
        raise SystemExit(f"REFUSED: no execution plan at {plan_path}. run "
                         f"`python run_p3b2.py --write-plan` first.")
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_ok, checks = xplan.verify_plan_document(doc)
    if not plan_ok:
        raise SystemExit(f"REFUSED: the stored execution plan does not "
                         f"regenerate from its own seed: {checks}")
    if doc["plan_digest"] != xplan.plan_digest(
            xplan.make_plan(seed, doc["n_per_arm"])):
        raise SystemExit("REFUSED: --order-seed does not match the stored plan.")

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
    print(f"plan {doc['plan_digest']}: {len(doc['positions'])} positions, "
          f"{len(doc['positions']) - len(todo)} already on disk, "
          f"running {len(todo)}")

    for p in todo:
        arm = arms.ARMS[p["arm"]]
        run_id = p["run_id"]
        buyer = Agent("buyer", buyer_prompt, config, client)
        seller = Agent("seller", arm.seller_prompt(), config, client)
        record = protocol_p3b2.run_negotiation_p3b2(arm, buyer, seller, config,
                                                    st)
        for e in record["action_events"]:
            e["run_id"] = run_id
        record.update({
            "run_id": run_id, "phase": args.phase,
            "plan_position": p["position"], "plan_block": p["block"],
            "plan_digest": doc["plan_digest"], "order_seed": doc["order_seed"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": config, "prompt_hashes": ph, "frozen_comparison": rows,
            "arm_prompt_check": apc,
            "resolved_model": {"buyer": buyer.resolved_model,
                               "seller": seller.resolved_model},
            "sdk_version": anthropic.__version__,
        })
        record["scores"] = scoring.score_run(record)
        (out_dir / f"{run_id}.json").write_text(json.dumps(record, indent=2),
                                                encoding="utf-8")
        g, sc, v = record["summary"], record["scores"], record["validity"]
        pr = g["primary_outcome"]
        u = g["unauthorized_levels"]
        print(f"[{p['position']:>3}/{doc['n_total']}] {run_id}: "
              f"blocked={g['attempts_blocked']} "
              f"PRIMARY={'n/a' if not pr['applicable'] else ('repaired' if pr['first_retry_repaired'] else 'not_repaired')}"
              f"({pr['first_retry_class']}) "
              f"unauth(a/s/c)={u['attempted']}/{u['sent']}/{u['committed']} "
              f"deal={sc['deal']} ended_by={record['outcome']['ended_by']} "
              f"base_elig={v['baseline_comparable_eligible']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
