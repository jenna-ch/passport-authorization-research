# analyze.py — aggregate run records into results.csv and a summary
# usage: python analyze.py --phase pilot
#
# every metric is recomputed by replaying each record's stored `actions`
# through the current scoring logic. raw run records are read-only and their
# embedded "scores" snapshots are never trusted, so a scoring correction takes
# effect here with no rescoring workflow and no rewriting of historical data.
#
# denominators are explicit and never mixed:
#   primary metrics    -> primary_analysis_eligible runs only
#                         (parse_ok AND scripted_buyer_ok AND full_pressure_exposure)
#   attrition          -> parse_ok runs that ended before full pressure
#                         exposure, reported by condition (a difference between
#                         A and B here is itself a behavioral signal)
#   secondary metrics  -> all parse_ok runs (deal rate legitimately includes
#                         early acceptances)
# ineligible runs are never silently dropped: every run appears in results.csv
# with its validity flags, and attrition is reported per condition.
import argparse
import csv
import json
import pathlib

import scoring

BASE = pathlib.Path(__file__).parent

ROW_FIELDS = [
    "run_id", "phase", "condition", "execution_index", "deal", "ended_by",
    "rounds_used",
    "unauthorized_concession_count", "has_unauthorized_concession",
    "hard_floor_breach", "final_price", "final_quantity", "final_payment_terms",
    "seller_concession_count", "leakage_deterministic_count",
    "leakage_flagged_count",
    "parse_ok", "scripted_buyer_ok", "full_pressure_exposure",
    "primary_analysis_eligible",
    "resolved_model_seller", "resolved_model_buyer",
]


def row_from(record):
    # scores are ALWAYS replayed from the stored action transcript with the
    # current scoring logic, never read from the record's "scores" field. that
    # field is a snapshot written when the run executed and goes stale whenever
    # scoring is corrected. replaying keeps historical raw records immutable
    # while still reporting corrected metrics (§ scores are recomputable from
    # stored actions without re-running negotiations).
    sc = scoring.score_run(record)
    v = record["validity"]
    rm = record.get("resolved_model", {})
    return {
        "run_id": record["run_id"],
        "phase": record["phase"],
        "condition": record["condition"],
        "execution_index": record.get("execution_index"),
        "deal": sc["deal"],
        "ended_by": record["outcome"]["ended_by"],
        "rounds_used": record["outcome"]["rounds_used"],
        "unauthorized_concession_count": sc["unauthorized_concession_count"],
        "has_unauthorized_concession": sc["has_unauthorized_concession"],
        "hard_floor_breach": sc["hard_floor_breach"],
        "final_price": sc["final_price"],
        "final_quantity": sc["final_quantity"],
        "final_payment_terms": sc["final_payment_terms"],
        "seller_concession_count": sc["seller_concession_count"],
        "leakage_deterministic_count": sc["leakage_deterministic_count"],
        "leakage_flagged_count": len(sc["leakage_flagged_for_review"]),
        "parse_ok": v["parse_ok"],
        "scripted_buyer_ok": v["scripted_buyer_ok"],
        "full_pressure_exposure": v["full_pressure_exposure"],
        "primary_analysis_eligible": v["primary_analysis_eligible"],
        "resolved_model_seller": rm.get("seller"),
        "resolved_model_buyer": rm.get("buyer"),
    }


def pct(k, n):
    return f"{k}/{n} ({k / n:.0%})" if n else f"{k}/0 (n/a)"


def summarize(rows, cond):
    total = [r for r in rows if r["condition"] == cond]
    valid = [r for r in total if r["parse_ok"]]
    eligible = [r for r in valid if r["primary_analysis_eligible"]]
    attrition = [r for r in valid if not r["full_pressure_exposure"]]

    lines = [f"condition {cond}: total runs={len(total)} | parse_ok={len(valid)} | "
             f"primary-eligible={len(eligible)} | "
             f"early termination before full exposure={len(attrition)}"]

    # primary metric — eligible runs only, denominator explicit
    if eligible:
        viol_runs = sum(1 for r in eligible if r["has_unauthorized_concession"])
        viol_total = sum(r["unauthorized_concession_count"] for r in eligible)
        lines.append(f"  primary [n={len(eligible)} eligible]: "
                     f"unauthorized concession rate={pct(viol_runs, len(eligible))} | "
                     f"total unauthorized concessions={viol_total}")
    else:
        lines.append("  primary: no eligible runs")

    # attrition detail — retained, reported, never mixed into primary
    if attrition:
        ends = {}
        for r in attrition:
            ends[r["ended_by"]] = ends.get(r["ended_by"], 0) + 1
        detail = ", ".join(f"{k} x{v}" for k, v in sorted(ends.items()))
        lines.append(f"  attrition [n={len(attrition)} of {len(valid)} valid]: {detail}")

    # secondary metrics — all parse_ok runs
    if valid:
        deals = sum(1 for r in valid if r["deal"])
        prices = [r["final_price"] for r in valid if r["final_price"] is not None]
        mean_price = f"{sum(prices) / len(prices):.3f}" if prices else "n/a"
        lines.append(f"  secondary [n={len(valid)} valid]: "
                     f"deal rate={pct(deals, len(valid))} | "
                     f"mean final price={mean_price} | "
                     f"floor breaches={sum(1 for r in valid if r['hard_floor_breach'])} | "
                     f"mean seller concessions={sum(r['seller_concession_count'] for r in valid) / len(valid):.1f} | "
                     f"det. leaks={sum(r['leakage_deterministic_count'] for r in valid)} | "
                     f"flagged for leak review={sum(r['leakage_flagged_count'] for r in valid)}")
    return "\n".join(lines)


def model_consistency_check(rows):
    models = {r["resolved_model_seller"] for r in rows} | {r["resolved_model_buyer"] for r in rows}
    models.discard(None)
    if len(models) > 1:
        return (f"WARNING: model-consistency validity issue — multiple resolved "
                f"model ids across runs: {sorted(models)}. resolve before "
                f"interpreting A/B results.")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="pilot")
    args = ap.parse_args()

    run_dir = BASE / "runs" / args.phase
    records = [json.loads(p.read_text())
               for p in sorted(run_dir.glob("*.json"))
               if not p.name.startswith("_")]
    if not records:
        print(f"no run records in {run_dir}")
        return
    rows = [row_from(r) for r in records]

    out = BASE / "runs" / f"results_{args.phase}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ROW_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows)\n")

    parse_failures = [r["run_id"] for r in rows if not r["parse_ok"]]
    if parse_failures:
        print(f"parse failures (in csv, excluded from all metrics): {parse_failures}\n")

    warn = model_consistency_check(rows)
    if warn:
        print(warn + "\n")

    for cond in ("A", "B"):
        print(summarize(rows, cond))
        print()


if __name__ == "__main__":
    main()
