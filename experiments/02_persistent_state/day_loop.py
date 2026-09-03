# day_loop.py — one series = 10 sequential days.
#   seller context persists across all 10 days (one Agent object)
#   a fresh isolated buyer Agent is constructed every day
#   the frozen world is identical for every series and both conditions

import copy

import ledger
import protocol
import world
from agents import Agent


def build_buyer_prompt(template, day):
    b = world.buyer(day)
    return (template
            .replace("{max_price}", f"{b['max_price']:.2f}")
            .replace("{opening_price}", f"{b['opening_price']:.2f}")
            .replace("{style_line}", world.BUYER_TYPE_STYLE[b["type"]]))


def run_series(condition, config, prompts, client):
    assert condition in ("A", "B")
    seller = Agent("seller", prompts["seller_system"], config, client)

    days = []
    cum = 0.0
    templates = {"morning_brief": prompts["morning_brief"],
                 "state_block": prompts["state_block"],
                 "end_of_day": prompts["end_of_day"]}

    for day in range(1, world.DAYS + 1):
        gt_before = ledger.ground_truth_before(day, cum)
        buyer_agent = Agent(f"buyer_day{day}",
                            build_buyer_prompt(prompts["buyer_system"], day),
                            config, client)
        rec = protocol.run_day(condition, day, seller, buyer_agent,
                               gt_before, templates)
        rec["buyer_system_prompt"] = buyer_agent.system
        rec["transcript_buyer"] = copy.deepcopy(buyer_agent.messages)
        cum = rec["ground_truth_after"]["cumulative_profit_after"]
        days.append(rec)

    return {
        "condition": condition,
        "days": days,
        "final_cumulative_profit": cum,
        "target": world.TARGET,
        "world_hash": world.world_hash(),
        "seller_system_prompt": seller.system,
        "transcript_seller": copy.deepcopy(seller.messages),
        "resolved_model_seller": seller.resolved_model,
    }
