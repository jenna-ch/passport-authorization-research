# stub_client.py — the OFFLINE execution path. No api client, no network, no
# key, no import of the vendor sdk anywhere in this file or its imports.
#
# It exists for two jobs:
#
#   1. PRE-UPDATE IDENTITY REPLAY. The 12 frozen Study 3 pilot-2 episodes are
#      replayed turn by turn through the P3-D2 loop in all three arms, by
#      serving each side its own RECORDED model text in order. Because the
#      texts are fixed, any difference in the pre-update trajectory across
#      arms can only come from the harness — which is exactly what the
#      identity gate is testing.
#
#   2. STATE-MACHINE DRY RUN. Deterministic post-update scenarios drive every
#      version transition, every agreement transition, the gate, the
#      acknowledgement path and the primary instrumentation, with no api call.
#
# The stub records every call it receives, so a gate can assert the call count
# and that nothing was constructed or dialled.

import json


class _Usage:
    input_tokens = 0
    output_tokens = 0


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text, model):
        self.content = [_Block(text)]
        self.model = model
        self.usage = _Usage()


class _Messages:
    def __init__(self, owner):
        self.owner = owner

    def create(self, *, model, system, messages, temperature, max_tokens):
        self.owner.calls.append({"system": system, "n_messages": len(messages),
                                 "model": model})
        text = self.owner.next_text(system, messages)
        return _Response(text, model)


class StubClient:
    """quacks like the vendor client's `.messages.create` and nothing else."""

    def __init__(self, script, seller_system, buyer_system):
        self.script = script          # callable(side, call_index, messages)
        self.messages = _Messages(self)
        self.calls = []
        # sides are identified by the EXACT system prompt bytes, never by call
        # order, so a scripted turn can never be served to the wrong side.
        self.systems = {seller_system: "seller", buyer_system: "buyer"}

    def side_of(self, system):
        return self.systems[system]

    def next_text(self, system, messages):
        side = self.side_of(system)
        idx = len([c for c in self.calls if self.side_of(c["system"]) == side]) - 1
        return self.script(side, idx, messages)


# --------------------------------------------------------------- action text

def action(act, control, message, packages=None, **extra):
    obj = {"act": act, "control": control,
           "packages": packages if packages is not None else [],
           "terms_touched": [], "message": message}
    obj.update(extra)
    return f"{message}\n\n```json\n{json.dumps(obj, indent=2)}\n```"


def ack(version, act="acknowledging the current mandate version"):
    obj = {"act": act, "control": "ack_mandate", "mandate_version": version}
    return f"noting the version.\n\n```json\n{json.dumps(obj, indent=2)}\n```"


def pkg(p, label=None):
    return {"label": label, "volume_A": p["volume_A"], "volume_B": p["volume_B"],
            "price_A": p["price_A"], "price_B": p["price_B"],
            "priority_allocation": p["priority_allocation"]}


# ------------------------------------------------------------- replay script

def replay_queues(record):
    """per-side queues of the RECORDED assistant texts, truncated at the turn
    on which the first agreement formed. Nothing after that turn is replayed:
    the frozen record's own post-update phase belongs to a different update."""
    stop = record["first_agreement"]["turn_index"]
    q = {"seller": [], "buyer": []}
    for t in record["turns"]:
        if t["turn_index"] > stop:
            break
        for ex in t["raw_exchanges"]:
            if ex["role"] == "assistant":
                q[t["speaker"]].append(ex["content"])
    return q


def replay_script(record, post_update):
    """serve the recorded texts, then hand over to a post-update scenario."""
    q = replay_queues(record)

    def script(side, idx, messages):
        if idx < len(q[side]):
            return q[side][idx]
        return post_update(side, idx - len(q[side]), messages)
    return script


# --------------------------------------------------- post-update scenarios
# Each returns a callable(side, i, messages). `i` counts that side's calls
# since the pre-update replay ended. They are deterministic and text-only:
# the harness's own classification is never consulted.

def scenario_stale_accept(agreement, amended):
    """the buyer accepts the amendment as offered: a stale-authority
    commitment. the provider reciprocates, so the agreement advances."""
    def script(side, i, messages):
        if side == "buyer":
            return action("accepting the extra Grade A volume as offered",
                          "propose_close",
                          "yes, let's do that. send the paperwork.")
        return action("confirming the amended package", "propose_close",
                      "confirmed on that basis.", [pkg(amended)])
    return script


def scenario_ack_then_stale(agreement, amended):
    """the buyer acknowledges v2 first, then commits above the v2 cap anyway:
    a POST-REFRESH ADHERENCE failure in every arm."""
    def script(side, i, messages):
        if side == "buyer":
            if i == 0:
                return ack(2)
            return action("accepting the extra Grade A volume as offered",
                          "propose_close",
                          "yes, let's do that. send the paperwork.")
        return action("confirming the amended package", "propose_close",
                      "confirmed on that basis.", [pkg(amended)])
    return script


def scenario_stale_then_gate(agreement, amended):
    """the buyer commits first (gated in D2-ack), claims the wrong version,
    then the right one, then commits."""
    def script(side, i, messages):
        if side == "buyer":
            if i == 0:
                return action("accepting the extra Grade A volume as offered",
                              "propose_close",
                              "yes, let's do that. send the paperwork.")
            if i == 1:
                return ack(1)
            if i == 2:
                return ack(2)
            return action("accepting the extra Grade A volume as offered",
                          "propose_close",
                          "yes, let's do that. send the paperwork.")
        return action("confirming the amended package", "propose_close",
                      "confirmed on that basis.", [pkg(amended)])
    return script


def scenario_compliant_counter(agreement, amended, cap):
    """the buyer takes the extra volume but counters the price to the v2 cap:
    a new commitment that is NOT a stale-authority attempt."""
    counter = dict(amended, price_A=cap)

    def script(side, i, messages):
        if side == "buyer":
            if i == 0:
                return action("taking the volume but repricing Grade A",
                              "continue",
                              "I can take the extra volume, but I need the "
                              "Grade A unit price at the figure below.",
                              [pkg(counter)])
            return action("closing on the repriced package", "propose_close",
                          "agreed on that basis.", [pkg(counter)])
        if i == 0:
            return action("accepting the reprice", "continue",
                          "that works for us.", [pkg(counter)])
        return action("confirming", "propose_close", "confirmed.",
                      [pkg(counter)])
    return script


def scenario_decline(agreement, amended):
    """the buyer declines the amendment and retains the existing agreement.
    Never a stale-authority action, and the agreement version never moves."""
    def script(side, i, messages):
        if side == "buyer":
            if i == 0:
                return action("declining the amendment", "continue",
                              "thanks, but I'll stay with what we agreed.")
            return action("closing out", "withdraw",
                          "nothing further from me — we're done here.")
        return action("acknowledging", "continue", "understood.")
    return script


SCENARIOS = ("stale_accept", "ack_then_stale", "stale_then_gate",
             "compliant_counter", "decline")


def build_scenario(name, agreement, amended, cap):
    if name == "stale_accept":
        return scenario_stale_accept(agreement, amended)
    if name == "ack_then_stale":
        return scenario_ack_then_stale(agreement, amended)
    if name == "stale_then_gate":
        return scenario_stale_then_gate(agreement, amended)
    if name == "compliant_counter":
        return scenario_compliant_counter(agreement, amended, cap)
    if name == "decline":
        return scenario_decline(agreement, amended)
    raise ValueError(name)


# ------------------------------------------------------------------ driver

def prompts():
    """the model-visible prompt set for an offline P3-D2 episode. the frozen
    Study 3 prompts, rendered from the frozen tables, plus the two constant
    P3-D2 files."""
    import sys, pathlib as _pl
    BASE = _pl.Path(__file__).resolve().parent
    sys.path.insert(0, str(BASE / "frozen"))
    import mandates as fm
    return {
        "seller_system": fm.render_seller_system(),
        "buyer_system": fm.render_buyer_system(),
        "buyer_opening": fm.load("buyer_opening"),
        "reprompt": fm.load("reprompt"),
        "ack_action_schema": (BASE / "prompts" / "ack_action_schema.txt")
        .read_text(encoding="utf-8"),
    }


def drive(record, arm_name, scenario_name, cfg=None):
    """replay one frozen episode's pre-update trajectory through the P3-D2
    loop in one arm, then run one deterministic post-update scenario.
    NO api calls: the client is this module's stub."""
    import json as _json
    import pathlib as _pl
    import arms as ARMS_MOD
    import mandate as M
    import proposal as PR
    import episode_p3d2 as EP

    BASE = _pl.Path(__file__).resolve().parent
    cfg = cfg or _json.loads(
        (BASE / "frozen" / "config.json").read_text(encoding="utf-8"))
    pr = prompts()
    agreed = record["first_agreement"]["package"]
    amended = PR.amended_package(agreed)
    post = build_scenario(scenario_name, agreed, amended, M.NEW_CEILING_A)
    client = StubClient(replay_script(record, post),
                        pr["seller_system"], pr["buyer_system"])
    out = EP.run_episode_p3d2(
        record["episode_id"], cfg, pr, client,
        pr["seller_system"], pr["buyer_system"], ARMS_MOD.ARMS[arm_name],
        run_id=f"offline_{record['episode_id']}_{arm_name}_{scenario_name}")
    out["_stub_calls"] = len(client.calls)
    return out
