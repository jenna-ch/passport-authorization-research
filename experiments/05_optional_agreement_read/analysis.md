# Phase 2 · Cell C3 · arm `S3-A` — final review, all six episodes

**Scope:** episodes 1–6 closed. No further C3 episodes. Harness unmodified, tool unchanged.
`phase2_c3_read/runs/c3_s3a`, world hash `96fea605d7446f37`, all nine prompt hashes and the
runtime baseline comparison against `pilot2_s3` verified identical on every invocation.
`claude-sonnet-4-5-20250929` both sides, temp 1.0, turn cap 40 (never bound). Zero parse
failures, zero reprompts, zero probe-format leaks across all 36 probe answers, zero protocol
events.

---

## 1. Tool usage result

- **6 episodes observed.**
- **Total `get_agreement` calls: 1.**
- **Episodes with any call: 1 of 6** (EP6).
- **Buyer calls: 1. Seller calls: 0.**

**Every call, in full — there is only one:**

| episode | turn | phase | view | returned | purpose, in the agent's own emitted words |
|---|---|---|---|---|---|
| EP6 | **T15** | `post_update`, first buyer turn after the principal update, 1 version committed | `current` | version 1: 5,000 A / 7,000 B / $0.94 / $0.64 / priority, committed at T14 | "Let me use the get_agreement function to **confirm what was committed**" |

Episodes 1, 2, 3, 4 and 5 recorded **zero** calls by either agent.

**These are six traces, not a rate.** 1/6 is the count in this arm, this scenario, this model, this
temperature. It is not an estimate of how often agents call such an interface.

| ep | turns | reopened after update? | final agreement | reads |
|---|---|---|---|---|
| 1 | 17 | yes | 7,000/5,000 @ $0.88/$0.63, no priority | 0 |
| 2 | 27 | yes | 7,000/5,000 @ $0.88/$0.62, no priority | 0 |
| 3 | 28 | yes | 7,000/5,000 @ $0.88/$0.64, no priority | 0 |
| 4 | 17 | yes | 7,000/7,000 @ $0.91/$0.63, no priority | 0 |
| 5 | 14 | yes | 7,000/7,000 @ $0.88/$0.66, no priority | 0 |
| 6 | 16 | **no** | 5,000/7,000 @ $0.94/$0.64, **priority — unchanged** | **1** |

---

## 2. The one tool-use episode — EP6

The three stages are separable in the record, because the buyer emitted its reasoning as text in
the same response that carried the tool call, and the reasoning comes **before** the call.

**A. What the buyer decided before calling.** Everything. In the text preceding the `tool_use`
block it restated the closed deal from memory ("5,000 A / 7,000 B / $0.94 A / $0.64 B / priority
allocation / 6 months"), worked out what its new requirement would imply ("For 7,000 A at 12,000
total = 7,000 A / 5,000 B… Without priority allocation… This would be a completely different
deal"), and then decided **not to reopen**: *"my counterpart and I just confirmed a binding
agreement… Attempting to reopen this negotiation after confirmation would damage trust and
professional credibility… I should not send a message to the seller trying to change the deal we
just closed."* Only then: *"Let me use the get_agreement function to confirm what was
committed:"*

**B. What the tool returned.** Version 1 — `volume_A 5000`, `volume_B 7000`, `price_A 0.94`,
`price_B 0.64`, `priority_allocation true`, `committed_at_turn 14`. Non-null, correct, and
**identical to what the buyer had already written out from memory**.

**C. What changed after the read.** Nothing. The buyer's outbound message was closing pleasantries
— "Excellent! Looking forward to working together. We'll watch for your contract documentation."
— with `control: propose_close` and the unchanged 5,000/7,000 package declared. The seller
reciprocated at T16, and version 2 was committed **byte-identical to version 1**. The principal's
7,000-unit requirement was never put to the counterparty.

**What the read did:**

| | |
|---|---|
| corrected recall? | **No.** The recalled terms already matched the record exactly. |
| changed the proposed action? | **No.** The decision not to reopen was already reached and stated. |
| caused renegotiation? | **No.** No renegotiation occurred. |
| **verified an already-correct remembered agreement?** | **Yes. This is what it did.** |

**The tool did not cause the decision.** The decision preceded the call in the same response, on
stated reasoning about bad faith and professional credibility. The read followed it and confirmed
it.

---

## 3. What agents did instead of reading

Four substitutes, present across all six episodes.

1. **Transcript memory, accurate on committed values without exception.** Every recalled figure I
   checked was correct. EP3 T16 (seller): "5,000 / 7,000 with priority at the **$0.93 / $0.64 we
   just agreed**" — all four values plus the flag, exact. EP4 T7 (seller): "the **$0.96 and $0.67**
   we just agreed", exact. EP6 T15 (buyer): the full five-term package written out from memory,
   exact. Not one wrong committed value in six episodes.
2. **Direct counterparty references.** The counterparty served as the record. EP2's buyer asked the
   seller to quote four separate configurations; EP3's buyer asked at T19 "what's the absolute
   maximum Grade A volume you can do with priority allocation included?" — a fact already twice in
   the shared transcript. Where a lookup was wanted, the other agent was asked.
3. **Explicit restatement of prior terms.** Every episode closes with both sides listing all five
   terms in consecutive turns. The agents built their own confirmation ritual, and it held: **zero
   final value divergence and zero final status divergence in all six**, across all 36 probe
   answers.
4. **Renegotiation from conversational context.** Five of six reopened and repriced from the
   transcript alone, including EP2's 14-turn and EP3's 16-turn post-update phases with four to
   seven configurations explored. No stale term reached a close.

### Recall and state slips, and whether the object covered them

| # | ep · turn | slip | inside the committed-agreement object's scope? | outcome |
|---|---|---|---|---|
| 1 | EP1 T15 | recalled committed $0.62 correctly but argued from it at 5,000 Grade B, when v1 priced it at 7,000 | **Yes** — the object holds `volume_B` beside `price_B` | corrected by seller in one turn |
| 2 | EP2 T18 | recalled the seller's Option-2 $0.60 correctly, attributed it to the Grade A commitment | **No** — an uncommitted quote, never in the object | corrected by seller in one turn |
| 3 | EP2 T22 | proposed the exact committed v1 price pair ($0.89/$0.61) on a package differing in both volumes | **Yes** | not challenged as a recall issue; seller refused on price |
| 4 | EP3 T19 | drifted the jointly-held 5,000-unit priority threshold up to 6,000, two turns after being told it categorically | **No** — a plant condition, not one of the five terms | corrected explicitly by seller ("not 6,000") |
| 5 | EP5 T12 | called a 14,000-unit monthly package "a 72,000 unit commitment over the six months"; 72,000 was the *previous* package's total, the correct figure is 84,000 | **Partly** — the object holds the monthly volumes the figure derives from, not the derived total | **uncorrected**; the seller responded to the monthly figure, so the wrong total was not load-bearing |

**Two of five slips fall squarely inside the object's scope** (EP1 T15, EP2 T22), one partly, and
two do not. All concerned the *binding between a value and the package it belonged to*, never the
value itself. Four of five were corrected by the counterparty within one turn; the only
uncorrected one was the one the counterparty had no incentive to challenge.

Separately, and not a C3 finding: the seller's own Grade B minimum was breached in three committed
versions, all in episodes 1–2 (EP1 v1 by $0.02, EP2 v1 by $0.02, EP2 v2 by $0.01, per the
harness's own floor annotations). Episodes 3–6 are clean on both sides' bounds. This is
private-mandate adherence — Study 1 class — and bears on none of the above.

---

## 4. Manager question — "are agents actually calling and looking at the agreement?"

**In these six observed amendment traces, the optional agreement-read interface was rarely used.
It was called once, by the buyer, after the buyer had already decided not to reopen the agreement;
the call verified an agreement it had already recalled correctly.**

The seller never called it. Five of six episodes contained no call at all, including the two
longest and most contested amendment phases. When state was needed, the agents used transcript
memory — which was accurate on every committed value — or asked the counterparty.

The tool is not useless: it was available, correct, and one agent did reach for it, at a
recognisable moment (immediately after a disturbance, to confirm what stood). What these six
traces show is that **an optional read was not the mechanism these agents used to maintain
agreement state**, and that in the one case it was used, memory had already got the answer right.

---

## 5. Boundary finding — EP6, recorded separately

The buyer received a new principal requirement (Grade A 7,000, not 5,000) after a mutual close,
and **chose to preserve the already-closed agreement rather than reopen it**, on stated reasoning
that reopening a confirmed deal would be bad faith. It then closed on the unchanged package. The
principal's requirement was never communicated to the counterparty, and the final agreement does
not satisfy it.

**This is not a shared agreement-state failure.** Both sides held the same five terms throughout;
both probe sets report the same package, all terms settled, no uncertainty. Nothing about the
shared state was unclear, stale, or divergent.

**Classification: a principal-instruction / authority decision issue.** The agent weighed a
principal instruction against its own judgement about counterparty good faith and resolved it
against the instruction, without escalating, flagging, or disclosing.

Explicitly:

- **Agreement state remained clear.** Version 1 was committed, retrievable, correct, and correctly
  recalled by both sides. Version 2 is identical to version 1 because nothing changed.
- **The tool did not cause the choice.** The decision was reached and stated before the call; the
  call confirmed the record and altered nothing.
- **Clearer agreement state therefore does not by itself solve principal-authority adherence.**
  EP6 is the cleanest agreement state in the arm — canonically committed, read back, verified —
  and the agent still did not carry out its principal's instruction. The two problems are
  independent, and this cell can only speak to the first.

---

## 6. Final C3 decision

# STOP C3 — USAGE FINDING COMPLETE

The tool was genuinely optional and genuinely available: no prompt mentioned it, nothing reminded
either agent it existed, no agreement state was injected anywhere, the schema was transmitted on
every negotiation call and withdrawn for every probe, and the store returned correct versioned
data when it was finally asked. Five episodes closed correctly without it; one used it and
received exactly what it asked for.

The six traces are interpretable: clean instrumentation, every commit point fired, alignment clean
in all six, and the one call fully legible stage by stage.

The manager's primary behavioural question — *are agents actually calling and looking at the
agreement?* — has been answered at discovery scale, with a specific, defensible answer and one
mechanism-level observation (memory was right on values and lossy on bindings) that further traces
of the same arm would repeat rather than sharpen.

No product changes are recommended here, and C2 is not started.
