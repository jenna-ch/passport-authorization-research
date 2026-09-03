# run_p3d2.py — cli for Phase 3 cell P3-D2 (mandate refresh). THE LAST CELL.
#
#   python run_p3d2.py                dry check. NO api calls, ever.
#   python run_p3d2.py --dry-run-loop offline state-machine dry run through the
#                                     full episode machine. NO api calls.
#   python run_p3d2.py --write-plan   write the frozen execution plan. NO api
#                                     calls.
#   python run_p3d2.py --confirm --limit 12    the 12-run gate. api calls.
#   python run_p3d2.py --confirm      the remaining positions. api calls.
#
# --confirm REFUSES to start unless ALL of these hold:
#   1. every frozen Study 3 file in frozen/ is byte-identical to
#      05_optional_agreement_read/ — world, packages, mandates, agents, episode, extract,
#      config and the whole prompt set;
#   2. the two P3-D2 constant prompt files hash to their recorded values
#      (principal update 941c2ade9bd5ee21, provider amendment 7f02e53a9eb05267);
#   3. the offline suite (test_offline_p3d2.py) exits 0;
#   4. the execution plan exists on disk, regenerates exactly from its stored
#      seed, and its stored prompt/frozen manifest matches the live files;
#   5. model, temperature, max_tokens and turn_cap match frozen config.json.
#
# It never overwrites an existing run record, and the plan can never be
# rewritten once any record exists.

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

import action_event as ae
import agents_p3d2 as AP
import arms
import episode_p3d2 as EP
import execution_plan as xplan
import identity as ID
import mandate as M
import proposal as PR

BASE = pathlib.Path(__file__).resolve().parent
FROZEN_SRC = BASE.parent / "05_optional_agreement_read"
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"

FROZEN_FILES = ("world.py", "packages.py", "mandates.py", "agents.py",
                "episode.py", "extract.py", "config.json")
P3D2_PROMPTS = {
    "principal_update_authority.txt": "941c2ade9bd5ee21",
    "provider_amendment.txt": "7f02e53a9eb05267",
    "ack_action_schema.txt": None,      # recorded, not pinned by hand
}


def sha16(path):
    p = pathlib.Path(path)
    return (hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists()
            else None)


def frozen_comparison():
    rows = []
    for f in FROZEN_FILES:
        here, there = sha16(BASE / "frozen" / f), sha16(FROZEN_SRC / f)
        rows.append({"group": "frozen_study3", "file": f, "p3d2_copy": here,
                     "baseline": there,
                     "baseline_path": f"05_optional_agreement_read/{f}",
                     "identical": here == there and here is not None})
    for p in sorted((FROZEN_SRC / "prompts").glob("*.txt")):
        here = sha16(BASE / "frozen" / "prompts" / p.name)
        there = sha16(p)
        rows.append({"group": "frozen_study3_prompts",
                     "file": f"prompts/{p.name}", "p3d2_copy": here,
                     "baseline": there,
                     "baseline_path": f"05_optional_agreement_read/prompts/{p.name}",
                     "identical": here == there and here is not None})
    for f, pinned in P3D2_PROMPTS.items():
        here = sha16(BASE / "prompts" / f)
        rows.append({"group": "p3d2_constant_prompts", "file": f"prompts/{f}",
                     "p3d2_copy": here, "baseline": pinned,
                     "baseline_path": "recorded in this file",
                     "identical": (here == pinned if pinned else
                                   here is not None)})
    return rows


def prompt_hashes():
    return {
        "seller_system_frozen": sha16(BASE / "frozen/prompts/seller_system.txt"),
        "buyer_system_frozen": sha16(BASE / "frozen/prompts/buyer_system.txt"),
        "buyer_opening_frozen": sha16(BASE / "frozen/prompts/buyer_opening.txt"),
        "reprompt_frozen": sha16(BASE / "frozen/prompts/reprompt.txt"),
        "principal_update_authority": arms.update_sha16(),
        "provider_amendment": PR.amendment_sha16(),
        "ack_action_schema": sha16(BASE / "prompts/ack_action_schema.txt"),
        "refresh_request_sha16": hashlib.sha256(
            arms.REFRESH_REQUEST.encode()).hexdigest()[:16],
        "ack_recorded_sha16": hashlib.sha256(
            EP.ACK_RECORDED.encode()).hexdigest()[:16],
        "ack_rejected_sha16": hashlib.sha256(
            EP.ACK_REJECTED.encode()).hexdigest()[:16],
        "rendered_seller_system": hashlib.sha256(
            prompts()["seller_system"].encode()).hexdigest()[:16],
        "rendered_buyer_system": hashlib.sha256(
            prompts()["buyer_system"].encode()).hexdigest()[:16],
    }


def prompts():
    sys.path.insert(0, str(BASE / "frozen"))
    import mandates as fm
    return {
        "seller_system": fm.render_seller_system(),
        "buyer_system": fm.render_buyer_system(),
        "buyer_opening": fm.load("buyer_opening"),
        "reprompt": fm.load("reprompt"),
        "ack_action_schema": (BASE / "prompts" / "ack_action_schema.txt")
        .read_text(encoding="utf-8"),
    }


def config_matches_frozen(cfg):
    frozen = json.loads((BASE / "frozen" / "config.json").read_text())
    return {k: cfg[k] == frozen[k]
            for k in ("model", "temperature", "max_tokens", "turn_cap")}


def offline_gate():
    proc = subprocess.run([sys.executable, str(BASE / "test_offline_p3d2.py")],
                          cwd=str(BASE), capture_output=True, text=True)
    return proc.returncode == 0, proc


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
        raise SystemExit(f"ANTHROPIC_API_KEY not found. expected a line "
                         f"`ANTHROPIC_API_KEY=<your key>` in:\n  {BASE / '.env'}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def frozen_records():
    """the 12 frozen Study 3 pilot-2 episodes, for the offline replay path."""
    import glob
    out = []
    for f in sorted(glob.glob(str(BASE.parent / "05_optional_agreement_read/runs/**/*.json"),
                              recursive=True)
                    + glob.glob(str(BASE.parent / "03_shared_agreement_state/pilot_2/runs/**/*.json"),
                                recursive=True)):
        p = pathlib.Path(f)
        if p.name.startswith(("FIRST", "_")):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        fa = r.get("first_agreement")
        if isinstance(fa, dict) and fa.get("package"):
            r["episode_id"] = p.stem
            out.append(r)
    return out


def dry_run_loop(cfg):
    """the OFFLINE state-machine dry run. no client, no key, no network."""
    import stub_client as SC
    recs = frozen_records()
    pr = prompts()
    rows, fps_all = [], []
    for r in recs:
        fps = {}
        for arm in arms.ARM_ORDER:
            out = SC.drive(r, arm, "decline", cfg)
            fps[arm] = ID.pre_update_fingerprint(out, pr)
        rows.append(ID.equality_row(r["episode_id"], fps))
        fps_all.append(fps)
    scen = []
    r0 = recs[0]
    for arm in arms.ARM_ORDER:
        for name in SC.SCENARIOS:
            out = SC.drive(r0, arm, name, cfg)
            p = out["primary"]
            d = p.get("decomposition") or {}
            scen.append({
                "arm": arm, "scenario": name,
                "locked_turn": p["locked_turn"],
                "stale_authority_attempt": p["stale_authority_attempt"],
                "attempted": p["attempted"], "sent": p["sent"],
                "committed": p["committed"],
                "observed_version": p["agent_observed_version"],
                "refresh_failure": d.get("refresh_failure"),
                "post_refresh_adherence_failure":
                    d.get("post_refresh_adherence_failure"),
                "decomposition_determinate": d.get("decomposition_determinate"),
                "gate_refusals": out["gate_refusals"],
                "termination": out["termination"]["mode"],
                "agreement_version_final":
                    (out["agreement"] or {}).get("agreement_version"),
                "api_client_constructed": False,
                "stub_calls": out["_stub_calls"]})
    return rows, scen


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-arm", type=int, default=None)
    ap.add_argument("--phase", default=None)
    ap.add_argument("--order-seed", type=int, default=None)
    ap.add_argument("--write-plan", action="store_true")
    ap.add_argument("--dry-run-loop", action="store_true",
                    help="offline state-machine dry run. no api calls.")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N unrun plan positions "
                         "(the 12-run gate: --limit 12)")
    return ap


def main(argv=None, client_factory=None):
    args = build_parser().parse_args(argv)
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    seed = args.order_seed if args.order_seed is not None else cfg["order_seed"]
    n_per_arm = args.n_per_arm if args.n_per_arm is not None else cfg["n_per_arm"]
    phase = args.phase or cfg["phase"]
    rows = frozen_comparison()
    cfg_ok = config_matches_frozen(cfg)
    out_dir = (pathlib.Path(args.out_dir) if args.out_dir
               else BASE / "runs" / phase)
    plan_path = out_dir / xplan.PLAN_FILENAME
    arm_defs = {n: arms.ARMS[n].as_dict() for n in arms.ARM_ORDER}

    # ---------------- offline state-machine dry run: NO api calls ----------
    if args.dry_run_loop:
        eq, scen = dry_run_loop(cfg)
        print("OFFLINE STATE-MACHINE DRY RUN — no api client, no network.\n")
        print("12-world pre-update identity across all three arms:")
        for r in eq:
            print(f"  {r['world']:<18} turns={r['turns']:<3} "
                  f"agreement={r['agreement_hash']} v1_ceiling={r['v1_ceiling']:.2f} "
                  f"fields_equal={sum(r['per_field_equal'].values())}/"
                  f"{len(r['per_field_equal'])} ALL_EQUAL={r['all_equal']}")
        print(f"  all 12 worlds identical pre-update in all 3 arms: "
              f"{all(r['all_equal'] for r in eq)}\n")
        print("post-update state machine, all arms x all scenarios:")
        print(f"  {'arm':<10} {'scenario':<18} {'lock':<5} {'stale':<6} "
              f"{'a/s/c':<14} {'obs':<4} {'refr':<6} {'adhr':<6} {'ref':<4} "
              f"{'vN':<3} termination")
        for s in scen:
            print(f"  {s['arm']:<10} {s['scenario']:<18} "
                  f"{str(s['locked_turn']):<5} "
                  f"{str(s['stale_authority_attempt']):<6} "
                  f"{str(s['attempted'])[0]}/{str(s['sent'])[0]}/"
                  f"{str(s['committed'])[0]:<10} "
                  f"{str(s['observed_version']):<4} "
                  f"{str(s['refresh_failure']):<6} "
                  f"{str(s['post_refresh_adherence_failure']):<6} "
                  f"{s['gate_refusals']:<4} "
                  f"{str(s['agreement_version_final']):<3} {s['termination']}")
        print(f"\n  api client constructed : False")
        print(f"  network calls          : 0")
        print(f"  plan written           : False")
        print("\nNO API CALLS WERE MADE.")
        return 0

    # ---------------- plan writing: NO api calls ----------------
    if args.write_plan:
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = xplan.records_exist(out_dir)
        if existing:
            raise SystemExit(
                f"REFUSED: {len(existing)} run record(s) already exist in "
                f"{out_dir}. the plan is the authority for run identity and "
                f"can never be rewritten once a record exists.")
        if plan_path.exists():
            raise SystemExit(
                f"REFUSED: {plan_path} already exists. the plan is written "
                f"once.")
        doc = xplan.build_plan_document(seed, n_per_arm, rows,
                                        prompt_hashes(), arm_defs)
        doc["config"] = cfg
        doc["config_matches_frozen"] = cfg_ok
        plan_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"execution plan written (NO api calls): {plan_path}")
        print(f"  seed              : {doc['order_seed']}")
        print(f"  n per arm         : {doc['n_per_arm']}  -> {doc['arm_counts']}")
        print(f"  total positions   : {doc['n_total']}")
        print(f"  plan digest       : {doc['plan_digest']}")
        print(f"  max consecutive   : {doc['max_consecutive_same_arm']}")
        print(f"  first 12 arms     : {[p['arm'] for p in doc['positions'][:12]]}")
        return 0

    # ---------------- dry check: NO api calls ----------------
    if not args.confirm:
        preview = xplan.build_plan_document(seed, n_per_arm, rows,
                                            prompt_hashes(), arm_defs)
        ok_gate, proc = offline_gate()
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print("cell                : P3-D2 (mandate refresh) — final cell")
        print(f"phase / output      : {phase} -> {out_dir}")
        print(f"model               : {cfg['model']} (same model both sides)")
        print(f"temperature         : {cfg['temperature']}   max_tokens: "
              f"{cfg['max_tokens']}   turn_cap: {cfg['turn_cap']}")
        print(f"config matches frozen: {cfg_ok}")
        print(f"action schema       : {ae.SCHEMA_NAME}  buyer control values: "
              f"{list(AP.CONTROL_VALUES_P3D2)}")
        print(f"gate refusal cap    : {EP.GATE_REFUSAL_CAP}")
        print("\narms — the ONLY intended differences:")
        print(f"  {'arm':<11} {'state block':<12} {'ack gate':<9} mechanism")
        for n in arms.ARM_ORDER:
            a = arms.ARMS[n]
            print(f"  {n:<11} {str(a.state_block):<12} {str(a.ack_gate):<9} "
                  f"{a.as_dict()['refresh_mechanism']}")
        print("\nmandate versions:")
        print(f"  v1 : frozen buyer Grade A ceiling, computed from frozen tables")
        print(f"  v2 : flat cap ${M.NEW_CEILING_A:.2f}, PROSPECTIVE "
              f"(prospective_only={M.PROSPECTIVE_ONLY})")
        print("\nfrozen byte comparison:")
        for r in rows:
            print(f"  {'OK ' if r['identical'] else 'FAIL'} "
                  f"[{r['group']:<22}] {r['file']:<28} {r['p3d2_copy']}  "
                  f"baseline={r['baseline']}")
        print(f"  all identical      : {all(r['identical'] for r in rows)}")
        print("\nexecution plan (preview — write it with --write-plan):")
        print(f"  order seed        : {preview['order_seed']}")
        print(f"  arm counts        : {preview['arm_counts']}")
        print(f"  total positions   : {preview['n_total']}")
        print(f"  plan digest       : {preview['plan_digest']}")
        print(f"  plan on disk      : {plan_path.exists()} ({plan_path})")
        print(f"  records on disk   : {len(xplan.records_exist(out_dir))}")
        print(f"\noffline gate        : "
              f"{'PASS' if ok_gate else 'FAIL'} (test_offline_p3d2.py)")
        if not ok_gate:
            print(proc.stdout[-2000:], proc.stderr[-2000:])
        print(f"api key present     : {bool(load_env())}")
        print(f"approx api calls    : {n_per_arm * 3} episodes x <= "
              f"{cfg['turn_cap']} turns")
        print("\nNO API CALLS WERE MADE.")
        return 0

    # ---------------- confirmed run: gates first ----------------
    if not all(r["identical"] for r in rows):
        raise SystemExit("REFUSED: frozen files are not byte-identical to "
                         "their baselines, or a P3-D2 constant prompt does "
                         "not match its recorded hash.")
    if not all(cfg_ok.values()):
        raise SystemExit(f"REFUSED: config does not match frozen: {cfg_ok}")
    ok_gate, proc = offline_gate()
    if not ok_gate:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit("REFUSED: the offline suite did not pass.")
    if not plan_path.exists():
        raise SystemExit(f"REFUSED: no execution plan at {plan_path}. run "
                         f"`python run_p3d2.py --write-plan` first.")
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_ok, plan_checks = xplan.verify_plan_document(doc)
    if not plan_ok:
        raise SystemExit(f"REFUSED: the stored plan does not regenerate from "
                         f"its own seed: {plan_checks}")
    if doc["plan_digest"] != xplan.plan_digest(
            xplan.make_plan(seed, doc["n_per_arm"])):
        raise SystemExit("REFUSED: --order-seed does not match the stored plan.")
    live_ph = prompt_hashes()
    if doc.get("prompt_hashes") != live_ph:
        diff = {k: (doc.get("prompt_hashes", {}).get(k), v)
                for k, v in live_ph.items()
                if doc.get("prompt_hashes", {}).get(k) != v}
        raise SystemExit(f"REFUSED: live prompt hashes differ from the stored "
                         f"plan manifest (stored, live): {diff}")
    stored_frozen = {(r["group"], r["file"]): r["p3d2_copy"]
                     for r in doc.get("frozen_comparison", [])}
    live_frozen = {(r["group"], r["file"]): r["p3d2_copy"] for r in rows}
    if stored_frozen != live_frozen:
        raise SystemExit("REFUSED: live frozen-file hashes differ from the "
                         "stored plan manifest.")

    # resumption is by PLAN POSITION, computed BEFORE any client exists.
    pending = xplan.pending_positions(doc, out_dir, None)
    todo = pending[:args.limit] if args.limit is not None else pending
    on_disk = len(doc["positions"]) - len(pending)
    print(f"plan {doc['plan_digest']}: {len(doc['positions'])} positions, "
          f"{on_disk} already on disk, {len(pending)} pending, "
          f"running {len(todo)}"
          + (f" (--limit {args.limit})" if args.limit is not None else ""))
    if not todo:
        print("nothing to run, no api calls made.")
        return 0

    client = make_client(load_env(), client_factory)
    import anthropic
    pr = prompts()
    ph = live_ph

    for p in todo:
        arm = arms.ARMS[p["arm"]]
        run_id = p["run_id"]
        record = EP.run_episode_p3d2(run_id, cfg, pr, client,
                                     pr["seller_system"], pr["buyer_system"],
                                     arm, run_id=run_id)
        record.update({
            "phase": phase, "plan_position": p["position"],
            "plan_block": p["block"], "plan_digest": doc["plan_digest"],
            "order_seed": doc["order_seed"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": cfg, "prompt_hashes": ph, "frozen_comparison": rows,
            "pre_update_fingerprint": ID.pre_update_fingerprint(record, pr),
            "sdk_version": anthropic.__version__,
        })
        (out_dir / f"{run_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8")
        pri, sec = record["primary"], record["secondary"]
        print(f"[{p['position']:>3}/{doc['n_total']}] {run_id}: "
              f"end={record['termination']['mode']} "
              f"lock={pri['locked_turn']} "
              f"stale={pri['stale_authority_attempt']} "
              f"a/s/c={pri['attempted']}/{pri['sent']}/{pri['committed']} "
              f"obs={pri['agent_observed_version']} "
              f"refusals={record['gate_refusals']} "
              f"vN={sec['agreement_version_final']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
