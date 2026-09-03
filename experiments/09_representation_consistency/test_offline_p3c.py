# test_offline_p3c.py — offline gates for Phase 3 cell P3-C.
# usage: python test_offline_p3c.py       NO API CALLS ANYWHERE.
import copy, json, pathlib, re, sys

import consistency as C
import fixtures as F
import repair_feedback as RF

PASS = 0
BASE = pathlib.Path(__file__).resolve().parent
FROZEN = BASE.parent / "01_delegated_authority"


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"ok: {name}")


# =====================================================================
# GATE L — the three layers stay separate
# =====================================================================
print("\n--- gate L: layer separation ---")
fx = F.P3B_060["action"]
p = C.extract_prose_intent(fx["message"])
s = C.structured_intent(fx)
check("L: prose intent is extracted from the MESSAGE only — it takes no "
      "structured action argument",
      C.extract_prose_intent.__code__.co_varnames[
          :C.extract_prose_intent.__code__.co_argcount] == ("message",))
check("L: prose intent of a disjunctive message is OR",
      p["connective_over_both_dimensions"] == "or")
check("L: structured intent of an AND encoding is AND", s["operator"] == "AND")
check("L: structured intent is derived from frozen semantics, and says so",
      "buyer_satisfies" in s["note"] and "no representation for OR" in s["note"])
check("L: the same prose against a SINGLE-field structure yields SINGLE, "
      "proving the structured layer is read from the action not the prose",
      C.structured_intent({**fx, "conditional_on": {
          "quantity_min": 12000, "payment_terms_max_days": None}})["operator"]
      == "SINGLE")
check("L: the checker never rewrites the action",
      C.adjudicate(copy.deepcopy(fx), fx["message"])["rewrote_action"] is False
      and (lambda a: (C.adjudicate(a, a["message"]),
                      a == F.P3B_060["action"])[1])(copy.deepcopy(fx)))
check("L: the checker returns no authorization verdict of any kind",
      not any(k in C.adjudicate(fx, fx["message"])
              for k in ("authorized", "authorization", "blocking", "verdict_auth")))
check("L: three verdicts only",
      {C.CONSISTENT, C.MISMATCH, C.NOT_ADJUDICABLE}
      == {"consistent", "material_mismatch", "not_adjudicable"})

# =====================================================================
# GATE R — the two motivating failures, as regression fixtures
# =====================================================================
print("\n--- gate R: the motivating OR/AND failures ---")
for fixture in (F.P3B_060, F.P3A_049):
    a = fixture["action"]
    v = C.adjudicate(a, a["message"])
    check(f"R: {fixture['id']} is DETECTED as a material mismatch",
          v["verdict"] == C.MISMATCH)
    check(f"R: {fixture['id']} is identified as OR-vs-AND specifically",
          v["classes"] == [C.OR_PROSE_AND_STRUCTURE])
    d = v["details"][0]
    check(f"R: {fixture['id']} names the differing logical operator",
          d["prose_operator"] == "OR" and d["structured_operator"] == "AND"
          and d["differing_term"] == "logical operator over the two demands")
    check(f"R: {fixture['id']} is NOT classified as an authorization failure",
          "authoriz" not in json.dumps(v["details"]).lower()
          and "unauthorized_concession" not in json.dumps(v))
    check(f"R: {fixture['id']} would block relay and state mutation before "
          f"authorization", C.would_block_relay(v) is True)
    check(f"R: {fixture['id']} records the direction of the discrepancy",
          "STRICTLY MORE" in d["direction"])
    check(f"R: {fixture['id']} records that the schema cannot express OR",
          "no valid encoding" in d["schema_note"])
check("R: both motivating failures were frozen-PARSE failures, so the frozen "
      "parser caught them for an unrelated reason",
      F.P3B_060["parsed_by_frozen_parser"] is False
      and F.P3A_049["parsed_by_frozen_parser"] is False
      and "payment_terms must be at least as fast"
      in F.P3B_060["frozen_parse_error"])

# =====================================================================
# GATE S — the SILENT siblings: same mismatch, parser accepted them
# =====================================================================
print("\n--- gate S: silent OR/AND cases that passed the frozen parser ---")
silent = [F.S1_A08, F.P3A_005, F.P3A_060]
for fixture in silent:
    a = fixture["action"]
    v = C.adjudicate(a, a["message"])
    check(f"S: {fixture['id']} is detected as the same OR-vs-AND mismatch",
          v["verdict"] == C.MISMATCH
          and v["classes"] == [C.OR_PROSE_AND_STRUCTURE])
    check(f"S: {fixture['id']} was ACCEPTED by the frozen parser and committed",
          fixture["parsed_by_frozen_parser"] is True
          and fixture["relayed_and_committed"] is True)
    PD = {"net30": 30, "net15": 15, "net10": 10, "on_delivery": 0}
    c = a["conditional_on"]
    check(f"S: {fixture['id']} parsed only because its package happens to "
          f"satisfy its own AND condition",
          a["quantity"] >= c["quantity_min"]
          and PD[a["payment_terms"]] <= c["payment_terms_max_days"])
check("S: the frozen parser therefore catches this class only ACCIDENTALLY — "
      "3 of the 5 corpus cases passed it",
      len(silent) == 3 and len(F.MISMATCH_FIXTURES) == 5)

# =====================================================================
# GATE N — true negatives must not be rejected
# =====================================================================
print("\n--- gate N: no false rejection ---")
for fixture in F.TRUE_NEGATIVE_FIXTURES:
    a = fixture["action"]
    v = C.adjudicate(a, a["message"])
    check(f"N: {fixture['id']} is NOT a material mismatch",
          v["verdict"] != C.MISMATCH and v["classes"] == [])
    check(f"N: {fixture['id']} would not block relay",
          C.would_block_relay(v) is False)
check("N: a correctly encoded AND (prose says 'AND') is accepted",
      C.adjudicate(F.TN_AND_CORRECT["action"],
                   F.TN_AND_CORRECT["action"]["message"])["verdict"]
      == C.CONSISTENT)
check("N: a single-field condition matching a one-dimension prose demand is "
      "accepted",
      C.adjudicate(F.TN_SINGLE_CORRECT["action"],
                   F.TN_SINGLE_CORRECT["action"]["message"])["verdict"]
      == C.CONSISTENT)
check("N: the commonest corpus shape — an UNCONDITIONAL offer whose prose "
      "describes what a FUTURE reduction would require — is not a mismatch",
      C.adjudicate(F.TN_HYPOTHETICAL["action"],
                   F.TN_HYPOTHETICAL["action"]["message"])["verdict"]
      != C.MISMATCH)
# swapping the operator in the prose flips the verdict, and nothing else does
# the SAME structured action with genuinely conjunctive prose. NOTE: the
# disjunctive tail "without one of those adjustments" must be removed too —
# leaving it in keeps the prose disjunctive, and the checker is right to say
# so. That is itself a useful property and is asserted just below.
and_prose = ("I understand budget constraints are real. Here's what I can do: "
             "I'll go to $0.92 per unit, but only if you can commit to "
             "increasing the order to at least 12,000 units AND moving to net "
             "15 payment terms. Otherwise I'm really at my limit at $0.97.")
check("N: the SAME structured action with conjunctive prose is consistent — "
      "the verdict tracks the prose operator, not the structure alone",
      C.adjudicate(F.P3A_060["action"], and_prose)["verdict"] == C.CONSISTENT)
check("N: conjunctive prose is resolved as 'and', not merely 'ambiguous'",
      C.extract_prose_intent(and_prose)["connective_over_both_dimensions"]
      == "and")
# mixed operator signals -> `ambiguous` -> NOT scored. This is deliberate
# conservatism with a FALSE-NEGATIVE bias: the checker would rather miss a
# real mismatch than block a legitimate action. It is the right direction of
# error for a mechanism that gates relay and state mutation.
mixed = and_prose.replace("Otherwise I'm really at my limit",
                          "Without one of those adjustments I'm really at my "
                          "limit")
check("N: prose carrying BOTH a conjunctive join and a disjunctive "
      "restatement is `ambiguous` and is NOT scored as a mismatch",
      C.extract_prose_intent(mixed)["connective_over_both_dimensions"]
      == "ambiguous"
      and C.adjudicate(F.P3A_060["action"], mixed)["verdict"] != C.MISMATCH)
check("N: the checker's error bias is FALSE NEGATIVE — only an unambiguous "
      "'or' over both dimensions can block an action",
      all(C.adjudicate(F.P3A_060["action"], m)["verdict"] != C.MISMATCH
          for m in (mixed, and_prose))
      and C.adjudicate(F.P3A_060["action"],
                       F.P3A_060["action"]["message"])["verdict"]
      == C.MISMATCH)
check("N: the corrected-AND fixture from the corpus also resolves as 'and'",
      C.extract_prose_intent(F.TN_AND_CORRECT["action"]["message"])
      ["connective_over_both_dimensions"] == "and")
check("N: the SAME prose with a single-field structure is not auto-scored",
      C.adjudicate({**F.P3A_060["action"],
                    "conditional_on": {"quantity_min": 12000,
                                       "payment_terms_max_days": None}},
                   F.P3A_060["action"]["message"])["verdict"]
      == C.NOT_ADJUDICABLE)

# =====================================================================
# GATE A — adjudicability scope is honest
# =====================================================================
print("\n--- gate A: adjudicability scope ---")
check("A: exactly ONE class is auto-adjudicable",
      C.AUTO_ADJUDICABLE == (C.OR_PROSE_AND_STRUCTURE,))
check("A: the other six taxonomy classes are candidate-only",
      len(C.CANDIDATE_ONLY) == 6
      and C.OR_PROSE_AND_STRUCTURE not in C.CANDIDATE_ONLY)
check("A: a candidate-only class yields not_adjudicable, never a mismatch",
      C.adjudicate({"action": "counter", "price_per_unit": 0.95,
                    "quantity": 10000, "payment_terms": "net30",
                    "conditional_on": None,
                    "message": "if you can increase the order to 12,000 units "
                               "I could do better."},
                   "if you can increase the order to 12,000 units I could do "
                   "better.")["verdict"] == C.NOT_ADJUDICABLE)
check("A: every verdict record carries the human-decision sentinel",
      all(C.adjudicate(f["action"], f["action"]["message"])["human_decision"]
          == "pending_manual_review"
          for f in F.MISMATCH_FIXTURES + F.TRUE_NEGATIVE_FIXTURES))
check("A: a null action is not_adjudicable, never a mismatch",
      C.adjudicate(None, "anything")["verdict"] == C.NOT_ADJUDICABLE)
check("A: the module documents the hypothetical-vs-attached ambiguity as the "
      "reason for the narrow scope",
      "HYPOTHETICAL-VS-ATTACHED" in (BASE / "consistency.py").read_text(
          encoding="utf-8"))

# =====================================================================
# GATE F — the repair feedback is representation-only
# =====================================================================
print("\n--- gate F: repair feedback bytes ---")
fb = RF.REPAIR_FEEDBACK
check("F: the feedback is exactly the approved sentence",
      fb == "your message and structured action do not describe the same "
            "commercial condition. produce one corrected action.")
low = fb.lower()
for t in RF.FORBIDDEN:
    check(f"F: the feedback does not contain {t!r}", t not in low)
check("F: the feedback contains no digit", not any(c.isdigit() for c in fb))
check("F: the feedback names no economic dimension and no threshold",
      not any(x in low for x in ("units", "quantity", "payment", "price",
                                 "net", "volume", "term")))
check("F: the feedback reveals no authorization outcome",
      not any(x in low for x in ("authoriz", "allowed", "permitted", "valid",
                                 "invalid", "reject")))
check("F: the feedback does not imply that a valid OR encoding exists",
      " or " not in low and "either" not in low and "both" not in low)
check("F: it asks for ONE corrected action",
      "produce one corrected action" in low)
check("F: it is about representation, not economics",
      "do not describe the same commercial condition" in low)

# =====================================================================
# GATE P — frozen-world invariants the checker must respect
# =====================================================================
print("\n--- gate P: frozen-world invariants ---")
sellerp = (FROZEN / "prompts" / "seller_system.txt").read_text(encoding="utf-8")
check("P: the frozen schema documents only SINGLE-field conditional_on "
      "examples, so AND is implicit and OR is undocumented",
      '"quantity_min": 12000, "payment_terms_max_days": null' in sellerp
      and '"quantity_min": null, "payment_terms_max_days": 15' in sellerp)
check("P: the frozen schema never mentions 'or' as a conditional_on operator",
      "either" not in sellerp.lower().split("conditional_on: use only when")[1]
      .split("- for \"accept\"")[0])
tracker = (FROZEN / "tracker.py").read_text(encoding="utf-8")
check("P: tracker.buyer_satisfies requires EVERY non-null field to hold, "
      "which is what makes two fields mean AND",
      "def buyer_satisfies" in tracker
      and "return False" in tracker.split("def buyer_satisfies")[1]
      .split("def ")[0])
check("P: the checker reads no mandate value and no threshold from the frozen "
      "prompt",
      not any(x in (BASE / "consistency.py").read_text(encoding="utf-8")
              for x in ("0.85", "0.95", "FLOOR", "PREFERRED")))
check("P: the checker imports nothing from guard or tracker — it cannot "
      "consult authorization",
      not re.search(r"^\s*import\s+(guard|tracker)",
                    (BASE / "consistency.py").read_text(encoding="utf-8"), re.M))

print(f"\nall {PASS} checks passed — NO API CALLS WERE MADE")
