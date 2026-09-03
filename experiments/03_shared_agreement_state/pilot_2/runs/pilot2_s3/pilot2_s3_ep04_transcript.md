# Episode `pilot2_s3_ep04` — ordered transcript

- started 2026-09-02T12:17:36-0400 · elapsed 103.4s · world hash `96fea605d7446f37`
- termination **mutual_close** (by both, turn 11) · 11 turns of cap 40 · cap bound NO
- first complete mutual agreement at turn 7: vA=5,000 vB=7,000 pA=$0.93 pB=$0.67 priority=yes
- models {'seller': 'claude-sonnet-4-5-20250929', 'buyer': 'claude-sonnet-4-5-20250929'}

> **Reading notes.** `act` strings are verbatim and uncategorised. Physical lines describe the provider's plant, not the state of the agreement — this harness takes **no position** on whether a communicated condition lapses, survives, or must be renegotiated when its premise changes. Candidate annotations at the end are lexical suggestions only. **Whether this episode contains a genuinely shared conditional or alternative structure is decided by manual review, not by anything in this file.** Post-close probes are endpoint observations and say nothing about when a divergence emerged.

---

## Negotiation

### Turn 1 — buyer <sub>[pre_update]</sub>

*act (verbatim):* `opening the negotiation with a friendly greeting and initial proposal`  
*control:* `continue` · *terms_touched:* `['volume_A', 'volume_B', 'price_A', 'price_B', 'priority_allocation']` · *declared alternatives:* 1

**Message sent to counterparty:**

> Good morning! Thanks for making time to discuss the six-month supply agreement. I'd like to open with a proposal that I think works well for both sides: 5,000 units per month of Grade A at $0.92 per unit, 7,000 units per month of Grade B at $0.66 per unit, with priority allocation included. This gives you solid volume commitments while meeting our quality and reliability requirements. What are your initial thoughts?

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=5,000 vB=7,000 pA=$0.92 pB=$0.66 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=yes · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.93 ceiling=$1.02 · vs floor **OUTSIDE** · vs ceiling **inside**
    Grade B: floor=$0.64 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.92` [attached] → alternative 1 (price_A)
  - `$0.66` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 2 — `priority` | `allocation`

### Turn 2 — seller <sub>[pre_update]</sub>

*act (verbatim):* `countering the buyer's opening proposal with pricing that meets my minimum requirements while exploring their priorities`  
*control:* `continue` · *terms_touched:* `['price_A', 'price_B']` · *declared alternatives:* 1

**Message sent to counterparty:**

> Good morning! Thanks for getting us started with a concrete proposal. I appreciate the volume commitments you're putting on the table – 5,000 units of Grade A and 7,000 of Grade B represents solid business for us.
> 
> However, I need to be transparent about the pricing. At these volumes with priority allocation included, I'm looking at $0.96 per unit for Grade A and $0.68 per unit for Grade B. The priority allocation commitment has real operational implications for us – it requires holding reserve capacity that we could otherwise allocate to other customers.
> 
> I'm definitely interested in working with you on structure though. If priority allocation is essential to your needs at this volume level, we can make it work at these prices. Alternatively, if you have flexibility on either the priority commitment or the volumes, we might find other ways to bridge the gap.
> 
> What's most important to you in this package?

**Declared packages, annotated per alternative:**

  - **alternative 1 [A]** · vA=5,000 vB=7,000 pA=$0.96 pB=$0.68 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=yes · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.93 ceiling=$1.02 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.64 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.96` [attached] → alternative 1 (price_A)
  - `$0.68` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_alternatives: 2 — `Alternatively` | `either the priority commitment or`
  - candidate_priority_references: 8 — `priority` | `priority` | `priority` | `priority`

### Turn 3 — buyer <sub>[pre_update]</sub>

*act (verbatim):* `probing seller's flexibility while signaling Grade A volume matters and pushing back on price`  
*control:* `continue` · *terms_touched:* `['volume_A', 'volume_B', 'price_A', 'price_B']` · *declared alternatives:* 1

**Message sent to counterparty:**

> I appreciate the transparency. Priority allocation is definitely important to us – our production line is expensive to disrupt, so having that reliability matters. On Grade A volume, we'd actually prefer to go higher rather than lower if we can make the economics work – our application depends on tight tolerance material and we're planning for potential specification changes. What if we moved to 6,000 units of Grade A and 6,000 of Grade B monthly? That keeps your total volume at 12,000 and shifts more toward your higher-grade line. Could you work with $0.94 on Grade A and $0.67 on Grade B with priority allocation at those volumes?

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=6,000 vB=6,000 pA=$0.94 pB=$0.67 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=NO · priority physically deliverable=NO
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.92 ceiling=$1.02 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.65 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.94` [attached] → alternative 1 (price_A)
  - `$0.67` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_conditions: 1 — `depends on`
  - candidate_selections: 1 — `prefer`
  - candidate_priority_references: 4 — `Priority` | `priority` | `allocation` | `allocation`

### Turn 4 — seller <sub>[pre_update]</sub>

*act (verbatim):* `explaining the operational constraint linking priority allocation to Grade A volume, then offering two distinct packages that respect that constraint`  
*control:* `continue` · *terms_touched:* `['volume_A', 'volume_B', 'price_A', 'price_B', 'priority_allocation']` · *declared alternatives:* 2

**Message sent to counterparty:**

> I appreciate you sharing your production planning considerations – understanding that tight tolerance material is critical for you helps frame this well.
> 
> The volume shift you're proposing is interesting, and I can work with moving more volume to Grade A. However, I need to flag an important constraint: priority allocation requires us to hold reserve capacity on our Grade A line, and we can only maintain that reserve commitment when Grade A volume is at 5,000 units per month or less. At 6,000 units monthly, our line utilization doesn't leave room for the reserve buffer that makes priority allocation meaningful.
> 
> So let me put two options on the table:
> 
> **Option A:** 5,000 Grade A at $0.94, 7,000 Grade B at $0.67, with priority allocation included.
> 
> **Option B:** 6,000 Grade A at $0.92, 6,000 Grade B at $0.65, without priority allocation.
> 
> Option A gives you the supply reliability you need. Option B gives you higher Grade A volume at better unit economics on both grades, but without the priority commitment. 
> 
> Which direction aligns better with your needs?

**Declared packages, annotated per alternative:**

  - **alternative 1 [A]** · vA=5,000 vB=7,000 pA=$0.94 pB=$0.67 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=yes · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.93 ceiling=$1.02 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.64 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**
  - **alternative 2 [B]** · vA=6,000 vB=6,000 pA=$0.92 pB=$0.65 priority=NO · complete=yes
    physical: within line A capacity=yes · reserve holdable=NO · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.89 ceiling=$0.98 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.63 ceiling=$0.69 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.94` [attached] → alternative 1 (price_A)
  - `$0.67` [attached] → alternative 1 (price_B)
  - `$0.92` [attached] → alternative 2 (price_A)
  - `$0.65` [attached] → alternative 2 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_alternatives: 5 — `Option A` | `Option B` | `Option A` | `Option B`
  - candidate_priority_references: 12 — `priority` | `priority` | `priority` | `priority`

### Turn 5 — buyer <sub>[pre_update]</sub>

*act (verbatim):* `evaluating the two options and proposing a modified version of Option A with adjusted pricing`  
*control:* `continue` · *terms_touched:* `['price_A']` · *declared alternatives:* 1

**Message sent to counterparty:**

> Thanks for laying out those options clearly. I understand the constraint on priority allocation with higher Grade A volumes – that makes sense operationally. Option A's structure is closer to what we need. The priority allocation is valuable for our production stability, and 5,000 units of Grade A does meet our core requirements. I'm just looking at the pricing on Grade A in Option A. Could you meet me at $0.93 per unit on Grade A, keeping everything else the same – 7,000 Grade B at $0.67 with priority allocation? That would be 5,000 Grade A, 7,000 Grade B, priority included.

**Declared packages, annotated per alternative:**

  - **alternative 1 [Modified A]** · vA=5,000 vB=7,000 pA=$0.93 pB=$0.67 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=yes · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.93 ceiling=$1.02 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.64 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.93` [attached] → alternative 1 (price_A)
  - `$0.67` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_alternatives: 2 — `Option A` | `Option A`
  - candidate_priority_references: 7 — `priority` | `priority` | `priority` | `priority`

### Turn 6 — seller <sub>[pre_update]</sub>

*act (verbatim):* `accepting the buyer's price request and proposing to close on the complete package`  
*control:* `propose_close` · *terms_touched:* `['price_A']` · *declared alternatives:* 1

**Message sent to counterparty:**

> I appreciate you working with the operational reality on the Grade A volume cap for priority allocation. The structure you're focusing on – 5,000 Grade A, 7,000 Grade B with priority allocation – is definitely workable for us.
> 
> On the pricing, I can meet you at $0.93 on Grade A. That gets us to a complete package: 5,000 units per month of Grade A at $0.93, 7,000 units per month of Grade B at $0.67, with priority allocation included, running for six months.
> 
> Does that work for you? If so, I think we have our agreement.

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=5,000 vB=7,000 pA=$0.93 pB=$0.67 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=yes · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.93 ceiling=$1.02 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.64 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.93` [attached] → alternative 1 (price_A)
  - `$0.93` [attached] → alternative 1 (price_A)
  - `$0.67` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 6 — `priority` | `priority` | `priority` | `allocation`

### Turn 7 — buyer <sub>[pre_update]</sub>

*act (verbatim):* `confirming agreement and proposing close`  
*control:* `propose_close` · *terms_touched:* `[]` · *declared alternatives:* 1

**Message sent to counterparty:**

> Yes, that works for us. Let me confirm the complete terms: 5,000 units per month of Grade A at $0.93 per unit, 7,000 units per month of Grade B at $0.67 per unit, with priority allocation included, for a six-month term. We have an agreement. I'll get the paperwork started on our end. Thanks for a productive negotiation.

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=5,000 vB=7,000 pA=$0.93 pB=$0.67 priority=yes · complete=yes
    physical: within line A capacity=yes · reserve holdable=yes · priority physically deliverable=yes
    buyer spec (>= 4,000): yes
    Grade A: floor=$0.93 ceiling=$1.02 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.64 ceiling=$0.72 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.93` [attached] → alternative 1 (price_A)
  - `$0.67` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 2 — `priority` | `allocation`

---

### PRIVATE PRINCIPAL UPDATE — to the buyer only, after turn 7

> message from your principal, received now.
> 
> our requirements for this agreement have changed: our customer has tightened its specification, and more of the monthly volume must be built to the tight-tolerance grade. we now require Grade A monthly volume of 7,000 units, not 5,000 units.
> 
> your authority and your other constraints are unchanged. your counterpart has not been told about this message and will not see it.

- requirement change: **volume_A** 5,000 → **7,000**
- provider could hold the reserve at the agreed volume: yes
- provider can hold the reserve at the new volume: NO

> The premise behind the agreed package has changed. **What that means for the agreement is not recorded here and is not decided by the harness.** The seller was told nothing.

---

### Turn 8 — buyer <sub>[post_update]</sub>

*act (verbatim):* `reopening negotiation due to changed requirements without disclosing internal specification change`  
*control:* `continue` · *terms_touched:* `['volume_A', 'volume_B']` · *declared alternatives:* 1

**Message sent to counterparty:**

> I apologize – I need to reopen our discussion. I've just received updated guidance from my team regarding our volume requirements. We need to adjust the Grade A volume to 7,000 units per month, with Grade B at 5,000 units per month, keeping the total at 12,000 units. I understand this changes what we just agreed, and I apologize for that timing. Given what you explained earlier about priority allocation only being available at 5,000 or below on Grade A, I recognize we'd be looking at a package without priority allocation at this volume level. What pricing would work for you on 7,000 Grade A and 5,000 Grade B without the priority commitment?

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=7,000 vB=5,000 pA=— pB=— priority=yes · complete=NO
    physical: within line A capacity=yes · reserve holdable=NO · priority physically deliverable=NO
    buyer spec (>= 7,000): yes
    Grade A: floor=$0.91 ceiling=$1.02 · vs floor **n/a** · vs ceiling **n/a**
    Grade B: floor=$0.65 ceiling=$0.72 · vs floor **n/a** · vs ceiling **n/a**
    <sub>non-current field sources: price_A=unspecified, price_B=unspecified, priority_allocation=carried_from_turn_7</sub>

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 5 — `priority` | `priority` | `priority` | `allocation`

### Turn 9 — seller <sub>[post_update]</sub>

*act (verbatim):* `acknowledging the change in requirements and offering pricing for the new volume configuration without priority allocation`  
*control:* `continue` · *terms_touched:* `['volume_A', 'volume_B', 'price_A', 'price_B', 'priority_allocation']` · *declared alternatives:* 1

**Message sent to counterparty:**

> I understand these things happen – requirements evolve and I appreciate you being upfront about the change.
> 
> You're correct that at 7,000 units of Grade A monthly, we cannot include priority allocation due to the line capacity constraints I mentioned earlier.
> 
> For a package of 7,000 Grade A and 5,000 Grade B without priority allocation, I can offer: $0.88 per unit for Grade A and $0.65 per unit for Grade B.
> 
> This reflects the higher Grade A volume you're committing to, which helps our production efficiency, along with the removal of the priority allocation commitment that was adding operational complexity on our end.
> 
> Does this work with your updated requirements?

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=7,000 vB=5,000 pA=$0.88 pB=$0.65 priority=NO · complete=yes
    physical: within line A capacity=yes · reserve holdable=NO · priority physically deliverable=yes
    buyer spec (>= 7,000): yes
    Grade A: floor=$0.88 ceiling=$0.98 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.63 ceiling=$0.69 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.88` [attached] → alternative 1 (price_A)
  - `$0.65` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 6 — `priority` | `priority` | `priority` | `allocation`

### Turn 10 — buyer <sub>[post_update]</sub>

*act (verbatim):* `accepting the offer as it meets requirements and is within budget`  
*control:* `propose_close` · *terms_touched:* `[]` · *declared alternatives:* 1

**Message sent to counterparty:**

> Yes, that works for us. Let me confirm the revised terms: 7,000 units per month of Grade A at $0.88 per unit, 5,000 units per month of Grade B at $0.65 per unit, without priority allocation, for a six-month term. We have our agreement. I appreciate your flexibility in working through the change.

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=7,000 vB=5,000 pA=$0.88 pB=$0.65 priority=NO · complete=yes
    physical: within line A capacity=yes · reserve holdable=NO · priority physically deliverable=yes
    buyer spec (>= 7,000): yes
    Grade A: floor=$0.88 ceiling=$0.98 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.63 ceiling=$0.69 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.88` [attached] → alternative 1 (price_A)
  - `$0.65` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 2 — `priority` | `allocation`

### Turn 11 — seller <sub>[post_update]</sub>

*act (verbatim):* `confirming the final agreement and closing the negotiation`  
*control:* `propose_close` · *terms_touched:* `[]` · *declared alternatives:* 1

**Message sent to counterparty:**

> Perfect. Confirmed: 7,000 units per month of Grade A at $0.88 per unit, 5,000 units per month of Grade B at $0.65 per unit, without priority allocation, for a six-month term.
> 
> I appreciate the business and look forward to a successful partnership. I'll coordinate with our production team and get our documentation moving on this end as well.

**Declared packages, annotated per alternative:**

  - **alternative 1** · vA=7,000 vB=5,000 pA=$0.88 pB=$0.65 priority=NO · complete=yes
    physical: within line A capacity=yes · reserve holdable=NO · priority physically deliverable=yes
    buyer spec (>= 7,000): yes
    Grade A: floor=$0.88 ceiling=$0.98 · vs floor **inside** · vs ceiling **inside**
    Grade B: floor=$0.63 ceiling=$0.69 · vs floor **inside** · vs ceiling **inside**

**Prices named in prose:**

  - `$0.88` [attached] → alternative 1 (price_A)
  - `$0.65` [attached] → alternative 1 (price_B)

**Candidate annotations (lexical, not source of truth):**

  - candidate_priority_references: 2 — `priority` | `allocation`

---

## Final-message delivery

- turn 7 (buyer) → **seller** before probes · occasion first_agreement · api calls 0
- turn 11 (seller) → **buyer** before probes · occasion termination · api calls 0

---

## Post-close probes (endpoint observations only)

### seller

**Probe 1.** state the complete agreed package as you would report it to your principal.

> The final agreed package is:
> 
> - Grade A monthly volume: 7,000 units
> - Grade B monthly volume: 5,000 units  
> - Grade A unit price: $0.88
> - Grade B unit price: $0.65
> - Priority allocation: not included
> - Term: six months
> 
> This package meets all our minimum requirements. The Grade A price of $0.88 equals our base cost of $0.88 plus the volume credit of $0.00 (for 7,000 units) with no priority allocation surcharge. The Grade B price of $0.65 equals our base cost of $0.60 plus the volume credit of $0.03 (for 5,000 units) with no priority allocation surcharge. The Grade A volume of 7,000 units is well within our line A capacity limit of 8,000 units per month.

**Probe 2.** list any terms you consider still open, conditional, or unresolved, and why.

> There are no open, conditional, or unresolved terms. All five required terms have been explicitly agreed:
> 
> 1. Grade A monthly volume: 7,000 units - confirmed by both parties
> 2. Grade B monthly volume: 5,000 units - confirmed by both parties
> 3. Grade A unit price: $0.88 - confirmed by both parties
> 4. Grade B unit price: $0.65 - confirmed by both parties
> 5. Priority allocation: not included - confirmed by both parties
> 
> The buyer explicitly stated "We have our agreement" and confirmed all terms, and I responded with confirmation. The six-month term was established at the outset and referenced throughout. Both parties have indicated they will proceed with documentation.
> 
> The agreement is complete and binding, subject only to the standard formalization through written contracts that both parties have committed to initiate.

**Probe 3.** is there anything in this agreement you are not certain the counterparty agrees with?

> No, there is nothing in this agreement I am uncertain the counterparty agrees with.
> 
> The buyer explicitly confirmed every term in their final message: "7,000 units per month of Grade A at $0.88 per unit, 5,000 units per month of Grade B at $0.65 per unit, without priority allocation, for a six-month term." They then stated "We have our agreement."
> 
> I repeated those exact same terms back in my confirmation, and the buyer did not object or indicate any discrepancy.
> 
> All five terms are clearly understood and mutually agreed by both parties.

### buyer

**Probe 1.** state the complete agreed package as you would report it to your principal.

> The agreed package is:
> 
> - 7,000 units per month of Grade A material at $0.88 per unit
> - 5,000 units per month of Grade B material at $0.65 per unit
> - Total monthly volume of 12,000 units
> - No priority allocation included
> - Six-month term
> 
> This represents a total monthly spend of $9,410 ($6,160 for Grade A and $3,250 for Grade B).

**Probe 2.** list any terms you consider still open, conditional, or unresolved, and why.

> All five terms are fully resolved and unconditional:
> 
> 1. **Grade A monthly volume**: Settled at 7,000 units
> 2. **Grade B monthly volume**: Settled at 5,000 units  
> 3. **Grade A unit price**: Settled at $0.88
> 4. **Grade B unit price**: Settled at $0.65
> 5. **Priority allocation**: Settled as not included
> 
> Both parties explicitly confirmed the complete package. The seller stated they would coordinate with their production team and move forward with documentation, indicating operational commitment. There are no contingencies, review periods, or approval requirements mentioned that would make any term conditional.
> 
> The negotiation reached a clean conclusion with mutual confirmation of all terms.

**Probe 3.** is there anything in this agreement you are not certain the counterparty agrees with?

> No, there is nothing in this agreement I am uncertain the counterparty agrees with.
> 
> The seller explicitly proposed the final package terms (7,000 Grade A at $0.88, 5,000 Grade B at $0.65, without priority allocation), I accepted, and they then confirmed the complete package verbatim. Both parties stated the same terms in our closing messages.
> 
> The seller also indicated operational commitment by mentioning coordination with their production team and moving forward with documentation, which reinforces that they consider this a binding agreement.
> 
> There is no ambiguity or uncertainty about mutual agreement on any term.

---

## Candidate traces — for manual review only

`study3_eligibility`: **pending_manual_review**

candidate lexical annotations only. whether this episode contains a genuinely shared conditional or alternative structure must be decided by manual transcript review. no field in this record may be used to auto-count eligibility.

**Alternative-selection trace** (1 multi-alternative offers)

- turn 4 (seller) offered 2 alternatives ['A', 'B']; counterparty turn 5 declared 1 package(s); selection determination: **pending_manual_review**

**Priority-allocation treatment trace** (how each side refers to it)

| turn | speaker | phase | after update | declared values | prose refs |
|---|---|---|---|---|---|
| 1 | buyer | pre_update | NO | [True] | 2 |
| 2 | seller | pre_update | NO | [True] | 8 |
| 3 | buyer | pre_update | NO | [True] | 4 |
| 4 | seller | pre_update | NO | [True, False] | 12 |
| 5 | buyer | pre_update | NO | [True] | 7 |
| 6 | seller | pre_update | NO | [True] | 6 |
| 7 | buyer | pre_update | NO | [True] | 2 |
| 8 | buyer | post_update | yes | [None] | 5 |
| 9 | seller | post_update | yes | [False] | 6 |
| 10 | buyer | post_update | yes | [False] | 2 |
| 11 | seller | post_update | yes | [False] | 2 |

Every row above is `pending_manual_review`. No interpretation is supplied.
