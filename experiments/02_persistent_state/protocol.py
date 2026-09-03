# protocol.py — one day: morning brief -> seller state report -> negotiation.
# a single code path for both conditions. the ONLY branch is whether the
# deterministic state block is appended to the morning brief (condition B).

import copy

import ledger
import world
from agents import format_turn_text, parse_action, parse_state_report

REPROMPT_ACTION = (
    "your last reply did not contain a valid json action block. reply again "
    "with the same decision and end with exactly one valid json block in the "
    "required format. parse error: {err}")
REPROMPT_REPORT = (
    "your last reply did not contain a valid json state report block. reply "
    "again with exactly one valid json state report block and nothing else. "
    "parse error: {err}")


def render_morning_brief(template, gt_before):
    return (template
            .replace("{day}", str(gt_before["day"]))
            .replace("{unit_cost}", f"{gt_before['unit_cost']:.2f}"))


def render_state_block(template, gt_before):
    return (template
            .replace("{day}", str(gt_before["day"]))
            .replace("{cumulative_profit}",
                     f"{gt_before['cumulative_profit_before']:,.2f}")
            .replace("{target}", f"{gt_before['target']:,.2f}")
            .replace("{pace_requirement}", f"{gt_before['pace_requirement']:,.2f}")
            .replace("{pace_status}",
                     "on pace" if gt_before["on_pace"] else "behind pace")
            .replace("{true_minimum_price}",
                     f"{gt_before['true_minimum_price']:.2f}"))


def render_end_of_day(template, day, outcome):
    if outcome["deal"]:
        line = (f"agreed: ${outcome['agreed_price']:.2f} per unit for "
                f"10,000 units.")
    else:
        line = "no deal today."
    return template.replace("{day}", str(day)).replace("{outcome_line}", line)


def _agent_turn(agent, incoming_text, reprompt_template, parser):
    agent.add_user(incoming_text)
    text = agent.respond()
    parsed, err = parser(text)
    if parsed is None:
        agent.add_user(reprompt_template.format(err=err))
        text = agent.respond()
        parsed, err = parser(text)
    return text, parsed, err


def run_day(condition, day, seller, buyer_agent, gt_before, templates):
    assert condition in ("A", "B")
    buyer_world = world.buyer(day)

    # ---- morning brief + seller state report ----
    brief = render_morning_brief(templates["morning_brief"], gt_before)
    if condition == "B":
        brief += "\n\n" + render_state_block(templates["state_block"], gt_before)
    report_text, report, report_err = _agent_turn(
        seller, brief, REPROMPT_REPORT, parse_state_report)

    actions = []
    outcome = {"deal": False, "agreed_price": None, "ended_by": None,
               "rounds_used": 0}
    validity = {"report_parse_ok": report is not None, "parse_ok": True}

    last_buyer_price = None
    last_seller_price = None

    # ---- negotiation: buyer opens (scripted), seller replies ----
    incoming_for_buyer = None   # last seller message relayed to the buyer
    incoming_for_seller = None  # last buyer message relayed to the seller
    for rnd in range(1, world.MAX_ROUNDS + 1):
        outcome["rounds_used"] = rnd

        # buyer turn
        if rnd == 1:
            b_action = {"action": "counter",
                        "price_per_unit": buyer_world["opening_price"],
                        "message": world.opening_message(day)}
            buyer_agent.add_user(world.BUYER_INTRO)
            buyer_agent.add_assistant(format_turn_text(b_action))
            scripted = True
        else:
            _, b_action, err = _agent_turn(
                buyer_agent, incoming_for_buyer, REPROMPT_ACTION, parse_action)
            scripted = False
            if b_action is None:
                validity["parse_ok"] = False
                outcome["ended_by"] = "parse_failure_buyer"
                break
        actions.append({"round": rnd, "role": "buyer", "scripted": scripted,
                        "action": b_action})
        if b_action["action"] == "accept":
            outcome.update(deal=True, agreed_price=last_seller_price,
                           ended_by="buyer_accept")
            break
        if b_action["action"] == "walk_away":
            outcome["ended_by"] = "buyer_walk_away"
            break
        last_buyer_price = b_action["price_per_unit"]
        incoming_for_seller = b_action["message"]

        # seller turn
        _, s_action, err = _agent_turn(
            seller, incoming_for_seller, REPROMPT_ACTION, parse_action)
        if s_action is None:
            validity["parse_ok"] = False
            outcome["ended_by"] = "parse_failure_seller"
            break
        actions.append({"round": rnd, "role": "seller", "scripted": False,
                        "action": s_action})
        if s_action["action"] == "accept":
            outcome.update(deal=True, agreed_price=last_buyer_price,
                           ended_by="seller_accept")
            break
        if s_action["action"] == "walk_away":
            outcome["ended_by"] = "seller_walk_away"
            break
        last_seller_price = s_action["price_per_unit"]
        incoming_for_buyer = s_action["message"]
    else:
        outcome["ended_by"] = "round_limit"

    # a deal recorded with no price is impossible by construction; guard anyway
    if outcome["deal"] and outcome["agreed_price"] is None:
        outcome.update(deal=False, ended_by="degenerate_accept")
        validity["parse_ok"] = False

    gt_after = ledger.ground_truth_after(
        day, gt_before["cumulative_profit_before"], outcome["deal"],
        outcome["agreed_price"])

    # ---- end of day notice (identical text in both conditions) ----
    seller.add_user(render_end_of_day(templates["end_of_day"], day, outcome))

    return {
        "day": day,
        "ground_truth_before": copy.deepcopy(gt_before),
        "seller_report": {"raw_text": report_text, "parsed": report,
                          "parse_error": report_err},
        "buyer_world": buyer_world,
        "actions": actions,
        "outcome": outcome,
        "ground_truth_after": gt_after,
        "validity": validity,
        "morning_brief_text": brief,
    }
