# run_c3.py — cli for Phase 2 cell C3, arm S3-A.
#
#   python run_c3.py --calibration        deterministic report, no api
#   python run_c3.py --episodes 1-3       dry check + S3-N baseline compare
#   python run_c3.py --episodes 1-3 --confirm
#
# refuses to call the api without --confirm, and refuses episodes beyond 3
# until a human has recorded a gate decision for the first three — the same
# discipline as pilot 2, with its own gate file in this arm's run directory.
# S3-N is NOT re-run: it is pilot2_s3, already collected.

import argparse
import hashlib
import json
import os
import pathlib
import time

import agreement
import calibrate
import episode_read
import mandates
import transcript
import world as w

BASE = pathlib.Path(__file__).resolve().parent
BASELINE = BASE.parent / "03_shared_agreement_state/pilot_2"
BASELINE_MANIFEST = BASELINE / "runs" / "pilot2_s3" / "_run_manifest.json"
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"
FIRST_GATE_EPISODES = (1, 2, 3)
GATE_FILE = "FIRST_GATE_DECISION.json"

EXPECTED_WORLD_HASH = "96fea605d7446f37"
FROZEN_FILES = ("world.py", "mandates.py", "packages.py", "extract.py",
                "transcript.py", "calibrate.py", "agents.py", "episode.py",
                "config.json")

GATE_TEMPLATE = {
    "episode_ids_reviewed": ["<episode ids 1-3>"],
    "manual_review_by": "<name>",
    "manual_review_at": "<iso timestamp>",
    "shared_condition_or_alternative_present": {
        "<episode id>": "<true|false, decided by reading the transcript>"},
    "disturbance_landed_as_designed": None,
    "five_variables_readable": None,
    "both_branches_reachable": None,
    "tool_calls_observed": None,
    "decision": "<proceed | redesign | stop>",
    "rationale": "<one paragraph>",
}
VALID_DECISIONS = ("proceed", "redesign", "stop")


def sha16(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:16]


def baseline_comparison():
    """world hash, all nine prompt hashes, config, update target and priority
    threshold, compared against the recorded pilot2_s3 manifest."""
    here = {"world_hash": w.world_hash(),
            "prompt_hashes": mandates.prompt_hashes(),
            "config": json.loads((BASE / "config.json").read_text(
                encoding="utf-8")),
            "spec_min_pre": w.SPEC_MIN_PRE, "spec_min_post": w.SPEC_MIN_POST,
            "reserve_limit": w.RESERVE_LIMIT}
    rec = None
    if BASELINE_MANIFEST.exists():
        rec = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    out = {"here": here, "recorded_baseline": None, "rows": [], "all_ok": True}
    if rec is None:
        out["all_ok"] = False
        out["rows"].append({"item": "pilot2_s3 manifest", "here": "found: no",
                            "baseline": "MISSING", "ok": False})
        return out
    out["recorded_baseline"] = {"world_hash": rec["world_hash"],
                                "prompt_hashes": rec["prompt_hashes"],
                                "config": rec["config"]}

    def row(item, a, b):
        ok = a == b
        out["rows"].append({"item": item, "here": a, "baseline": b, "ok": ok})
        if not ok:
            out["all_ok"] = False

    row("world_hash", here["world_hash"], rec["world_hash"])
    row("world_hash == expected", here["world_hash"], EXPECTED_WORLD_HASH)
    for n in mandates.PROMPT_NAMES:
        row(f"prompt:{n}", here["prompt_hashes"][n], rec["prompt_hashes"][n])
    for k in ("model", "temperature", "max_tokens", "turn_cap"):
        row(f"config:{k}", here["config"][k], rec["config"][k])
    row("update target volume_A", here["spec_min_post"], 7000)
    row("priority threshold (reserve limit)", here["reserve_limit"], 5000)
    row("pre-update spec minimum", here["spec_min_pre"], 4000)
    for f in FROZEN_FILES:
        row(f"file:{f}", sha16(BASE / f),
            sha16(BASELINE / f) if (BASELINE / f).exists() else None)
    return out


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
            f"`ANTHROPIC_API_KEY=<your key>` in:\n  {BASE / '.env'}\n"
            f"file present = {(BASE / '.env').exists()}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def parse_range(s):
    if "-" in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s)]


def read_gate(out_dir):
    p = out_dir / GATE_FILE
    if not p.exists():
        return None, f"no {GATE_FILE} in {p.parent}"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"{GATE_FILE} is not valid json: {e}"
    missing = [k for k in GATE_TEMPLATE if k not in d]
    if missing:
        return None, f"{GATE_FILE} missing fields: {missing}"
    if d["decision"] not in VALID_DECISIONS:
        return None, f"decision must be one of {VALID_DECISIONS}"
    who = str(d.get("manual_review_by", ""))
    if not who.strip() or who.startswith("<"):
        return None, "manual_review_by must name the person who read the transcripts"
    return d, None


def gate(episodes, out_dir):
    later = [e for e in episodes if e not in FIRST_GATE_EPISODES]
    if not later:
        return ["episodes 1-3: first discovery block"]
    done = {int(p.stem.split("_ep")[-1]) for p in out_dir.glob("*_ep*.json")}
    missing = [e for e in FIRST_GATE_EPISODES if e not in done]
    if missing:
        raise SystemExit(f"REFUSED: episodes {later} requested but {missing} "
                         f"have not completed.")
    d, err = read_gate(out_dir)
    if d is None:
        (out_dir / GATE_FILE.replace(".json", ".template.json")).write_text(
            json.dumps(GATE_TEMPLATE, indent=2), encoding="utf-8")
        raise SystemExit(
            f"REFUSED: {err}\nepisodes 1-3 are complete. a human must read the "
            f"three transcripts and record the gate decision, including whether "
            f"a genuinely SHARED conditional or alternative structure was "
            f"present per episode. that cannot come from the candidate "
            f"extractor. a template has been written next to this file.")
    if d["decision"] != "proceed":
        raise SystemExit(f"REFUSED: recorded decision is '{d['decision']}'.")
    return [f"recorded gate decision: proceed, by {d['manual_review_by']}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="1-3")
    ap.add_argument("--phase", default="c3_s3a")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--calibration", action="store_true")
    args = ap.parse_args()

    if args.calibration:
        text, checks = calibrate.report()
        print(text)
        return

    api_key = load_env()
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    out_dir = BASE / "runs" / args.phase
    episodes = parse_range(args.episodes)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes = gate(episodes, out_dir)

    seller_system = mandates.render_seller_system()
    buyer_system = mandates.render_buyer_system()
    hashes = mandates.prompt_hashes()
    _, checks = calibrate.report()
    cmp_ = baseline_comparison()

    if not args.confirm:
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print(f"cell / arm         : C3 / S3-A")
        print(f"before arm         : S3-N (pilot2_s3, already collected, "
              f"NOT re-run)")
        print(f"phase              : {args.phase}")
        print(f"episodes           : {episodes}")
        print(f"model              : {cfg['model']}  (same model both sides)")
        print(f"temperature        : {cfg['temperature']}")
        print(f"max_tokens         : {cfg['max_tokens']}")
        print(f"turn cap           : {cfg['turn_cap']}"
              f" ({cfg['turn_cap'] // 2} each)")
        print(f"variables          : {list(w.VARIABLES)}")
        print(f"world hash         : {w.world_hash()}")
        print(f"calibration checks : "
              f"{'ALL PASS' if all(checks.values()) else checks}")
        print(f"update target      : volume_A -> {w.SPEC_MIN_POST:,}"
              f" (delivered to buyer only, after the first complete agreement)")
        print(f"priority threshold : Grade A <= {w.RESERVE_LIMIT:,}")
        print("\nS3-N baseline comparison (design gate 4):")
        for r in cmp_["rows"]:
            print(f"  {'OK ' if r['ok'] else 'FAIL'} {r['item']:<38} "
                  f"{r['here']}  baseline={r['baseline']}")
        print(f"  all identical to S3-N : {cmp_['all_ok']}")
        print("\nthe one addition:")
        print(f"  tool               : {agreement.TOOL_NAME}"
              f"  views={list(agreement.VIEWS)}")
        print(f"  offered to         : both agents, symmetrically")
        print(f"  delivered via      : the api `tools` parameter — NOT any "
              f"prompt file, which is why all nine prompt hashes are unchanged")
        print(f"  optional           : no instruction to call it, no reminder, "
              f"no automatic injection of agreement state anywhere")
        print(f"  during probes      : withdrawn, so the probes still measure "
              f"recall")
        print(f"  committed at       : each mutual close on a single complete "
              f"package; version 1 is the existing first_agreement record")
        for n in notes:
            print(f"gate               : {n}")
        print(f"\napi key present    : {bool(api_key)}")
        print(f"output dir         : {out_dir}")
        print("\nharness will NOT: supply agreement semantics, decide whether a")
        print("communicated condition lapses, or auto-decide study 3")
        print("eligibility. every episode record carries")
        print("study3_eligibility = 'pending_manual_review'.")
        print(f"\napprox api calls   : {len(episodes)} x"
              f" (<= {cfg['turn_cap']} turns + 6 probe calls + one extra call "
              f"per tool use)")
        return

    if not cmp_["all_ok"]:
        raise SystemExit("REFUSED: this arm is not byte-identical to the S3-N "
                         "baseline. see the dry check for the failing rows.")

    client = make_client(api_key)
    import anthropic
    prompts = {n: mandates.load(n) for n in mandates.PROMPT_NAMES}

    (out_dir / "_run_manifest.json").write_text(json.dumps({
        "cell": "C3", "arm": "S3-A",
        "simulated_primitive": ("simulated Passport primitive interfaces based "
                                "on current design materials"),
        "phase": args.phase, "episodes": episodes, "config": cfg,
        "world_spec": w.spec(), "world_hash": w.world_hash(),
        "calibration_checks": checks, "prompt_hashes": hashes,
        "baseline_comparison": cmp_, "gate_notes": notes,
        "tool_spec": agreement.TOOL_SPEC,
        "sdk_version": anthropic.__version__,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "not_included": [
            "agreement state injected into any prompt or turn",
            "commit notification", "reminder that the tool exists",
            "instruction on when to call it",
            "automatic diff between committed version and proposal",
            "tool availability during the post-close probes",
            "semantic resolution supplied to agents", "scoring",
            "frozen metrics", "cross-model cell"],
    }, indent=2), encoding="utf-8")

    for n in episodes:
        eid = f"{args.phase}_ep{n:02d}"
        print(f"running {eid} ...", flush=True)
        rec = episode_read.run_episode_read(eid, cfg, prompts, client,
                                            seller_system, buyer_system)
        rec.update({"phase": args.phase, "episode_number": n, "config": cfg,
                    "prompt_hashes": hashes, "world_spec": w.spec(),
                    "baseline_comparison": cmp_,
                    "sdk_version": anthropic.__version__})
        (out_dir / f"{eid}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / f"{eid}_transcript.md").write_text(
            transcript.render(rec), encoding="utf-8")
        u = rec["principal_update"] or {}
        a = rec["agreement_record"]
        print(f"  {rec['termination']['mode']} at turn"
              f" {rec['termination']['turn_index']} ·"
              f" {len(rec['turns'])} turns ·"
              f" update delivered: {u.get('delivered')} ·"
              f" versions committed: {a['versions_committed']} ·"
              f" tool reads: {a['reads_total']} {a['reads_by_caller']}")
        print(f"  -> {eid}.json / {eid}_transcript.md")

    print("\nNo metrics computed and no eligibility decided, by design.")
    print("Zero tool reads is a result, not a failure.")
    print(f"Read the transcripts by hand, then record {GATE_FILE}.")


if __name__ == "__main__":
    main()
