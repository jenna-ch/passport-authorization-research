# Passport Authorization-Control Research

**Status: closed.** This is the finished record of a completed research programme. Nothing here is
active work, and the API-calling runners are historical reproduction infrastructure rather than a
starting point.

> **Scope note applying to everything below.** Every Passport-like control in this programme is a
> **simulated control built from design concepts under consideration** — not deployed Passport
> functionality. No number here is a production performance figure, and some scaffolding exists only
> to isolate a control mechanism and should not be read as a proposed Passport primitive.

## 1. What this repository is

The evidence chain for a study of where authorization becomes operationally hard when autonomous
agents make commercial commitments: ten experiment cells with their frozen inputs, raw run records,
analysis code and final analyses, plus the two reports that interpret them.

## 2. Research question

The programme did **not** ask whether agents need delegated authorization — Kite's architecture
already assumes they do. It asked:

> **Once delegated authorization exists, where does it become operationally difficult when agents
> make commercial commitments?**

## 3. The five control boundaries

| # | Boundary | Failure mode | Strongest evidence |
|---|---|---|---|
| 1 | **Commitment surface** | Authorization bound to an action's *label* misses economically identical commitments made by another path | P3-A: exact tracker/classifier equivalence on 35/35 observed accepts; unauthorized accepts settle deeper (median $0.890, 4 ≤ $0.87) than counters (median $0.900, 0 ≤ $0.87) |
| 2 | **Containment & recovery** | Blocking stops propagation but leaves the agent unable to recover; it repeats the same economics until the retry budget is gone | P3-B: unauthorized sent/committed 25 → 0 → 0, no detectable change in attempt propensity (pairwise p ≥ 0.264). P3-B2: first-retry repair 0/15 vs 7/14 (p = 0.0022); economic term changed 1/15 vs 10/14 (p = 0.00048) |
| 3 | **Intent & structured representation** | The structured commitment cannot express the commercial intent, so enforcement correctly evaluates the wrong commitment | P3-C: `conditional_on` conjoins non-null fields and has **no OR operator**. Retrospectively, 3 of 5 verified OR-prose/AND-structure cases parsed, relayed and committed; 0 of 5 were detected as a prose/structure disagreement |
| 4 | **State availability vs state use** | State can exist, be correct and be reachable, and still never enter the decision | Study 2: a deterministic morning block removed 8/8 classification errors (arithmetic exact 200/200), yet one unsafe attempt still occurred. C3: an optional canonical read was called once in six episodes, after the decision was already stated |
| 5 | **Mandate refresh & authority lifecycle** | Authority is versioned and dynamic; refresh mechanisms can be costly and be mistaken for economic enforcement | P3-D2: stale-authority attempts 0/16 in every arm (CI [0, 0.206]); 48/48 declined the amendment. The ack gate blocked 37/37 **non-committing** actions, ended 10/16 runs with no deal, and never inspected the price cap it nominally protected |

**Cross-cutting:** measuring **attempted → sent → committed** separately was the single most useful
instrument. Outcome-only scoring would have recorded nothing in Study 2's day-7 floor breach, nothing
in P3-B's 78 blocked attempts, and nothing in P3-D2's stale-authority attempt.

## 4. Start here

1. **[`report/final_synthesis.md`](report/final_synthesis.md)** — the authoritative conclusion. Start,
   and for most readers finish, here. Limitations are §9; provenance is §10.
2. **[`report/foundational_studies.md`](report/foundational_studies.md)** — the Phase 1–2 record that
   defines the five boundaries.
3. **[`report/phase3_design_of_record.md`](report/phase3_design_of_record.md)** — the Phase 3
   pre-registration: why this cell set exists and what was deliberately not revisited.

Then, per cell, `experiments/<cell>/analysis.md`.

## 5. Experiment map

| Directory | Question | Status | Main output |
|---|---|---|---|
| [`01_delegated_authority`](experiments/01_delegated_authority) | Study 1 — is delegated authority respected under repeated pressure? | complete · 20/arm, eligible 19 A / 20 B | `runs/results_main.csv`; findings in the foundational report |
| [`02_persistent_state`](experiments/02_persistent_state) | Study 2 — is commercial state kept correct over a horizon? | complete · 10 series/arm, 200 episodes | [`runs/analysis_main_v2_1_r1/`](experiments/02_persistent_state/runs/analysis_main_v2_1_r1) |
| [`03_shared_agreement_state`](experiments/03_shared_agreement_state) | Study 3 — shared bilateral agreement state, two six-episode pilots | complete · 12 episodes · **meaningful null** | [`analysis.md`](experiments/03_shared_agreement_state/analysis.md) |
| [`04_authority_guard`](experiments/04_authority_guard) | C1 — does an authorization guard change behaviour? | complete · n = 20 primary (25 traces) | [`analysis.md`](experiments/04_authority_guard/analysis.md) + `manifest.json` |
| [`05_optional_agreement_read`](experiments/05_optional_agreement_read) | C3 — is canonical agreement state consulted when the tool is optional? | complete · 6 episodes | [`analysis.md`](experiments/05_optional_agreement_read/analysis.md) |
| [`06_commitment_surface`](experiments/06_commitment_surface) | P3-A — is the same constraint respected across actions creating the same commitment? | complete · 80 runs, 79 eligible | [`analysis.md`](experiments/06_commitment_surface/analysis.md) + `manifest.json` + `design.md` |
| [`07_enforcement_recovery`](experiments/07_enforcement_recovery) | P3-B — does enforcement change attempts, and does refusal content change recovery? | complete · 120 runs, 119 eligible | [`analysis.md`](experiments/07_enforcement_recovery/analysis.md) |
| [`08_refusal_feedback`](experiments/08_refusal_feedback) | P3-B2 — which component of post-block feedback causes repair? | complete · 80 runs; primary denominator 29 | [`analysis.md`](experiments/08_refusal_feedback/analysis.md) + `manifest.json` + `design.md` |
| [`09_representation_consistency`](experiments/09_representation_consistency) | P3-C — intent vs structured representation | complete · **offline only, no API runs by design** | [`design_and_analysis.md`](experiments/09_representation_consistency/design_and_analysis.md) §10, §14 |
| [`10_mandate_refresh`](experiments/10_mandate_refresh) | P3-D2 — what makes an updated mandate govern the next commitment? | complete · 48 runs | [`analysis.md`](experiments/10_mandate_refresh/analysis.md) + `manifest.json` + `analysis_computed.json` + `design.md` |
| [`demos/commitment_guard`](demos/commitment_guard) | Walkthrough: a pre-commit authorization check applied to one recorded residual failure | — | open `index.html` (no server, no network) |

Study 3 holds two pilots as `pilot_1/` and `pilot_2/` — separate codebases with colliding module
names, so they cannot be flattened. Pilot 1's status observations were excluded as contaminated by a
close-delivery defect; its records are retained because the 12-episode figure rests on both.

**Designed but never built,** so you do not go looking: C2 (disclosure/envelope) was scoped and left
unbuilt, and P3-D1 was designed in the Phase 3 design of record but not executed — boundary 4's
evidence comes from Study 2 and C3.

## 6. Historical path → clean handoff path

The reports, the frozen manifests and the design records were written against the original working
tree and **have not been edited**, so they refer to the paths on the left. Frozen execution plans and
run records also embed `"design_of_record": "phase3_design_of_record.md"` /
`"phase3_p3d2_design_and_implementation.md"`, and those strings are left intact because they are part
of the frozen provenance. Resolve any such reference with this table.

| Historical path | Clean handoff path |
|---|---|
| `negotiation_exp/` | `experiments/01_delegated_authority/` |
| `study2_repeated_negotiation/` | `experiments/02_persistent_state/` |
| `study3_pilot/` | `experiments/03_shared_agreement_state/pilot_1/` |
| `study3_pilot2/` | `experiments/03_shared_agreement_state/pilot_2/` |
| `phase2_c1_guard/` | `experiments/04_authority_guard/` |
| `phase2_c3_read/` | `experiments/05_optional_agreement_read/` |
| `phase3_p3a_surface/` | `experiments/06_commitment_surface/` |
| `phase3_p3b_enforcement/` | `experiments/07_enforcement_recovery/` |
| `phase3_p3b2_refusal/` | `experiments/08_refusal_feedback/` |
| `phase3_p3c_representation/` | `experiments/09_representation_consistency/` |
| `phase3_p3d2_mandate/` | `experiments/10_mandate_refresh/` |
| `phase3_final_synthesis_authorization_control_boundaries.md` | `report/final_synthesis.md` |
| `autonomous_agents_authority_and_agreement_state.md` | `report/foundational_studies.md` |
| `phase3_design_of_record.md` | `report/phase3_design_of_record.md` |
| `phase3_p3a_analysis.md` · `_manifest.json` · `_design_and_implementation.md` | `experiments/06_commitment_surface/analysis.md` · `manifest.json` · `design.md` |
| `phase3_p3b_analysis.md` | `experiments/07_enforcement_recovery/analysis.md` |
| `phase3_p3b2_analysis.md` · `_manifest.json` · `_design_and_implementation.md` | `experiments/08_refusal_feedback/analysis.md` · `manifest.json` · `design.md` |
| `phase3_p3c_design_and_implementation.md` | `experiments/09_representation_consistency/design_and_analysis.md` |
| `phase3_p3d2_analysis.md` · `_manifest.json` · `_computed.json` · `_design_and_implementation.md` | `experiments/10_mandate_refresh/analysis.md` · `manifest.json` · `analysis_computed.json` · `design.md` |
| `phase2_c1_final_review.md` · `phase2_c1_analysis_manifest.json` | `experiments/04_authority_guard/analysis.md` · `manifest.json` |
| `phase2_c3_final_review.md` | `experiments/05_optional_agreement_read/analysis.md` |
| `study3_pilot2_final_review.md` | `experiments/03_shared_agreement_state/analysis.md` |
| `negotiation_exp/experiment_spec_v1.1.md` | `experiments/01_delegated_authority/spec.md` |
| `study2_.../spec_v2_frozen.md` · `analysis_plan_main_v2_1.md` | `experiments/02_persistent_state/spec.md` · `analysis_plan.md` |
| `commitment_guard_prototype/` | `demos/commitment_guard/` |

The foundational report's provenance table (§ near the end) and superseded development documents —
interim memos, design-review iterations, Study 1 and Study 2 pilot runs, the aborted Study 2 main
phase — are **not** in this repository. They are preserved in the researcher's archival backup of the
original working tree, which remains the reference for development chronology.

## 7. Evidence hierarchy

Most raw to most interpreted. **Raw runs govern fact; the final synthesis governs interpretation.**

1. **Frozen inputs** — `<cell>/prompts/`, `10_mandate_refresh/frozen/` (a byte-identical copy of the
   C3 world), `frozen_eligibility.py`, `spec.md`. Hashed into the manifests; each Phase 3 cell froze
   its predecessor's mechanics and refuses to start a confirmed run on a hash mismatch.
2. **Harness code** — the `.py` files in each cell. **Duplicated across cells deliberately:** the
   manifests hash the per-cell copies, so deduplicating would break the audit chain.
3. **Execution plans** — `runs/*/_execution_plan.json`, `_execution_order.json`,
   `_run_manifest*.json`, `FIRST_GATE_DECISION.json`, frozen before execution and carrying no
   timestamps for that reason. Digests: P3-A `a84221ec93fc3e6c`, P3-B `f7fe5a9cd9d19804`,
   P3-B2 `2af662f12314cbb7`, P3-D2 `878d5ecddd2373c3`.
4. **Raw run records** — `<cell>/runs/<name>/*.json` plus `*_transcript.md`. The primary evidence.
5. **Analysis outputs** — per-cell CSV/metrics, `analysis.md`, `manifest.json`,
   `analysis_computed.json`. Manifests were frozen **before outcome interpretation**.
6. **Final synthesis** — `report/final_synthesis.md`.

Study 2 precedence: `runs/main_v2_1_r1/` is the authoritative sample. Its pilots and the aborted
credit-exhausted main phase were removed in the handoff cleanup and live in the archival backup.

## 8. Reproduction

**The programme is closed; the confirmed runners should not be re-run in normal use.** A rerun costs
money, produces records outside the frozen sample, and proves nothing about the frozen results.

**Offline-only — no credential needed.** Run each from inside its own directory:

| Cell | Command | Checks |
|---|---|---|
| 01 | `python test_offline.py` | 122 |
| 02 | `python test_offline.py` · `test_analysis.py` · `test_concurrency.py` | 230 · 127 · 139 |
| 03 pilot_1 / pilot_2 | `python test_offline.py` | unittest |
| 04 | `python test_offline_c1.py` | 107 |
| 05 | `python test_offline_c3.py` | 80 |
| 06 | `python test_offline_p3a.py` | 213 |
| 07 | `python test_offline_p3b.py` | 260 |
| 08 | `python test_offline_p3b2.py` | 366 |
| 09 | `python test_offline_p3c.py` | 101 |
| 10 | `python test_offline_p3d2.py` | 353 |

Several suites read **sibling** cells to verify byte-identity (04, 06, 07, 08, 09 read 01; 10 reads
03/pilot_2 and 05). Run them from a full checkout, not a copied-out single directory, or those gates
silently find nothing. P3-D2 additionally asserts that exactly **12** retrospective fixtures are
recovered from C3 and pilot_2 records — a guard against an empty glob passing vacuously.

**Analysis-only — reads existing records, no API calls.**
`01/analyze.py`, `02/analyze_main.py --phase main_v2_1_r1`, `10/analyze_p3d2.py`, `10/exact_stats.py`,
`09/` in full, and `demos/commitment_guard/build_data.py`.
`10/analyze_p3d2.py` **rewrites `analysis_computed.json` in place** — to verify without disturbing the
committed artifact, run it in a scratch copy of the repository and diff.

**API-calling (historical):** `run.py` / `run_parallel.py` / `run_c1.py` / `run_c3.py` / `run_p3a.py`
/ `run_p3b.py` / `run_p3b2.py` / `run_p3d2.py` / `run_pilot.py` / `run_pilot2.py`. Each needs a
credential (§10) and `pip install -r requirements.txt` **from inside that cell** — environments were
frozen per cell and are deliberately not unified.

## 9. Integrity rules

- **Do not modify frozen files:** anything under `runs/`, any `prompts/`, `10_mandate_refresh/frozen/`,
  every `manifest.json` and execution plan, every `analysis.md` / `analysis_computed.json`, every
  `design.md`, `spec.md`, `frozen_eligibility.py`, and both reports.
- **Do not overwrite run records.** If you ever re-execute a runner, write to a new run directory.
- **Do not regenerate manifests or plans.** They are provenance records whose value is the moment
  they were frozen. `10_mandate_refresh/freeze_manifest_p3d2.py` is retained as historical tooling
  and is marked **do not re-run**. Verify by comparing hashes, never by rewriting.
- **Do not narrow or remove `.gitattributes`.** Its `* -text` rule keeps a checkout byte-identical to
  the committed record, which is what keeps the recorded hashes verifiable. Run records intentionally
  carry mixed line endings, so any normalization would rewrite them.

## 10. Environment and credentials

No credentials are committed; `.env` and `.env.*` are ignored and `.env.example` is the template.

```bash
cp .env.example experiments/06_commitment_surface/.env   # or whichever cell you will run
cd experiments/06_commitment_surface && pip install -r requirements.txt
```

Each API-calling cell reads a **cell-local** `.env`. A static workspace-scoped Anthropic key works as
written; an identity-linked key additionally needs an `anthropic-workspace-id` header the runners do
not send, so it fails authentication rather than revealing a bug. The keys used during the original
research have been **revoked**; a fresh key is required for any rerun.

## 11. Programme status

**Closed.** Evidence collection is complete, the synthesis is written, and no further experiments are
planned. Unresolved questions are stated as limitations rather than gaps to fill: whether the results
survive a different model, scenario family or scale; whether enforcement *causes* P3-B's containment
pattern (the guard was announced as well as applied); and whether a commitment schema should be able
to express the conditions agents actually form. Start from `report/final_synthesis.md` §9.
