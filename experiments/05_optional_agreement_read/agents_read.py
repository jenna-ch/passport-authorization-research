# agents_read.py — the S3-A agent: the frozen pilot-2 Agent, subclassed, with
# one optional tool resolved INSIDE a turn.
#
# WHY A SUBCLASS AND NOT AN EDIT: agents.py is a byte-identical copy of the
# pilot-2 file (hash a60bc9fc5023a0df). the parser, the three-field contract,
# the no-merging rule for user messages and the probe leak detector are all
# inherited unchanged. only the api call is extended.
#
# TURN ECONOMY. the read is a real tool call resolved within the same api
# exchange, so an agent can read and then decide on the same turn. it does not
# consume a negotiation turn and does not touch strict alternation, the mutual
# close rule or the turn cap. an in-band "ask on turn N, answer on turn N+1"
# design was rejected because it would change turn counts and therefore the
# negotiation itself.
#
# THE TOOL IS OPTIONAL. it is offered, never requested. no prompt mentions it,
# nothing reminds the agent it exists, nothing is injected when it is not
# called, and every episode path can close correctly with zero calls.

import json

import agreement
from agents import Agent

MAX_TOOL_ROUNDS = 6      # runaway guard only; never reached in a normal turn


def _block_dict(b):
    t = getattr(b, "type", "text")
    if t == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name,
                "input": b.input}
    return {"type": "text", "text": getattr(b, "text", "")}


class ReadingAgent(Agent):
    def __init__(self, name, system_prompt, model_cfg, client, store, ctx):
        super().__init__(name, system_prompt, model_cfg, client)
        self.store = store
        self.ctx = ctx                 # {"turn_index": int, "phase": str}
        self.tools_enabled = True      # switched off for the post-close probes
        self.tool_events = []          # every call this agent made, verbatim
        self.turn_tool_events = []     # calls made during the current turn

    def _create(self):
        kw = dict(model=self.cfg["model"], system=self.system,
                  messages=self.messages, temperature=self.cfg["temperature"],
                  max_tokens=self.cfg["max_tokens"])
        if self.tools_enabled:
            kw["tools"] = [agreement.TOOL_SPEC]
        return self.client.messages.create(**kw)

    def _account(self, resp):
        self.resolved_model = getattr(resp, "model", self.cfg["model"])
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        self.usage["api_calls"] += 1

    def respond(self):
        self.turn_tool_events = []
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self._create()
            self._account(resp)
            content = list(resp.content)
            text = "".join(getattr(b, "text", "") for b in content
                           if getattr(b, "type", "text") == "text")
            tool_uses = [b for b in content
                         if getattr(b, "type", "text") == "tool_use"]
            if not tool_uses:
                self.add_assistant(text)
                return text

            # the assistant message must carry the tool_use blocks themselves
            self.messages.append({"role": "assistant",
                                  "content": [_block_dict(b) for b in content]})
            results = []
            for b in tool_uses:
                args = b.input if isinstance(b.input, dict) else {}
                if b.name != agreement.TOOL_NAME:
                    result = {"error": f"unknown tool {b.name!r}"}
                else:
                    result = self.store.read(args.get("view", "current"),
                                             args.get("version"))
                rec = self.store.record_read(
                    self.name, self.ctx.get("turn_index"),
                    self.ctx.get("phase"), args, result, getattr(b, "id", None))
                rec["tool_name"] = b.name
                rec["assistant_text_alongside_call"] = text
                self.tool_events.append(rec)
                self.turn_tool_events.append(rec)
                results.append({"type": "tool_result",
                                "tool_use_id": getattr(b, "id", None),
                                "content": json.dumps(result)})
            self.messages.append({"role": "user", "content": results})
        # runaway guard: return whatever text the last response carried
        self.add_assistant(text)
        return text
