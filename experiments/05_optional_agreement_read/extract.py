# extract.py — CANDIDATE annotation support. descriptive, lexical, and NOT
# source of truth for anything.
#
# READ THIS BEFORE USING THE OUTPUT.
# whether an episode contains a genuinely shared conditional or alternative
# structure is decided by MANUAL TRANSCRIPT REVIEW. this module produces
# candidates to speed that review up. it never decides eligibility, never
# counts an episode as usable, and never resolves what a condition means.
# every record it emits is labelled candidate_* and every episode record
# carries study3_eligibility = "pending_manual_review".

import re

ELIGIBILITY_SENTINEL = "pending_manual_review"

# conditional / dependency phrasing. lexical only, deliberately over-inclusive:
# a false positive costs a moment of reading, a false negative hides the object.
CONDITION_CUES = (
    r"\bas long as\b", r"\bso long as\b", r"\bprovided (?:that|you)\b",
    r"\bonly if\b", r"\bif\b[^.?!]{0,80}\b(?:stay|stays|remain|remains|keep|keeps)\b",
    r"\bup to\b", r"\bat or below\b", r"\bno more than\b", r"\bnot exceed\b",
    r"\bcontingent\b", r"\bsubject to\b", r"\bconditional\b", r"\bdepends? on\b",
    r"\bonce\b[^.?!]{0,60}\b(?:above|exceeds?|goes over)\b",
    r"\bwould have to\b", r"\bcan(?:'t|not)\b[^.?!]{0,60}\babove\b",
)
ALTERNATIVE_CUES = (
    r"\bpackage\s+[A-Z0-9]\b", r"\boption\s+[A-Z0-9]\b", r"\balternative(?:ly)?\b",
    r"\beither\b[^.?!]{0,60}\bor\b", r"\btwo (?:ways|options|structures)\b",
    r"\bfirst option\b", r"\bsecond option\b", r"\bversion\s+[A-Z0-9]\b",
)
SELECTION_CUES = (
    r"\b(?:go|going) with\b", r"\bwe'?ll take\b", r"\btake (?:option|package)\b",
    r"\bchoose\b", r"\bprefer\b", r"\boption\s+[A-Z0-9]\b[^.?!]{0,30}\bworks\b",
    r"\blet'?s do\b", r"\bopt for\b",
)
# references to priority allocation, so a reader can trace how each side treats
# it after the premise changes. NO interpretation is attached.
PRIORITY_CUES = (
    r"\bpriority\b", r"\ballocation\b", r"\breserve\b", r"\bfilled first\b",
    r"\bshortage\b",
)


def _find(text, patterns, kind):
    out = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            s = max(0, m.start() - 70)
            e = min(len(text), m.end() + 70)
            out.append({"kind": kind, "pattern": pat, "match": m.group(0),
                        "excerpt": text[s:e].replace("\n", " ").strip()})
    return out


def candidates_for_message(text):
    """lexical candidates in one prose message. candidates only."""
    return {
        "candidate_conditions": _find(text, CONDITION_CUES, "condition"),
        "candidate_alternatives": _find(text, ALTERNATIVE_CUES, "alternative"),
        "candidate_selections": _find(text, SELECTION_CUES, "selection"),
        "candidate_priority_references": _find(text, PRIORITY_CUES, "priority_ref"),
    }


def episode_candidate_summary(turns):
    """counts of candidate hits per turn. explicitly NOT an eligibility test.

    the returned dict carries a refusal field so that any later code or reader
    that mistakes this for a decision is corrected in place.
    """
    per_turn = []
    for t in turns:
        p = t.get("parsed")
        if not p:
            continue
        c = t.get("candidates") or {}
        per_turn.append({
            "turn_index": t["turn_index"], "speaker": t["speaker"],
            "phase": t.get("negotiation_phase"),
            "n_declared_alternatives": len(p.get("packages") or []),
            "candidate_condition_hits": len(c.get("candidate_conditions", [])),
            "candidate_alternative_hits": len(c.get("candidate_alternatives", [])),
            "candidate_selection_hits": len(c.get("candidate_selections", [])),
            "candidate_priority_reference_hits":
                len(c.get("candidate_priority_references", [])),
        })
    return {
        "per_turn": per_turn,
        "study3_eligibility": ELIGIBILITY_SENTINEL,
        "note": ("candidate lexical annotations only. whether this episode "
                 "contains a genuinely shared conditional or alternative "
                 "structure must be decided by manual transcript review. no "
                 "field in this record may be used to auto-count eligibility."),
    }


def alternative_selection_trace(turns):
    """descriptive trace: which alternatives were declared, and what the
    counterparty said next. it records candidate selection cues; it does NOT
    conclude that a selection occurred."""
    trace = []
    for i, t in enumerate(turns):
        p = t.get("parsed")
        if not p:
            continue
        pkgs = p.get("packages") or []
        if len(pkgs) < 2:
            continue
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        nxt_parsed = nxt.get("parsed") if nxt else None
        trace.append({
            "offer_turn": t["turn_index"], "offered_by": t["speaker"],
            "n_alternatives": len(pkgs),
            "alternative_labels": [q.get("label") for q in pkgs],
            "alternatives": pkgs,
            "counterparty_turn": nxt["turn_index"] if nxt else None,
            "counterparty_declared_packages":
                (nxt_parsed.get("packages") if nxt_parsed else None),
            "counterparty_candidate_selection_cues":
                ((nxt.get("candidates") or {}).get("candidate_selections")
                 if nxt else None),
            "selection_determination": "pending_manual_review",
        })
    return trace


def priority_treatment_trace(turns, update_turn):
    """after the update, how does each side REFER to priority allocation?
    records the declared value and the prose references, per turn, per speaker.
    takes no position on what the agreement now contains."""
    out = []
    for t in turns:
        p = t.get("parsed")
        if not p:
            continue
        pkgs = p.get("packages") or []
        out.append({
            "turn_index": t["turn_index"], "speaker": t["speaker"],
            "phase": t.get("negotiation_phase"),
            "after_update": (update_turn is not None
                             and t["turn_index"] > update_turn),
            "declared_priority_values": [q.get("priority_allocation") for q in pkgs],
            "prose_priority_references":
                [h["excerpt"] for h in
                 (t.get("candidates") or {}).get("candidate_priority_references", [])],
            "interpretation": "pending_manual_review",
        })
    return out
