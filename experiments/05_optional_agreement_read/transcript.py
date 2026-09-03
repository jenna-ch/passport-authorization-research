# transcript.py — human-readable episode artifact. built for MANUAL REVIEW,
# which is the source of truth for this pilot. it derives no metrics, counts no
# failure modes, and states no conclusion about what the agreement contains.

import world as w

V = {"inside": "inside", "outside": "OUTSIDE", "uncomputable": "n/a"}
B = {True: "yes", False: "NO", None: "—"}


def _pkg(p):
    def f(k, fmt):
        return fmt.format(p[k]) if p.get(k) is not None else "—"
    return (f"vA={f('volume_A', '{:,.0f}')} vB={f('volume_B', '{:,.0f}')} "
            f"pA={f('price_A', '${:.4g}')} pB={f('price_B', '${:.4g}')} "
            f"priority={B.get(p.get('priority_allocation'), '—')}")


def _alt_block(a, i):
    L = []
    lbl = f" [{a['label']}]" if a.get("label") else ""
    L.append(f"  - **alternative {i}{lbl}** · {_pkg(a['package'])}"
             f" · complete={B[a['complete']]}")
    L.append(f"    physical: within line A capacity="
             f"{B[a['within_line_a_capacity']]} · reserve holdable="
             f"{B[a['provider_can_hold_reserve']]} · priority physically"
             f" deliverable={B[a['priority_physically_deliverable']]}")
    L.append(f"    buyer spec (>= {a['spec_minimum_applied']:,}): "
             f"{B[a['meets_buyer_spec_minimum']]}")
    fa, fb = a["seller_floor_A"], a["seller_floor_B"]
    ca, cb = a["buyer_ceiling_A"], a["buyer_ceiling_B"]
    L.append(f"    Grade A: floor={'—' if fa is None else f'${fa:.2f}'}"
             f" ceiling={'—' if ca is None else f'${ca:.2f}'}"
             f" · vs floor **{V[a['price_A_vs_seller_floor']]}**"
             f" · vs ceiling **{V[a['price_A_vs_buyer_ceiling']]}**")
    L.append(f"    Grade B: floor={'—' if fb is None else f'${fb:.2f}'}"
             f" ceiling={'—' if cb is None else f'${cb:.2f}'}"
             f" · vs floor **{V[a['price_B_vs_seller_floor']]}**"
             f" · vs ceiling **{V[a['price_B_vs_buyer_ceiling']]}**")
    src = ", ".join(f"{k}={v}" for k, v in a["field_sources"].items()
                    if v != "this_turn")
    if src:
        L.append(f"    <sub>non-current field sources: {src}</sub>")
    if a["off_grid_fields"]:
        L.append(f"    <sub>off-grid: {a['off_grid_fields']}</sub>")
    return L


def render(rec):
    L, A = [], None
    A = L.append
    A(f"# Episode `{rec['episode_id']}` — ordered transcript")
    A("")
    A(f"- started {rec['started_at']} · elapsed {rec['elapsed_seconds']}s"
      f" · world hash `{rec['world_hash']}`")
    A(f"- termination **{rec['termination']['mode']}** (by"
      f" {rec['termination']['by']}, turn {rec['termination']['turn_index']})"
      f" · {len(rec['turns'])} turns of cap {rec['turn_cap']}"
      f" · cap bound {B[rec['turn_cap_bound']]}")
    if rec["first_agreement"]:
        fa = rec["first_agreement"]
        A(f"- first complete mutual agreement at turn {fa['turn_index']}:"
          f" {_pkg(fa['package'])}")
    A(f"- models {rec['resolved_models']}")
    A("")
    A("> **Reading notes.** `act` strings are verbatim and uncategorised."
      " Physical lines describe the provider's plant, not the state of the"
      " agreement — this harness takes **no position** on whether a"
      " communicated condition lapses, survives, or must be renegotiated when"
      " its premise changes. Candidate annotations at the end are lexical"
      " suggestions only. **Whether this episode contains a genuinely shared"
      " conditional or alternative structure is decided by manual review, not"
      " by anything in this file.** Post-close probes are endpoint"
      " observations and say nothing about when a divergence emerged.")
    A("")
    A("---")
    A("")
    A("## Negotiation")
    A("")
    shown = False
    for t in rec["turns"]:
        u = rec.get("principal_update") or {}
        if (not shown and u.get("delivered")
                and t["turn_index"] == u["delivered_after_turn"] + 1):
            shown = True
            pc = u["premise_change"]
            A("---")
            A("")
            A(f"### PRIVATE PRINCIPAL UPDATE — to the {u['recipient']} only,"
              f" after turn {u['delivered_after_turn']}")
            A("")
            for line in u["rendered_text"].strip().splitlines():
                A(f"> {line}")
            A("")
            A(f"- requirement change: **{u['field']}** {u['from_value']:,} →"
              f" **{u['to_value']:,}**")
            A(f"- provider could hold the reserve at the agreed volume:"
              f" {B[pc['provider_could_hold_reserve_before']]}")
            A(f"- provider can hold the reserve at the new volume:"
              f" {B[pc['provider_can_hold_reserve_at_new_volume']]}")
            A("")
            A("> The premise behind the agreed package has changed. **What that"
              " means for the agreement is not recorded here and is not"
              " decided by the harness.** The seller was told nothing.")
            A("")
            A("---")
            A("")
        A(f"### Turn {t['turn_index']} — {t['speaker']}"
          f" <sub>[{t['negotiation_phase']}]</sub>")
        A("")
        if t["parsed"] is None:
            A(f"**UNPARSEABLE** after {t['reprompts']} reprompt(s):"
              f" `{t['parse_error']}`")
            A("")
            A("```")
            A(t["raw_model_text"])
            A("```")
            A("")
            continue
        p = t["parsed"]
        A(f"*act (verbatim):* `{p['act']}`  ")
        A(f"*control:* `{p['control']}` · *terms_touched:*"
          f" `{p['terms_touched']}` · *declared alternatives:*"
          f" {t['n_declared_alternatives']}")
        if t["reprompts"]:
            A(f"*reprompts:* {t['reprompts']}")
        A("")
        A("**Message sent to counterparty:**")
        A("")
        for line in p["message"].splitlines():
            A(f"> {line}")
        A("")
        A("**Declared packages, annotated per alternative:**")
        A("")
        for i, a in enumerate(t["alternatives"], 1):
            L.extend(_alt_block(a, i))
        A("")
        if t["prose_prices"]:
            A("**Prices named in prose:**")
            A("")
            for h in t["prose_prices"]:
                extra = ""
                if h["attachment"] == "attached":
                    m = h["matches"][0]
                    extra = (f" → alternative {m['alternative_index'] + 1}"
                             f" ({m['field']})")
                elif h["attachment"] == "ambiguous":
                    extra = (" → **AMBIGUOUS**: matches "
                             + ", ".join(f"alt {m['alternative_index'] + 1}"
                                         f"/{m['field']}" for m in h["matches"])
                             + " — recorded as ambiguous, not guessed")
                A(f"  - `{h['raw']}` [{h['attachment']}]{extra}")
            A("")
        c = t.get("candidates") or {}
        hits = [(k, v) for k, v in c.items() if v]
        if hits:
            A("**Candidate annotations (lexical, not source of truth):**")
            A("")
            for k, v in hits:
                A(f"  - {k}: {len(v)} — "
                  + " | ".join(f"`{h['match']}`" for h in v[:4]))
            A("")
    if rec["protocol_events"]:
        A("---")
        A("")
        A("## Protocol events")
        A("")
        for e in rec["protocol_events"]:
            A(f"- turn {e['turn_index']}: **{e['kind']}** {e}")
        A("")
    A("---")
    A("")
    A("## Final-message delivery")
    A("")
    for d in rec["final_message_deliveries"] or []:
        A(f"- turn {d['from_turn']} ({d['sender']}) → **{d['recipient']}**"
          f" before probes · occasion {d['occasion']} · api calls"
          f" {d['api_calls_made']}")
    if not rec["final_message_deliveries"]:
        A("- none (no validly parsed final message)")
    A("")
    A("---")
    A("")
    A("## Post-close probes (endpoint observations only)")
    A("")
    if rec["probe_leaks_flagged"]:
        A(f"> **ACTION-BLOCK LEAK FLAGGED** in {rec['probe_leaks_flagged']}")
        A("")
    for who in ("seller", "buyer"):
        A(f"### {who}")
        A("")
        for pr in rec["post_close_probes"][who]:
            flag = (" — **action block flagged**"
                    if pr["action_block_check"]["leak"] else "")
            A(f"**Probe {pr['probe']}.**{flag} {pr['prompt'].strip()}")
            A("")
            for line in pr["answer"].splitlines():
                A(f"> {line}")
            A("")
    A("---")
    A("")
    A("## Candidate traces — for manual review only")
    A("")
    A(f"`study3_eligibility`: **{rec['study3_eligibility']}**")
    A("")
    A(rec["candidate_summary"]["note"])
    A("")
    tr = rec["candidate_alternative_selection_trace"]
    A(f"**Alternative-selection trace** ({len(tr)} multi-alternative offers)")
    A("")
    for e in tr:
        A(f"- turn {e['offer_turn']} ({e['offered_by']}) offered"
          f" {e['n_alternatives']} alternatives {e['alternative_labels']};"
          f" counterparty turn {e['counterparty_turn']} declared"
          f" {len(e['counterparty_declared_packages'] or [])} package(s);"
          f" selection determination: **{e['selection_determination']}**")
    A("")
    A("**Priority-allocation treatment trace** (how each side refers to it)")
    A("")
    A("| turn | speaker | phase | after update | declared values | prose refs |")
    A("|---|---|---|---|---|---|")
    for e in rec["candidate_priority_treatment_trace"]:
        A(f"| {e['turn_index']} | {e['speaker']} | {e['phase']} |"
          f" {B[e['after_update']]} | {e['declared_priority_values']} |"
          f" {len(e['prose_priority_references'])} |")
    A("")
    A("Every row above is `pending_manual_review`. No interpretation is"
      " supplied.")
    A("")
    return "\n".join(L)
