# run_pilot.py — cli entry for the study 3 unscripted micro-pilot.
#
# refuses to call the api without --confirm.
# refuses episodes 4-6 unless a calibration decision has been explicitly
# recorded on disk (see CALIBRATION GATE below).
#
#   python run_pilot.py                        dry check, no api calls
#   python run_pilot.py --episodes 1-3 --confirm
#   python run_pilot.py --calibration-status
#
# NOT IN THIS PILOT, by design: A0/A1/A2 treatments, shared agreement state,
# per-turn state elicitation, false-recital injection, cross-model cells,
# primary metrics, failure-mode counts, any kite/passport primitive.

import argparse
import json
import os
import pathlib
import time

import episode
import mandates
import package as pk
import transcript

# resolve() so the .env is found from any shell working directory.
BASE = pathlib.Path(__file__).resolve().parent
# only env_path() reads this. kept separate from BASE so the offline test can
# point credential loading at a temp dir without disturbing prompts/config.
ENV_DIR = BASE
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"
CLEAN_EPISODES = (1, 2, 3)
DECISION_FILE = "CALIBRATION_DECISION.json"
PROMPT_NAMES = ("seller_system", "buyer_system", "buyer_opening", "reprompt",
                "calibration_clause", "principal_update",
                "probe_1", "probe_2", "probe_3")


# ------------------------------------------------------------ credentials
# static api-key pattern, matching study 2: the key lives in a .env next to
# this script and is passed to the client EXPLICITLY, so no other local
# anthropic profile or ambient credential can win resolution. the value is
# never printed, logged, or written to any run artifact.

def env_path():
    return ENV_DIR / ".env"


def load_env():
    """load the .env beside this script and return the key, or None."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit(
            "python-dotenv is not installed. run: pip install -r requirements.txt")
    # override=False: a key already exported in the shell wins over the file.
    load_dotenv(env_path(), override=False)
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key or key == PLACEHOLDER_KEY:
        return None
    return key


def make_client(api_key, client_factory=None):
    """construct the client with the key passed explicitly."""
    if not api_key:
        raise SystemExit(
            f"ANTHROPIC_API_KEY not found.\n"
            f"expected a line `ANTHROPIC_API_KEY=<your key>` in:\n"
            f"  {env_path()}\n"
            f"checked: file present = {env_path().exists()}\n"
            f"note: Notepad may have saved it as .env.txt — check with `dir /a`.")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def load_config():
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def load_prompts():
    return {n: mandates.load(n) for n in PROMPT_NAMES}


def parse_range(s):
    if "-" in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(s)]


# ------------------------------------------------------------ CALIBRATION GATE
# episodes 1-3 run clean: the buyer's calibration clause is absent, full stop.
# only after all three have completed may a human inspect them and record a
# decision. episodes 4-6 will not start without that record.

DECISION_TEMPLATE = {
    "episode_ids_reviewed": ["<episode ids 1-3>"],
    "amendment_observed_in_1_3": None,
    "decision": "<activate_clause | proceed_clean | stop>",
    "rationale": "<one paragraph>",
    "recorded_by": "<name>",
    "recorded_at": "<iso timestamp>",
}
VALID_DECISIONS = ("activate_clause", "proceed_clean", "stop")


def decision_path(out_dir):
    return out_dir / DECISION_FILE


def read_decision(out_dir):
    p = decision_path(out_dir)
    if not p.exists():
        return None, f"no {DECISION_FILE} in {p.parent}"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"{DECISION_FILE} is not valid json: {e}"
    missing = [k for k in DECISION_TEMPLATE if k not in d]
    if missing:
        return None, f"{DECISION_FILE} missing fields: {missing}"
    if d["decision"] not in VALID_DECISIONS:
        return None, (f"decision must be one of {VALID_DECISIONS}, "
                      f"got {d['decision']!r}")
    if not isinstance(d["amendment_observed_in_1_3"], bool):
        return None, "amendment_observed_in_1_3 must be true or false"
    if not str(d.get("recorded_by", "")).strip() or \
            str(d["recorded_by"]).startswith("<"):
        return None, "recorded_by must name a person"
    return d, None


def gate(episodes, out_dir):
    # returns (allowed_episodes, calibration_clause_active, notes)
    later = [e for e in episodes if e not in CLEAN_EPISODES]
    if not later:
        return episodes, False, ["episodes 1-3: calibration clause ABSENT"]

    done = {int(p.stem.split("_ep")[-1]) for p in out_dir.glob("*_ep*.json")}
    not_done = [e for e in CLEAN_EPISODES if e not in done]
    if not_done:
        raise SystemExit(
            f"REFUSED: episodes {later} requested but clean episodes "
            f"{not_done} have not completed. all of 1-3 must finish first.")

    d, err = read_decision(out_dir)
    if d is None:
        p = decision_path(out_dir)
        p.with_suffix(".template.json").write_text(
            json.dumps(DECISION_TEMPLATE, indent=2), encoding="utf-8")
        raise SystemExit(
            f"REFUSED: {err}\n"
            f"episodes 1-3 are complete. a human must now inspect them and "
            f"record a decision.\n"
            f"a template has been written to "
            f"{p.with_suffix('.template.json').name} — fill it in and save it "
            f"as {DECISION_FILE}.\n"
            f"if no genuine amendment occurred in episodes 1-3, the "
            f"calibration trigger condition has been met: record that, and "
            f"report it before continuing.")
    if d["decision"] == "stop":
        raise SystemExit(
            "REFUSED: recorded decision is 'stop'. no further episodes.")
    active = d["decision"] == "activate_clause"
    return episodes, active, [
        f"recorded decision: {d['decision']} by {d['recorded_by']} "
        f"at {d['recorded_at']}",
        f"amendment observed in 1-3: {d['amendment_observed_in_1_3']}",
        f"episodes {later}: calibration clause "
        f"{'ACTIVE' if active else 'ABSENT'}",
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="1-3",
                    help="e.g. 1-3, or 4-6, or 2")
    ap.add_argument("--phase", default=None)
    ap.add_argument("--confirm", action="store_true",
                    help="required to actually call the api")
    ap.add_argument("--calibration-status", action="store_true")
    args = ap.parse_args()

    # loaded BEFORE the dry check reads it and before any client exists
    api_key = load_env()

    cfg = load_config()
    phase = args.phase or cfg["phase"]
    out_dir = BASE / "runs" / phase
    episodes = parse_range(args.episodes)

    if args.calibration_status:
        done = sorted(int(p.stem.split("_ep")[-1])
                      for p in out_dir.glob("*_ep*.json"))
        d, err = read_decision(out_dir)
        print(f"phase          : {phase}")
        print(f"episodes done  : {done or 'none'}")
        print(f"clean 1-3 done : {all(e in done for e in CLEAN_EPISODES)}")
        print(f"decision file  : {'present' if d else 'absent — ' + err}")
        if d:
            print(json.dumps(d, indent=2))
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    episodes, clause_active, notes = gate(episodes, out_dir)

    seller_system = mandates.render_seller_system()
    # the calibration intervention is NO LONGER a system-prompt clause. it is a
    # post-agreement principal update delivered mid-episode (see intervention.py
    # and the episodes 1-3 review: the original flex clause could never fire on
    # the observed final packages). the buyer system prompt is therefore
    # identical in every cell — the only difference between cells is whether a
    # requirement change arrives after a complete package has been agreed.
    buyer_system = mandates.render_buyer_system(False)
    update_active = clause_active
    hashes = mandates.prompt_hashes()

    if not args.confirm:
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print(f"phase           : {phase}")
        print(f"episodes        : {episodes}")
        print(f"model           : {cfg['model']}  (same model both sides)")
        print(f"temperature     : {cfg['temperature']}")
        print(f"max_tokens      : {cfg['max_tokens']}")
        print(f"turn cap        : {cfg['turn_cap']} ({cfg['turn_cap'] // 2} each)")
        print(f"coupling hash   : {pk.coupling_hash()}")
        print(f"zopa non-empty  : "
              f"{all(r['zopa_width'] > 0 for r in pk.zopa_table())} "
              f"across {len(pk.zopa_table())} packages")
        for n in notes:
            print(f"gate            : {n}")
        print(f"intervention    : "
              f"{'post-agreement principal update' if update_active else 'none (clean cell)'}")
        print(f"cell            : "
              f"{'post_agreement_update' if update_active else 'clean'}")
        print(f"legacy clause in buyer prompt : "
              f"{'must reopen the flex band' in buyer_system}  (always False)")
        print(f"api key present : {bool(api_key)}")
        print(f"\napprox api calls: {len(episodes)} episodes x "
              f"(<= {cfg['turn_cap']} negotiation turns + 6 probe calls)")
        print(f"output dir      : {out_dir}")
        return

    client = make_client(api_key)   # raises before any api call if absent
    import anthropic
    prompts = load_prompts()

    (out_dir / "_run_manifest.json").write_text(json.dumps({
        "phase": phase, "episodes": episodes,
        "post_agreement_update_active": update_active,
        "cell": "post_agreement_update" if update_active else "clean",
        "intervention": ("post_agreement_principal_update" if update_active
                         else None),
        "gate_notes": notes,
        "config": cfg,
        "coupling_spec": pk.coupling_spec(),
        "coupling_hash": pk.coupling_hash(),
        "prompt_hashes": hashes,
        "sdk_version": anthropic.__version__,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "not_included": ["A0/A1/A2 treatments", "shared agreement state",
                         "per-turn state elicitation", "false-recital probe",
                         "cross-model cell", "primary metrics",
                         "failure-mode counts"],
    }, indent=2), encoding="utf-8")

    for n in episodes:
        eid = f"{phase}_ep{n:02d}"
        print(f"running {eid} ...", flush=True)
        rec = episode.run_episode(eid, cfg, prompts, client, update_active,
                                  seller_system, buyer_system)
        rec.update({"phase": phase, "episode_number": n,
                    "config": cfg, "prompt_hashes": hashes,
                    "coupling_spec": pk.coupling_spec(),
                    "sdk_version": anthropic.__version__})
        (out_dir / f"{eid}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / f"{eid}_transcript.md").write_text(
            transcript.render(rec), encoding="utf-8")
        tot = rec["usage"]["seller"]["input_tokens"] + \
            rec["usage"]["buyer"]["input_tokens"]
        print(f"  {rec['termination']['mode']} at turn "
              f"{rec['termination']['turn_index']} · "
              f"{len(rec['turns'])} turns · "
              f"{rec['usage']['seller']['api_calls'] + rec['usage']['buyer']['api_calls']}"
              f" api calls · {tot:,} input tokens · "
              f"{rec['elapsed_seconds']}s")
        print(f"  -> {eid}.json / {eid}_transcript.md")

    print("\nno metrics computed, by design. read the transcripts and fill in "
          "reading_log_template.md, one page per episode, before tabulating "
          "anything.")


if __name__ == "__main__":
    main()
