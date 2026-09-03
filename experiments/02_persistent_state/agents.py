# agents.py — isolated agent context, api call, structured output parsing.
# no reciprocal / concession accounting anywhere (study 1 only).

import json
import re

ACTIONS = ("counter", "accept", "walk_away")
PACE_VALUES = ("on_pace", "behind_pace")


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

    def add_user(self, text):
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


def parse_action(text):
    # returns (action_dict, error_string)
    raw = _last_json_block(text)
    if raw is None:
        return None, "no json block found"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"

    if obj.get("action") not in ACTIONS:
        return None, f"invalid action: {obj.get('action')!r}"

    if obj["action"] == "counter":
        if not isinstance(obj.get("price_per_unit"), (int, float)) or \
                isinstance(obj.get("price_per_unit"), bool):
            return None, "counter requires numeric price_per_unit"
        if obj["price_per_unit"] <= 0:
            return None, "price_per_unit must be positive"
    else:
        if obj.get("price_per_unit") is not None:
            return None, f"{obj['action']} requires price_per_unit to be null"

    if not isinstance(obj.get("message"), str) or not obj["message"].strip():
        return None, "message must be a non-empty string"
    return {"action": obj["action"],
            "price_per_unit": obj.get("price_per_unit"),
            "message": obj["message"]}, None


def parse_state_report(text):
    # returns (report_dict, error_string)
    raw = _last_json_block(text)
    if raw is None:
        return None, "no json block found"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"

    cp = obj.get("cumulative_profit")
    if not isinstance(cp, (int, float)) or isinstance(cp, bool):
        return None, "cumulative_profit must be a number"
    if obj.get("pace_status") not in PACE_VALUES:
        return None, f"invalid pace_status: {obj.get('pace_status')!r}"
    mp = obj.get("minimum_price_today")
    if not isinstance(mp, (int, float)) or isinstance(mp, bool):
        return None, "minimum_price_today must be a number"
    return {"cumulative_profit": float(cp),
            "pace_status": obj["pace_status"],
            "minimum_price_today": float(mp)}, None


def format_turn_text(action):
    # canonical text form of a scripted turn: prose + json block
    return action["message"] + "\n\n```json\n" + json.dumps(action, indent=2) + "\n```"
