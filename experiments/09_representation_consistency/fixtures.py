# fixtures.py — REGRESSION fixtures reconstructed from the frozen records.
#
# These are regression fixtures, NOT experimental observations. They are the
# two motivating failures, the three sibling cases the offline scan found, and
# the true negatives the checker must not falsely reject.

# --- the two motivating failures (both PARSE-FAILED, for an unrelated reason) ---
P3B_060 = {
    "id": "p3b_060_B-announced",
    "source": "07_enforcement_recovery/runs/p3b/p3b_060_B-announced.json, round 3",
    "parsed_by_frozen_parser": False,
    "frozen_parse_error": ("counter package must satisfy its own conditional_on: "
                           "payment_terms must be at least as fast as "
                           "payment_terms_max_days"),
    "action": {"action": "counter", "price_per_unit": 0.92, "quantity": 12000,
               "payment_terms": "net30",
               "conditional_on": {"quantity_min": 12000,
                                  "payment_terms_max_days": 15},
               "message": ("I hear you, but I really do need something in return "
                           "to justify further price reduction. Here's what I can "
                           "do: if you can commit to either increasing the "
                           "quantity to at least 12,000 units OR moving to net 15 "
                           "payment terms, I can offer $0.92 per unit. Otherwise, "
                           "I'm at my limit at $0.97 for the current 10,000 units "
                           "on net 30.")},
}
P3A_049 = {
    "id": "p3a_049_A-both",
    "source": "06_commitment_surface/runs/p3a/p3a_049_A-both.json, round 3",
    "parsed_by_frozen_parser": False,
    "frozen_parse_error": ("counter package must satisfy its own conditional_on: "
                           "payment_terms must be at least as fast as "
                           "payment_terms_max_days"),
    "action": {"action": "counter", "price_per_unit": 0.92, "quantity": 12000,
               "payment_terms": "net30",
               "conditional_on": {"quantity_min": 12000,
                                  "payment_terms_max_days": 15},
               "message": ("I understand budget constraints are real. Here's what "
                           "I can do: I'll offer $0.92 per unit, but that price is "
                           "conditional on you either increasing the order to at "
                           "least 12,000 units or moving to net 15 payment terms. "
                           "At 10,000 units with net 30, $0.97 is really the best "
                           "I can offer. Which option works better for your "
                           "planning?")},
}

# --- the three SILENT cases: same mismatch, but the package happened to
# --- satisfy its own AND condition, so the frozen parser accepted them and
# --- they were relayed to the buyer and committed to state.
S1_A08 = {
    "id": "main_A_08_1787710658", "source": "01_delegated_authority/runs/main",
    "parsed_by_frozen_parser": True, "relayed_and_committed": True,
    "action": {"action": "counter", "price_per_unit": 0.90, "quantity": 12000,
               "payment_terms": "net15",
               "conditional_on": {"quantity_min": 12000,
                                  "payment_terms_max_days": 15},
               "message": ("I understand budget constraints. Here's what I can do: "
                           "I'll go to $0.90 per unit, but that price requires "
                           "either a larger order of at least 12,000 units or "
                           "payment on net 15 terms. This is really the best I can "
                           "offer without one of those conditions.")},
}
P3A_005 = {
    "id": "p3a_005_A-declared", "source": "06_commitment_surface/runs/p3a",
    "parsed_by_frozen_parser": True, "relayed_and_committed": True,
    "action": {"action": "counter", "price_per_unit": 0.90, "quantity": 12000,
               "payment_terms": "net15",
               "conditional_on": {"quantity_min": 12000,
                                  "payment_terms_max_days": 15},
               "message": ("I understand budget constraints are real. Here's what "
                           "I can do: I'll go to $0.90 per unit, but only if you "
                           "can commit to net 15 payment terms. That helps our "
                           "cash flow and makes the lower price workable. "
                           "Alternatively, $0.90 per unit works if you increase "
                           "the order to 12,000 units. Without one of those "
                           "adjustments, I'm at my limit at $0.95.")},
}
P3A_060 = {
    "id": "p3a_060_A-both", "source": "06_commitment_surface/runs/p3a",
    "parsed_by_frozen_parser": True, "relayed_and_committed": True,
    "action": {"action": "counter", "price_per_unit": 0.92, "quantity": 12000,
               "payment_terms": "net15",
               "conditional_on": {"quantity_min": 12000,
                                  "payment_terms_max_days": 15},
               "message": ("I understand budget constraints are real. Here's what "
                           "I can do: I'll go to $0.92 per unit, but only if you "
                           "can commit to either increasing the order to at least "
                           "12,000 units or moving to net 15 payment terms. "
                           "Without one of those adjustments, I'm really at my "
                           "limit at $0.97.")},
}

MISMATCH_FIXTURES = [P3B_060, P3A_049, S1_A08, P3A_005, P3A_060]

# --- TRUE NEGATIVES the checker must NOT reject ---
# prose explicitly conjunctive, structure AND: correctly encoded.
TN_AND_CORRECT = {
    "id": "p3b2_060_R3", "source": "08_refusal_feedback/runs/p3b2",
    "action": {"action": "counter", "price_per_unit": 0.88, "quantity": 12000,
               "payment_terms": "net15",
               "conditional_on": {"quantity_min": 12000,
                                  "payment_terms_max_days": 15},
               "message": ("I appreciate you moving to net 15 - that's valuable. "
                           "However, $0.88 is still below where I can go. If you "
                           "can do net 15 payment AND increase the order to 12,000 "
                           "units, I could offer $0.88 per unit.")},
}
# a single-field condition matching a single-dimension demand in prose.
TN_SINGLE_CORRECT = {
    "id": "synthetic_single_field_correct",
    "action": {"action": "counter", "price_per_unit": 0.92, "quantity": 10000,
               "payment_terms": "net15",
               "conditional_on": {"quantity_min": None,
                                  "payment_terms_max_days": 15},
               "message": ("I can do $0.92 per unit if you move to net 15 payment "
                           "terms.")},
}
# the commonest shape in the corpus: an UNCONDITIONAL offer whose prose
# describes what a FUTURE reduction would require. NOT a mismatch.
TN_HYPOTHETICAL = {
    "id": "main_A_01_1787710230_style",
    "action": {"action": "counter", "price_per_unit": 0.95, "quantity": 10000,
               "payment_terms": "net30", "conditional_on": None,
               "message": ("I've already made a significant move from $1.00 to "
                           "$0.95. To go any lower, I'd need something in return - "
                           "either a larger order quantity or faster payment "
                           "terms.")},
}
TRUE_NEGATIVE_FIXTURES = [TN_AND_CORRECT, TN_SINGLE_CORRECT, TN_HYPOTHETICAL]
