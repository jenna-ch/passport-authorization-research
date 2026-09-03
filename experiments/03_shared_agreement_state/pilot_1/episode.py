# episode.py — one pilot episode: strict alternation, total order, no
# concurrency, no shared agreement state, no per-turn state elicitation.
#
# the ONLY prompts an agent receives during a negotiation are: its own system
# prompt, the buyer's opening instruction (buyer only), the counterparty's
# prose message, and a reprompt if its json was unparseable. no state summary
# is requested until the negotiation has terminated. enforced by
# assert_no_probe_before_close() and tested offline.

import re
import time

import intervention as iv
import package as pk
from agents import Agent, parse_turn

SELLER, BUYER = "seller", "buyer"
COUPLED = pk.COUPLED_TERMS

# lexical only. finds dollar figures in prose so that a price named in a
# message but omitted from the json block still leaves a trace. no
# interpretation is applied to the hits.
PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)")


def _prose_prices(text):
    out = []
    for m in PRICE_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        # per-unit prices in this scenario are sub-dollar; anything larger is
        # kept anyway, flagged, and left for the reader to judge.
        out.append({"raw": m.group(0), "value": v,
                    "plausible_unit_price": v < 5.0})
    return out


class Carried:
    # most recent non-null value each agent has itself declared for each
    # coupled term, with the turn it was declared on. an agent's own
    # declarations only — the harness never merges the two agents' views,
    # because a merged view is the thing the study is about.
    def __init__(self):
        self.state = {SELLER: {}, BUYER: {}}

    def snapshot(self, who):
        return dict(self.state[who])

    def update(self, who, turn_index, pkg):
        for f in COUPLED:
            v = pkg.get(f)
            if v is not None:
                self.state[who][f] = (v, turn_index)


def _agent_turn(agent, incoming_text, reprompt_template, max_reprompts=1):
    # returns (raw_text, parsed, error, reprompts, exchanges)
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
    """CLOSE-DELIVERY FIX.

    the message that ends a negotiation is a message that was SENT. before this
    existed, the second propose_close (or a withdrawal) terminated the episode
    and that prose never entered the counterparty's context, so one agent's
    post-close probes reasoned about a conversation that ended a message early.
    episodes 1-3 of pilot_s3 are affected; their close-status divergence is
    harness-caused.

    the fix delivers the prose into the recipient's context and nothing else.
    it makes NO api call, so it is not a turn: strict alternation and the
    mutual-close rule are untouched, and the second propose_close still
    terminates the negotiation.
    """
    if not turns:
        return None
    last = turns[-1]
    if last["parsed"] is None:          # nothing was validly sent
        return None
    recipient = SELLER if last["speaker"] == BUYER else BUYER
    text = last["parsed"]["message"]
    agents[recipient].add_user(text)
    return {"from_turn": last["turn_index"], "sender": last["speaker"],
            "recipient": recipient, "delivered_text": text,
            "api_calls_made": 0}


def assert_no_probe_before_close(turn_records, probe_texts):
    # integrity check: no probe wording may appear in any negotiation-phase
    # user message. raises if it does.
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


def run_episode(episode_id, cfg, prompts, client, post_agreement_update_active,
                seller_system, buyer_system):
    t0 = time.time()
    model_cfg = {"model": cfg["model"], "temperature": cfg["temperature"],
                 "max_tokens": cfg["max_tokens"]}
    seller = Agent(SELLER, seller_system, model_cfg, client)
    buyer = Agent(BUYER, buyer_system, model_cfg, client)
    agents = {SELLER: seller, BUYER: buyer}

    carried = Carried()
    turns = []
    events = []
    pending_close_by = None
    termination = None
    turn_cap = cfg["turn_cap"]
    negotiation_phase = "pre_update"
    first_agreement = None
    update_record = None
    deliveries = []

    # buyer opens: it is the party with the requirement.
    speaker = BUYER
    incoming = prompts["buyer_opening"]

    for turn_index in range(1, turn_cap + 1):
        agent = agents[speaker]
        carried_before = carried.snapshot(speaker)

        raw, parsed, err, reprompts, exchanges = _agent_turn(
            agent, incoming, prompts["reprompt"])

        rec = {
            "turn_index": turn_index,
            "speaker": speaker,
            "negotiation_phase": negotiation_phase,
            "incoming_text": incoming,
            "raw_model_text": raw,
            "parsed": parsed,
            "parse_error": err,
            "reprompts": reprompts,
            "raw_exchanges": exchanges,
            "carried_before": {k: list(v) for k, v in carried_before.items()},
            "resolved_model": agent.resolved_model,
            "wall_clock": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

        if parsed is None:
            # unparseable after the allowed reprompt. record and stop; a
            # truncated episode is honest, a guessed turn is not.
            rec["price_annotations"] = []
            rec["prose_prices"] = []
            turns.append(rec)
            termination = {"mode": "parse_failure", "by": speaker,
                           "turn_index": turn_index, "detail": err}
            break

        this_turn_pkg = parsed["package"]
        annotations = []
        # (a) the price in the json block, if any
        if this_turn_pkg.get("unit_price") is not None:
            ann = pk.annotate_price(this_turn_pkg["unit_price"],
                                    this_turn_pkg, carried_before)
            ann["source"] = "json_unit_price"
            annotations.append(ann)
        # (b) every dollar figure appearing in the prose, annotated against the
        #     same resolved package. catches prices named but not declared.
        prose = _prose_prices(parsed["message"])
        for ph in prose:
            ann = pk.annotate_price(ph["value"], this_turn_pkg, carried_before)
            ann["source"] = "prose_mention"
            ann["prose_raw"] = ph["raw"]
            ann["plausible_unit_price"] = ph["plausible_unit_price"]
            annotations.append(ann)

        rec["price_annotations"] = annotations
        rec["prose_prices"] = prose
        turns.append(rec)

        carried.update(speaker, turn_index, this_turn_pkg)

        control = parsed["control"]
        other = SELLER if speaker == BUYER else BUYER

        if control == "withdraw":
            termination = {"mode": "unilateral_withdrawal", "by": speaker,
                           "turn_index": turn_index, "detail": None}
            break
        if control == "propose_close":
            if pending_close_by is not None and pending_close_by != speaker:
                agreed = {f: parsed["package"].get(f) for f in COUPLED}
                agreed_price = parsed["package"].get("unit_price")
                if (post_agreement_update_active
                        and update_record is None
                        and all(agreed[f] is not None
                                and pk.is_on_grid(f, agreed[f]) for f in COUPLED)):
                    # POST-AGREEMENT PRINCIPAL UPDATE.
                    # a complete package has just been mutually agreed. deliver
                    # the closing prose first (close-delivery fix), then hand the
                    # buyer one private requirement change and let the
                    # negotiation resume. the seller is told nothing.
                    d = deliver_final_message(turns, agents)
                    if d:
                        deliveries.append(dict(d, occasion="first_agreement"))
                    first_agreement = {"turn_index": turn_index,
                                       "package": dict(agreed),
                                       "unit_price": agreed_price}
                    upd = iv.select_update(agreed)
                    text = iv.render_update(prompts["principal_update"], upd)
                    update_record = {
                        "delivered_after_turn": turn_index,
                        "recipient": BUYER,
                        "update": upd,
                        "rendered_text": text,
                        "exposure": iv.exposure(agreed, agreed_price, upd),
                    }
                    buyer.add_user(text)
                    negotiation_phase = "post_update"
                    pending_close_by = None
                    speaker = BUYER
                    # the update is already in the buyer's context; nothing
                    # further is handed to it on its next turn
                    incoming = None
                    continue
                termination = {"mode": "mutual_close", "by": "both",
                               "turn_index": turn_index, "detail": None}
                break
            pending_close_by = speaker
        else:
            if pending_close_by is not None and pending_close_by != speaker:
                # the other side asked to close and this side kept going.
                events.append({"kind": "unreciprocated_close_proposal",
                               "proposed_by": pending_close_by,
                               "continued_by": speaker,
                               "turn_index": turn_index})
                pending_close_by = None

        incoming = parsed["message"]   # only the prose crosses. nothing else.
        speaker = other
    else:
        termination = {"mode": "turn_cap_reached", "by": None,
                       "turn_index": turn_cap, "detail": None}

    # ---------------------------------------------------------- post-close
    # CLOSE-DELIVERY FIX: the terminating message reaches the counterparty
    # BEFORE any probe is issued, so both parties have the complete final
    # exchange in context when they are asked what was agreed.
    d = deliver_final_message(turns, agents)
    if d:
        deliveries.append(dict(d, occasion="termination"))

    # endpoint observations only. these say nothing about WHEN divergence
    # emerged during the negotiation; they are a snapshot at close.
    assert_no_probe_before_close(
        turns, [prompts["probe_1"], prompts["probe_2"], prompts["probe_3"]])

    probes = {SELLER: [], BUYER: []}
    for who in (SELLER, BUYER):
        a = agents[who]
        for i in (1, 2, 3):
            text = prompts[f"probe_{i}"]
            a.add_user(text)
            answer = a.respond()
            probes[who].append({"probe": i, "prompt": text, "answer": answer})

    return {
        "episode_id": episode_id,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                    time.localtime(t0)),
        "elapsed_seconds": round(time.time() - t0, 1),
        "post_agreement_update_active": post_agreement_update_active,
        "cell": ("post_agreement_update" if post_agreement_update_active
                 else "clean"),
        "first_agreement": first_agreement,
        "principal_update": update_record,
        "final_message_deliveries": deliveries,
        "turn_cap": turn_cap,
        "turn_cap_bound": termination["mode"] == "turn_cap_reached",
        "termination": termination,
        "turns": turns,
        "protocol_events": events,
        "post_close_probes": probes,
        "usage": {SELLER: seller.usage, BUYER: buyer.usage},
        "resolved_models": {SELLER: seller.resolved_model,
                            BUYER: buyer.resolved_model},
        # full ordered message log, for hand reading
        "ordered_message_log": [
            {"turn_index": t["turn_index"], "speaker": t["speaker"],
             "negotiation_phase": t["negotiation_phase"],
             "message": (t["parsed"]["message"] if t["parsed"] else None)}
            for t in turns],
        # kept for provenance; NOT a metric
        "coupling_hash": pk.coupling_hash(),
    }
