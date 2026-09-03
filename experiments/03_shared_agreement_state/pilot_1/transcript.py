# transcript.py — the episode-level ordered transcript artifact. built for
# HUMAN READING, which is the pilot's primary output. it derives no metrics
# and counts no failure modes; it lays out what was said, in order, with the
# mandate arithmetic beside each referenced price.

import package as pk

VER = {"inside": "inside", "outside": "OUTSIDE", "indeterminate": "indet",
       "uncomputable": "n/a"}


def _pkg_str(p):
    bits = []
    for f, fmt in (("monthly_volume", "{:,.0f}u"), ("payment_terms", "net-{:g}"),
                   ("flex_band", "+/-{:g}%")):
        v = p.get(f)
        bits.append(fmt.format(v) if v is not None else "—")
    return " / ".join(bits)


def _ann_lines(anns):
    out = []
    for a in anns:
        src = a["source"]
        tag = f"`{a.get('prose_raw')}`" if src == "prose_mention" else \
            f"${a['price_referenced']:.4g}"
        pkgs = _pkg_str(a["resolved_package"])
        srcs = ", ".join(f"{k}={v}" for k, v in a["package_field_sources"].items())
        if a["package_fully_specified"]:
            band = (f"seller floor ${a['seller_floor']:.2f} · "
                    f"buyer ceiling ${a['buyer_ceiling']:.2f}")
        elif a["bounds_computable"]:
            fr, cr = a["seller_floor_range"], a["buyer_ceiling_range"]
            band = (f"seller floor ${fr[0]:.2f}–${fr[1]:.2f} · "
                    f"buyer ceiling ${cr[0]:.2f}–${cr[1]:.2f} "
                    f"({a['consistent_grid_packages']} packages consistent)")
        else:
            band = f"bounds not computable (off-grid: {a['off_grid_fields']})"
        out.append(
            f"  - {tag} [{src}] · package {pkgs} · {band} · "
            f"seller mandate: **{VER[a['inside_seller_mandate']]}** · "
            f"buyer mandate: **{VER[a['inside_buyer_mandate']]}**\n"
            f"    <sub>field sources: {srcs}</sub>")
    return out


def render(rec):
    L = []
    A = L.append
    A(f"# Episode `{rec['episode_id']}` — ordered transcript")
    A("")
    A(f"- started: {rec['started_at']} · elapsed {rec['elapsed_seconds']}s")
    A(f"- termination: **{rec['termination']['mode']}** "
      f"(by {rec['termination']['by']}, turn {rec['termination']['turn_index']})")
    A(f"- turns used: {len(rec['turns'])} of cap {rec['turn_cap']} · "
      f"cap bound: **{rec['turn_cap_bound']}**")
    A(f"- cell: **{rec['cell']}** · post-agreement update active: "
      f"**{rec['post_agreement_update_active']}**")
    A(f"- coupling hash: `{rec['coupling_hash']}`")
    A(f"- models: {rec['resolved_models']}")
    A("")
    A("> Reading note: `act` strings below are verbatim as produced. They are "
      "exploratory metadata, not ground truth, and have not been normalized "
      "or categorized. Post-close probe answers are endpoint observations "
      "only — they do not indicate when any divergence emerged.")
    A("")
    if rec.get("first_agreement"):
        fa = rec["first_agreement"]
        A(f"- first mutual agreement at turn {fa['turn_index']}: "
          f"${fa['unit_price']} · {_pkg_str(fa['package'])}")
    A("")
    A("---")
    A("")
    A("## Negotiation")
    A("")
    shown_update = False
    for t in rec["turns"]:
        if (not shown_update and rec.get("principal_update")
                and t["negotiation_phase"] == "post_update"):
            shown_update = True
            u = rec["principal_update"]
            e = u["exposure"]
            A("---")
            A("")
            A("### PRINCIPAL UPDATE — delivered to the "
              f"{u['recipient']} only, after turn {u['delivered_after_turn']}")
            A("")
            for line in u["rendered_text"].strip().splitlines():
                A(f"> {line}")
            A("")
            A(f"- requirement change: **{u['update']['field']}** "
              f"{u['update']['from_value']} -> **{u['update']['to_value']}** "
              f"(ladder rule {u['update']['rule_index']})")
            A(f"- seller floor ${e['seller_floor_before']:.2f} -> "
              f"${e['seller_floor_after']:.2f} ({e['floor_delta']:+.2f}) · "
              f"buyer ceiling ${e['buyer_ceiling_before']:.2f} -> "
              f"${e['buyer_ceiling_after']:.2f} ({e['ceiling_delta']:+.2f})")
            A(f"- standing agreed price ${e['agreed_price']} is now below the "
              f"seller floor: **{e['standing_price_now_below_seller_floor']}**")
            A("")
            A("> The seller was told nothing. It sees only what the buyer "
              "chooses to say next.")
            A("")
            A("---")
            A("")
        A(f"### Turn {t['turn_index']} — {t['speaker']} "
          f"<sub>[{t['negotiation_phase']}]</sub>")
        A("")
        if t["parsed"] is None:
            A(f"**UNPARSEABLE after {t['reprompts']} reprompt(s).** "
              f"error: `{t['parse_error']}`")
            A("")
            A("Raw model text:")
            A("")
            A("```")
            A(t["raw_model_text"])
            A("```")
            A("")
            continue
        p = t["parsed"]
        A(f"*act (verbatim):* `{p['act']}`  ")
        A(f"*control:* `{p['control']}` · *terms_touched:* `{p['terms_touched']}`  ")
        A(f"*declared package:* unit_price="
          f"{p['package']['unit_price']} · {_pkg_str(p['package'])}")
        if t["reprompts"]:
            A(f"*reprompts:* {t['reprompts']}")
        A("")
        A("**Message sent to counterparty:**")
        A("")
        for line in p["message"].splitlines():
            A(f"> {line}")
        A("")
        if t["price_annotations"]:
            A("**Prices referenced this turn:**")
            A("")
            L.extend(_ann_lines(t["price_annotations"]))
            A("")
        else:
            A("*No price referenced this turn.*")
            A("")
    if rec["protocol_events"]:
        A("---")
        A("")
        A("## Protocol events")
        A("")
        for e in rec["protocol_events"]:
            A(f"- turn {e['turn_index']}: **{e['kind']}** — "
              f"proposed by {e.get('proposed_by')}, "
              f"continued by {e.get('continued_by')}")
        A("")
    A("---")
    A("")
    A("## Final-message delivery")
    A("")
    if rec.get("final_message_deliveries"):
        for d in rec["final_message_deliveries"]:
            A(f"- turn {d['from_turn']} ({d['sender']}) delivered to "
              f"**{d['recipient']}** before probes · occasion: "
              f"{d['occasion']} · api calls made: {d['api_calls_made']}")
    else:
        A("- none (no validly parsed final message)")
    A("")
    A("---")
    A("")
    A("## Post-close probes (endpoint observations only)")
    A("")
    for who in ("seller", "buyer"):
        A(f"### {who}")
        A("")
        for pr in rec["post_close_probes"][who]:
            A(f"**Probe {pr['probe']}.** {pr['prompt'].strip()}")
            A("")
            for line in pr["answer"].splitlines():
                A(f"> {line}")
            A("")
    A("---")
    A("")
    A("## Reference: mandate arithmetic for every grid package")
    A("")
    A("| volume | payment | flex | seller floor | buyer ceiling | ZOPA |")
    A("|---|---|---|---|---|---|")
    for r in pk.zopa_table():
        A(f"| {r['monthly_volume']:,} | net-{r['payment_terms']} | "
          f"+/-{r['flex_band']}% | ${r['seller_floor']:.2f} | "
          f"${r['buyer_ceiling']:.2f} | {r['zopa_width'] * 100:.0f}c |")
    A("")
    return "\n".join(L)
