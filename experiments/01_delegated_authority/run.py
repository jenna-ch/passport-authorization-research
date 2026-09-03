# run.py — cli entry for pilot/main runs
# usage: python run.py --condition both --runs 10 --phase pilot
# refuses to call the api without --confirm, so nothing runs by accident.
import argparse
import hashlib
import json
import pathlib
import random
import time

import protocol
import scoring
from agents import Agent

BASE = pathlib.Path(__file__).parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_text(name):
    return (BASE / "prompts" / name).read_text()


def make_execution_order(seed, conditions, n_runs):
    # balanced randomized interleaving of conditions, deterministic in seed.
    # affects execution order only — never model sampling.
    labels = [c for c in conditions for _ in range(n_runs)]
    random.Random(seed).shuffle(labels)
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", choices=["A", "B", "both"], default="both")
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--phase", default=None)
    ap.add_argument("--confirm", action="store_true",
                    help="required to actually call the api")
    args = ap.parse_args()

    config = json.loads((BASE / "config.json").read_text())
    phase = args.phase or config["phase"]
    n_runs = args.runs or config["runs_per_condition"]
    conditions = ["A", "B"] if args.condition == "both" else [args.condition]

    order_seed = config["order_seed"]
    order = make_execution_order(order_seed, conditions, n_runs)

    if not args.confirm:
        print("dry check only. pass --confirm to actually run the experiment.")
        print(f"would run: phase={phase} conditions={conditions} runs={n_runs} "
              f"model={config['model']} temp={config['temperature']}")
        print(f"execution order (seed={order_seed}): {''.join(order)}")
        return

    import anthropic
    client = anthropic.Anthropic()

    seller_prompt = load_text("seller_system.txt")
    buyer_prompt = load_text("buyer_system.txt")
    state_template = load_text("state_block.txt")
    prompt_hashes = {
        "seller_system": sha256(BASE / "prompts" / "seller_system.txt"),
        "buyer_system": sha256(BASE / "prompts" / "buyer_system.txt"),
        "state_block": sha256(BASE / "prompts" / "state_block.txt"),
    }

    out_dir = BASE / "runs" / phase
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_execution_order.json").write_text(json.dumps({
        "order_seed": order_seed,
        "conditions": conditions,
        "runs_per_condition": n_runs,
        "execution_order": order,
    }, indent=2))

    per_cond_count = {c: 0 for c in conditions}
    for exec_idx, cond in enumerate(order):
        per_cond_count[cond] += 1
        run_id = f"{phase}_{cond}_{per_cond_count[cond]:02d}_{int(time.time())}"
        buyer = Agent("buyer", buyer_prompt, config, client)
        seller = Agent("seller", seller_prompt, config, client)
        record = protocol.run_negotiation(cond, buyer, seller, config, state_template)
        record.update({
            "run_id": run_id,
            "phase": phase,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config": config,
            "order_seed": order_seed,
            "execution_index": exec_idx,
            "prompt_hashes": prompt_hashes,
            "resolved_model": {"buyer": buyer.resolved_model,
                               "seller": seller.resolved_model},
            # freeze artifact: the SDK determines which generation parameters
            # are actually transmitted, so it is recorded with the model id,
            # generation params (in `config`) and prompt hashes.
            "sdk_version": anthropic.__version__,
        })
        record["scores"] = scoring.score_run(record)
        path = out_dir / f"{run_id}.json"
        path.write_text(json.dumps(record, indent=2))
        sc = record["scores"]
        print(f"[{exec_idx + 1}/{len(order)}] {run_id}: deal={sc['deal']} "
              f"unauthorized={sc['unauthorized_concession_count']} "
              f"final_price={sc['final_price']} "
              f"parse_ok={record['validity']['parse_ok']} "
              f"scripted_ok={record['validity']['scripted_buyer_ok']} "
              f"exposure={record['validity']['full_pressure_exposure']} "
              f"eligible={record['validity']['primary_analysis_eligible']}")


if __name__ == "__main__":
    main()
