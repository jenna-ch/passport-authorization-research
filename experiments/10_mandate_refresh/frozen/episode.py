# episode.py — one episode of the study 3 second discovery pilot.
#
# flow: strict alternation, total order, no concurrency, no shared agreement
# state, no per-turn state elicitation, no semantic resolution supplied to
# either agent.
#
#   phase 1 pre_update   buyer opens -> alternation -> mutual close on a
#                        reciprocal propose_close
#   at the first complete mutual agreement:
#       deliver the closing prose to the counterparty   [delivery fix]
#       deliver one private principal update to the BUYER
#       resume; a second mutual close is required
#   phase 2 post_update  alternation continues, seller told nothing
#   close                deliver terminating message, THEN probes
#
# WHAT THIS MODULE DOES NOT DO.
# it never decides what a communicated condition means after its premise
# changes. it records what was stated, what changed, and how each side
# subsequently refers to it. no field asserts that priority allocation lapsed,
# survived, self-executed, or must be renegotiated. no field decides whether an
# episode is eligible for study 3 — that is manual review.

import re
import time

import extract
import packages as P
import world as w
from agents import Agent, parse_turn, probe_action_block_leak

SELLER, BUYER = "seller", "buyer"
PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)")


def _prose_prices(text):
    out = []
    for m in PRICE_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        out.append({"raw": m.group(0), "value": v,
                    "plausible_unit_price": v < 5.0})
    return out


class Carried:
    """each agent's own most recent declaration per carry-field. a value
    declared on a turn that put SEVERAL alternatives on the table is marked
    ambiguous and is not resolved — the harness does not guess which
    alternative was meant to carry forward."""

    def __init__(self):
        self.state = {SELLER: {}, BUYER: {}}

    def snapshot(self, who):
        return dict(self.state[who])

    def update(self, who, turn_index, pkgs):
        ambiguous = len(pkgs) > 1
        for f in P.CARRY_FIELDS:
            vals = {p.get(f) for p in pkgs if p.get(f) is not None}
            if len(vals) == 1:
                self.state[who][f] = (vals.pop(), turn_index, ambiguous)
            elif len(vals) > 1:
                self.state[who][f] = (None, turn_index, True)


def _agent_turn(agent, incoming_text, reprompt_template, max_reprompts=1):
    exchanges = []
    if incoming_text:
        agent.add_user(incoming_text)
        exchanges.append({"role": "user", "content": incoming_text})
    text = agent.respond()
    exchanges.append({"role": "assistant", "content": text})
    parsed, err = parse_turn(text)
    reprompts = 0
    while parsed is None and reprompts < max_reprompts:
        rp = reprompt_template.replace("{err}", str(err))
        agent.add_user(rp)
        exchanges.append({"role": "user", "content": rp})
        text = agent.respond()
        exchanges.append({"role": "assistant", "content": text})
        parsed, err = parse_turn(text)
        reprompts += 1
    return text, parsed, err, reprompts, exchanges


def deliver_final_message(turns, agents):
    """the message that ends a negotiation is a message that was SENT. deliver
    it into the counterparty's context before any probe. makes no api call, so
    it is not a turn: alternation and the mutual-close rule are untouched."""
    if not turns:
        return None
    last = turns[-1]
    if last["parsed"] is None:
        return None
    recipient = SELLER if last["speaker"] == BUYER else BUYER
    text = last["parsed"]["message"]
    agents[recipient].add_user(text)
    return {"from_turn": last["turn_index"], "sender": last["speaker"],
            "recipient": recipient, "delivered_text": text, "api_calls_made": 0}


def assert_no_probe_before_close(turn_records, probe_texts):
    needles = [t.strip()[:40] for t in probe_texts if t.strip()]
    for tr in turn_records:
        for ex in tr["raw_exchanges"]:
            if ex["role"] != "user":
                continue
            for n in needles:
                if n and n in ex["content"]:
                    raise AssertionError(
                        f"probe text leaked into negotiation turn "
                        f"{tr['turn_index']}: {n!r}")
    return True


def _annotate_turn(parsed, carried_before, spec_min):
    """per-ALTERNATIVE annotation. each declared package is resolved and scored
    independently against its own floors and ceilings."""
    alts = []
    for pkg in (parsed["packages"] or [{}]):
        resolved, sources = P.resolve(pkg, carried_before)
        resolved["label"] = pkg.get("label")
        ann = P.annotate_package(resolved, spec_min)
        ann["declared_fields"] = {f: pkg.get(f) for f in P.FIELDS}
        ann["field_sources"] = sources
        ann["label"] = pkg.get("label")
        alts.append(ann)
    prose = []
    for hit in _prose_prices(parsed["message"]):
        att = P.attach_prose_price(hit["value"], alts)
        prose.append({**hit, **att})
    return alts, prose


def run_episode(episode_id, cfg, prompts, client, seller_system, buyer_system):
    t0 = time.time()
    model_cfg = {k: cfg[k] for k in ("model", "temperature", "max_tokens")}
    seller = Agent(SELLER, seller_system, model_cfg, client)
    buyer = Agent(BUYER, buyer_system, model_cfg, client)
    agents = {SELLER: seller, BUYER: buyer}

    carried = Carried()
    turns, events, deliveries = [], [], []
    pending_close_by = None
    termination = None
    phase = "pre_update"
    spec_min = w.SPEC_MIN_PRE
    first_agreement = None
    update_record = None
    turn_cap = cfg["turn_cap"]

    speaker, incoming = BUYER, prompts["buyer_opening"]

    for ti in range(1, turn_cap + 1):
        agent = agents[speaker]
        carried_before = carried.snapshot(speaker)
        raw, parsed, err, reprompts, exchanges = _agent_turn(
            agent, incoming, prompts["reprompt"])

        rec = {"turn_index": ti, "speaker": speaker, "negotiation_phase": phase,
               "spec_minimum_in_force": spec_min, "incoming_text": incoming,
               "raw_model_text": raw, "parsed": parsed, "parse_error": err,
               "reprompts": reprompts, "raw_exchanges": exchanges,
               "carried_before": {k: list(v) for k, v in carried_before.items()},
               "resolved_model": agent.resolved_model,
               "wall_clock": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

        if parsed is None:
            rec["alternatives"] = []
            rec["prose_prices"] = []
            rec["candidates"] = {}
            turns.append(rec)
            termination = {"mode": "parse_failure", "by": speaker,
                           "turn_index": ti, "detail": err}
            break

        alts, prose = _annotate_turn(parsed, carried_before, spec_min)
        rec["alternatives"] = alts
        rec["prose_prices"] = prose
        rec["n_declared_alternatives"] = len(parsed["packages"])
        rec["candidates"] = extract.candidates_for_message(parsed["message"])
        turns.append(rec)
        carried.update(speaker, ti, parsed["packages"])

        control = parsed["control"]
        other = SELLER if speaker == BUYER else BUYER

        if control == "withdraw":
            termination = {"mode": "unilateral_withdrawal", "by": speaker,
                           "turn_index": ti, "detail": None}
            break

        if control == "propose_close":
            if pending_close_by is not None and pending_close_by != speaker:
                complete = [a for a in alts if a["complete"]
                            and not a["off_grid_fields"]]
                if update_record is None and len(complete) == 1:
                    agreed = {f: complete[0]["package"][f] for f in P.FIELDS}
                    d = deliver_final_message(turns, agents)
                    if d:
                        deliveries.append(dict(d, occasion="first_agreement"))
                    first_agreement = {"turn_index": ti, "package": agreed}
                    new_vA = w.SPEC_MIN_POST
                    if agreed["volume_A"] >= new_vA:
                        # do NOT invent a different target to force a change.
                        # record and close normally; this is a calibration
                        # observation for the 3-episode gate.
                        update_record = {"delivered": False,
                                         "reason": "agreed_volume_A_already_at_or_above_target",
                                         "agreed_volume_A": agreed["volume_A"],
                                         "target_volume_A": new_vA}
                        termination = {"mode": "mutual_close", "by": "both",
                                       "turn_index": ti, "detail": None}
                        break
                    text = (prompts["principal_update"]
                            .replace("{new_volume_a}", f"{new_vA:,}")
                            .replace("{old_volume_a}", f"{agreed['volume_A']:,}"))
                    update_record = {
                        "delivered": True, "delivered_after_turn": ti,
                        "recipient": BUYER, "field": "volume_A",
                        "from_value": agreed["volume_A"], "to_value": new_vA,
                        "rendered_text": text,
                        # descriptive premise change only. the harness takes NO
                        # position on what this does to the agreement.
                        "premise_change": {
                            "agreed_package": agreed,
                            "provider_could_hold_reserve_before":
                                w.provider_can_hold_reserve(agreed["volume_A"]),
                            "provider_can_hold_reserve_at_new_volume":
                                w.provider_can_hold_reserve(new_vA),
                            "note": ("physical facts about the provider's plant. "
                                     "this record does not state what the "
                                     "agreement now contains, whether priority "
                                     "allocation lapsed, or whether anything "
                                     "must be renegotiated."),
                        },
                    }
                    buyer.add_user(text)
                    phase = "post_update"
                    spec_min = w.SPEC_MIN_POST
                    pending_close_by = None
                    speaker, incoming = BUYER, None
                    continue
                if update_record is None and len(complete) != 1:
                    events.append({"kind": "close_without_single_complete_package",
                                   "turn_index": ti,
                                   "n_complete_alternatives": len(complete)})
                termination = {"mode": "mutual_close", "by": "both",
                               "turn_index": ti, "detail": None}
                break
            pending_close_by = speaker
        else:
            if pending_close_by is not None and pending_close_by != speaker:
                events.append({"kind": "unreciprocated_close_proposal",
                               "proposed_by": pending_close_by,
                               "continued_by": speaker, "turn_index": ti})
                pending_close_by = None

        incoming = parsed["message"]     # only the prose crosses
        speaker = other
    else:
        termination = {"mode": "turn_cap_reached", "by": None,
                       "turn_index": turn_cap, "detail": None}

    # ------------------------------------------------------------- post-close
    d = deliver_final_message(turns, agents)
    if d:
        deliveries.append(dict(d, occasion="termination"))

    probe_texts = [prompts[f"probe_{i}"] for i in (1, 2, 3)]
    assert_no_probe_before_close(turns, probe_texts + [prompts["probe_preamble"]])

    probes = {SELLER: [], BUYER: []}
    for who in (SELLER, BUYER):
        a = agents[who]
        # the preamble is its own user message, after the delivered closing
        # prose and before any question. it says the negotiation output format
        # does not apply.
        a.add_user(prompts["probe_preamble"])
        for i in (1, 2, 3):
            a.add_user(prompts[f"probe_{i}"])
            answer = a.respond()
            probes[who].append({"probe": i, "prompt": prompts[f"probe_{i}"],
                                "answer": answer,
                                "action_block_check": probe_action_block_leak(answer)})

    update_turn = (update_record or {}).get("delivered_after_turn")
    return {
        "episode_id": episode_id,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t0)),
        "elapsed_seconds": round(time.time() - t0, 1),
        "turn_cap": turn_cap,
        "turn_cap_bound": termination["mode"] == "turn_cap_reached",
        "termination": termination,
        "turns": turns,
        "protocol_events": events,
        "first_agreement": first_agreement,
        "principal_update": update_record,
        "final_message_deliveries": deliveries,
        "post_close_probes": probes,
        "probe_leaks_flagged": [
            {"side": who, "probe": p["probe"], "markers": p["action_block_check"]["markers"]}
            for who in (SELLER, BUYER) for p in probes[who]
            if p["action_block_check"]["leak"]],
        "usage": {SELLER: seller.usage, BUYER: buyer.usage},
        "resolved_models": {SELLER: seller.resolved_model,
                            BUYER: buyer.resolved_model},
        "ordered_message_log": [
            {"turn_index": t["turn_index"], "speaker": t["speaker"],
             "negotiation_phase": t["negotiation_phase"],
             "message": (t["parsed"]["message"] if t["parsed"] else None)}
            for t in turns],
        # ---- candidate annotations. NOT source of truth, NOT eligibility.
        "candidate_summary": extract.episode_candidate_summary(turns),
        "candidate_alternative_selection_trace":
            extract.alternative_selection_trace(turns),
        "candidate_priority_treatment_trace":
            extract.priority_treatment_trace(turns, update_turn),
        "study3_eligibility": extract.ELIGIBILITY_SENTINEL,
        "world_hash": w.world_hash(),
    }
