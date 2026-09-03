# =====================================================================
# HISTORICAL PROVENANCE TOOLING - DO NOT RE-RUN.
#
# This script produced the authoritative frozen manifest committed beside
# it as manifest.json. That manifest is a provenance record: it was frozen
# before any outcome was interpreted, and its value depends on WHEN it was
# written. Re-running this script would overwrite that record with a new
# one computed today, silently destroying the freeze. The experimental
# programme is closed; there is no situation in normal handoff use where
# regenerating the manifest is correct. To verify integrity, compare
# hashes against manifest.json - never rewrite it.
# =====================================================================
# freeze_manifest_p3d2.py — FREEZE THE SAMPLE BEFORE ANY OUTCOME IS COMPUTED.
#
# This script reads the 48 records and the frozen plan and writes
# phase3_p3d2_analysis_manifest.json. It computes NO behavioural outcome: no
# stale-authority rate, no arm comparison, no primary. It only establishes
# that the sample is the planned one, that every run was produced from the
# same bytes, and that each record is internally consistent.
#
# It modifies nothing. It reads records read-only and writes one new file.

import glob
import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent
RUNS = BASE / "runs" / "p3d2"
PLAN_DIGEST = "878d5ecddd2373c3"
SEED = 20260825
UPDATE_SHA = "941c2ade9bd5ee21"
AMENDMENT_SHA = "7f02e53a9eb05267"
ARMS = ("D2-prompt", "D2-state", "D2-ack")


def sha16_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


plan = json.loads((RUNS / "_execution_plan.json").read_text(encoding="utf-8"))
paths = sorted(RUNS.glob("p3d2_*.json"))
recs = []
for p in paths:
    r = json.loads(p.read_text(encoding="utf-8"))
    r["_file"] = p.name
    r["_file_sha16"] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    r["_mtime"] = p.stat().st_mtime
    recs.append(r)
recs.sort(key=lambda r: r["plan_position"])

M = {"schema": "p3d2.analysis_manifest.v1",
     "cell": "P3-D2", "frozen_at_utc": None,
     "records_dir": str(RUNS.relative_to(BASE)),
     "n_records": len(recs)}

# ---------------------------------------------------------------- 1. the plan
pos = [r["plan_position"] for r in recs]
M["plan"] = {
    "stored_plan_digest": plan["plan_digest"],
    "expected_plan_digest": PLAN_DIGEST,
    "plan_digest_matches": plan["plan_digest"] == PLAN_DIGEST,
    "stored_order_seed": plan["order_seed"],
    "expected_order_seed": SEED,
    "seed_matches": plan["order_seed"] == SEED,
    "plan_n_total": plan["n_total"],
    "plan_arm_counts": plan["arm_counts"],
    "exactly_48_positions_represented": (sorted(pos) == list(range(1, 49))),
    "positions_unique": len(set(pos)) == len(pos),
    "run_ids_match_plan_exactly": all(
        r["run_id"] == p["run_id"] and r["arm"] == p["arm"]
        and r["plan_block"] == p["block"]
        for r, p in zip(recs, plan["positions"])),
    "every_record_carries_the_plan_digest": all(
        r["plan_digest"] == PLAN_DIGEST for r in recs),
    "every_record_carries_the_seed": all(r["order_seed"] == SEED for r in recs),
}
M["arm_counts_observed"] = {a: len([r for r in recs if r["arm"] == a])
                            for a in ARMS}
M["arm_counts_exact_16"] = all(v == 16 for v in M["arm_counts_observed"].values())

# ------------------------------------------------- 2. execution order + batch
order = sorted(recs, key=lambda r: r["timestamp"])
M["execution_order"] = {
    "timestamps_nondecreasing_in_plan_position": all(
        recs[i]["timestamp"] <= recs[i + 1]["timestamp"]
        for i in range(len(recs) - 1)),
    "execution_order_equals_plan_position": [r["plan_position"] for r in order]
    == list(range(1, 49)),
    "first_timestamp": recs[0]["timestamp"],
    "last_timestamp": recs[-1]["timestamp"],
}
b1 = [r for r in recs if r["plan_position"] <= 12]
b2 = [r for r in recs if r["plan_position"] > 12]


def byte_fingerprint(r):
    """everything model-visible or frozen that a run was produced from."""
    return {
        "prompt_hashes": r["prompt_hashes"],
        "frozen_comparison": {f'{x["group"]}::{x["file"]}': x["p3d2_copy"]
                              for x in r["frozen_comparison"]},
        "config": {k: r["config"][k] for k in
                   ("model", "temperature", "max_tokens", "turn_cap")},
        "control_strings": {k: sha16_text(v)
                            for k, v in r["control_strings"].items()},
        "world_hash": r["world_hash"],
        "update_text": sha16_text(r["principal_update"]["rendered_text"]),
        "amendment_text": sha16_text(r["provider_amendment"]["text"]),
        "ack_schema_note": sha16_text(r["principal_update"]["ack_schema_note"]),
        "rendered_prompts": {
            k: r["pre_update_fingerprint"]["model_visible_prompts"][k]
            for k in sorted(r["pre_update_fingerprint"]["model_visible_prompts"])},
    }


def fp16(r):
    return hashlib.sha256(json.dumps(byte_fingerprint(r), sort_keys=True,
                                     default=str).encode()).hexdigest()[:16]


fps = {r["run_id"]: fp16(r) for r in recs}
M["byte_identity"] = {
    "distinct_byte_fingerprints_across_all_48": len(set(fps.values())),
    "all_48_identical": len(set(fps.values())) == 1,
    "batch_1_positions_1_12_fingerprint": sorted({fps[r["run_id"]] for r in b1}),
    "batch_2_positions_13_48_fingerprint": sorted({fps[r["run_id"]] for r in b2}),
    "batches_used_identical_bytes": ({fps[r["run_id"]] for r in b1}
                                     == {fps[r["run_id"]] for r in b2}),
    "fingerprint_covers": sorted(byte_fingerprint(recs[0])),
}
M["prompt_and_frozen_manifests"] = {
    "principal_update_sha16": sorted({r["prompt_hashes"]
                                      ["principal_update_authority"] for r in recs}),
    "principal_update_matches_expected": all(
        r["prompt_hashes"]["principal_update_authority"] == UPDATE_SHA
        for r in recs),
    "provider_amendment_sha16": sorted({r["prompt_hashes"]["provider_amendment"]
                                        for r in recs}),
    "provider_amendment_matches_expected": all(
        r["prompt_hashes"]["provider_amendment"] == AMENDMENT_SHA for r in recs),
    "record_manifests_match_plan_manifest": all(
        r["prompt_hashes"] == plan["prompt_hashes"] for r in recs),
    "frozen_rows_per_record": sorted({len(r["frozen_comparison"]) for r in recs}),
    "all_frozen_files_identical_in_every_record": all(
        x["identical"] for r in recs for x in r["frozen_comparison"]),
    "record_frozen_manifest_matches_plan": all(
        {f'{x["group"]}::{x["file"]}': x["p3d2_copy"]
         for x in r["frozen_comparison"]}
        == {f'{x["group"]}::{x["file"]}': x["p3d2_copy"]
            for x in plan["frozen_comparison"]} for r in recs),
    "update_bytes_identical_across_48": len(
        {r["principal_update"]["rendered_text"] for r in recs}) == 1,
    "amendment_bytes_identical_across_48": len(
        {r["provider_amendment"]["text"] for r in recs}) == 1,
    "ack_note_bytes_identical_across_48": len(
        {r["principal_update"]["ack_schema_note"] for r in recs}) == 1,
}

# ------------------------------------------- 3. no overwrite / no rerun
M["no_overwrite_or_rerun"] = {
    "one_file_per_position": len(paths) == 48 and len(set(pos)) == 48,
    "distinct_file_hashes": len({r["_file_sha16"] for r in recs}) == 48,
    "distinct_started_at": len({r["started_at"] for r in recs}),
    "distinct_timestamps": len({r["timestamp"] for r in recs}),
    "mtime_order_matches_position": [r["plan_position"] for r in
                                     sorted(recs, key=lambda x: x["_mtime"])]
    == list(range(1, 49)),
    "no_duplicate_run_ids": len({r["run_id"] for r in recs}) == 48,
    "note": ("each position appears exactly once, with its own file hash, "
             "start time and completion timestamp, and file mtimes follow plan "
             "position — consistent with a single pass per position and no "
             "overwrite."),
}

# ---------------------------------------- 4. internal consistency, per record
integrity = []
for r in recs:
    row = {"run_id": r["run_id"], "arm": r["arm"],
           "position": r["plan_position"]}
    evs = r["action_events"]
    row["n_action_events"] = len(evs)
    row["monotonic_levels"] = all(
        (not e["committed"] or e["sent"]) and (not e["sent"] or e["attempted"])
        for e in evs)
    row["blocked_never_sent_or_committed"] = all(
        (not e["blocked"]) or (not e["sent"] and not e["committed"])
        for e in evs)
    row["level_reached_consistent"] = all(
        e["level_reached"] == ("committed" if e["committed"] else
                              "sent" if e["sent"] else
                              "attempted" if e["attempted"] else "not_attempted")
        for e in evs)
    row["committed_events_carry_state_delta"] = all(
        (not e["committed"]) or (e.get("state_delta") and
                                 e["state_delta"]["agreement_version_after"]
                                 == e["state_delta"]["agreement_version_before"] + 1)
        for e in evs)
    av_at_update = r["agreement_at_update"]["agreement_version"]
    av_final = (r["agreement"] or {}).get("agreement_version")
    n_adv = len([e for e in r["protocol_events"]
                 if e["kind"] == "agreement_version_advanced"])
    row["agreement_version_at_update"] = av_at_update
    row["agreement_version_final"] = av_final
    row["n_version_advances_logged"] = n_adv
    row["version_transition_consistent"] = (av_final == av_at_update + n_adv
                                            and av_at_update == 1
                                            and n_adv <= 1)
    row["n_committed_events"] = len([e for e in evs if e["committed"]])
    row["commit_count_matches_advances"] = (row["n_committed_events"] == n_adv)
    row["agreement_unchanged_at_update"] = (
        r["principal_update"]["agreement_at_update"] == r["agreement_at_update"])
    row["update_delivered_to_buyer_after_agreement"] = (
        r["principal_update"]["recipient"] == "buyer"
        and r["principal_update"]["delivered_after_turn"]
        == r["agreement_at_update"]["formed_at_turn"])
    row["amendment_scripted_zero_provider_calls"] = (
        r["provider_amendment"]["scripted"] is True
        and r["provider_amendment"]["provider_api_calls_for_it"] == 0)
    row["termination"] = r["termination"]["mode"]
    row["parse_failure"] = r["termination"]["mode"] == "parse_failure"
    row["parse_failure_detail"] = (r["termination"]["detail"]
                                   if row["parse_failure"] else None)
    row["reprompts_total"] = sum(t["reprompts"] for t in r["turns"])
    row["eligible"] = r["primary"]["eligible"]
    row["eligibility_reason"] = r["primary"].get("reason")
    row["gate_refusals"] = r["gate_refusals"]
    row["state_blocks_pre_update"] = sum(
        1 for t in r["turns"] if t["negotiation_phase"] == "pre_update"
        and t["state_block_rendered"])
    row["arm_consistent_with_mechanism"] = (
        (r["arm"] == "D2-prompt" and not r["arm_definition"]["state_block"]
         and not r["arm_definition"]["ack_gate"])
        or (r["arm"] == "D2-state" and r["arm_definition"]["state_block"]
            and not r["arm_definition"]["ack_gate"])
        or (r["arm"] == "D2-ack" and r["arm_definition"]["state_block"]
            and r["arm_definition"]["ack_gate"]))
    row["gate_refusals_only_in_gated_arm"] = (r["gate_refusals"] == 0
                                              or r["arm"] == "D2-ack")
    row["all_checks_pass"] = all(
        v is True for k, v in row.items()
        if k.startswith(("monotonic", "blocked_", "level_", "committed_ev",
                         "version_transition", "commit_count",
                         "agreement_unchanged", "update_delivered",
                         "amendment_scripted", "arm_consistent",
                         "gate_refusals_only")))
    integrity.append(row)

M["per_record_integrity"] = integrity
M["integrity_summary"] = {
    "records_passing_all_internal_checks": len(
        [x for x in integrity if x["all_checks_pass"]]),
    "parse_failures": [x["run_id"] for x in integrity if x["parse_failure"]],
    "records_with_reprompts": [(x["run_id"], x["reprompts_total"])
                               for x in integrity if x["reprompts_total"]],
    "ineligible_runs": [(x["run_id"], x["eligibility_reason"])
                        for x in integrity if not x["eligible"]],
    "state_blocks_pre_update_total": sum(x["state_blocks_pre_update"]
                                         for x in integrity),
    "termination_composition": {},
    "abnormal_terminations": [],
}
for x in integrity:
    M["integrity_summary"]["termination_composition"][x["termination"]] = \
        M["integrity_summary"]["termination_composition"].get(x["termination"], 0) + 1
for x in integrity:
    if x["termination"] in ("parse_failure", "turn_cap_reached",
                            "mutual_close_no_single_package"):
        M["integrity_summary"]["abnormal_terminations"].append(
            {"run_id": x["run_id"], "arm": x["arm"],
             "mode": x["termination"], "detail": x["parse_failure_detail"]})

M["FREEZE_VERDICT"] = (
    "SAMPLE FROZEN — 48 planned positions, byte-identical across both batches"
    if (M["plan"]["exactly_48_positions_represented"]
        and M["arm_counts_exact_16"]
        and M["plan"]["plan_digest_matches"]
        and M["plan"]["seed_matches"]
        and M["plan"]["run_ids_match_plan_exactly"]
        and M["byte_identity"]["all_48_identical"]
        and M["prompt_and_frozen_manifests"]["principal_update_matches_expected"]
        and M["prompt_and_frozen_manifests"]["provider_amendment_matches_expected"]
        and M["no_overwrite_or_rerun"]["distinct_file_hashes"]
        and M["integrity_summary"]["records_passing_all_internal_checks"] == 48)
    else "SAMPLE NOT CLEAN — see failing fields")

import time
M["frozen_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
out = BASE / "manifest.json"   # stays inside this experiment directory
out.write_text(json.dumps(M, indent=2, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in M.items()
                  if k not in ("per_record_integrity",)}, indent=2,
                 default=str))
print("\nwritten:", out)
