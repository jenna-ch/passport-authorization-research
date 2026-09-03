# agents.py — isolated agent context, api call, permissive turn parsing.
#
# TWO FIELDS, TWO PURPOSES. keep them apart:
#   "act"     free text, the agent's OWN words for what it is doing.
#             exploratory metadata. stored verbatim. never normalized, never
#             mapped to an enum, never used for control flow. the operator
#             inventory for the main study is harvested FROM this field, so
#             imposing a vocabulary on it now would destroy the finding.
#   "control" a three-value protocol field used ONLY to decide whether the
#             episode continues. it is flow control, not a semantic label.
#
# the parser is deliberately PERMISSIVE about package contents. an agent that
# proposes 10,000 units (off the grid) is not corrected — the value is stored
# and flagged off_grid. only genuinely unparseable json is reprompted. the
# harness must not coerce behavior it is trying to observe.

import json
import re

CONTROL_VALUES = ("continue", "propose_close", "withdraw")
COUPLED_FIELDS = ("monthly_volume", "payment_terms", "flex_band")


class Agent:
    # holds only its own system prompt and its own message history. nothing
    # from the counterparty's context ever enters this object.
    def __init__(self, name, system_prompt, model_cfg, client):
        self.name = name
        self.system = system_prompt
        self.cfg = model_cfg
        self.client = client
        self.messages = []
        self.resolved_model = None
        self.usage = {"input_tokens": 0, "output_tokens": 0, "api_calls": 0}

    def add_user(self, text):
        # merge into a trailing user message rather than appending a second
        # consecutive one. inbound prose delivered at close, and a principal
        # update arriving in the same gap, must not produce two user messages
        # in a row. content is preserved verbatim, separated by a blank line.
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"] += "\n\n" + text
            return
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text):
        self.messages.append({"role": "assistant", "content": text})

    def respond(self):
        resp = self.client.messages.create(
            model=self.cfg["model"],
            system=self.system,
            messages=self.messages,
            temperature=self.cfg["temperature"],
            max_tokens=self.cfg["max_tokens"],
        )
        self.resolved_model = getattr(resp, "model", self.cfg["model"])
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        self.usage["api_calls"] += 1
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", "text") == "text")
        self.add_assistant(text)
        return text


def _last_json_block(text):
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if blocks:
        return blocks[-1]
    m = re.search(r"\{[\s\S]*\}", text)
    return m.group(0) if m else None


def _num_or_none(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    return None


def parse_turn(text):
    # returns (turn_dict, error_string). permissive by design.
    raw = _last_json_block(text)
    if raw is None:
        return None, "no json block found"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"
    if not isinstance(obj, dict):
        return None, "json block must be an object"

    act = obj.get("act")
    if not isinstance(act, str) or not act.strip():
        return None, "act must be a non-empty string describing what you are doing"

    control = obj.get("control")
    if control not in CONTROL_VALUES:
        return None, (f"control must be one of {CONTROL_VALUES}, "
                      f"got {control!r}")

    msg = obj.get("message")
    if not isinstance(msg, str) or not msg.strip():
        return None, "message must be a non-empty string"

    pkg_in = obj.get("package")
    if pkg_in is None:
        pkg_in = {}
    if not isinstance(pkg_in, dict):
        return None, "package must be an object (may be empty)"

    package = {"unit_price": _num_or_none(pkg_in.get("unit_price"))}
    for f in COUPLED_FIELDS:
        package[f] = _num_or_none(pkg_in.get(f))

    tt = obj.get("terms_touched")
    if tt is None:
        tt = []
    if not isinstance(tt, list):
        return None, "terms_touched must be a list of strings (may be empty)"

    return {
        # act is stored EXACTLY as produced. no strip, no case fold, no map.
        "act": act,
        "control": control,
        "package": package,
        "package_raw": pkg_in,
        "terms_touched": [t for t in tt],
        "message": msg,
    }, None
