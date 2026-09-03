# analyze_main.py — implements analysis_plan_main_v2_1.md exactly.
#
# reads ONLY runs/<phase>/<phase>_*.json and replays scoring.score_series().
# it never imports pilot data into a main-phase run and never mutates any
# stored record. scoring.py is used as-is: this file defines no new scored
# event type, no new leakage pattern and no new tolerance.
#
# usage:
#   python analyze_main.py --phase pilot_v2_1     # pilot-only validation
#   python analyze_main.py --phase main_v2_1_r1   # primary analysis

import argparse
import csv
import json
import pathlib

import ledger
import scoring
import world

BASE = pathlib.Path(__file__).parent
MAIN_PHASE = "main_v2_1_r1"

# phases that must never be analysed. `main_v2_1` was aborted by api credit
# exhaustion; its partial records live in runs/aborted_main_v2_1_credit/ for
# audit only. this guard is an access rule, not a metric definition - nothing
# in analysis_plan_main_v2_1.md changes.
BLOCKED_PHASES = {"main_v2_1"}
BLOCKED_PREFIXES = ("aborted_",)
TOL_PROFIT = scoring.PROFIT_TOLERANCE     # $50, frozen
TOL_PRICE = scoring.PRICE_TOLERANCE       # $0.005, frozen

BINS = (("early", (1, 2, 3)), ("middle", (4, 5, 6, 7)), ("late", (8, 9, 10)))
STATE_TYPES = scoring.STATE_ERROR_TYPES
DECISION_TYPES = ("floor_breach_baseline", "floor_breach_pace", "below_cost_deal")
FAILURE_TYPES = scoring.VIOLATION_TYPES   # decision types + leakage


def bin_of(day):
    for name, days in BINS:
        if day in days:
            return name
    raise ValueError(day)


def state_dependent_days():
    # days where the correct action differs between the two minimums:
    # the buyer's max sits at or above the baseline minimum but below the
    # pace minimum. computed from the frozen world, never hard-coded.
    out = []
    for d in range(1, world.DAYS + 1):
        bmax = world.buyer(d)["max_price"]
        if (bmax >= ledger.baseline_minimum(d) - world.EPS
                and bmax < ledger.pace_minimum(d) - world.EPS):
            out.append(d)
    return out


def implied_minimum(day, reported_pace):
    margin = (world.BASELINE_MARGIN if reported_pace == "on_pace"
              else world.PACE_MARGIN)
    return round(world.cost(day) + margin, 4)


# ------------------------------------------------- execution metadata lookup
# execution metadata is written per record by the sequential runner and at
# phase level by the parallel runner (_execution_plan.json). the analyzer reads
# whichever exists and reports "missing" when neither does. this is metadata
# provenance only - no metric in analysis_plan_main_v2_1.md is affected.
PHASE_META_FILES = ("_execution_plan.json", "_execution_order.json")


def load_phase_metadata(phase):
    for name in PHASE_META_FILES:
        p = BASE / "runs" / phase / name
        if p.is_file():
            try:
                return json.load(open(p, encoding="utf-8")), name
            except (ValueError, OSError):
                return {}, None
    return {}, None


def _canon(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def meta_field(records, key, phase_meta, phase_meta_file):
    """(values, source). per-record first, then phase-level, then missing.
    never invents a value."""
    vals = sorted({_canon(r[key]) for r in records
                   if key in r and r[key] is not None})
    if vals:
        return vals, "per_record"
    if phase_meta and phase_meta.get(key) is not None:
        return [_canon(phase_meta[key])], f"phase:{phase_meta_file}"
    return [], "missing"


# ------------------------------------------------------------------ loading
def load_phase(phase):
    if phase in BLOCKED_PHASES or phase.startswith(BLOCKED_PREFIXES):
        raise SystemExit(
            f"refused: phase {phase!r} is an aborted or audit-only phase and "
            f"may never be analysed (see runs/aborted_main_v2_1_credit/ABORTED.md)")
    d = BASE / "runs" / phase
    if not d.is_dir():
        raise SystemExit(f"no such phase directory: {d}")
    files = sorted(d.glob(f"{phase}_*.json"))
    if not files:
        raise SystemExit(f"no records matching {phase}_*.json in {d}")
    out = []
    for f in files:
        rec = json.load(open(f, encoding="utf-8"))
        assert rec["run_id"].startswith(phase + "_"), \
            f"phase-scope violation: {rec['run_id']} in {phase}"
        out.append(rec)
    return out


# --------------------------------------------------------------- episodes
def episode_rows(rec, scored):
    rows = []
    for row, day_rec in zip(scored["per_day"], rec["days"]):
        day = row["day"]
        rp = day_rec["seller_report"]["parsed"] or {}
        types = [e["type"] for e in row["events"]]
        state_types = [t for t in types if t in STATE_TYPES]
        dec_types = [t for t in types if t in DECISION_TYPES]
        rep_min = rp.get("minimum_price_today")
        rep_pace = rp.get("pace_status")

        # direction of a state error, judged on the minimum the agent believed
        if not state_types:
            direction = "none"
        elif rep_min is None:
            direction = "unknown"
        elif rep_min > row["true_minimum_price"] + TOL_PRICE:
            direction = "conservative"
        elif rep_min < row["true_minimum_price"] - TOL_PRICE:
            direction = "permissive"
        else:
            direction = "neutral"

        # a minimum misstatement is DERIVED when it is exactly what the
        # agent's own (wrong) pace claim implies
        derived_min = None
        if "minimum_misstatement" in types and rep_pace is not None:
            derived_min = abs(rep_min - implied_minimum(day, rep_pace)) <= TOL_PRICE

        seller_prices = [a["action"]["price_per_unit"] for a in day_rec["actions"]
                         if a["role"] == "seller"
                         and a["action"]["price_per_unit"] is not None]
        buyer_prices = [a["action"]["price_per_unit"] for a in day_rec["actions"]
                        if a["role"] == "buyer"
                        and a["action"]["price_per_unit"] is not None]

        rows.append({
            "run_id": rec["run_id"], "condition": rec["condition"], "day": day,
            "bin": bin_of(day),
            "cumulative_profit_before": row["cumulative_profit_before"],
            "pace_requirement": ledger.pace_requirement(day),
            "on_pace": row["on_pace"],
            "true_minimum_price": row["true_minimum_price"],
            "baseline_minimum_price": ledger.baseline_minimum(day),
            "pace_minimum_price": ledger.pace_minimum(day),
            "buyer_max_price": day_rec["ground_truth_before"]["buyer_max_price"],
            "feasible_deal_exists": row["feasible_deal_exists"],
            "deal": row["deal"], "agreed_price": row["agreed_price"],
            "realized_profit": row["realized_profit"],
            "cumulative_profit_after": row["cumulative_profit_after"],
            "margin_vs_true_minimum": row["margin_vs_true_minimum"],
            "reported_profit": row["reported_profit"],
            "profit_belief_error": row["profit_belief_error"],
            "reported_pace": rep_pace, "reported_minimum": rep_min,
            "state_error": bool(state_types),
            "state_error_types": "|".join(state_types),
            "minimum_misstatement_derived": derived_min,
            "decision_wrong": bool(dec_types),
            "decision_types": "|".join(dec_types),
            "error_direction": direction,
            "leakage_count": sum(1 for t in types if t == "leakage"),
            "no_deal_with_feasible_deal": "no_deal_with_feasible_deal" in types,
            "no_deal_correct": "no_deal_correct" in types,
            "rounds_used": day_rec["outcome"]["rounds_used"],
            "rounds_remaining": world.MAX_ROUNDS - day_rec["outcome"]["rounds_used"],
            "ended_by": day_rec["outcome"]["ended_by"],
            "seller_last_price": seller_prices[-1] if seller_prices else None,
            "buyer_last_price": buyer_prices[-1] if buyer_prices else None,
        })
    return rows


# ---------------------------------------------------------------- sections
def section_a(eps, series):
    by_day = {}
    for d in range(1, world.DAYS + 1):
        rows = [e for e in eps if e["day"] == d]
        errs = [e["profit_belief_error"] for e in rows
                if e["profit_belief_error"] is not None]
        by_day[d] = {
            "n": len(rows),
            "mean_abs_profit_error": (round(sum(abs(x) for x in errs) / len(errs), 2)
                                      if errs else None),
            "n_profit_error_over_tolerance": sum(1 for x in errs if abs(x) > TOL_PROFIT),
            "n_over": sum(1 for x in errs if x > TOL_PROFIT),
            "n_under": sum(1 for x in errs if x < -TOL_PROFIT),
            "n_pace_misstatement": sum(1 for e in rows
                                       if "pace_misstatement" in e["state_error_types"]),
            "n_minimum_misstatement": sum(1 for e in rows
                                          if "minimum_misstatement" in e["state_error_types"]),
            "n_report_unparseable": sum(1 for e in rows
                                        if "state_report_unparseable" in e["state_error_types"]),
        }
    mins = [e for e in eps if "minimum_misstatement" in e["state_error_types"]]
    return {
        "by_day": by_day,
        "minimum_misstatements_total": len(mins),
        "minimum_misstatements_derived": sum(1 for e in mins
                                             if e["minimum_misstatement_derived"]),
        "minimum_misstatements_independent": sum(1 for e in mins
                                                 if e["minimum_misstatement_derived"] is False),
        "first_state_error_day": {s["run_id"]: s["first_state_error_day"] for s in series},
        "persistence": {s["run_id"]: s["persistence"] for s in series},
    }


def classify_persistence(rows, first_day):
    if first_day is None:
        return "no_state_error"
    later = [r for r in rows if r["day"] > first_day]
    if not later:
        return "terminal_day_only"
    flags = [r["state_error"] for r in later]
    if not any(flags):
        return "self_corrected"
    if all(flags):
        return "persistent"
    return "intermittent"


def section_b(eps, series):
    def n(key):
        return sum(1 for e in eps if e[key])
    deals = [e for e in eps if e["deal"]]
    margins = [e["margin_vs_true_minimum"] for e in deals]
    return {
        "episodes": len(eps),
        "floor_breach_baseline": sum(1 for e in eps
                                     if "floor_breach_baseline" in e["decision_types"]),
        "floor_breach_pace": sum(1 for e in eps
                                 if "floor_breach_pace" in e["decision_types"]),
        "below_cost_deal": sum(1 for e in eps if "below_cost_deal" in e["decision_types"]),
        "no_deal_with_feasible_deal": n("no_deal_with_feasible_deal"),
        "no_deal_correct": n("no_deal_correct"),
        "deals": len(deals),
        "target_met_series": sum(1 for s in series if s["target_met"]),
        "series": len(series),
        "final_profits": {s["run_id"]: s["final_cumulative_profit"] for s in series},
        "mean_margin_over_minimum": (round(sum(margins) / len(margins), 4)
                                     if margins else None),
        "deals_at_exactly_minimum": sum(1 for m in margins if abs(m) <= 1e-9),
        "realized_profit_by_day": {d: round(sum(e["realized_profit"] for e in eps
                                                if e["day"] == d), 2)
                                   for d in range(1, world.DAYS + 1)},
    }


def section_c(eps, series, by_run):
    bins = {}
    for name, days in BINS:
        rows = [e for e in eps if e["day"] in days]
        bins[name] = {
            "episodes": len(rows),
            "series_contributing": len({e["run_id"] for e in rows}),
            "state_errors": sum(1 for e in rows if e["state_error"]),
            "decision_violations": sum(1 for e in rows if e["decision_wrong"]),
            "leakage": sum(e["leakage_count"] for e in rows),
            "no_deal_with_feasible_deal": sum(1 for e in rows
                                              if e["no_deal_with_feasible_deal"]),
            "no_deal_correct": sum(1 for e in rows if e["no_deal_correct"]),
            "deals": sum(1 for e in rows if e["deal"]),
            "realized_profit": round(sum(e["realized_profit"] for e in rows), 2),
        }
    # clustering after zero-profit days
    after_zero = {"pairs": 0, "state_error": 0, "violation": 0}
    after_profit = {"pairs": 0, "state_error": 0, "violation": 0}
    for run_id, rows in by_run.items():
        rows = sorted(rows, key=lambda r: r["day"])
        for i in range(len(rows) - 1):
            bucket = after_zero if rows[i]["realized_profit"] == 0 else after_profit
            bucket["pairs"] += 1
            nxt = rows[i + 1]
            if nxt["state_error"]:
                bucket["state_error"] += 1
            if nxt["decision_wrong"] or nxt["leakage_count"]:
                bucket["violation"] += 1
    return {
        "bins": bins,
        "first_objective_failure_day": {s["run_id"]: s["first_violation_day"]
                                        for s in series},
        "after_zero_profit_day": after_zero,
        "after_profitable_day": after_profit,
        "at_cost_deals": sum(1 for e in eps if e["deal"] and e["realized_profit"] == 0),
    }


def section_d(eps):
    cell = {"wrong_state_wrong_decision": 0, "wrong_state_correct_decision": 0,
            "correct_state_wrong_decision": 0, "correct_state_correct_decision": 0}
    for e in eps:
        s, d = e["state_error"], e["decision_wrong"]
        key = (("wrong_state" if s else "correct_state") + "_"
               + ("wrong_decision" if d else "correct_decision"))
        cell[key] += 1
    directions = {}
    for name in ("conservative", "permissive", "neutral", "unknown"):
        rows = [e for e in eps if e["error_direction"] == name]
        directions[name] = {
            "episodes": len(rows),
            "wrong_decision": sum(1 for e in rows if e["decision_wrong"]),
            "correct_decision": sum(1 for e in rows if not e["decision_wrong"]),
        }
    near_misses = [{"run_id": e["run_id"], "day": e["day"],
                    "reported_minimum": e["reported_minimum"],
                    "true_minimum": e["true_minimum_price"],
                    "agreed_price": e["agreed_price"]}
                   for e in eps
                   if e["error_direction"] == "permissive" and not e["decision_wrong"]]
    return {"cells": cell, "by_direction": directions,
            "near_misses": near_misses,
            "note": "no_deal_with_feasible_deal and leakage are NOT wrong decisions"}


def section_e(eps, by_run):
    sd_days = state_dependent_days()
    behind = [e for e in eps if not e["on_pace"]]
    series_behind, first_behind, recoveries, on_behind_on = [], {}, {}, {}
    for run_id, rows in by_run.items():
        rows = sorted(rows, key=lambda r: r["day"])
        st = [r["on_pace"] for r in rows]
        b = [r["day"] for r in rows if not r["on_pace"]]
        if b:
            series_behind.append(run_id)
            first_behind[run_id] = b[0]
        recoveries[run_id] = [i + 1 for i in range(1, len(st)) if not st[i - 1] and st[i]]
        on_behind_on[run_id] = [i + 1 for i in range(1, len(st) - 1)
                                if st[i - 1] and not st[i] and st[i + 1]]
    opportunities = [{"run_id": e["run_id"], "day": e["day"],
                      "buyer_max": e["buyer_max_price"],
                      "true_minimum": e["true_minimum_price"],
                      "deal": e["deal"], "correct_action": "walk_away"}
                     for e in behind if e["day"] in sd_days]
    return {
        "state_dependent_days_in_world": sd_days,
        "series_entering_behind_pace": len(series_behind),
        "series_total": len(by_run),
        "behind_pace_days": len(behind),
        "episodes_total": len(eps),
        "first_behind_pace_day": first_behind,
        "recoveries": {k: v for k, v in recoveries.items() if v},
        "on_behind_on": {k: v for k, v in on_behind_on.items() if v},
        "state_dependent_opportunities": opportunities,
        "thin_exposure": len(series_behind) < 5,
    }


def section_f(eps):
    missed, all_walkaways = [], []
    for e in eps:
        if e["deal"]:
            continue
        entry = {
            "run_id": e["run_id"], "condition": e["condition"], "day": e["day"],
            "rounds_used": e["rounds_used"], "rounds_remaining": e["rounds_remaining"],
            "true_pace_state": "on_pace" if e["on_pace"] else "behind_pace",
            "behind_pace": not e["on_pace"],
            "buyer_max_price": e["buyer_max_price"],
            "true_minimum_price": e["true_minimum_price"],
            "seller_last_price": e["seller_last_price"],
            "buyer_last_price": e["buyer_last_price"],
            "gap": (round(e["seller_last_price"] - e["buyer_last_price"], 4)
                    if e["seller_last_price"] is not None
                    and e["buyer_last_price"] is not None else None),
            "pace_shortfall": round(e["pace_requirement"]
                                    - e["cumulative_profit_before"], 2),
            "feasible": e["feasible_deal_exists"],
            "ended_by": e["ended_by"],
        }
        all_walkaways.append(entry)
        if e["no_deal_with_feasible_deal"]:
            entry = dict(entry)
            entry["forgone_surplus"] = round(
                (e["buyer_max_price"] - e["true_minimum_price"]) * world.QUANTITY, 2)
            missed.append(entry)
    rounds_dist = {}
    for w in all_walkaways:
        rounds_dist[w["rounds_used"]] = rounds_dist.get(w["rounds_used"], 0) + 1
    return {
        "missed_feasible_deals": missed,
        "missed_by_day": {d: sum(1 for m in missed if m["day"] == d)
                          for d in sorted({m["day"] for m in missed})},
        "all_no_deal_days": len(all_walkaways),
        "walkaway_rounds_distribution": rounds_dist,
        "total_forgone_surplus": round(sum(m["forgone_surplus"] for m in missed), 2),
        "note": "commercial behaviour, reported separately from section B violations",
    }


def section_g(eps, records, scored_by_run):
    by_kind, by_day, events = {}, {}, []
    for rec in records:
        s = scored_by_run[rec["run_id"]]
        for e in s["events"]:
            if e["type"] != "leakage":
                continue
            k = e.get("kind", "unknown")
            by_kind[k] = by_kind.get(k, 0) + 1
            by_day[e["day"]] = by_day.get(e["day"], 0) + 1
            row = next(r for r in eps
                       if r["run_id"] == rec["run_id"] and r["day"] == e["day"])
            events.append({
                "run_id": rec["run_id"], "condition": rec["condition"],
                "day": e["day"], "kind": k, "sentence": e.get("sentence"),
                "economic_outcome": ("deal at " + str(row["agreed_price"])
                                     if row["deal"]
                                     else ("correct walk-away"
                                           if row["no_deal_correct"]
                                           else "walk-away from a feasible deal")),
                "decision_wrong": row["decision_wrong"],
            })
    ambiguous = sum(len(scored_by_run[r["run_id"]]["flagged_for_review"])
                    for r in records)
    return {
        "deterministic_leakage_total": sum(by_kind.values()),
        "by_kind": by_kind, "by_day": by_day, "events": events,
        "ambiguous_flags_total": ambiguous,
        "undercount_note": ("the same-sentence scoping rule means the "
                            "deterministic count is a FLOOR, not a total"),
    }


def section_h(series, by_run):
    review, clean = [], {"A": [], "B": []}
    for s in series:
        start = s["first_violation_day"]
        if start is not None:
            review.append({"run_id": s["run_id"], "condition": s["condition"],
                           "review_days": list(range(start, world.DAYS + 1)),
                           "reason": f"first objective failure day {start}"})
        elif s["first_state_error_day"] is None:
            clean[s["condition"]].append(s["run_id"])
    controls = {c: clean[c][:2] for c in ("A", "B")}
    return {"series_requiring_review": review,
            "clean_control_candidates": clean,
            "controls_selected": controls,
            "protocol": "spec v2.0 section 8, unchanged; new categories are "
                        "logged, never back-fitted into primary scoring"}


def section_i(eps, series):
    out = {}
    for cond in ("A", "B"):
        ce = [e for e in eps if e["condition"] == cond]
        cs = [s for s in series if s["condition"] == cond]
        if not cs:
            continue
        out[cond] = {
            "series": len(cs), "episodes": len(ce),
            "state_error_episodes": sum(1 for e in ce if e["state_error"]),
            "pace_misstatements": sum(1 for e in ce
                                      if "pace_misstatement" in e["state_error_types"]),
            "minimum_misstatements": sum(1 for e in ce
                                         if "minimum_misstatement" in e["state_error_types"]),
            "profit_misreports": sum(1 for e in ce
                                     if "state_misreport" in e["state_error_types"]),
            "decision_violations": sum(1 for e in ce if e["decision_wrong"]),
            "leakage": sum(e["leakage_count"] for e in ce),
            "no_deal_with_feasible_deal": sum(1 for e in ce
                                              if e["no_deal_with_feasible_deal"]),
            "behind_pace_days": sum(1 for e in ce if not e["on_pace"]),
            "series_behind_pace": len({e["run_id"] for e in ce if not e["on_pace"]}),
            "target_met": sum(1 for s in cs if s["target_met"]),
            "final_profit_mean": round(sum(s["final_cumulative_profit"]
                                           for s in cs) / len(cs), 2),
            "final_profit_min": min(s["final_cumulative_profit"] for s in cs),
            "final_profit_max": max(s["final_cumulative_profit"] for s in cs),
        }
    out["rules"] = ("descriptive only; counts with denominators; no significance "
                    "testing; no causal claim beyond the morning state block; "
                    "pilot phases are never pooled with main")
    return out


# ------------------------------------------------------------------ driver
def analyze(phase):
    records = load_phase(phase)
    scored_by_run, eps, series, excluded = {}, [], [], []
    for rec in records:
        s = scoring.score_series(rec)
        scored_by_run[rec["run_id"]] = s
        if not s["integrity_ok"]:
            excluded.append(rec["run_id"])
            continue
        rows = episode_rows(rec, s)
        eps.extend(rows)
        series.append({
            "run_id": rec["run_id"], "condition": rec["condition"],
            "final_cumulative_profit": s["final_cumulative_profit"],
            "target_met": s["target_met"],
            "first_state_error_day": s["first_state_error_day"],
            "first_violation_day": s["first_violation_day"],
            "persistence": classify_persistence(rows, s["first_state_error_day"]),
        })
    by_run = {}
    for e in eps:
        by_run.setdefault(e["run_id"], []).append(e)

    phase_meta, phase_meta_file = load_phase_metadata(phase)
    world_hashes, world_src = meta_field(records, "world_hash", phase_meta,
                                         phase_meta_file)
    sdk_versions, sdk_src = meta_field(records, "sdk_version", phase_meta,
                                       phase_meta_file)
    resolved_models, resolved_src = meta_field(records, "resolved_model_seller",
                                               phase_meta, phase_meta_file)
    configured_models, cfgmodel_src = meta_field(
        [r.get("config", {}) for r in records], "model", phase_meta, phase_meta_file)
    prompt_hash_sets, prompt_src = meta_field(records, "prompt_hashes", phase_meta,
                                              phase_meta_file)
    planned = [r["planned_execution_index"] for r in records
               if "planned_execution_index" in r]
    legacy_idx = [r["execution_index"] for r in records if "execution_index" in r]
    starts = sorted(r["started_at"] for r in records if r.get("started_at"))
    ends = sorted(r["completed_at"] for r in records if r.get("completed_at"))
    legacy_ts = sorted(r["timestamp"] for r in records if r.get("timestamp"))

    validity = {
        "phase": phase, "series_found": len(records),
        "series_excluded_integrity": excluded,
        "series_in_primary": len(series), "episodes_in_primary": len(eps),
        "world_hashes": world_hashes, "world_hash_source": world_src,
        "resolved_models": resolved_models, "resolved_model_source": resolved_src,
        "configured_models": configured_models,
        "configured_model_source": cfgmodel_src,
        "sdk_versions": sdk_versions, "sdk_version_source": sdk_src,
        "prompt_hash_sets": len(prompt_hash_sets),
        "prompt_hash_source": prompt_src,
        "phase_metadata_file": phase_meta_file or "missing",
        "planned_execution_indices": (sorted(planned) if planned else []),
        "planned_index_source": ("per_record" if planned else
                                 ("legacy_execution_index" if legacy_idx else "missing")),
        "planned_indices_complete": (sorted(planned) == list(range(len(records)))
                                     if planned else None),
        "first_started_at": starts[0] if starts else (legacy_ts[0] if legacy_ts else "missing"),
        "last_completed_at": ends[-1] if ends else (legacy_ts[-1] if legacy_ts else "missing"),
        "timestamp_source": ("started_at/completed_at" if starts or ends
                             else ("legacy_timestamp" if legacy_ts else "missing")),
        "report_parse_failures": sum(1 for r in records for d in r["days"]
                                     if not d["validity"]["report_parse_ok"]),
        "negotiation_parse_failures": sum(1 for r in records for d in r["days"]
                                          if not d["validity"]["parse_ok"]),
        "days_completed": sum(len(r["days"]) for r in records),
    }
    return {
        "is_primary": phase == MAIN_PHASE,
        "label": ("PRIMARY MAIN-PHASE RESULT" if phase == MAIN_PHASE
                  else f"PILOT-ONLY VALIDATION ({phase}) - NOT MAIN RESULTS"),
        "validity": validity,
        "A_state_accuracy": section_a(eps, series),
        "B_decision_coherence": section_b(eps, series),
        "C_horizon_pattern": section_c(eps, series, by_run),
        "D_state_vs_decision": section_d(eps),
        "E_behind_pace_exposure": section_e(eps, by_run),
        "F_walkaway_behavior": section_f(eps),
        "G_leakage": section_g(eps, [r for r in records
                                     if r["run_id"] not in excluded], scored_by_run),
        "H_manual_review": section_h(series, by_run),
        "I_condition_comparison": section_i(eps, series),
        "_episodes": eps,
    }


def write_outputs(phase, m):
    out = BASE / "runs" / f"analysis_{phase}"
    out.mkdir(parents=True, exist_ok=True)
    eps = m.pop("_episodes")
    (out / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    with open(out / "episodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(eps[0].keys()))
        w.writeheader()
        w.writerows(eps)
    lines = [f"# {m['label']}", "",
             f"world hash(es): {m['validity']['world_hashes']}",
             f"series: {m['validity']['series_in_primary']} | "
             f"episodes: {m['validity']['episodes_in_primary']}", ""]
    h = m["H_manual_review"]
    lines.append("## manual review worklist")
    for r in h["series_requiring_review"]:
        lines.append(f"- {r['run_id']} ({r['condition']}): days "
                     f"{r['review_days'][0]}-{world.DAYS} ({r['reason']})")
    lines.append(f"- controls: {h['controls_selected']}")
    (out / "manual_review_worklist.md").write_text("\n".join(lines) + "\n",
                                                   encoding="utf-8")
    m["_episodes"] = eps
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True,
                    help="main_v2_1_r1 for the primary analysis; a pilot phase "
                         "runs the same code as labelled validation")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    m = analyze(args.phase)
    out = write_outputs(args.phase, m)
    if not args.quiet:
        print("=" * 72)
        print(m["label"])
        print("=" * 72)
        v = m["validity"]
        print(f"series {v['series_in_primary']}/{v['series_found']} | episodes "
              f"{v['episodes_in_primary']} | days {v['days_completed']} | "
              f"parse failures {v['report_parse_failures']}/{v['negotiation_parse_failures']}")
        print(f"excluded for integrity: {v['series_excluded_integrity'] or 'none'}")
        e = m["E_behind_pace_exposure"]
        print(f"\nE. behind pace: {e['series_entering_behind_pace']}/{e['series_total']} series, "
              f"{e['behind_pace_days']}/{e['episodes_total']} days, "
              f"{len(e['state_dependent_opportunities'])} state-dependent opportunities"
              f"{'  [THIN EXPOSURE]' if e['thin_exposure'] else ''}")
        d = m["D_state_vs_decision"]["cells"]
        print(f"D. 2x2: {d}")
        b = m["B_decision_coherence"]
        print(f"B. breaches base/pace/below-cost: {b['floor_breach_baseline']}/"
              f"{b['floor_breach_pace']}/{b['below_cost_deal']} | "
              f"missed feasible {b['no_deal_with_feasible_deal']} | "
              f"correct walk-aways {b['no_deal_correct']} | "
              f"target met {b['target_met_series']}/{b['series']}")
        g = m["G_leakage"]
        print(f"G. leakage {g['deterministic_leakage_total']} deterministic "
              f"(floor), {g['ambiguous_flags_total']} ambiguous flags")
        f_ = m["F_walkaway_behavior"]
        print(f"F. missed feasible deals {len(f_['missed_feasible_deals'])} | "
              f"forgone ${f_['total_forgone_surplus']:,.0f} | "
              f"walk-away rounds {f_['walkaway_rounds_distribution']}")
    print(f"\nwrote {out}/metrics.json, episodes.csv, manual_review_worklist.md")


if __name__ == "__main__":
    main()
