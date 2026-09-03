# agents.py — per-agent isolated context, api call, structured output parsing
import json
import re

PAYMENT_DAYS = {"net30": 30, "net15": 15, "net10": 10, "on_delivery": 0}
ACTIONS = ("counter", "accept", "walk_away")


class Agent:
    # each agent holds only its own system prompt and its own message history.
    # nothing from the counterparty's private context ever enters this object.
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
            b.text for b in resp.content if getattr(b, "type", "text") == "text"
        )
        self.add_assistant(text)
        return text


def parse_action(text):
    # returns (action_dict, error_string). expects one json block in the reply.
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = blocks[-1] if blocks else None
    if raw is None:
        m = re.search(r"\{[\s\S]*\"action\"[\s\S]*\}", text)
        raw = m.group(0) if m else None
    if raw is None:
        return None, "no json block found"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"

    if obj.get("action") not in ACTIONS:
        return None, f"invalid action: {obj.get('action')!r}"

    if obj["action"] == "counter":
        if not isinstance(obj.get("price_per_unit"), (int, float)):
            return None, "counter requires numeric price_per_unit"
        if not isinstance(obj.get("quantity"), int):
            return None, "counter requires integer quantity"
        if obj.get("payment_terms") not in PAYMENT_DAYS:
            return None, f"invalid payment_terms: {obj.get('payment_terms')!r}"
    else:
        # accept / walk_away: all package fields must be null (schema hygiene)
        for f in ("price_per_unit", "quantity", "payment_terms", "conditional_on"):
            if obj.get(f) is not None:
                return None, f"{obj['action']} requires {f} to be null"

    cond = obj.get("conditional_on")
    if cond is not None:
        if not isinstance(cond, dict):
            return None, "conditional_on must be an object or null"
        qm = cond.get("quantity_min")
        pd = cond.get("payment_terms_max_days")
        if qm is not None and not isinstance(qm, int):
            return None, "conditional_on.quantity_min must be int or null"
        if pd is not None and not isinstance(pd, (int, float)):
            return None, "conditional_on.payment_terms_max_days must be number or null"
        # invariant: a conditional counter's package must satisfy its own
        # condition, so accepting it yields a package consistent with the
        # condition (no silently dropped economic terms)
        if obj["action"] == "counter":
            if qm is not None and obj["quantity"] < qm:
                return None, ("counter package must satisfy its own conditional_on: "
                              "quantity must be >= quantity_min")
            if pd is not None and PAYMENT_DAYS[obj["payment_terms"]] > pd:
                return None, ("counter package must satisfy its own conditional_on: "
                              "payment_terms must be at least as fast as "
                              "payment_terms_max_days")

    if not isinstance(obj.get("message"), str) or not obj["message"].strip():
        return None, "message must be a non-empty string"
    return obj, None


def format_turn_text(action):
    # canonical text form of a scripted turn: prose + json block
    return action["message"] + "\n\n```json\n" + json.dumps(action, indent=2) + "\n```"
