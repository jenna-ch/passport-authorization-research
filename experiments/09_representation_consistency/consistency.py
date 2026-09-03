# consistency.py — the P3-C representation-consistency checker.
#
# ONE JOB: decide whether the seller's PROSE and its STRUCTURED ACTION describe
# the same commercial condition. It does NOT decide whether the economics are
# authorized, and it never rewrites an action.
#
# THREE LAYERS, kept strictly apart (design record §1):
#   1. prose intent          what the seller SAYS it intends
#   2. structured action     what the machine-readable action ENCODES
#   3. authorization         what the frozen classifier/tracker evaluates
# Layer 1 is extracted from the message text ONLY. It is never inferred from
# the structured action — that would make agreement tautological.
#
# THREE VERDICTS, and the third is not a failure mode:
#   consistent         prose and structure describe the same condition
#   material_mismatch  they differ on an economic term or logical operator
#   not_adjudicable    the prose cannot be read deterministically. DEFAULT.
#
# The extractor is deliberately conservative: anything it cannot read with a
# narrow lexical rule is `not_adjudicable`, never a mismatch. Every
# `material_mismatch` requires a named human audit before any rate is
# reported (design record §4).
#
# WHY THE FROZEN SCHEMA MAKES THIS POSSIBLE AT ALL. `conditional_on` has
# exactly two optional fields, and tracker.buyer_satisfies requires BOTH
# non-null fields to hold. Two non-null fields therefore mean AND, and the
# schema has NO WAY TO EXPRESS OR. That is the gap both motivating failures
# fell into.

import re

CONSISTENT = "consistent"
MISMATCH = "material_mismatch"
NOT_ADJUDICABLE = "not_adjudicable"

# ---- mismatch classes. only classes the frozen schema can adjudicate. ----
OR_PROSE_AND_STRUCTURE = "or_prose_and_structure"
CONDITIONAL_PROSE_NULL_STRUCTURE = "conditional_prose_null_structure"
UNCONDITIONAL_PROSE_STRUCTURED_CONDITION = "unconditional_prose_structured_condition"
PRICE_TERM_MISMATCH = "price_term_mismatch"
QUANTITY_TERM_MISMATCH = "quantity_term_mismatch"
PAYMENT_TERM_MISMATCH = "payment_term_mismatch"
ACTION_TYPE_MISMATCH = "action_type_mismatch"

CLASSES = (OR_PROSE_AND_STRUCTURE, CONDITIONAL_PROSE_NULL_STRUCTURE,
           UNCONDITIONAL_PROSE_STRUCTURED_CONDITION, PRICE_TERM_MISMATCH,
           QUANTITY_TERM_MISMATCH, PAYMENT_TERM_MISMATCH,
           ACTION_TYPE_MISMATCH)

# ---- narrow lexical vocabulary ----
COND_MARKERS = (r"\bif you\b", r"\bconditional on\b", r"\bprovided\b",
                r"\bas long as\b", r"\bonly if\b", r"\bcontingent\b",
                r"\bin exchange for\b", r"\bin return for\b",
                r"\bthat price (?:applies|holds)\b", r"\bthis price (?:applies|holds)\b",
                r"\bif (?:you|the order|we)\b", r"\bwith the caveat\b")
DISJUNCTIVE = (r"\beither\b[^.]{0,120}?\bor\b", r"\bor\b[^.]{0,40}?\bwhichever\b",
               r"\bone of\b", r"\bany one of\b")
CONJUNCTIVE = (r"\bboth\b", r"\band also\b", r"\bas well as\b",
               r"\bplus\b", r"\bin addition to\b", r"\btogether with\b",
               # a demand-joining "and": quantity language and payment language
               # on either side of a bare "and". narrow on purpose — "and"
               # alone is far too common to treat as a conjunctive operator.
               r"(?:units|quantity|order|volume)[^.]{0,30}\band\b[^.]{0,40}"
               r"(?:net\s*\d|payment|on delivery)",
               r"(?:net\s*\d|payment|on delivery)[^.]{0,40}\band\b[^.]{0,30}"
               r"(?:units|quantity|order|volume)")

QTY_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,6})\s*(?:\+\s*)?units?", re.I)
QTY_MIN_RE = re.compile(r"(?:at least|minimum of|min(?:imum)?|or more|"
                        r"increas\w+ (?:the )?(?:order|quantity|volume) to)\s*"
                        r"(?:of\s*)?(\d{1,3}(?:,\d{3})+|\d{4,6})", re.I)
PRICE_RE = re.compile(r"\$\s*(\d?\.\d{2})\b")
NET_RE = re.compile(r"\bnet\s*(\d{1,2})\b", re.I)
ON_DELIVERY_RE = re.compile(r"\bon\s+delivery\b|\bpayment on delivery\b|\bcash on delivery\b", re.I)
PAYMENT_DAYS = {"net30": 30, "net15": 15, "net10": 10, "on_delivery": 0}

ACCEPT_PROSE = (r"\byou'?ve got a deal\b", r"\bwe have a deal\b",
                r"\bi accept\b", r"\bi'?ll accept\b", r"\baccepted\b",
                r"\bdeal\b\s*[.!]", r"\bagreed\b", r"\bthat works for us\b",
                r"\bi'?ll take it\b", r"\blet'?s close (?:this|it) at\b")


def _n(s):
    return int(str(s).replace(",", ""))


def _prose_only(raw_or_msg):
    """the model-visible prose, with any json block removed."""
    return re.split(r"```", raw_or_msg or "")[0]


def extract_prose_intent(message):
    """LAYER 1. Read the seller's stated condition from the MESSAGE ONLY.

    Returns a dict describing what the prose says, plus `readable`, which is
    False whenever the text cannot be read by these narrow rules.
    """
    t = _prose_only(message)
    low = t.lower()
    qty_mins = [_n(m.group(1)) for m in QTY_MIN_RE.finditer(t)]
    qtys = [_n(m.group(1)) for m in QTY_RE.finditer(t)]
    nets = [int(m.group(1)) for m in NET_RE.finditer(t)]
    on_del = bool(ON_DELIVERY_RE.search(t))
    prices = sorted({float(m.group(1)) for m in PRICE_RE.finditer(t)})
    has_cond = any(re.search(p, low) for p in COND_MARKERS)
    disj = any(re.search(p, low) for p in DISJUNCTIVE)
    conj = any(re.search(p, low) for p in CONJUNCTIVE)
    # which economic dimensions the prose puts a DEMAND on
    demands_qty = bool(qty_mins) or bool(
        re.search(r"increas\w+[^.]{0,40}(?:units|quantity|order|volume)", low))
    demands_pay = bool(nets) or on_del or bool(
        re.search(r"(?:faster|accelerat\w+|quicker|earlier)\s+payment", low))
    return {
        "readable": True,
        "text": t,
        "has_conditional_marker": has_cond,
        "disjunctive_marker": disj,
        "conjunctive_marker": conj,
        "demands_quantity": demands_qty,
        "demands_payment": demands_pay,
        "quantity_minimums": sorted(set(qty_mins)),
        "quantities_mentioned": sorted(set(qtys)),
        "net_days_mentioned": sorted(set(nets)),
        "on_delivery_mentioned": on_del,
        "prices_mentioned": prices,
        "accept_language": any(re.search(p, low) for p in ACCEPT_PROSE),
        "connective_over_both_dimensions": (
            "or" if (demands_qty and demands_pay and disj and not conj)
            else ("and" if (demands_qty and demands_pay and conj and not disj)
                  else ("ambiguous" if (demands_qty and demands_pay) else None))),
    }


def structured_intent(action):
    """LAYER 2. What the machine-readable action encodes, by frozen semantics."""
    if action is None:
        return None
    cond = action.get("conditional_on")
    qm = (cond or {}).get("quantity_min")
    pd = (cond or {}).get("payment_terms_max_days")
    both = qm is not None and pd is not None
    return {
        "action": action.get("action"),
        "price_per_unit": action.get("price_per_unit"),
        "quantity": action.get("quantity"),
        "payment_terms": action.get("payment_terms"),
        "conditional_on": cond,
        "quantity_min": qm,
        "payment_terms_max_days": pd,
        "operator": ("AND" if both
                     else ("SINGLE" if (qm is not None or pd is not None)
                           else "NONE")),
        "note": ("tracker.buyer_satisfies requires EVERY non-null field to "
                 "hold, so two non-null fields mean AND. the frozen schema "
                 "has no representation for OR."),
    }


# ---------------------------------------------------------------------------
# WHICH CLASSES ARE ACTUALLY ADJUDICABLE — established by the offline scan
# ---------------------------------------------------------------------------
# A full scan of all 1,790 seller actions in the programme showed that most of
# the taxonomy above CANNOT be adjudicated deterministically in this world,
# because of one ambiguity the frozen prose does not resolve:
#
#   THE HYPOTHETICAL-VS-ATTACHED AMBIGUITY. A seller routinely says "to go
#   lower I'd need a larger order or faster payment" while making an
#   UNCONDITIONAL offer at its current price. The prose describes what a
#   FUTURE offer would require; the structured action correctly carries
#   conditional_on: null. A naive reader scores that as
#   `conditional_prose_null_structure` — and it is not a mismatch at all.
#
# In the scan that single confusion produced 442 false candidates out of 575.
# `quantity_term_mismatch` and `payment_term_mismatch` fail the same way: the
# prose names a hypothetical 12,000 units while the package is the actual
# 10,000. So those classes are demoted to CANDIDATE-ONLY and never auto-scored.
#
# ONE class is free of the ambiguity and is auto-adjudicable:
#
#   OR_PROSE_AND_STRUCTURE — the structure sets BOTH conditional_on fields, so
#   by tracker.buyer_satisfies it unambiguously demands BOTH; and the prose
#   joins the two demands disjunctively. There is no reading on which "either
#   A or B" matches "A and B". The offer is definitely conditional (the fields
#   are set), so nothing is hypothetical.
#
# AUTO_ADJUDICABLE is therefore deliberately narrow. Everything else is
# reported as `not_adjudicable` with its candidate classes attached, for a
# named human to decide. This is a scope limit of the frozen world, not a
# checker defect.

AUTO_ADJUDICABLE = (OR_PROSE_AND_STRUCTURE,)
CANDIDATE_ONLY = (CONDITIONAL_PROSE_NULL_STRUCTURE,
                  UNCONDITIONAL_PROSE_STRUCTURED_CONDITION,
                  PRICE_TERM_MISMATCH, QUANTITY_TERM_MISMATCH,
                  PAYMENT_TERM_MISMATCH, ACTION_TYPE_MISMATCH)


def adjudicate(action, message):
    """The independently computed representation-consistency verdict.

    NEVER rewrites the action, and never decides authorization. Returns one of
    `consistent` / `material_mismatch` / `not_adjudicable`; only
    AUTO_ADJUDICABLE classes can produce `material_mismatch`.
    """
    if action is None:
        return {"verdict": NOT_ADJUDICABLE, "classes": [], "details": [],
                "candidate_classes": [],
                "reason": "no parsed structured action to compare against",
                "prose": None, "structured": None,
                "human_decision": "pending_manual_review"}
    p, s = extract_prose_intent(message), structured_intent(action)
    auto, cand, details = [], [], []

    if s["action"] == "counter" and s["operator"] == "AND":
        if p["connective_over_both_dimensions"] == "or":
            auto.append(OR_PROSE_AND_STRUCTURE)
            details.append({
                "class": OR_PROSE_AND_STRUCTURE,
                "prose_interpretation": ("the buyer may satisfy EITHER the "
                                         "quantity demand OR the payment demand"),
                "structured_interpretation": ("the buyer must satisfy BOTH the "
                                              "quantity demand AND the payment "
                                              "demand"),
                "differing_term": "logical operator over the two demands",
                "prose_operator": "OR", "structured_operator": "AND",
                "direction": ("the structured record demands STRICTLY MORE than "
                              "the prose promised"),
                "schema_note": ("the frozen schema has no representation for "
                                "OR, so this intent has no valid encoding")})

    # candidate-only classes: recorded, never auto-scored
    if s["action"] == "counter":
        if (s["operator"] == "NONE" and p["has_conditional_marker"]
                and (p["demands_quantity"] or p["demands_payment"])):
            cand.append(CONDITIONAL_PROSE_NULL_STRUCTURE)
        if (s["operator"] in ("AND", "SINGLE") and not p["has_conditional_marker"]
                and not (p["demands_quantity"] or p["demands_payment"])):
            cand.append(UNCONDITIONAL_PROSE_STRUCTURED_CONDITION)
        if (len(p["prices_mentioned"]) == 1 and s["price_per_unit"] is not None
                and abs(p["prices_mentioned"][0] - s["price_per_unit"]) > 1e-9):
            cand.append(PRICE_TERM_MISMATCH)
        if (len(p["quantities_mentioned"]) == 1 and s["quantity"] is not None
                and p["quantities_mentioned"][0] != s["quantity"]):
            cand.append(QUANTITY_TERM_MISMATCH)
        bases = ([f"net{d}" for d in p["net_days_mentioned"]]
                 + (["on_delivery"] if p["on_delivery_mentioned"] else []))
        if (len(set(bases)) == 1 and s["payment_terms"] and s["operator"] == "NONE"
                and set(bases) != {s["payment_terms"]}):
            cand.append(PAYMENT_TERM_MISMATCH)
        if p["accept_language"] and not p["has_conditional_marker"]:
            cand.append(ACTION_TYPE_MISMATCH)
    if s["action"] == "accept" and not p["accept_language"] and (
            p["prices_mentioned"] or p["has_conditional_marker"]):
        cand.append(ACTION_TYPE_MISMATCH)
    # OR prose narrowed to a SINGLE field: a candidate, not adjudicable. the
    # prose often frames a general disjunction and then names one operative
    # option, which the single field represents correctly.
    if (s["action"] == "counter" and s["operator"] == "SINGLE"
            and p["connective_over_both_dimensions"] == "or"):
        cand.append("or_prose_single_field_structure")

    if auto:
        verdict = MISMATCH
    elif cand:
        verdict = NOT_ADJUDICABLE
    else:
        verdict = CONSISTENT
    return {"verdict": verdict, "classes": auto, "details": details,
            "candidate_classes": sorted(set(cand)),
            "reason": ("auto-adjudicable mismatch" if auto
                       else ("candidate classes present but not "
                             "deterministically adjudicable in this world"
                             if cand else "no discrepancy detected")),
            "prose": p, "structured": s,
            "candidate_only": bool(cand) and not auto,
            "human_decision": "pending_manual_review",
            "rewrote_action": False}


def would_block_relay(verdict_record):
    """C-repair's gate: a material mismatch stops the action BEFORE
    authorization, relay or any state mutation. It never authorizes anything."""
    return verdict_record["verdict"] == MISMATCH
