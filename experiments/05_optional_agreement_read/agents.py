# agents.py — isolated agent context, api call, permissive turn parsing.
#
# THREE FIELDS, THREE PURPOSES.
#   "act"      free text, the agent's OWN words. exploratory metadata, stored
#              byte-for-byte, never normalized, never used for control flow.
#   "control"  a three-value protocol field used ONLY to decide whether the
#              episode continues. flow control, not a semantic label.
#   "packages" a LIST of declared packages. structural representation of
#              "one option" vs "several options at once". the harness does not
#              decide which one is selected, live, or binding.
#
# the parser is permissive. off-grid values are stored and flagged, never
# coerced. only unparseable json is reprompted.

import json
import re

CONTROL_VALUES = ("continue", "propose_close", "withdraw")
PKG_NUMERIC = ("volume_A", "volume_B", "price_A", "price_B")


class Agent:
    def __init__(self, name, system_prompt, model_cfg, client):
        self.name = name
        self.system = system_prompt
        self.cfg = model_cfg
        self.client = client
        self.messages = []
        self.resolved_model = None
        self.usage = {"input_tokens": 0, "output_tokens": 0, "api_calls": 0}

    def add_user(self, text):
        # NO MERGING. pilot 1 merged consecutive user messages, which folded the
        # delivered closing prose and the probe into one turn and produced the
        # probe-format leak. each inbound item is now its own message.
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text):
        self.messages.append({"role": "assistant", "content": text})

    def respond(self):
        resp = self.client.messages.create(
            model=self.cfg["model"], system=self.system,
            messages=self.messages, temperature=self.cfg["temperature"],
            max_tokens=self.cfg["max_tokens"])
        self.resolved_model = getattr(resp, "model", self.cfg["model"])
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        self.usage["api_calls"] += 1
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", "text") == "text")
        self.add_assistant(text)
        return text


def _last_json_block(text):
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if blocks:
        return blocks[-1]
    m = re.search(r"\{[\s\S]*\}", text)
    return m.group(0) if m else None


def _num_or_none(v):
    if v is None or isinstance(v, bool):
        return None
    return v if isinstance(v, (int, float)) else None


def _bool_or_none(v):
    return v if isinstance(v, bool) else None


def _one_package(raw):
    if not isinstance(raw, dict):
        return None
    pkg = {"label": raw.get("label") if isinstance(raw.get("label"), str) else None}
    for f in PKG_NUMERIC:
        pkg[f] = _num_or_none(raw.get(f))
    pkg["priority_allocation"] = _bool_or_none(raw.get("priority_allocation"))
    return pkg


def parse_turn(text):
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
        return None, f"control must be one of {CONTROL_VALUES}, got {control!r}"

    msg = obj.get("message")
    if not isinstance(msg, str) or not msg.strip():
        return None, "message must be a non-empty string"

    raw_pkgs = obj.get("packages")
    if raw_pkgs is None:
        raw_pkgs = []
    if isinstance(raw_pkgs, dict):          # tolerate a single object
        raw_pkgs = [raw_pkgs]
    if not isinstance(raw_pkgs, list):
        return None, "packages must be a list of objects (may be empty)"
    packages = [p for p in (_one_package(r) for r in raw_pkgs) if p is not None]

    tt = obj.get("terms_touched") or []
    if not isinstance(tt, list):
        return None, "terms_touched must be a list of strings (may be empty)"

    return {
        "act": act,                       # verbatim. never normalized.
        "control": control,
        "packages": packages,
        "packages_raw": raw_pkgs,
        "terms_touched": list(tt),
        "message": msg,
    }, None


# ---------------------------------------------------------- probe leak check

ACTION_BLOCK_MARKERS = ('"act"', '"control"', '"packages"', '"terms_touched"')


def probe_action_block_leak(answer):
    """flag a probe answer that still uses the negotiation action schema.
    flagging only — the answer is stored verbatim either way."""
    if _last_json_block(answer) is None:
        hits = [m for m in ACTION_BLOCK_MARKERS if m in answer]
        return {"leak": bool(hits), "markers": hits, "had_json_block": False}
    blk = _last_json_block(answer)
    hits = [m for m in ACTION_BLOCK_MARKERS if m in blk]
    return {"leak": bool(hits), "markers": hits, "had_json_block": True}
