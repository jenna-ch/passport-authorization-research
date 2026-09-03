# run_parallel.py — bounded-parallel runner for the restarted main phase.
#
# execution mechanics only. it changes NOTHING experimental: the world, the
# prompts, the mandate, the A/B treatment, scoring and the analysis plan are
# untouched, and every series runs through the same day_loop.run_series() used
# by the sequential runner.
#
# semantics guaranteed here:
#   * a series is sequential internally - one seller context, day 1..10 in order
#   * the seller Agent for a series is created inside that series' task and is
#     never shared; buyers are fresh per day (day_loop does that)
#   * different series run concurrently, at most `max_workers` (3) at a time
#   * no state is shared between series: each gets its own api client, its own
#     agents, its own ledger walk. world/ledger/scoring are pure or return copies
#   * each series record is written atomically (temp file + os.replace)
#   * a failure in one series cannot corrupt another: a failed series writes no
#     record at all and is reported as an execution failure
#
# usage:
#   python run_parallel.py                # dry check
#   python run_parallel.py --confirm      # run the phase
#   python run_parallel.py --confirm      # re-running skips completed series

import argparse
import hashlib
import json
import os
import pathlib
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

import day_loop
import scoring
import world

BASE = pathlib.Path(__file__).parent
load_dotenv(BASE / ".env")

PROMPT_FILES = ("seller_system", "buyer_system", "morning_brief",
                "state_block", "end_of_day")

# the planned condition sequence, frozen before execution. identical to the
# sequential runner's seeded order; asserted at plan time so it can never drift.
FROZEN_CONDITION_ORDER = "ABAABBAABBBBABAABAAB"

# transient transport conditions that may be retried. anything else - auth,
# permission, invalid request, and credit exhaustion (a 400) - is permanent and
# is never retried. model BEHAVIOUR is never a retry reason.
TRANSIENT_STATUS = (408, 409, 429, 500, 502, 503, 504)
TRANSIENT_NAMES = ("APIConnectionError", "APITimeoutError",
                   "APIConnectionTimeoutError", "OverloadedError")


def load_prompts():
    return {k: (BASE / "prompts" / f"{k}.txt").read_text(encoding="utf-8")
            for k in PROMPT_FILES}


def prompt_hashes():
    return {k: hashlib.sha256((BASE / "prompts" / f"{k}.txt").read_bytes()).hexdigest()
            for k in PROMPT_FILES}


def make_condition_order(seed, conditions, n):
    labels = [c for c in conditions for _ in range(n)]
    random.Random(seed).shuffle(labels)
    return labels


def build_series_plan(config):
    """the 20 series identities, frozen BEFORE any api call. identity is fully
    determined by the seed: no timestamp, no completion order."""
    order = make_condition_order(config["order_seed"], ["A", "B"],
                                 config["series_per_condition"])
    assert "".join(order) == FROZEN_CONDITION_ORDER, (
        "planned condition order drifted from the frozen sequence")
    counts, plan = {"A": 0, "B": 0}, []
    for idx, cond in enumerate(order):
        counts[cond] += 1
        plan.append({
            "run_id": f"{config['phase']}_{cond}_{counts[cond]:02d}",
            "condition": cond,
            "series_number": counts[cond],
            "planned_execution_index": idx,
        })
    return plan


def is_transient(exc):
    if type(exc).__name__ in TRANSIENT_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return status in TRANSIENT_STATUS


class RetryingMessages:
    """wraps client.messages with bounded exponential backoff. the wrapped
    object is per-series, so no retry state is shared across series."""

    def __init__(self, inner, policy, stats, rng):
        self._inner = inner
        self._policy = policy
        self._stats = stats
        self._rng = rng

    def create(self, **kwargs):
        delay = self._policy["base_delay_seconds"]
        last = None
        for attempt in range(1, self._policy["max_attempts"] + 1):
            try:
                self._stats["api_calls"] += 1
                return self._inner.create(**kwargs)
            except Exception as exc:                      # noqa: BLE001
                last = exc
                if not is_transient(exc):
                    self._stats["permanent_errors"] += 1
                    raise
                self._stats["transient_retries"] += 1
                if attempt == self._policy["max_attempts"]:
                    raise
                time.sleep(min(delay, self._policy["max_delay_seconds"])
                           + self._rng.random() * self._policy["jitter_seconds"])
                delay = min(delay * 2, self._policy["max_delay_seconds"])
        raise last


class RetryingClient:
    def __init__(self, inner, policy, seed):
        self.stats = {"api_calls": 0, "transient_retries": 0, "permanent_errors": 0}
        self.messages = RetryingMessages(inner.messages, policy, self.stats,
                                         random.Random(seed))


def atomic_write_json(path, obj):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, path)          # atomic on the same volume


def run_one_series(item, config, prompts, client_factory, out_dir, hashes):
    """one complete 10-day series, sequential inside. runs in a worker thread."""
    run_id = item["run_id"]
    path = out_dir / f"{run_id}.json"
    if path.exists():
        return {**item, "status": "skipped_already_complete"}

    started = time.time()
    client = RetryingClient(client_factory(), config["retry"],
                            seed=item["planned_execution_index"])
    record = day_loop.run_series(item["condition"], config, prompts, client)
    record.update({
        "run_id": run_id,
        "phase": config["phase"],
        "condition": item["condition"],
        "series_number": item["series_number"],
        "planned_execution_index": item["planned_execution_index"],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "duration_seconds": round(time.time() - started, 1),
        "config": config,
        "prompt_hashes": hashes,
        "execution_mode": "parallel_workers",
        "max_workers": config["max_workers"],
        "api_call_stats": dict(client.stats),
    })
    record["scores"] = scoring.score_series(record)
    atomic_write_json(path, record)
    return {**item, "status": "completed",
            "started_at": record["started_at"],
            "completed_at": record["completed_at"],
            "duration_seconds": record["duration_seconds"],
            "api_call_stats": record["api_call_stats"],
            "final_cumulative_profit": record["scores"]["final_cumulative_profit"],
            "first_state_error_day": record["scores"]["first_state_error_day"],
            "first_violation_day": record["scores"]["first_violation_day"],
            "integrity_ok": record["scores"]["integrity_ok"]}


def execute(config, prompts, client_factory, out_dir, sdk_version, log=print):
    plan = build_series_plan(config)
    hashes = prompt_hashes()
    out_dir.mkdir(parents=True, exist_ok=True)

    # written BEFORE the first api call
    atomic_write_json(out_dir / "_execution_plan.json", {
        "phase": config["phase"], "order_seed": config["order_seed"],
        "planned_condition_order": FROZEN_CONDITION_ORDER,
        "series_plan": plan, "days_per_series": world.DAYS,
        "world_hash": world.world_hash(), "prompt_hashes": hashes,
        "model": config["model"], "temperature": config["temperature"],
        "max_tokens": config["max_tokens"], "sdk_version": sdk_version,
        "max_workers": config["max_workers"], "retry": config["retry"],
        "execution_mode": "parallel_workers",
        "note": ("completion order is NOT experimental order; use "
                 "planned_execution_index"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })

    results, failures, lock = {}, [], threading.Lock()

    def record_result(item, res):
        with lock:
            results[item["run_id"]] = res
            atomic_write_json(out_dir / "_execution_manifest.json", {
                "phase": config["phase"],
                "completed": sum(1 for r in results.values()
                                 if r["status"] in ("completed",
                                                    "skipped_already_complete")),
                "failed": len(failures), "planned": len(plan),
                "results": [results[i["run_id"]] for i in plan
                            if i["run_id"] in results],
                "failures": failures,
            })

    with ThreadPoolExecutor(max_workers=config["max_workers"]) as pool:
        futures = {pool.submit(run_one_series, item, config, prompts,
                               client_factory, out_dir, hashes): item
                   for item in plan}
        done = 0
        for fut in as_completed(futures):
            item = futures[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as exc:                       # noqa: BLE001
                res = {**item, "status": "failed",
                       "error_type": type(exc).__name__, "error": str(exc)[:400]}
                with lock:
                    failures.append(res)
                log(f"[{done}/{len(plan)}] {item['run_id']}: FAILED "
                    f"{type(exc).__name__}: {str(exc)[:160]}")
            else:
                log(f"[{done}/{len(plan)}] {res['run_id']}: {res['status']}"
                    + (f" final=${res.get('final_cumulative_profit', 0):.0f}"
                       f" first_state_error={res.get('first_state_error_day')}"
                       f" first_violation={res.get('first_violation_day')}"
                       f" retries={res.get('api_call_stats', {}).get('transient_retries', 0)}"
                       if res["status"] == "completed" else ""))
            record_result(item, res)
    return plan, results, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="required to actually call the api")
    ap.add_argument("--phase", default=None)
    args = ap.parse_args()

    config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    if args.phase:
        config["phase"] = args.phase
    plan = build_series_plan(config)
    out_dir = BASE / "runs" / config["phase"]

    if not args.confirm:
        print("dry check only. pass --confirm to actually run the experiment.")
        print(f"phase={config['phase']} series={len(plan)} "
              f"(A={sum(1 for p in plan if p['condition'] == 'A')}, "
              f"B={sum(1 for p in plan if p['condition'] == 'B')}) "
              f"days_per_series={world.DAYS}")
        print(f"model={config['model']} temp={config['temperature']} "
              f"max_tokens={config['max_tokens']}")
        print(f"world_hash={world.world_hash()}")
        print(f"planned condition order (seed={config['order_seed']}): "
              f"{FROZEN_CONDITION_ORDER}")
        print(f"max_workers={config['max_workers']} retry={config['retry']}")
        print(f"output={out_dir}")
        existing = sorted(p.name for p in out_dir.glob(f"{config['phase']}_*.json")) \
            if out_dir.is_dir() else []
        print(f"already complete (would be skipped): {len(existing)}")
        print("ANTHROPIC_API_KEY detected: "
              f"{bool(os.environ.get('ANTHROPIC_API_KEY'))}")
        return

    import anthropic
    prompts = load_prompts()
    plan, results, failures = execute(
        config, prompts, lambda: anthropic.Anthropic(), out_dir,
        anthropic.__version__)

    ok = [r for r in results.values()
          if r["status"] in ("completed", "skipped_already_complete")]
    print(f"\n{len(ok)}/{len(plan)} series complete, {len(failures)} failed")
    if failures:
        print("EXECUTION FAILURE - do not analyse this phase. failed series:")
        for f in failures:
            print(f"  {f['run_id']}: {f['error_type']}: {f['error']}")
        print("no series was substituted and no completed series was rerun.")
        raise SystemExit(1)
    print(f"all series written to {out_dir}")


if __name__ == "__main__":
    main()
