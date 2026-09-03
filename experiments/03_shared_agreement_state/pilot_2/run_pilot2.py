# run_pilot2.py — cli for the study 3 second discovery pilot (design v3).
#
#   python run_pilot2.py --calibration          deterministic report, no api
#   python run_pilot2.py --episodes 1-3         dry check, no api
#   python run_pilot2.py --episodes 1-3 --confirm
#
# refuses to call the api without --confirm, and refuses episodes beyond 3
# until a human has recorded a gate decision for the first three.
#
# NOT IN THIS PILOT: shared agreement-state summary, per-turn state
# elicitation, any semantic resolution supplied to the agents, any instruction
# on how to renegotiate, scoring, frozen metrics, main-study analyzer,
# cross-model cells, Passport primitives.

import argparse
import json
import os
import pathlib
import time

import calibrate
import episode
import mandates
import transcript
import world as w

BASE = pathlib.Path(__file__).resolve().parent
ENV_DIR = BASE
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"
FIRST_GATE_EPISODES = (1, 2, 3)
GATE_FILE = "FIRST_GATE_DECISION.json"

GATE_TEMPLATE = {
    "episode_ids_reviewed": ["<episode ids 1-3>"],
    "manual_review_by": "<name>",
    "manual_review_at": "<iso timestamp>",
    "shared_condition_or_alternative_present": {
        "<episode id>": "<true|false, decided by reading the transcript>"},
    "disturbance_landed_as_designed": None,
    "five_variables_readable": None,
    "both_branches_reachable": None,
    "decision": "<proceed | redesign | stop>",
    "rationale": "<one paragraph>",
}
VALID_DECISIONS = ("proceed", "redesign", "stop")


def env_path():
    return ENV_DIR / ".env"


def load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit("python-dotenv missing. pip install -r requirements.txt")
    load_dotenv(env_path(), override=False)
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return None if (not key or key == PLACEHOLDER_KEY) else key


def make_client(api_key, client_factory=None):
    if not api_key:
        raise SystemExit(
            f"ANTHROPIC_API_KEY not found.\nexpected a line "
            f"`ANTHROPIC_API_KEY=<your key>` in:\n  {env_path()}\n"
            f"file present = {env_path().exists()}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def load_config():
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def load_prompts():
    return {n: mandates.load(n) for n in mandates.PROMPT_NAMES}


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
        (out_dir / (GATE_FILE.replace(".json", ".template.json"))).write_text(
            json.dumps(GATE_TEMPLATE, indent=2), encoding="utf-8")
        raise SystemExit(
            f"REFUSED: {err}\nepisodes 1-3 are complete. a manual review is "
            f"required: a human must read the "
            f"three transcripts and record the gate decision — including, per "
            f"episode, whether a genuinely SHARED conditional or alternative "
            f"structure was present. that determination cannot come from the "
            f"candidate extractor. a template has been written next to this "
            f"file.")
    if d["decision"] != "proceed":
        raise SystemExit(f"REFUSED: recorded decision is '{d['decision']}'.")
    return [f"recorded gate decision: proceed, by {d['manual_review_by']}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="1-3")
    ap.add_argument("--phase", default=None)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--calibration", action="store_true")
    args = ap.parse_args()

    if args.calibration:
        text, checks = calibrate.report()
        print(text)
        return

    api_key = load_env()
    cfg = load_config()
    phase = args.phase or cfg["phase"]
    out_dir = BASE / "runs" / phase
    episodes = parse_range(args.episodes)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes = gate(episodes, out_dir)

    seller_system = mandates.render_seller_system()
    buyer_system = mandates.render_buyer_system()
    hashes = mandates.prompt_hashes()
    _, checks = calibrate.report()

    if not args.confirm:
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print(f"phase              : {phase}")
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
        for n in notes:
            print(f"gate               : {n}")
        print(f"api key present    : {bool(api_key)}")
        print(f"output dir         : {out_dir}")
        print("\nharness will NOT: supply agreement semantics, decide whether a")
        print("communicated condition lapses, or auto-decide study 3")
        print("eligibility. every episode record carries")
        print("study3_eligibility = 'pending_manual_review'.")
        print(f"\napprox api calls   : {len(episodes)} x"
              f" (<= {cfg['turn_cap']} turns + 6 probe calls)")
        return

    client = make_client(api_key)
    import anthropic
    prompts = load_prompts()

    (out_dir / "_run_manifest.json").write_text(json.dumps({
        "phase": phase, "episodes": episodes, "config": cfg,
        "world_spec": w.spec(), "world_hash": w.world_hash(),
        "calibration_checks": checks, "prompt_hashes": hashes,
        "gate_notes": notes, "sdk_version": anthropic.__version__,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "not_included": [
            "shared agreement-state summary", "per-turn state elicitation",
            "semantic resolution supplied to agents",
            "instruction on how to renegotiate", "scoring", "frozen metrics",
            "main-study analyzer", "cross-model cell", "Passport primitives"],
    }, indent=2), encoding="utf-8")

    for n in episodes:
        eid = f"{phase}_ep{n:02d}"
        print(f"running {eid} ...", flush=True)
        rec = episode.run_episode(eid, cfg, prompts, client,
                                  seller_system, buyer_system)
        rec.update({"phase": phase, "episode_number": n, "config": cfg,
                    "prompt_hashes": hashes, "world_spec": w.spec(),
                    "sdk_version": anthropic.__version__})
        (out_dir / f"{eid}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / f"{eid}_transcript.md").write_text(
            transcript.render(rec), encoding="utf-8")
        u = rec["principal_update"] or {}
        print(f"  {rec['termination']['mode']} at turn"
              f" {rec['termination']['turn_index']} ·"
              f" {len(rec['turns'])} turns ·"
              f" update delivered: {u.get('delivered')} ·"
              f" probe leaks flagged: {len(rec['probe_leaks_flagged'])}")
        print(f"  -> {eid}.json / {eid}_transcript.md")

    print("\nNo metrics computed and no eligibility decided, by design.")
    print("Read the three transcripts by hand, then record"
          f" {GATE_FILE}.")


if __name__ == "__main__":
    main()
