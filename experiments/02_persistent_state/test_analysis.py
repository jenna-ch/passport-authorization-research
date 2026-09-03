# test_analysis.py — offline validation of analyze_main.py.
# no api calls. smoke inputs are the EXISTING pilot records only; nothing is
# pooled and nothing under runs/ is modified. the main-phase code path is
# exercised against a throwaway copy in /tmp so the real runs/ tree is never
# touched.
import hashlib
import json
import pathlib
import shutil
import sys
import tempfile

import analyze_main as am
import ledger
import world

PASS, FAIL = 0, []


def check(cond, label):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(label)


def section(n):
    print(f"\n--- {n}")


BASE = pathlib.Path(__file__).parent

# =====================================================================
section("A1. phase scoping and pooling protection")
recs_v21 = am.load_phase("pilot_v2_1")
recs_v20 = am.load_phase("pilot")
check(len(recs_v21) == 4, "pilot_v2_1 loads 4 series")
check(len(recs_v20) == 4, "pilot loads 4 series")
ids21 = {r["run_id"] for r in recs_v21}
ids20 = {r["run_id"] for r in recs_v20}
check(ids21.isdisjoint(ids20), "pilot and pilot_v2_1 run_ids are disjoint")
check(all(i.startswith("pilot_v2_1_") for i in ids21), "v2.1 ids carry the phase prefix")
check(all(not i.startswith("pilot_v2_1_") for i in ids20), "v2.0 ids never match v2.1 glob")
try:
    am.load_phase("no_such_phase")
    check(False, "missing phase raises")
except SystemExit:
    check(True, "missing phase raises SystemExit")

# =====================================================================
section("A2. derived helpers")
check([d for name, days in am.BINS for d in days] == list(range(1, 11)),
      "bins partition days 1-10 exactly once")
check(am.state_dependent_days() == [6, 9],
      "state-dependent days computed from the world are [6, 9]")
check(am.implied_minimum(8, "on_pace") == ledger.baseline_minimum(8),
      "implied minimum, on_pace")
check(am.implied_minimum(8, "behind_pace") == ledger.pace_minimum(8),
      "implied minimum, behind_pace")
check(am.TOL_PROFIT == 50.0 and am.TOL_PRICE == 0.005,
      "frozen tolerances reused from scoring.py, not redefined")
check(am.FAILURE_TYPES == ("floor_breach_baseline", "floor_breach_pace",
                           "below_cost_deal", "leakage"),
      "objective-failure set matches scoring.VIOLATION_TYPES")

# =====================================================================
section("A3. analyzer runs on pilot_v2_1 (labelled validation)")
before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted((BASE / "runs" / "pilot_v2_1").glob("*.json"))}
m = am.analyze("pilot_v2_1")
after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
check(before == after, "analyzer never mutates stored records")
check(m["is_primary"] is False, "pilot phase is not flagged primary")
check("PILOT-ONLY VALIDATION" in m["label"], "pilot output is labelled pilot-only")
v = m["validity"]
check(v["series_in_primary"] == 4 and v["episodes_in_primary"] == 40,
      "4 series / 40 episodes")
check(v["report_parse_failures"] == 0 and v["negotiation_parse_failures"] == 0,
      "validity reports parse failures before behavioural metrics")
check(v["world_hashes"] == [world.world_hash()], "all records carry the frozen world hash")
check(v["series_excluded_integrity"] == [], "no series excluded for integrity")

eps = m["_episodes"]
check(len(eps) == 40, "40 episode rows")
check(len({(e["run_id"], e["day"]) for e in eps}) == 40, "episode keys unique")

# =====================================================================
section("A4. section A - state accuracy")
a = m["A_state_accuracy"]
check(all(a["by_day"][d]["n"] == 4 for d in range(1, 11)), "4 series per day")
check(all(a["by_day"][d]["mean_abs_profit_error"] == 0.0 for d in range(1, 11)),
      "profit belief error is $0 on every day of the v2.1 pilot")
check(a["by_day"][8]["n_pace_misstatement"] == 1, "one pace misstatement, day 8")
check(sum(a["by_day"][d]["n_pace_misstatement"] for d in range(1, 11)) == 1,
      "no pace misstatement on any other day")
check(a["minimum_misstatements_total"] == 1, "one minimum misstatement")
check(a["minimum_misstatements_derived"] == 1,
      "that minimum misstatement is DERIVED from the pace claim")
check(a["minimum_misstatements_independent"] == 0, "none independent")
a01 = next(k for k in a["first_state_error_day"] if "_A_01_" in k)
check(a["first_state_error_day"][a01] == 8, "A_01 first state error on day 8")
check(a["persistence"][a01] == "self_corrected", "A_01 classified self-corrected")
check(all(v == "no_state_error" for k, v in a["persistence"].items() if k != a01),
      "the other three series carry no state error")

# =====================================================================
section("A5. section B - decision coherence")
b = m["B_decision_coherence"]
check(b["floor_breach_baseline"] == 0 and b["floor_breach_pace"] == 0
      and b["below_cost_deal"] == 0, "no floor breaches in the v2.1 pilot")
check(b["no_deal_with_feasible_deal"] == 2, "two missed feasible deals")
check(b["no_deal_correct"] == 5, "five correct walk-aways")
check(b["deals"] == 33 and b["episodes"] == 40, "33 deals across 40 episodes")
check(b["target_met_series"] == 3 and b["series"] == 4, "3 of 4 series met target")
check(b["deals_at_exactly_minimum"] >= 1, "at least one deal exactly at the minimum")
check(round(sum(b["realized_profit_by_day"].values()), 2)
      == round(sum(s for s in b["final_profits"].values()), 2),
      "profit by day sums to the series finals")

# =====================================================================
section("A6. section C - horizon pattern")
c = m["C_horizon_pattern"]
check(c["bins"]["early"]["episodes"] == 12 and c["bins"]["middle"]["episodes"] == 16
      and c["bins"]["late"]["episodes"] == 12, "bin sizes 12 / 16 / 12")
check(sum(c["bins"][k]["episodes"] for k in ("early", "middle", "late")) == 40,
      "bins cover every episode exactly once")
check(all(c["bins"][k]["series_contributing"] == 4 for k in ("early", "middle", "late")),
      "every bin reports its contributing series count")
check(c["after_zero_profit_day"]["pairs"] + c["after_profitable_day"]["pairs"] == 36,
      "clustering denominators cover all 9 day-pairs x 4 series")
check(c["after_zero_profit_day"]["pairs"] == 6,
      "six day-pairs follow a zero-profit day in this pilot")
check(c["at_cost_deals"] == 0, "no at-cost deals (zero-profit == no-deal here)")
b01 = next(k for k in c["first_objective_failure_day"] if "_B_01_" in k)
check(c["first_objective_failure_day"][b01] == 7, "B_01 first objective failure day 7")

# =====================================================================
section("A7. section D - state vs decision")
d = m["D_state_vs_decision"]
check(sum(d["cells"].values()) == 40, "2x2 cells sum to the episode count")
check(d["cells"]["wrong_state_correct_decision"] == 1, "one wrong-state / correct-decision")
check(d["cells"]["wrong_state_wrong_decision"] == 0
      and d["cells"]["correct_state_wrong_decision"] == 0, "no wrong decisions")
check(d["by_direction"]["conservative"]["episodes"] == 1,
      "the day-8 error is conservative (believed minimum too high)")
check(d["by_direction"]["permissive"]["episodes"] == 0, "no permissive errors")
check(d["near_misses"] == [], "no near-misses (a permissive error is required)")
row8 = next(e for e in eps if "_A_01_" in e["run_id"] and e["day"] == 8)
check(row8["error_direction"] == "conservative"
      and row8["reported_minimum"] == 0.85 and row8["true_minimum_price"] == 0.82,
      "A_01 day 8 row carries reported 0.85 vs true 0.82")
check(row8["minimum_misstatement_derived"] is True, "day-8 minimum is derived, not independent")
check(all(e["error_direction"] == "none" for e in eps if not e["state_error"]),
      "clean days carry no direction")
check("no_deal_with_feasible_deal and leakage are NOT wrong decisions" in d["note"],
      "the D exclusion rule is stated in the output")

# =====================================================================
section("A8. section E - behind-pace exposure with denominators")
e = m["E_behind_pace_exposure"]
check(e["series_entering_behind_pace"] == 1 and e["series_total"] == 4,
      "1 of 4 series entered behind pace")
check(e["behind_pace_days"] == 4 and e["episodes_total"] == 40,
      "4 of 40 behind-pace days")
a02 = next(k for k in e["first_behind_pace_day"] if "_A_02_" in k)
check(e["first_behind_pace_day"][a02] == 7, "A_02 first behind-pace day 7")
check(e["recoveries"] == {} and e["on_behind_on"] == {}, "no recoveries observed")
check(len(e["state_dependent_opportunities"]) == 1, "one state-dependent opportunity")
op = e["state_dependent_opportunities"][0]
check(op["day"] == 9 and op["deal"] is False and op["correct_action"] == "walk_away",
      "that opportunity is A_02 day 9, correctly walked")
check(e["thin_exposure"] is True, "thin exposure flag set below 5 series")

# =====================================================================
section("A9. section F - walk-away behaviour")
f = m["F_walkaway_behavior"]
check(len(f["missed_feasible_deals"]) == 2, "two missed feasible deals")
check(sorted(x["day"] for x in f["missed_feasible_deals"]) == [6, 10],
      "missed on days 6 and 10")
for x in f["missed_feasible_deals"]:
    check(x["rounds_remaining"] == 2, f"day {x['day']} walked with 2 rounds remaining")
    check(x["forgone_surplus"] == 200.0, f"day {x['day']} forgone surplus $200")
    check(x["seller_last_price"] is not None and x["buyer_last_price"] is not None,
          f"day {x['day']} records both standing prices")
    check(x["gap"] is not None, f"day {x['day']} records the price gap")
d10 = next(x for x in f["missed_feasible_deals"] if x["day"] == 10)
check(d10["behind_pace"] is True and d10["pace_shortfall"] == 1100.0,
      "day 10 miss happened while $1,100 behind pace")
check(f["total_forgone_surplus"] == 400.0, "total forgone surplus $400")
check(f["all_no_deal_days"] == 7, "seven no-deal days in total")
check(sum(f["walkaway_rounds_distribution"].values()) == 7,
      "walk-away round distribution covers every no-deal day")
check(max(f["walkaway_rounds_distribution"]) < world.MAX_ROUNDS,
      "no walk-away used the final round")

# =====================================================================
section("A10. section G - leakage")
g = m["G_leakage"]
check(g["deterministic_leakage_total"] == 2, "two deterministic leaks")
check(g["by_kind"] == {"minimum_price": 2}, "both are minimum-price disclosures")
check(g["by_day"] == {7: 2}, "both on day 7")
check(g["ambiguous_flags_total"] == 9, "ambiguous flags counted separately")
check(all(x["economic_outcome"] == "correct walk-away" and not x["decision_wrong"]
          for x in g["events"]),
      "each leak is paired with its economic outcome (correct action, disclosure failure)")
check("FLOOR" in g["undercount_note"], "the under-count caveat travels with the number")

# =====================================================================
section("A11. sections H and I")
h = m["H_manual_review"]
review_ids = {r["run_id"] for r in h["series_requiring_review"]}
check(len(review_ids) == 2, "two series carry an objective failure and need review")
check(all(r["review_days"][0] == 7 and r["review_days"][-1] == 10
          for r in h["series_requiring_review"]),
      "review runs from the first failure day through day 10")
check(len(h["controls_selected"]["A"]) + len(h["controls_selected"]["B"]) >= 1,
      "clean control series are nominated")
i = m["I_condition_comparison"]
check(i["A"]["series"] == 2 and i["B"]["series"] == 2, "2 series per condition")
check(i["A"]["episodes"] == 20 and i["B"]["episodes"] == 20, "20 episodes per condition")
check(i["A"]["behind_pace_days"] == 4 and i["B"]["behind_pace_days"] == 0,
      "behind-pace days reported per condition with denominators")
check("no significance testing" in i["rules"] and "never pooled" in i["rules"],
      "condition-comparison rules are emitted with the numbers")

# =====================================================================
section("A12. main-phase code path (throwaway copy, real runs/ untouched)")
real_main_before = ({p.name: p.stat().st_mtime_ns
                     for p in (BASE / "runs" / "main_v2_1_r1").glob("*")}
                    if (BASE / "runs" / "main_v2_1_r1").is_dir() else None)
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "runs" / "main_v2_1_r1").mkdir(parents=True)
for p in sorted((BASE / "runs" / "pilot_v2_1").glob("pilot_v2_1_*.json")):
    rec = json.load(open(p, encoding="utf-8"))
    rec["run_id"] = rec["run_id"].replace("pilot_v2_1_", "main_v2_1_r1_")
    (tmp / "runs" / "main_v2_1_r1" / f"{rec['run_id']}.json").write_text(
        json.dumps(rec), encoding="utf-8")
real_base = am.BASE
try:
    am.BASE = tmp
    mm = am.analyze("main_v2_1_r1")
    check(mm["is_primary"] is True, "main phase is flagged primary")
    check(mm["label"] == "PRIMARY MAIN-PHASE RESULT", "main output carries the primary label")
    check("PILOT" not in mm["label"], "main label never says pilot")
    check(mm["validity"]["episodes_in_primary"] == 40,
          "analyzer runs unchanged on a main_v2_1 directory")
    check(set(mm["A_state_accuracy"].keys()) == set(m["A_state_accuracy"].keys()),
          "identical metric structure on both phases")
finally:
    am.BASE = real_base
    shutil.rmtree(tmp, ignore_errors=True)
check(am.BASE == real_base, "analyzer BASE restored")
# the real main phase directory (if it exists) must be completely untouched by
# the tmp-based main-path test above
real_main = BASE / "runs" / "main_v2_1_r1"
check(real_main_before == ({p.name: p.stat().st_mtime_ns for p in real_main.glob("*")}
                           if real_main.is_dir() else None),
      "the real main_v2_1_r1 directory is byte-for-byte untouched by the tests")
# aborted / audit-only phases are refused outright
for blocked in ("main_v2_1", "aborted_main_v2_1_credit"):
    try:
        am.load_phase(blocked)
        check(False, f"{blocked} refused")
    except SystemExit:
        check(True, f"{blocked} refused by the analyzer guard")

# =====================================================================
section("A12b. execution-metadata schema tolerance (regression)")
# the parallel runner stores sdk_version once per PHASE (_execution_plan.json)
# instead of once per record. the analyzer must read either shape, fall back to
# phase metadata, and report "missing" rather than crash. records here are
# synthetic reshapes of pilot records - no main record is read or written.


def _reshape(dst_phase, mutate, with_plan=None):
    t = pathlib.Path(tempfile.mkdtemp())
    (t / "runs" / dst_phase).mkdir(parents=True)
    for i, q in enumerate(sorted((BASE / "runs" / "pilot_v2_1").glob("pilot_v2_1_*.json"))):
        rec = json.load(open(q, encoding="utf-8"))
        rec["run_id"] = rec["run_id"].replace("pilot_v2_1_", dst_phase + "_")
        rec["_seq"] = i
        mutate(rec)
        rec.pop("_seq", None)
        (t / "runs" / dst_phase / f"{rec['run_id']}.json").write_text(
            json.dumps(rec), encoding="utf-8")
    if with_plan is not None:
        (t / "runs" / dst_phase / "_execution_plan.json").write_text(
            json.dumps(with_plan), encoding="utf-8")
    return t


def parallel_shape(rec):
    rec.pop("sdk_version", None)          # phase-level in the parallel runner
    rec.pop("execution_index", None)
    rec.pop("timestamp", None)
    rec["planned_execution_index"] = rec["_seq"]
    rec["started_at"] = "2026-08-27T16:25:16-0400"
    rec["completed_at"] = "2026-08-27T16:30:31-0400"
    rec["execution_mode"] = "parallel_workers"


PLAN = {"phase": "main_v2_1_r1", "sdk_version": "0.125.0",
        "model": "claude-sonnet-4-5", "world_hash": world.world_hash(),
        "prompt_hashes": {"seller_system": "x"}, "max_workers": 3}

real = am.BASE
t1 = _reshape("main_v2_1_r1", parallel_shape, with_plan=PLAN)
try:
    am.BASE = t1
    mp = am.analyze("main_v2_1_r1")          # must not raise KeyError
    check(True, "parallel-shaped records analyse without crashing")
    v = mp["validity"]
    check(v["sdk_versions"] == ["0.125.0"], "sdk_version recovered from phase metadata")
    check(v["sdk_version_source"] == "phase:_execution_plan.json",
          "sdk_version source is reported as phase-level, not invented")
    check(v["world_hash_source"] == "per_record", "world hash still read per record")
    check(v["resolved_models"] and v["resolved_model_source"] == "per_record",
          "resolved model still read per record")
    check(v["planned_index_source"] == "per_record"
          and v["planned_indices_complete"] is True,
          "planned execution indices read from records and complete")
    check(v["timestamp_source"] == "started_at/completed_at",
          "parallel timestamps recognised")
    check(v["phase_metadata_file"] == "_execution_plan.json",
          "phase metadata file recorded")
    check(v["episodes_in_primary"] == 40, "metrics still computed on the new shape")
finally:
    am.BASE = real
    shutil.rmtree(t1, ignore_errors=True)

# sequential shape still works unchanged
t2 = _reshape("main_v2_1_r1", lambda rec: None)
try:
    am.BASE = t2
    ms = am.analyze("main_v2_1_r1")
    vs = ms["validity"]
    check(vs["sdk_versions"] == ["0.125.0"] and vs["sdk_version_source"] == "per_record",
          "sequential shape still reads sdk_version per record")
    check(vs["timestamp_source"] == "legacy_timestamp",
          "sequential timestamp field recognised as legacy")
    check(vs["planned_index_source"] == "legacy_execution_index",
          "sequential execution_index recognised as legacy")
finally:
    am.BASE = real
    shutil.rmtree(t2, ignore_errors=True)

# metadata missing everywhere: report, never crash, never invent


def strip_all(rec):
    parallel_shape(rec)
    rec.pop("resolved_model_seller", None)
    rec.pop("prompt_hashes", None)
    rec.pop("started_at", None)
    rec.pop("completed_at", None)
    rec.pop("planned_execution_index", None)


t3 = _reshape("main_v2_1_r1", strip_all)          # no plan file at all
try:
    am.BASE = t3
    mn = am.analyze("main_v2_1_r1")
    vn = mn["validity"]
    check(vn["sdk_versions"] == [] and vn["sdk_version_source"] == "missing",
          "missing sdk_version is reported as missing, not invented")
    check(vn["resolved_models"] == [] and vn["resolved_model_source"] == "missing",
          "missing resolved model reported as missing")
    check(vn["prompt_hash_source"] == "missing", "missing prompt hashes reported")
    check(vn["first_started_at"] == "missing"
          and vn["timestamp_source"] == "missing", "missing timestamps reported")
    check(vn["planned_index_source"] == "missing", "missing planned index reported")
    check(vn["phase_metadata_file"] == "missing", "absent phase metadata reported")
    check(vn["episodes_in_primary"] == 40,
          "all metrics still computed when metadata is absent")
    check(vn["world_hashes"] == [world.world_hash()],
          "world hash still available per record")
finally:
    am.BASE = real
    shutil.rmtree(t3, ignore_errors=True)
check(am.BASE == real, "analyzer BASE restored after the schema tests")

# =====================================================================
section("A13. written outputs")
out = am.write_outputs("pilot_v2_1", m)
check((out / "metrics.json").exists(), "metrics.json written")
check((out / "episodes.csv").exists(), "episodes.csv written")
check((out / "manual_review_worklist.md").exists(), "manual_review_worklist.md written")
csv_lines = (out / "episodes.csv").read_text(encoding="utf-8").strip().splitlines()
check(len(csv_lines) == 41, "episodes.csv has 40 rows plus a header")
loaded = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
check("PILOT-ONLY VALIDATION" in loaded["label"], "written metrics carry the pilot-only label")
check("_episodes" not in loaded, "metrics.json holds summaries, episodes go to csv")
check("PILOT-ONLY" in (out / "manual_review_worklist.md").read_text(encoding="utf-8"),
      "worklist carries the pilot-only label")

print(f"\n{'=' * 60}")
print(f"analyzer suite — passed: {PASS}   failed: {len(FAIL)}")
for x in FAIL:
    print("  FAIL:", x)
sys.exit(1 if FAIL else 0)
