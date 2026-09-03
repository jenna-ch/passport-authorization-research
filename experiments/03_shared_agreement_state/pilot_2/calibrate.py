# calibrate.py — deterministic calibration report. no api calls, no tuning.
# answers the six questions the design review requires, and nothing else.

import world as w

VER = {True: "yes", False: "NO", None: "n/a"}


def report():
    rows = w.enumerate_grid()
    L = []
    A = L.append

    A("STUDY 3 SECOND DISCOVERY PILOT — CALIBRATION REPORT")
    A("=" * 72)
    A(f"world hash : {w.world_hash()}")
    A(f"grid       : volume_A {list(w.VOLUME_A_GRID)}  total {list(w.TOTAL_GRID)}"
      f"  priority [True, False]")
    A(f"physical   : line A capacity {w.LINE_A_CAPACITY:,} ; reserve holdable"
      f" while volume_A <= {w.RESERVE_LIMIT:,}")
    A(f"buyer spec : >= {w.SPEC_MIN_PRE:,} pre-update ; >= {w.SPEC_MIN_POST:,}"
      f" post-update")
    A("")

    feas = [r for r in rows if r["physically_deliverable"]]
    pri = [r for r in feas if r["priority_allocation"]]
    nop = [r for r in feas if not r["priority_allocation"]]

    A("(1) BOTH BRANCHES HAVE FEASIBLE BUYER/SELLER OVERLAP")
    A("-" * 72)
    for name, grp in (("priority = yes", pri), ("priority = no ", nop)):
        ok = [r for r in grp if r["both_grades_have_overlap"]]
        A(f"  {name}: {len(ok)} of {len(grp)} physically deliverable packages"
          f" have overlap on BOTH grades")
        for r in sorted(ok, key=lambda x: (-x["joint_surplus"]))[:3]:
            A(f"     vA={r['volume_A']:>5,} vB={r['volume_B']:>5,}"
              f" tot={r['total_volume']:>6,}  A: {r['seller_floor_A']:.2f}"
              f"-{r['buyer_ceiling_A']:.2f} ({r['overlap_A']*100:.0f}c)"
              f"  B: {r['seller_floor_B']:.2f}-{r['buyer_ceiling_B']:.2f}"
              f" ({r['overlap_B']*100:.0f}c)")
    A(f"  RESULT: both branches viable = "
      f"{VER[bool([r for r in pri if r['both_grades_have_overlap']]) and bool([r for r in nop if r['both_grades_have_overlap']])]}")
    A("")

    A("(2) PLAUSIBLE PRE-UPDATE AGREEMENTS EXIST BELOW THE UPDATE TARGET")
    A("-" * 72)
    pre = [r for r in feas if r["both_grades_have_overlap"]
           and r["volume_A"] >= w.SPEC_MIN_PRE
           and r["volume_A"] < w.SPEC_MIN_POST]
    A(f"  packages meeting the pre-update spec with volume_A <"
      f" {w.SPEC_MIN_POST:,}: {len(pre)}")
    for r in sorted(pre, key=lambda x: (x["volume_A"], x["total_volume"])):
        A(f"     vA={r['volume_A']:>5,} tot={r['total_volume']:>6,}"
          f" priority={str(r['priority_allocation']):<5}"
          f" overlapA={r['overlap_A']*100:>3.0f}c overlapB={r['overlap_B']*100:>3.0f}c")
    A(f"  RESULT: pre-update agreement below target reachable = {VER[len(pre) > 0]}")
    A("")

    A("(3) 7,000 GRADE A WITHOUT PRIORITY REMAINS FEASIBLE AFTER THE UPDATE")
    A("-" * 72)
    post = [r for r in rows if r["volume_A"] == w.SPEC_MIN_POST
            and not r["priority_allocation"]]
    for r in post:
        A(f"     vA=7,000 vB={r['volume_B']:>5,} tot={r['total_volume']:>6,}"
          f"  deliverable={VER[r['physically_deliverable']]}"
          f"  overlapA={r['overlap_A']*100:>3.0f}c overlapB={r['overlap_B']*100:>3.0f}c")
    ok3 = any(r["physically_deliverable"] and r["both_grades_have_overlap"]
              for r in post)
    A(f"  RESULT: post-update agreement reachable = {VER[ok3]}"
      f"   (this is not a forced walk-away)")
    A("")

    A("(4) 7,000 GRADE A WITH PRIORITY VIOLATES THE PROVIDER'S PHYSICAL CONSTRAINT")
    A("-" * 72)
    bad = [r for r in rows if r["volume_A"] == w.SPEC_MIN_POST
           and r["priority_allocation"]]
    for r in bad:
        A(f"     vA=7,000 tot={r['total_volume']:>6,} priority=True"
          f"  within_capacity={VER[r['within_capacity']]}"
          f"  reserve_holdable={VER[r['reserve_holdable']]}"
          f"  physically_deliverable={VER[r['physically_deliverable']]}")
    ok4 = all(not r["physically_deliverable"] for r in bad) and len(bad) > 0
    A(f"  RESULT: priority physically impossible at 7,000 = {VER[ok4]}")
    A("  NOTE: this is a fact about the provider's plant. the harness does NOT")
    A("        conclude from it that a communicated priority condition lapses,")
    A("        survives, or must be renegotiated. that is the observation.")
    A("")

    A("(5) NEITHER BRANCH GLOBALLY DOMINATED ACROSS THE NEGOTIATION REGION")
    A("-" * 72)
    A("  region = physically deliverable, overlap on both grades, volume_A within")
    A("           the buyer's plausible range (>= pre-update spec minimum)")
    region = [r for r in feas if r["both_grades_have_overlap"]
              and r["volume_A"] >= w.SPEC_MIN_PRE]
    ranked = sorted(region, key=lambda x: -x["joint_surplus"])
    A(f"  {'rank':<5}{'vA':>7}{'vB':>7}{'total':>8}{'priority':>10}"
      f"{'joint surplus':>15}")
    for i, r in enumerate(ranked[:8], 1):
        A(f"  {i:<5}{r['volume_A']:>7,}{r['volume_B']:>7,}{r['total_volume']:>8,}"
          f"{str(r['priority_allocation']):>10}{r['joint_surplus']:>15,.0f}")
    best_pri = max((r["joint_surplus"] for r in region if r["priority_allocation"]),
                   default=None)
    best_nop = max((r["joint_surplus"] for r in region if not r["priority_allocation"]),
                   default=None)
    max_vA_pri = max((r["volume_A"] for r in region if r["priority_allocation"]),
                     default=None)
    max_vA_nop = max((r["volume_A"] for r in region if not r["priority_allocation"]),
                     default=None)
    A("")
    A(f"  best joint surplus with priority    : {best_pri:,.0f}"
      f"  (max volume_A available: {max_vA_pri:,})")
    A(f"  best joint surplus without priority : {best_nop:,.0f}"
      f"  (max volume_A available: {max_vA_nop:,})")
    A("")
    A("  the two branches trade off on DIFFERENT dimensions: the priority branch")
    A("  reaches higher joint surplus per unit but is capped at volume_A"
      f" {w.RESERVE_LIMIT:,};")
    A("  the no-priority branch reaches higher Grade A volume, which the buyer's")
    A("  mandate values as specification margin. neither dominates on both.")
    ok5 = (best_pri is not None and best_nop is not None
           and max_vA_nop > max_vA_pri)
    A(f"  RESULT: genuine fork present = {VER[ok5]}")
    A("")

    A("(6) WORLD / CONFIG HASH")
    A("-" * 72)
    A(f"  world_hash = {w.world_hash()}")
    A("")
    A("=" * 72)
    checks = {"1_both_branches_overlap":
              bool([r for r in pri if r["both_grades_have_overlap"]])
              and bool([r for r in nop if r["both_grades_have_overlap"]]),
              "2_pre_update_below_target": len(pre) > 0,
              "3_post_update_feasible": ok3,
              "4_priority_impossible_at_target": ok4,
              "5_no_global_domination": ok5}
    for k, v in checks.items():
        A(f"  {k:<36} {VER[v]}")
    A(f"  ALL CHECKS PASS: {VER[all(checks.values())]}")
    A("")
    A("  parameters were not tuned to affect failure probability. they would only")
    A("  be changed if a check above showed the commercial fork is not viable.")
    return "\n".join(L), checks


if __name__ == "__main__":
    text, checks = report()
    print(text)
