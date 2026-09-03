# run_c1.py — cli for Phase 2 cell C1, arm S1-G.
#
#   python run_c1.py                 dry check + frozen-baseline hash compare
#   python run_c1.py --runs 5        dry check for the 5-negotiation protocol check
#   python run_c1.py --runs 5 --confirm
#
# refuses to call the api without --confirm.
# S1-B is NOT re-run: it is study 1 condition B, already collected.

import argparse
import hashlib
import json
import os
import pathlib
import random
import time

import protocol_guard
import scoring
from agents import Agent

BASE = pathlib.Path(__file__).resolve().parent
BASELINE = BASE.parent / "01_delegated_authority"
PLACEHOLDER_KEY = "PASTE_YOUR_KEY_HERE"

# the frozen study 1 files that MUST be byte-identical for S1-G to be
# comparable to S1-B (design gate 5).
FROZEN_FILES = ("agents.py", "protocol.py", "tracker.py", "scoring.py",
                "config.json", "prompts/seller_system.txt",
                "prompts/buyer_system.txt", "prompts/state_block.txt")
FROZEN_EXPECTED = {
    "agents.py": "b9b8da5946ced705",
    "protocol.py": "304a2dd59e0c6c3b",
    "tracker.py": "285f26c090ec62d7",
    "scoring.py": "5f34d0cedd193db3",
    "config.json": "5752faec21fe6088",
    "prompts/seller_system.txt": "d4005aaea3b9b780",
    "prompts/buyer_system.txt": "2fccc7bc2b403f3a",
    "prompts/state_block.txt": "9ca8af7e68b2474a",
}


def sha16(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]


def frozen_comparison():
    rows = []
    for f in FROZEN_FILES:
        here = sha16(BASE / f)
        there = sha16(BASELINE / f) if (BASELINE / f).exists() else None
        rows.append({"file": f, "c1_copy": here, "frozen_baseline": there,
                     "expected": FROZEN_EXPECTED[f],
                     "identical": here == there == FROZEN_EXPECTED[f]})
    return rows


def guard_prompt_check():
    frozen = (BASE / "prompts" / "seller_system.txt").read_bytes()
    guarded = (BASE / "prompts" / "seller_system_guard.txt").read_bytes()
    return {"frozen_prefix_preserved": guarded.startswith(frozen),
            "appended_bytes": len(guarded) - len(frozen),
            "frozen_seller_system_sha16": sha16(
                BASE / "prompts" / "seller_system.txt"),
            "guarded_seller_system_sha16": sha16(
                BASE / "prompts" / "seller_system_guard.txt")}


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
            f"`ANTHROPIC_API_KEY=<your key>` in:\n  {BASE / '.env'}\n"
            f"file present = {(BASE / '.env').exists()}")
    if client_factory is None:
        import anthropic
        client_factory = anthropic.Anthropic
    return client_factory(api_key=api_key)


def make_execution_order(seed, n_runs):
    labels = ["G"] * n_runs
    random.Random(seed).shuffle(labels)
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--phase", default="c1_s1g")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    rows = frozen_comparison()
    gp = guard_prompt_check()
    api_key = load_env()
    out_dir = BASE / "runs" / args.phase

    if not args.confirm:
        print("DRY CHECK ONLY — no api calls. pass --confirm to run.\n")
        print(f"cell / arm          : C1 / S1-G")
        print(f"before arm          : S1-B (study 1 condition B, already "
              f"collected, NOT re-run)")
        print(f"phase               : {args.phase}")
        print(f"negotiations         : {args.runs}")
        print(f"model               : {config['model']}  (same model both sides)")
        print(f"temperature         : {config['temperature']}")
        print(f"max_tokens          : {config['max_tokens']}")
        print(f"max_rounds          : {config['max_rounds']}")
        print(f"order_seed          : {config['order_seed']}")
        print(f"attempts per turn   : {protocol_guard.MAX_ATTEMPTS_PER_TURN}")
        print(f"action schema       : {protocol_guard.SCHEMA_VERSION}")
        print("\nfrozen-baseline byte comparison (design gate 5):")
        for r in rows:
            print(f"  {'OK ' if r['identical'] else 'FAIL'} {r['file']:<28} "
                  f"{r['c1_copy']}  baseline={r['frozen_baseline']}")
        print(f"  all frozen files identical : "
              f"{all(r['identical'] for r in rows)}")
        print("\nguarded seller prompt:")
        print(f"  frozen prefix preserved : {gp['frozen_prefix_preserved']}")
        print(f"  appended bytes          : {gp['appended_bytes']} "
              f"(the authorization-check paragraph, design section 6)")
        print("\ndeal-outcome handling: guard_exhausted counts as NO DEAL and is")
        print("never excluded. only parse/harness/api/integrity failures are")
        print("excluded from outcome analysis.")
        print("behavioural logging: every attempt tagged phase A (up to and")
        print("including the first block) or phase B (strictly after it).")
        print("\ndual denominator — every S1-B comparison must name one:")
        print("  baseline_comparable_eligible : the FROZEN study 1 rule,")
        print("    unchanged (frozen_eligibility.py). use for any claim of")
        print("    direct comparability with the S1-B dataset.")
        print("  commercial_outcome_eligible  : deal / no-deal, guard_exhausted")
        print("    cost, termination composition. includes a negotiation whose")
        print("    round action was entirely blocked.")
        print("  the frozen primary_analysis_eligible field is retained with")
        print("  its original semantics and is not overwritten.")
        print(f"\napi key present     : {bool(api_key)}")
        print(f"output dir          : {out_dir}")
        print(f"approx api calls    : {args.runs} x (<= "
              f"{config['max_rounds']} rounds x up to "
              f"{protocol_guard.MAX_ATTEMPTS_PER_TURN} seller attempts + buyer "
              f"turns from round 4)")
        return

    if not all(r["identical"] for r in rows):
        raise SystemExit("REFUSED: frozen study 1 files are not byte-identical "
                         "to the baseline. S1-G would not be comparable to S1-B.")
    if not gp["frozen_prefix_preserved"]:
        raise SystemExit("REFUSED: the guarded seller prompt does not start "
                         "with the frozen seller_system.txt bytes.")

    import anthropic
    client = make_client(api_key)

    seller_prompt = load_text("seller_system_guard.txt")
    buyer_prompt = load_text("buyer_system.txt")
    state_template = load_text("state_block.txt")
    prompt_hashes = {
        "seller_system_frozen": sha16(BASE / "prompts" / "seller_system.txt"),
        "seller_system_guard": sha16(BASE / "prompts" / "seller_system_guard.txt"),
        "buyer_system": sha16(BASE / "prompts" / "buyer_system.txt"),
        "state_block": sha16(BASE / "prompts" / "state_block.txt"),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    order = make_execution_order(config["order_seed"], args.runs)
    (out_dir / "_execution_order.json").write_text(json.dumps({
        "order_seed": config["order_seed"], "arm": "S1-G",
        "runs": args.runs, "execution_order": order,
        "frozen_comparison": rows, "guard_prompt_check": gp,
    }, indent=2), encoding="utf-8")

    for i in range(args.runs):
        run_id = f"{args.phase}_G_{i + 1:02d}_{int(time.time())}"
        buyer = Agent("buyer", buyer_prompt, config, client)
        seller = Agent("seller", seller_prompt, config, client)
        record = protocol_guard.run_negotiation_guard(
            buyer, seller, config, state_template)
        record.update({
            "run_id": run_id, "phase": args.phase,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": config, "order_seed": config["order_seed"],
            "execution_index": i, "prompt_hashes": prompt_hashes,
            "frozen_comparison": rows,
            "resolved_model": {"buyer": buyer.resolved_model,
                               "seller": seller.resolved_model},
            "sdk_version": anthropic.__version__,
        })
        # frozen scoring, replayed over RELAYED actions only. its unauthorized
        # count is a live integrity check and must read 0 in S1-G.
        record["scores"] = scoring.score_run(record)
        (out_dir / f"{run_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8")
        g, sc = record["guard_summary"], record["scores"]
        print(f"[{i + 1}/{args.runs}] {run_id}: deal={sc['deal']} "
              f"ended_by={record['outcome']['ended_by']} "
              f"attempted={g['unauthorized_attempted']} "
              f"blocked={g['attempts_blocked']} "
              f"sent={g['unauthorized_sent']} "
              f"committed={g['unauthorized_committed']} "
              f"phaseA={g['phase_A']['blocked']} "
              f"phaseB={g['phase_B']['blocked']} "
              f"escalations={g['escalation_requests']} "
              f"baseline_eligible="
              f"{record['validity']['baseline_comparable_eligible']} "
              f"commercial_eligible="
              f"{record['validity']['commercial_outcome_eligible']}")


if __name__ == "__main__":
    main()
