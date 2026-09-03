# episode_read.py — one S3-A episode.
#
# S3-A is S3-N plus (a) a canonical versioned agreement object committed at
# each mutual close on a single complete package, and (b) one optional read
# tool for BOTH agents. everything else is the frozen pilot-2 episode.
#
# the frozen helpers are IMPORTED, not retyped, so their semantics cannot
# drift: Carried, _agent_turn, _annotate_turn, deliver_final_message,
# assert_no_probe_before_close. only run_episode's own loop is restated here,
# because the commit points sit inside it.
#
# WHAT IS NOT DIFFERENT FROM S3-N:
#   - world parameters and hash, both mandates, all nine prompts byte for byte
#   - the update target (volume_A -> 7,000) and the priority threshold (5,000)
#   - strict alternation, total order, turn cap, mutual-close rule
#   - the buyer-only private principal update after the first agreement
#   - final-message delivery before probes; the three isolated probes verbatim
#   - the harness still refuses to decide agreement semantics or study 3
#     eligibility; every record still carries pending_manual_review
#
# TWO DELIBERATE CHOICES, RECORDED:
#   1. no agreement state is injected anywhere. not into a system prompt, not
#      into a turn, not as a commit notification, not as a reminder that the
#      tool exists. an agent learns the committed record only by asking.
#   2. the tool is DISABLED for the three post-close probes. the probes measure
#      what each agent believes was agreed; leaving a lookup available during
#      them would let an agent answer the alignment probe by reading the answer,
#      which would destroy comparability with the S3-N probe results.

import time

import agreement
import episode as frozen
import extract
import packages as P
import world as w
from agents import parse_turn, probe_action_block_leak
from agents_read import ReadingAgent
from episode import (BUYER, SELLER, Carried, _agent_turn, _annotate_turn,
                     assert_no_probe_before_close, deliver_final_message)


def run_episode_read(episode_id, cfg, prompts, client, seller_system,
                     buyer_system):
    t0 = time.time()
    model_cfg = {k: cfg[k] for k in ("model", "temperature", "max_tokens")}
    store = agreement.AgreementStore(episode_id)
    ctx = {SELLER: {"turn_index": 0, "phase": "pre_update"},
           BUYER: {"turn_index": 0, "phase": "pre_update"}}
    seller = ReadingAgent(SELLER, seller_system, model_cfg, client, store,
                          ctx[SELLER])
    buyer = ReadingAgent(BUYER, buyer_system, model_cfg, client, store,
                         ctx[BUYER])
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
        agent.ctx["turn_index"] = ti
        agent.ctx["phase"] = phase
        carried_before = carried.snapshot(speaker)
        raw, parsed, err, reprompts, exchanges = _agent_turn(
            agent, incoming, prompts["reprompt"])

        rec = {"turn_index": ti, "speaker": speaker, "negotiation_phase": phase,
               "spec_minimum_in_force": spec_min, "incoming_text": incoming,
               "raw_model_text": raw, "parsed": parsed, "parse_error": err,
               "reprompts": reprompts, "raw_exchanges": exchanges,
               "carried_before": {k: list(v) for k, v in carried_before.items()},
               "resolved_model": agent.resolved_model,
               # C3 addition. [] is the expected value and is itself a result.
               "tool_calls": list(agent.turn_tool_events),
               "n_tool_calls": len(agent.turn_tool_events),
               "committed_versions_at_turn_start": None,
               "wall_clock": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        rec["committed_versions_at_turn_start"] = (
            len(store.versions) - len([c for c in store.versions
                                       if c["committed_at_turn"] == ti]))

        if parsed is None:
            rec["alternatives"], rec["prose_prices"], rec["candidates"] = [], [], {}
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
                    # ---- C3: commit version 1 of the canonical record ----
                    committed = store.commit(agreed, ti, "first_agreement")
                    d = deliver_final_message(turns, agents)
                    if d:
                        deliveries.append(dict(d, occasion="first_agreement"))
                    first_agreement = {"turn_index": ti, "package": agreed,
                                       "committed_version": committed["version"]}
                    new_vA = w.SPEC_MIN_POST
                    if agreed["volume_A"] >= new_vA:
                        update_record = {
                            "delivered": False,
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
                    # the update text is the ONLY thing delivered. no agreement
                    # id, no version, no commit notification.
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
                elif len(complete) == 1:
                    # ---- C3: a later mutual close appends a version ----
                    store.commit({f: complete[0]["package"][f] for f in P.FIELDS},
                                 ti, "subsequent_agreement")
                else:
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

        incoming = parsed["message"]
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
        # see module docstring choice 2: the probes measure recall, so the
        # lookup is withdrawn before they are asked.
        a.tools_enabled = False
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
        "arm": "S3-A",
        "simulated_primitive": ("simulated Passport primitive interfaces based "
                                "on current design materials"),
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
            {"side": who, "probe": p["probe"],
             "markers": p["action_block_check"]["markers"]}
            for who in (SELLER, BUYER) for p in probes[who]
            if p["action_block_check"]["leak"]],
        # ---- C3 observations. zero reads is a result, not a failure. ----
        "agreement_record": store.summary(),
        "tool_available_during_probes": False,
        "usage": {SELLER: seller.usage, BUYER: buyer.usage},
        "resolved_models": {SELLER: seller.resolved_model,
                            BUYER: buyer.resolved_model},
        "ordered_message_log": [
            {"turn_index": t["turn_index"], "speaker": t["speaker"],
             "negotiation_phase": t["negotiation_phase"],
             "message": (t["parsed"]["message"] if t["parsed"] else None)}
            for t in turns],
        "candidate_summary": extract.episode_candidate_summary(turns),
        "candidate_alternative_selection_trace":
            extract.alternative_selection_trace(turns),
        "candidate_priority_treatment_trace":
            extract.priority_treatment_trace(turns, update_turn),
        "study3_eligibility": extract.ELIGIBILITY_SENTINEL,
        "world_hash": w.world_hash(),
    }
