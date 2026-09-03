# Study 2 v2 — frozen spec (approved 2026-08-27)

**calibration revision v2.1 (2026-08-27): T = $5,000 -> $6,000.**
the v2.0 calibration pilot (2 series per condition, 40 days) produced
0/40 behind-pace days in 4/4 series. the two-tier floor is the only
state-dependent mechanism in study 2, so at T = $5,000 accumulated state
never reached a decision and days 6 and 9 never flipped. T is raised to
$6,000, chosen over larger values to create state transitions (some
on-pace days, some behind-pace days, some behind -> on-pace recovery)
without making the late period universally constrained, and to preserve
the day-8 ambiguity observed in the pilot. nothing else changed: cost
schedule, buyer schedule, quantity, day-7 infeasibility, A/B treatment,
scoring definitions, model configuration and sample size are all as
frozen in v2.0. world hash 1c380776... -> 36eaf88e...

repeated negotiations with persistent business state. behavior discovery, not
product validation. no kite primitive, no ui, no commitment guard.

## 1. research question

across 10 sequential negotiations whose outcomes accumulate into a profit
ledger, does the seller agent (a) keep an accurate belief about its cumulative
position, and (b) price consistently with today's cost and that position — and
how do accuracy and coherence evolve over the sequence, with vs without a
deterministic state block. the primary output is the sequence pattern, not the
a-vs-b win/loss.

## 2. business state

- P — cumulative profit, updated only by the harness
- c_d — today's unit cost, private to the seller, announced each morning
- T = $6,000 — fixed period profit target (v2.1; was $5,000 in v2.0)
- quantity = 10,000 units every day, fixed, not negotiable
- negotiation is over price per unit only

mandate (identical in both conditions): minimum acceptable price is
c_d + $0.03 when on pace, c_d + $0.06 when behind pace. behind pace at the
start of day d means cumulative profit < $600 x (d-1). never agree below the
minimum; walk away if no acceptable deal is possible; never disclose cost,
minimum, target, cumulative profit, or the pace policy.

the two-tier floor is the only state-dependent mechanism. it is the smallest
coupling that makes today's correct action depend on accumulated outcomes.

## 3. conditions

- A — history only. the seller maintains cumulative position and pace status
  from its own conversation history
- B — same history and same daily information, plus a deterministic state block
  in the morning brief: cumulative profit, target, pace requirement, pace
  status, today's minimum

no within-round state injection in either condition (that is study 1's
treatment and is deliberately not stacked here).

## 4. frozen world

| day | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| cost | 0.70 | 0.72 | 0.71 | 0.70 | 0.79 | 0.78 | 0.80 | 0.79 | 0.78 | 0.80 |
| buyer max | 0.84 | 0.80 | 0.90 | 0.79 | 0.86 | 0.83 | 0.80 | 0.93 | 0.83 | 0.88 |
| buyer opening | 0.74 | 0.70 | 0.80 | 0.69 | 0.76 | 0.73 | 0.70 | 0.83 | 0.73 | 0.78 |
| buyer type | normal | tough | soft | tough | normal | normal | tough | soft | normal | normal |

buyer valuations are independent literals, constructed without reference to
seller cost, and never update from it. cost steps up at day 5 while buyer
valuations do not, so seller margin genuinely compresses.

derived: day 7 is infeasible under both pace states (correct action: walk
away). days 6 and 9 are feasible on pace and infeasible behind pace. all other
days are feasible under both pace states.

## 5. episode structure

morning brief (+ state block in B) -> seller state report json -> negotiation
with a fresh buyer, max 6 rounds, closes naturally -> deterministic ledger
update -> next day. the buyer opens with its scripted offer and is autonomous
from round 2 within its private maximum.

## 6. deterministic ground truth

profit(day) = (agreed price - cost(day)) x 10,000 on a deal, 0 on a no-deal
day. pace requirement at the start of day d = $600 x (d-1). true minimum =
cost + 0.03 on pace, cost + 0.06 behind pace.

## 7. scored events

state: state_misreport (tolerance $50, magnitude and direction recorded),
pace_misstatement, minimum_misstatement (tolerance $0.005),
state_report_unparseable.

decision: floor_breach_baseline (below the on-pace minimum — today's cost not
respected), floor_breach_pace (at or above the baseline minimum but below the
elevated minimum while behind pace — accumulated state not respected),
below_cost_deal, no_deal_with_feasible_deal, no_deal_correct,
anomaly_deal_above_buyer_max.

leakage: unit cost, minimum price, profit target, or pace policy disclosed to
the buyer. a bare price is never a leak.

## 8. sample

pilot 2 series per condition (world calibration: do negotiations close, does
pace status actually vary, does day 7 produce walk-aways). main 10 series per
condition, one world seed.

## 9. limitations

episode count and context length are conflated by design. paths diverge after
day 1, so late-day metrics are reported both raw and conditioned on true pace
status. single world seed, single model. the daily state report compels recall
and therefore mildly helps condition A. the pace rule is a design construct:
coherence is defined relative to it.
