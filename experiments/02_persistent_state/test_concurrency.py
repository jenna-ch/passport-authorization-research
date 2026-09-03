# test_concurrency.py — offline validation of run_parallel.py. no api calls.
# every "api" here is a fake client that tags its output with the series it
# belongs to, so cross-series leakage would be visible in the stored records.
import json
import pathlib
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import run_parallel as rp
import world

PASS, FAIL = 0, []

# snapshot of the real main phase directory, to prove the tests never touch it
REAL_MAIN_BEFORE = ({p.name: p.stat().st_mtime_ns
                     for p in (pathlib.Path(__file__).parent / "runs"
                               / "main_v2_1_r1").glob("*")}
                    if (pathlib.Path(__file__).parent / "runs"
                        / "main_v2_1_r1").is_dir() else None)


def check(cond, label):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(label)


def section(n):
    print(f"\n--- {n}")


CFG = {"model": "offline", "temperature": 1.0, "max_tokens": 512,
       "phase": "test_phase", "series_per_condition": 10,
       "order_seed": 20260827, "max_workers": 3,
       "retry": {"max_attempts": 4, "base_delay_seconds": 0.01,
                 "max_delay_seconds": 0.05, "jitter_seconds": 0.0}}
BASE = pathlib.Path(__file__).parent
PROMPTS = {k: (BASE / "prompts" / f"{k}.txt").read_text(encoding="utf-8")
           for k in rp.PROMPT_FILES}


# ------------------------------------------------------------------ fakes
class FakeClient:
    """one per series. tags every message with `tag` so any leaked turn is
    attributable. records the exact call sequence it saw."""

    def __init__(self, tag, sink, fail_on=None, transient_times=0):
        self.tag = tag
        self.sink = sink
        self.fail_on = fail_on
        self.transient_left = transient_times
        self.calls = 0
        self.messages = self

    def create(self, model, system, messages, temperature, max_tokens):
        self.calls += 1
        if self.transient_left > 0:
            self.transient_left -= 1
            raise SimpleNamespace  # placeholder, replaced below
        if self.fail_on == "permanent":
            err = RuntimeError("invalid request: credit balance is too low")
            err.status_code = 400
            raise err
        role = "buyer" if "procurement agent" in system else "seller"
        last = messages[-1]["content"]
        self.sink.append((self.tag, role, len(messages), last[:14]))
        if role == "seller" and last.startswith("=== day"):
            body = {"cumulative_profit": 0, "pace_status": "on_pace",
                    "minimum_price_today": 0.73}
        else:
            body = {"action": "accept", "price_per_unit": None,
                    "message": f"deal [{self.tag}]"}
        text = f"tag={self.tag}\n\n```json\n{json.dumps(body)}\n```"
        return SimpleNamespace(model="offline-fake",
                               content=[SimpleNamespace(type="text", text=text)])


class Transient(Exception):
    status_code = 429


class FlakyClient(FakeClient):
    def create(self, *a, **kw):
        if self.transient_left > 0:
            self.transient_left -= 1
            raise Transient("rate limited")
        return FakeClient.create(self, *a, **kw)


# =====================================================================
section("C1. frozen series plan")
plan = rp.build_series_plan(CFG)
check(len(plan) == 20, "20 series planned")
check("".join(p["condition"] for p in plan) == rp.FROZEN_CONDITION_ORDER,
      "planned condition order matches the frozen sequence")
check(rp.FROZEN_CONDITION_ORDER == "ABAABBAABBBBABAABAAB", "frozen literal unchanged")
check(sum(1 for p in plan if p["condition"] == "A") == 10
      and sum(1 for p in plan if p["condition"] == "B") == 10, "10 A + 10 B")
check([p["planned_execution_index"] for p in plan] == list(range(20)),
      "planned execution indices are 0..19")
check(len({p["run_id"] for p in plan}) == 20, "run ids unique")
check(all("_" + p["condition"] + "_" in p["run_id"] for p in plan),
      "run id carries its condition")
check(rp.build_series_plan(CFG) == plan, "plan is deterministic across calls")
check(all("time" not in p and "timestamp" not in p for p in plan),
      "identity contains no timestamp - frozen before execution")

# =====================================================================
section("C2. retry policy")
stats = {"api_calls": 0, "transient_retries": 0, "permanent_errors": 0}
import random as _r
flaky = FlakyClient("t", [], transient_times=2)
wrapped = rp.RetryingClient(flaky, CFG["retry"], seed=0)
resp = wrapped.messages.create(model="m", system="you are a sales agent",
                               messages=[{"role": "user", "content": "=== day 1"}],
                               temperature=1.0, max_tokens=8)
check(resp is not None, "transient errors are retried to success")
check(wrapped.stats["transient_retries"] == 2, "exactly two retries counted")
check(wrapped.stats["permanent_errors"] == 0, "no permanent error recorded")

perm = FakeClient("p", [], fail_on="permanent")
wrapped2 = rp.RetryingClient(perm, CFG["retry"], seed=0)
try:
    wrapped2.messages.create(model="m", system="s", messages=[], temperature=1.0,
                             max_tokens=8)
    check(False, "permanent error raises")
except Exception as exc:                                    # noqa: BLE001
    check(getattr(exc, "status_code", None) == 400, "permanent error propagates")
check(perm.calls == 1, "a permanent error (credit exhaustion) is NOT retried")
check(wrapped2.stats["transient_retries"] == 0, "no retry counted for permanent")
check(rp.is_transient(Transient()) is True, "429 classified transient")
e401 = RuntimeError(); e401.status_code = 401
check(rp.is_transient(e401) is False, "401 classified permanent")
e400 = RuntimeError(); e400.status_code = 400
check(rp.is_transient(e400) is False, "400 (credit) classified permanent")
check(rp.is_transient(type("APIConnectionError", (Exception,), {})()) is True,
      "connection error classified transient")

# =====================================================================
section("C3. bounded parallel execution end to end")
tmp = pathlib.Path(tempfile.mkdtemp())
out = tmp / "runs" / CFG["phase"]
sink = []
live = {"now": 0, "max": 0}
live_lock = threading.Lock()


def make_client_factory(sink, live, fail_ids=()):
    counter = {"n": 0}
    lock = threading.Lock()

    def factory():
        with lock:
            counter["n"] += 1
            tag = f"S{counter['n']:02d}"
        with live_lock:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        return FakeClient(tag, sink)
    return factory


factory = make_client_factory(sink, live)


real_run_one = rp.run_one_series


def counting_run_one(item, config, prompts, client_factory, out_dir, hashes):
    # wraps the REAL implementation (bound before patching, so no recursion)
    try:
        return real_run_one(item, config, prompts, client_factory, out_dir, hashes)
    finally:
        with live_lock:
            live["now"] -= 1


rp.run_one_series = counting_run_one
try:
    plan2, results, failures = rp.execute(CFG, PROMPTS, factory, out,
                                          "offline", log=lambda *a: None)
finally:
    rp.run_one_series = real_run_one

check(len(results) == 20 and not failures, "all 20 series completed, none failed")
files = sorted(out.glob(f"{CFG['phase']}_*.json"))
check(len(files) == 20, "20 record files written")
check(live["max"] <= CFG["max_workers"],
      f"never more than {CFG['max_workers']} series in flight (peak {live['max']})")
check(live["max"] > 1, "execution really was concurrent (peak > 1)")
check(not list(out.glob("*.tmp")), "no temp files left behind (atomic replace)")
check((out / "_execution_plan.json").exists(), "pre-flight plan written")
check((out / "_execution_manifest.json").exists(), "manifest written")

pre = json.loads((out / "_execution_plan.json").read_text(encoding="utf-8"))
check(pre["planned_condition_order"] == rp.FROZEN_CONDITION_ORDER,
      "pre-flight plan records the frozen order")
check(pre["world_hash"] == world.world_hash(), "pre-flight plan records the world hash")
check(pre["max_workers"] == 3 and pre["retry"]["max_attempts"] == 4,
      "pre-flight plan records concurrency and retry policy")
check("completion order is NOT experimental order" in pre["note"],
      "pre-flight plan warns against reading completion order as experimental order")

# =====================================================================
section("C4. per-series isolation and internal sequencing")
recs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
check(len({r["run_id"] for r in recs}) == 20, "20 distinct run ids on disk")
check(all(len(r["days"]) == world.DAYS for r in recs), "every series has 10 days")
check(all([d["day"] for d in r["days"]] == list(range(1, 11)) for r in recs),
      "days stored in order 1..10 inside every series")

tags_per_record = []
for r in recs:
    tags = set()
    for m in r["transcript_seller"]:
        if m["role"] == "assistant" and m["content"].startswith("tag="):
            tags.add(m["content"].split("\n", 1)[0])
    tags_per_record.append(tags)
check(all(len(t) == 1 for t in tags_per_record),
      "each series' seller transcript carries exactly one client tag")
check(len({next(iter(t)) for t in tags_per_record}) == 20,
      "all 20 tags distinct - no client shared between series")
check(all(len(r["transcript_seller"]) == 5 * world.DAYS for r in recs),
      "seller context is one continuous 10-day conversation (50 messages)")
for r in recs:
    briefs = [i for i, m in enumerate(r["transcript_seller"])
              if m["role"] == "user" and m["content"].startswith("=== day")]
    check(briefs == sorted(briefs) and len(briefs) == 10,
          f"{r['run_id']}: morning briefs appear once per day, in order")
    days_seen = [int(r["transcript_seller"][i]["content"].split()[2]) for i in briefs]
    check(days_seen == list(range(1, 11)),
          f"{r['run_id']}: seller saw days 1..10 sequentially")
for r in recs:
    for d in r["days"]:
        check(len(d["transcript_buyer"]) == 2,
              f"{r['run_id']} day {d['day']}: buyer context is fresh and isolated")
        break

# per-series ledger independence: cumulative profit only ever comes from that
# series' own days
for r in recs:
    cum = 0.0
    ok = True
    for d in r["days"]:
        if d["ground_truth_before"]["cumulative_profit_before"] != cum:
            ok = False
        cum = d["ground_truth_after"]["cumulative_profit_after"]
    check(ok, f"{r['run_id']}: ledger chain is self-contained")

check(all(r["scores"]["integrity_ok"] for r in recs),
      "every parallel-written record passes the scoring integrity replay")
check(all(r["execution_mode"] == "parallel_workers" for r in recs),
      "records state their execution mode")
check(all("planned_execution_index" in r and "started_at" in r
          and "completed_at" in r for r in recs),
      "records carry planned index plus real start/completion timestamps")
by_plan = {p["run_id"]: p["planned_execution_index"] for p in plan2}
check(all(r["planned_execution_index"] == by_plan[r["run_id"]] for r in recs),
      "stored planned index matches the frozen plan")
check(all(r["condition"] == next(p["condition"] for p in plan2
                                 if p["run_id"] == r["run_id"]) for r in recs),
      "stored condition matches the frozen plan")

# =====================================================================
section("C5. failure isolation and no-substitution policy")
tmp2 = pathlib.Path(tempfile.mkdtemp())
out2 = tmp2 / "runs" / CFG["phase"]
sink2 = []
fail_target = plan[7]["run_id"]
counter2 = {"n": 0}
lock2 = threading.Lock()


def failing_factory():
    # the 8th client constructed fails permanently; which series that is
    # depends on scheduling, which is exactly the point - one worker dying
    # must not affect the others
    with lock2:
        counter2["n"] += 1
        n = counter2["n"]
    return FakeClient(f"F{n:02d}", sink2,
                      fail_on="permanent" if n == 8 else None)


plan3, results3, failures3 = rp.execute(CFG, PROMPTS, failing_factory, out2,
                                        "offline", log=lambda *a: None)
check(len(failures3) == 1, "exactly one series failed")
check(len(list(out2.glob(f"{CFG['phase']}_*.json"))) == 19,
      "19 records written, the failed series wrote none")
check(not list(out2.glob("*.tmp")), "failed series left no partial file")
failed_id = failures3[0]["run_id"]
check(not (out2 / f"{failed_id}.json").exists(),
      "no partial record exists for the failed series")
others = [json.loads(f.read_text(encoding="utf-8"))
          for f in out2.glob(f"{CFG['phase']}_*.json")]
check(all(len(r["days"]) == 10 for r in others),
      "every surviving series is complete and uncorrupted")
check(all(r["scores"]["integrity_ok"] for r in others),
      "surviving series still pass the integrity replay")
man = json.loads((out2 / "_execution_manifest.json").read_text(encoding="utf-8"))
check(man["failed"] == 1 and man["planned"] == 20,
      "manifest records the failure against the planned count")
check(any(f["status"] == "failed" for f in man["failures"]),
      "failure is recorded, not silently dropped")
check(len({r["run_id"] for r in others}) == 19
      and failed_id not in {r["run_id"] for r in others},
      "no substitute series was created for the failed one")

# =====================================================================
section("C6. completed series are never rerun")
sink3 = []
before_ids = sorted(p.name for p in out.glob(f"{CFG['phase']}_*.json"))
before_mtimes = {p.name: p.stat().st_mtime_ns for p in out.glob(f"{CFG['phase']}_*.json")}
time.sleep(0.01)
plan4, results4, failures4 = rp.execute(
    CFG, PROMPTS, make_client_factory(sink3, {"now": 0, "max": 0}), out,
    "offline", log=lambda *a: None)
check(all(r["status"] == "skipped_already_complete" for r in results4.values()),
      "a second execution skips every completed series")
check(sink3 == [], "no api call was made on the second execution")
after_mtimes = {p.name: p.stat().st_mtime_ns for p in out.glob(f"{CFG['phase']}_*.json")}
check(before_mtimes == after_mtimes, "completed record files were not rewritten")
check(sorted(after_mtimes) == before_ids, "no extra records appeared")

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)

# =====================================================================
section("C7. frozen artefacts untouched by the parallel runner")
check(world.world_hash() ==
      "36eaf88ed96377cb89875825fc49afcfe9084b0cd14ff92259f2eb1a73791e5c",
      "world hash unchanged")
check(world.TARGET == 6000.0 and world.QUANTITY == 10000, "T and quantity unchanged")
h = rp.prompt_hashes()
check(h["seller_system"] ==
      "34f90960e2d3961738fc93ebcfcd7582b1a8cc49241a2bb7162974959d5dcca9",
      "seller prompt hash unchanged")
check(h["state_block"] ==
      "665445e1a9437df6ec00be6d72e82d2462a0a9f5c99b093b68c21aca574b497b",
      "state block hash unchanged")
# the real main phase directory must be untouched: these tests only ever write
# into temp dirs. snapshot taken at import time, compared here.
real_main = BASE / "runs" / "main_v2_1_r1"
check(REAL_MAIN_BEFORE == ({q.name: q.stat().st_mtime_ns for q in real_main.glob("*")}
                           if real_main.is_dir() else None),
      "the real main_v2_1_r1 directory is untouched by the concurrency tests")

print(f"\n{'=' * 60}")
print(f"concurrency suite — passed: {PASS}   failed: {len(FAIL)}")
for x in FAIL:
    print("  FAIL:", x)
sys.exit(1 if FAIL else 0)
