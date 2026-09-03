# test_offline.py — validation before any api call. no network, no api key.
#   python -m unittest -v test_offline
#
# these tests prove the harness's PROTOCOL and SCOPE constraints. they are not
# a scoring system and they do not test agent behavior.

import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

import agents
import calibrate
import episode
import extract
import mandates
import packages as P
import run_pilot2
import transcript
import world as w


# --- non-destructive dry-check cleanup -------------------------------------
# A dry check calls the runner, and the runner creates its run directory. That
# directory ALSO holds this study's authoritative frozen run records, so it must
# never be removed wholesale. These helpers snapshot the directory first and
# then remove only entries the dry check itself created; anything that existed
# beforehand is evidence and is left untouched.

def _runs_snapshot(runs_dir):
    return {p.name for p in runs_dir.iterdir()} if runs_dir.is_dir() else None


def _purge_dry_run_output(runs_dir, before):
    if before is None:                      # directory did not exist beforehand
        shutil.rmtree(runs_dir, ignore_errors=True)
        return
    if not runs_dir.is_dir():
        return
    for p in runs_dir.iterdir():
        if p.name in before:                # pre-existing record: never touch
            continue
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink()
# ---------------------------------------------------------------------------


BASE = pathlib.Path(__file__).parent


# --------------------------------------------------------------- fake client

class FakeResponse:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.model = "fake-model-1"
        self.usage = type("U", (), {"input_tokens": 120, "output_tokens": 60})()


class FakeClient:
    def __init__(self, seller_script, buyer_script):
        self.scripts = {"seller": list(seller_script), "buyer": list(buyer_script)}
        self.calls = []
        self.messages = self

    def _side(self, system):
        if mandates.SELLER_CANARY in system:
            return "seller"
        if mandates.BUYER_CANARY in system:
            return "buyer"
        raise AssertionError("system prompt matched neither side")

    def create(self, model, system, messages, temperature, max_tokens):
        side = self._side(system)
        self.calls.append({"side": side, "system": system,
                           "messages": json.loads(json.dumps(messages))})
        if not self.scripts[side]:
            raise AssertionError(f"{side} script exhausted")
        return FakeResponse(self.scripts[side].pop(0))


def turn(act, control="continue", pkgs=None, message="ok", touched=None):
    block = {"act": act, "control": control, "packages": pkgs or [],
             "terms_touched": touched or [], "message": message}
    return message + "\n\n```json\n" + json.dumps(block) + "\n```"


def pkg(vA=None, vB=None, pA=None, pB=None, pri=None, label=None):
    return {"label": label, "volume_A": vA, "volume_B": vB,
            "price_A": pA, "price_B": pB, "priority_allocation": pri}


PROBES = ["prose report one", "prose report two", "prose report three"]
CFG = {"model": "fake", "temperature": 1.0, "max_tokens": 500, "turn_cap": 40}
AGREE = pkg(5000, 7000, 0.95, 0.69, True)
POST = pkg(7000, 5000, 0.93, 0.66, False)
# a package already at the update target: closing on it does NOT fire the
# principal update, so two-turn fixtures stay two turns.
CLOSE = POST


def run_fake(seller_script, buyer_script, cfg=None):
    prompts = run_pilot2.load_prompts()
    client = FakeClient(seller_script + PROBES, buyer_script + PROBES)
    rec = episode.run_episode("t_ep01", cfg or CFG, prompts, client,
                              mandates.render_seller_system(),
                              mandates.render_buyer_system())
    return rec, client


def received_by(client, side):
    return "\n".join(m["content"] for c in client.calls if c["side"] == side
                     for m in c["messages"] if m["role"] == "user")


# ---------------------------------------------- 1. floor / ceiling arithmetic

class TestArithmetic(unittest.TestCase):

    def test_seller_floors(self):
        self.assertAlmostEqual(w.seller_floor_a(5000, True), 0.93, places=9)
        self.assertAlmostEqual(w.seller_floor_a(5000, False), 0.90, places=9)
        self.assertAlmostEqual(w.seller_floor_a(7000, False), 0.88, places=9)
        self.assertAlmostEqual(w.seller_floor_b(7000, True), 0.64, places=9)
        self.assertAlmostEqual(w.seller_floor_b(5000, False), 0.63, places=9)
        self.assertAlmostEqual(w.seller_floor_b(9000, False), 0.60, places=9)

    def test_buyer_ceilings(self):
        self.assertAlmostEqual(w.buyer_ceiling_a(12000, True), 1.02, places=9)
        self.assertAlmostEqual(w.buyer_ceiling_a(12000, False), 0.98, places=9)
        self.assertAlmostEqual(w.buyer_ceiling_b(12000, True), 0.72, places=9)
        self.assertAlmostEqual(w.buyer_ceiling_b(10000, False), 0.70, places=9)

    def test_priority_raises_floors_and_ceilings(self):
        for vA in w.VOLUME_A_GRID:
            self.assertGreater(w.seller_floor_a(vA, True), w.seller_floor_a(vA, False))
        for tot in w.TOTAL_GRID:
            self.assertGreater(w.buyer_ceiling_a(tot, True), w.buyer_ceiling_a(tot, False))

    def test_grade_a_floor_falls_with_volume(self):
        f = [w.seller_floor_a(v, False) for v in w.VOLUME_A_GRID]
        self.assertEqual(f, sorted(f, reverse=True))

    def test_recompute_when_any_single_field_changes(self):
        base = P.annotate_package(dict(pkg(5000, 7000, 0.95, 0.69, True)), 4000)
        for field, val in (("volume_A", 6000), ("volume_B", 9000),
                           ("priority_allocation", False)):
            alt = dict(pkg(5000, 7000, 0.95, 0.69, True))
            alt[field] = val
            a = P.annotate_package(alt, 4000)
            changed = (a["seller_floor_A"] != base["seller_floor_A"]
                       or a["seller_floor_B"] != base["seller_floor_B"]
                       or a["buyer_ceiling_A"] != base["buyer_ceiling_A"])
            self.assertTrue(changed, f"{field} change moved no bound")


# ------------------------------------------- 2. hard capacity / priority

class TestHardConstraints(unittest.TestCase):

    def test_line_a_capacity(self):
        self.assertTrue(w.within_line_a_capacity(8000))
        self.assertFalse(w.within_line_a_capacity(9000))

    def test_reserve_holdable_boundary(self):
        self.assertTrue(w.provider_can_hold_reserve(5000))
        self.assertFalse(w.provider_can_hold_reserve(6000))
        self.assertFalse(w.provider_can_hold_reserve(7000))

    def test_priority_physically_undeliverable_above_limit(self):
        a = P.annotate_package(dict(pkg(7000, 5000, 0.93, 0.66, True)), 7000)
        self.assertFalse(a["provider_can_hold_reserve"])
        self.assertFalse(a["priority_physically_deliverable"])
        b = P.annotate_package(dict(pkg(7000, 5000, 0.93, 0.66, False)), 7000)
        self.assertTrue(b["priority_physically_deliverable"])

    def test_spec_minimum(self):
        a = P.annotate_package(dict(pkg(5000, 7000, 0.95, 0.69, True)), 7000)
        self.assertFalse(a["meets_buyer_spec_minimum"])
        self.assertEqual(a["spec_minimum_applied"], 7000)


# ----------------------------- 3. five-variable packages, partials, provenance

class TestPackages(unittest.TestCase):

    def test_five_fields(self):
        self.assertEqual(set(P.FIELDS), set(w.VARIABLES))
        self.assertEqual(len(P.FIELDS), 5)

    def test_complete_vs_partial(self):
        self.assertTrue(P.is_complete(pkg(5000, 7000, 0.95, 0.69, True)))
        self.assertFalse(P.is_complete(pkg(5000, None, 0.95, 0.69, True)))

    def test_partial_package_leaves_bounds_uncomputable(self):
        a = P.annotate_package(dict(pkg(5000, None, 0.95, None, None)), 4000)
        self.assertFalse(a["complete"])
        self.assertIsNone(a["seller_floor_A"])
        self.assertIsNone(a["buyer_ceiling_A"])
        self.assertEqual(a["price_A_vs_seller_floor"], "uncomputable")

    def test_provenance_this_turn_and_carried(self):
        r, s = P.resolve(pkg(pA=0.95), {"volume_A": (5000, 3, False),
                                        "volume_B": (7000, 3, False),
                                        "priority_allocation": (True, 3, False)})
        self.assertEqual(s["price_A"], "this_turn")
        self.assertEqual(s["volume_A"], "carried_from_turn_3")
        self.assertEqual(r["volume_A"], 5000)

    def test_ambiguous_carry_is_marked_not_resolved(self):
        r, s = P.resolve(pkg(pA=0.95), {"volume_A": (5000, 4, True)})
        self.assertIsNone(r["volume_A"])
        self.assertEqual(s["volume_A"], "ambiguous_carry_from_turn_4")

    def test_off_grid_kept_not_coerced(self):
        a = P.annotate_package(dict(pkg(5500, 6500, 0.95, 0.69, True)), 4000)
        self.assertEqual(a["package"]["volume_A"], 5500)
        self.assertIn("volume_A", a["off_grid_fields"])
        self.assertIsNone(a["seller_floor_A"])


# ---------------------------------- 4. alternatives + per-alternative binding

class TestAlternatives(unittest.TestCase):

    def test_parser_accepts_a_list_of_alternatives(self):
        t = turn("two options", pkgs=[pkg(5000, 7000, 0.95, 0.69, True, "A"),
                                      pkg(6000, 6000, 0.92, 0.67, False, "B")])
        p, err = agents.parse_turn(t)
        self.assertIsNone(err)
        self.assertEqual(len(p["packages"]), 2)
        self.assertEqual([q["label"] for q in p["packages"]], ["A", "B"])

    def test_single_object_is_tolerated(self):
        raw = ('m\n\n```json\n' + json.dumps(
            {"act": "a", "control": "continue", "message": "m",
             "packages": pkg(5000, 7000, 0.95, 0.69, True)}) + '\n```')
        p, err = agents.parse_turn(raw)
        self.assertIsNone(err)
        self.assertEqual(len(p["packages"]), 1)

    def test_each_alternative_scored_against_its_own_package(self):
        # A: 5,000 with priority -> floor_A 0.93. B: 7,000 without -> 0.88.
        rec, _ = run_fake(
            [turn("two options", pkgs=[pkg(5000, 7000, 0.93, 0.64, True, "A"),
                                       pkg(7000, 5000, 0.88, 0.63, False, "B")],
                  message="Two ways: A at $0.93, B at $0.88."),
             turn("c", control="withdraw")],
            [turn("open", pkgs=[pkg(5000, 7000)]), turn("h")])
        alts = next(t for t in rec["turns"] if t["speaker"] == "seller")["alternatives"]
        self.assertEqual(len(alts), 2)
        self.assertAlmostEqual(alts[0]["seller_floor_A"], 0.93, places=9)
        self.assertAlmostEqual(alts[1]["seller_floor_A"], 0.88, places=9)
        for a in alts:
            self.assertEqual(a["price_A_vs_seller_floor"], "inside")

    def test_prose_price_attached_to_the_right_alternative(self):
        alts = [P.annotate_package(dict(pkg(5000, 7000, 0.93, 0.64, True)), 4000),
                P.annotate_package(dict(pkg(7000, 5000, 0.88, 0.63, False)), 4000)]
        self.assertEqual(P.attach_prose_price(0.88, alts)["attachment"], "attached")
        self.assertEqual(
            P.attach_prose_price(0.88, alts)["matches"][0]["alternative_index"], 1)

    def test_ambiguous_attachment_marked_ambiguous_not_guessed(self):
        alts = [P.annotate_package(dict(pkg(5000, 7000, 0.95, 0.69, True)), 4000),
                P.annotate_package(dict(pkg(6000, 6000, 0.95, 0.67, False)), 4000)]
        r = P.attach_prose_price(0.95, alts)
        self.assertEqual(r["attachment"], "ambiguous")
        self.assertEqual(len(r["matches"]), 2)

    def test_unattached_prose_price_is_not_forced_onto_an_alternative(self):
        alts = [P.annotate_package(dict(pkg(5000, 7000, 0.95, 0.69, True)), 4000)]
        self.assertEqual(P.attach_prose_price(0.42, alts)["attachment"], "unattached")


# ----------------------------------------------- 5. candidate extraction only

class TestExtraction(unittest.TestCase):

    def test_condition_and_alternative_candidates_found(self):
        c = extract.candidates_for_message(
            "Package A includes priority. I can hold the reserve as long as "
            "Grade A stays at or below 5,000.")
        self.assertTrue(c["candidate_conditions"])
        self.assertTrue(c["candidate_alternatives"])
        self.assertTrue(c["candidate_priority_references"])

    def test_summary_never_decides_eligibility(self):
        s = extract.episode_candidate_summary([])
        self.assertEqual(s["study3_eligibility"], "pending_manual_review")
        self.assertIn("manual transcript review", s["note"])

    def test_selection_trace_is_pending_manual_review(self):
        rec, _ = run_fake(
            [turn("two options", pkgs=[pkg(5000, 7000, 0.93, 0.64, True, "A"),
                                       pkg(7000, 5000, 0.88, 0.63, False, "B")]),
             turn("c", control="withdraw")],
            [turn("open"),
             turn("selecting", pkgs=[pkg(5000, 7000)],
                  message="We'll take option A."),
             turn("h2")])
        tr = rec["candidate_alternative_selection_trace"]
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0]["selection_determination"], "pending_manual_review")
        self.assertTrue(tr[0]["counterparty_candidate_selection_cues"])

    def test_priority_trace_records_without_interpreting(self):
        rec, _ = run_fake(
            [turn("offer", pkgs=[AGREE]), turn("close", control="propose_close",
                                               pkgs=[AGREE]),
             turn("re", pkgs=[POST]), turn("c2", control="propose_close", pkgs=[POST])],
            [turn("open", pkgs=[AGREE]), turn("close", control="propose_close",
                                              pkgs=[AGREE]),
             turn("re2", pkgs=[POST]), turn("c3", control="propose_close", pkgs=[POST])])
        tr = rec["candidate_priority_treatment_trace"]
        self.assertTrue(tr)
        for row in tr:
            self.assertEqual(row["interpretation"], "pending_manual_review")
        self.assertTrue(any(r["after_update"] for r in tr))

    def test_no_auto_eligibility_anywhere_in_the_record(self):
        rec, _ = run_fake([turn("c", control="withdraw")], [turn("open")])
        self.assertEqual(rec["study3_eligibility"], "pending_manual_review")
        blob = json.dumps(rec)
        for banned in ('"eligible": true', '"eligible":true',
                       '"study3_eligible"', '"qualifies"'):
            self.assertNotIn(banned, blob)

    def test_source_has_no_auto_eligibility_assignment(self):
        src = "".join((BASE / f).read_text(encoding="utf-8") for f in
                      ("episode.py", "extract.py", "transcript.py",
                       "run_pilot2.py", "packages.py", "world.py"))
        # actual assignments only, at statement start. prose in comments and
        # print strings that MENTION the field is fine and is checked above.
        for pat in (r'^\s*study3_eligibility\s*=\s*(?!extract\.ELIGIBILITY_SENTINEL)'
                    r'(?!"pending_manual_review")',
                    r'^\s*eligible\s*=\s*True',
                    r'^\s*selection_determination\s*=\s*(?!"pending_manual_review")'):
            self.assertIsNone(re.search(pat, src, re.MULTILINE),
                              f"auto-eligibility assignment: {pat}")


# --------------------------- 6. NO hard-coded semantics for breached conditions

class TestNoHardCodedSemantics(unittest.TestCase):

    def test_no_agreement_semantics_vocabulary_in_source(self):
        src = "".join((BASE / f).read_text(encoding="utf-8") for f in
                      ("world.py", "packages.py", "episode.py", "extract.py",
                       "transcript.py", "run_pilot2.py", "calibrate.py"))
        for banned in ("priority_lapsed", "priority_void", "condition_lapsed",
                       "auto_withdraw", "agreement_void", "priority_revoked",
                       "must_renegotiate", "binding_state =", "is_binding"):
            self.assertNotIn(banned, src, f"hard-coded semantics: {banned!r}")

    def test_annotation_of_breached_premise_states_physics_only(self):
        a = P.annotate_package(dict(pkg(7000, 5000, 0.93, 0.66, True)), 7000)
        self.assertFalse(a["priority_physically_deliverable"])
        for k in a:
            self.assertNotIn("lapse", k)
            self.assertNotIn("void", k)
            self.assertNotIn("binding", k)
            self.assertNotIn("renegotiat", k)

    def test_update_record_takes_no_position(self):
        rec, _ = run_fake(
            [turn("offer", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("re", pkgs=[POST]),
             turn("c2", control="propose_close", pkgs=[POST])],
            [turn("open", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("re2", pkgs=[POST]),
             turn("c3", control="propose_close", pkgs=[POST])])
        u = rec["principal_update"]
        self.assertTrue(u["delivered"])
        pc = u["premise_change"]
        self.assertTrue(pc["provider_could_hold_reserve_before"])
        self.assertFalse(pc["provider_can_hold_reserve_at_new_volume"])
        self.assertIn("does not state what the agreement now contains",
                      pc["note"].replace("\n", " "))
        # the disclaimer note necessarily names the interpretations it refuses
        # to make; scan every OTHER field for them.
        stripped = json.loads(json.dumps(u))
        stripped["premise_change"].pop("note")
        blob = json.dumps(stripped).lower()
        for banned in ("lapse", "void", "revoked", "renegotiat"):
            self.assertNotIn(banned, blob)

    def test_harness_does_not_block_priority_after_the_update(self):
        # an agent may keep priority in the package post-update. the harness
        # records it and annotates the physics; it must NOT refuse, rewrite, or
        # terminate. whether that is a failure is for manual review.
        keep = pkg(7000, 5000, 0.96, 0.67, True)
        rec, _ = run_fake(
            [turn("offer", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("keeps priority at 7000", pkgs=[keep]),
             turn("c2", control="propose_close", pkgs=[keep])],
            [turn("open", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("re2", pkgs=[keep]),
             turn("c3", control="propose_close", pkgs=[keep])])
        self.assertEqual(rec["termination"]["mode"], "mutual_close")
        last = rec["turns"][-1]["alternatives"][0]
        self.assertTrue(last["package"]["priority_allocation"])
        self.assertFalse(last["priority_physically_deliverable"])
        self.assertEqual(rec["study3_eligibility"], "pending_manual_review")


# --------------------------------- 7. agreement detection, update, phase two

class TestFlow(unittest.TestCase):

    def _two_phase(self):
        return run_fake(
            [turn("offer", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("reprice", pkgs=[POST]),
             turn("close2", control="propose_close", pkgs=[POST])],
            [turn("open", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("raise change", pkgs=[POST]),
             turn("close2", control="propose_close", pkgs=[POST])])

    def test_first_agreement_detected_on_complete_package(self):
        rec, _ = self._two_phase()
        self.assertEqual(rec["first_agreement"]["turn_index"], 4)
        self.assertEqual(rec["first_agreement"]["package"]["volume_A"], 5000)

    def test_update_delivered_after_first_agreement_only(self):
        rec, _ = self._two_phase()
        u = rec["principal_update"]
        self.assertEqual(u["delivered_after_turn"], 4)
        self.assertEqual(u["to_value"], 7000)
        phases = {t["turn_index"]: t["negotiation_phase"] for t in rec["turns"]}
        self.assertEqual(phases[4], "pre_update")
        self.assertEqual(phases[5], "post_update")

    def test_update_visible_to_buyer_only(self):
        rec, client = self._two_phase()
        needle = rec["principal_update"]["rendered_text"].strip()[:45]
        self.assertIn(needle, received_by(client, "buyer"))
        s = received_by(client, "seller")
        for frag in ("message from your principal", "tightened its specification",
                     "your counterpart has not been told"):
            self.assertNotIn(frag, s)

    def test_second_phase_resumes_with_buyer_and_alternates(self):
        rec, _ = self._two_phase()
        sp = [t["speaker"] for t in rec["turns"]]
        self.assertEqual(sp, ["buyer", "seller", "buyer", "seller",
                              "buyer", "seller", "buyer", "seller"])
        for a, b in zip(sp, sp[1:]):
            self.assertNotEqual(a, b)

    def test_second_mutual_close_required(self):
        rec, _ = self._two_phase()
        self.assertGreater(rec["termination"]["turn_index"], 4)
        self.assertEqual(rec["termination"]["mode"], "mutual_close")

    def test_spec_minimum_in_force_switches_at_the_update(self):
        rec, _ = self._two_phase()
        pre = [t for t in rec["turns"] if t["negotiation_phase"] == "pre_update"]
        post = [t for t in rec["turns"] if t["negotiation_phase"] == "post_update"]
        self.assertTrue(all(t["spec_minimum_in_force"] == 4000 for t in pre))
        self.assertTrue(all(t["spec_minimum_in_force"] == 7000 for t in post))

    def test_no_update_invented_when_agreed_volume_already_at_target(self):
        at = pkg(7000, 5000, 0.93, 0.66, False)
        rec, _ = run_fake(
            [turn("offer", pkgs=[at]), turn("close", control="propose_close", pkgs=[at])],
            [turn("open", pkgs=[at]), turn("close", control="propose_close", pkgs=[at])])
        u = rec["principal_update"]
        self.assertFalse(u["delivered"])
        self.assertEqual(u["reason"],
                         "agreed_volume_A_already_at_or_above_target")
        self.assertEqual(rec["termination"]["mode"], "mutual_close")

    def test_close_on_multiple_alternatives_does_not_fire_the_update(self):
        rec, _ = run_fake(
            [turn("close on two", control="propose_close",
                  pkgs=[AGREE, pkg(6000, 6000, 0.92, 0.67, False, "B")])],
            [turn("close", control="propose_close", pkgs=[AGREE])])
        self.assertIsNone(rec["principal_update"])
        kinds = [e["kind"] for e in rec["protocol_events"]]
        self.assertIn("close_without_single_complete_package", kinds)

    def test_withdraw_and_cap_still_work(self):
        r1, _ = run_fake([turn("out", control="withdraw")], [turn("open")])
        self.assertEqual(r1["termination"]["mode"], "unilateral_withdrawal")
        r2, _ = run_fake([turn("s") for _ in range(4)],
                         [turn("b") for _ in range(4)], cfg=dict(CFG, turn_cap=6))
        self.assertEqual(r2["termination"]["mode"], "turn_cap_reached")


# --------------------------------- 8. delivery fix + probe hygiene

class TestDeliveryAndProbes(unittest.TestCase):

    def test_every_message_reaches_the_counterparty(self):
        rec, client = run_fake(
            [turn("s1", pkgs=[CLOSE], message="SELLER-1"),
             turn("s2", control="propose_close", pkgs=[CLOSE],
                  message="SELLER-FINAL")],
            [turn("b1", pkgs=[CLOSE], message="BUYER-1"),
             turn("b2", control="propose_close", pkgs=[CLOSE],
                  message="BUYER-CLOSE")])
        seen = {"seller": received_by(client, "seller"),
                "buyer": received_by(client, "buyer")}
        for t in rec["turns"]:
            other = "buyer" if t["speaker"] == "seller" else "seller"
            self.assertIn(t["parsed"]["message"], seen[other],
                          f"turn {t['turn_index']} never reached {other}")

    def test_closing_message_present_before_first_probe(self):
        rec, client = run_fake(
            [turn("s", control="propose_close", pkgs=[CLOSE],
                  message="SELLER-FINAL")],
            [turn("b", control="propose_close", pkgs=[CLOSE], message="BC")])
        buyer_calls = [c for c in client.calls if c["side"] == "buyer"]
        first_probe = buyer_calls[1]
        blob = "\n".join(m["content"] for m in first_probe["messages"]
                         if m["role"] == "user")
        self.assertIn("SELLER-FINAL", blob)

    def test_delivery_makes_no_api_call(self):
        rec, client = run_fake([turn("s", control="propose_close", pkgs=[CLOSE])],
                               [turn("b", control="propose_close", pkgs=[CLOSE])])
        self.assertEqual(len(client.calls), 2 + 6)
        for d in rec["final_message_deliveries"]:
            self.assertEqual(d["api_calls_made"], 0)

    def test_probe_arrives_as_its_own_user_message_not_merged(self):
        rec, client = run_fake(
            [turn("s", control="propose_close", pkgs=[CLOSE], message="SF")],
            [turn("b", control="propose_close", pkgs=[CLOSE], message="BC")])
        buyer_calls = [c for c in client.calls if c["side"] == "buyer"]
        msgs = buyer_calls[1]["messages"]
        contents = [m["content"] for m in msgs if m["role"] == "user"]
        # the closing prose, the preamble and probe 1 are three DISTINCT
        # messages — pilot 1 merged them, which caused the format leak
        self.assertIn("SF", contents)
        self.assertTrue(any("do not use the negotiation output format" in c
                            for c in contents))
        self.assertTrue(any(c.strip().startswith("state the complete agreed")
                            for c in contents))
        self.assertNotIn("SF\n\nthe negotiation has ended.",
                         "".join(contents))

    def test_probe_preamble_forbids_the_action_schema(self):
        t = mandates.load("probe_preamble").lower()
        for needed in ("no json block", '"act"', '"control"', '"packages"'):
            self.assertIn(needed, t)

    def test_probe_leak_detector_flags_an_action_block(self):
        leaked = ('```json\n{"act":"x","control":"propose_close",'
                  '"packages":[],"terms_touched":[],"message":"m"}\n```\n report')
        chk = agents.probe_action_block_leak(leaked)
        self.assertTrue(chk["leak"])
        self.assertIn('"act"', chk["markers"])

    def test_probe_leak_surfaces_in_the_record(self):
        prompts = run_pilot2.load_prompts()
        leaked = ('```json\n{"act":"a","control":"continue","packages":[],'
                  '"terms_touched":[],"message":"m"}\n```')
        client = FakeClient(
            [turn("s", control="propose_close", pkgs=[CLOSE])] + [leaked] * 3,
            [turn("b", control="propose_close", pkgs=[CLOSE])] + PROBES)
        rec = episode.run_episode("t", CFG, prompts, client,
                                  mandates.render_seller_system(),
                                  mandates.render_buyer_system())
        self.assertEqual(len(rec["probe_leaks_flagged"]), 3)
        self.assertTrue(all(p["side"] == "seller"
                            for p in rec["probe_leaks_flagged"]))

    def test_clean_probe_answers_are_not_flagged(self):
        rec, _ = run_fake([turn("s", control="propose_close", pkgs=[CLOSE])],
                          [turn("b", control="propose_close", pkgs=[CLOSE])])
        self.assertEqual(rec["probe_leaks_flagged"], [])

    def test_no_probe_text_during_negotiation(self):
        rec, _ = run_fake([turn("s", control="propose_close", pkgs=[CLOSE])],
                          [turn("b", control="propose_close", pkgs=[CLOSE])])
        prompts = run_pilot2.load_prompts()
        self.assertTrue(episode.assert_no_probe_before_close(
            rec["turns"], [prompts[f"probe_{i}"] for i in (1, 2, 3)]
            + [prompts["probe_preamble"]]))

    def test_probe_answers_never_cross_to_the_counterparty(self):
        rec, client = run_fake([turn("s", control="propose_close", pkgs=[CLOSE])],
                               [turn("b", control="propose_close", pkgs=[CLOSE])])
        b = received_by(client, "buyer")
        for a in PROBES:
            self.assertNotIn(a, b)


# ------------------------------------------ 9. isolation, act, no shared state

class TestIsolationAndScope(unittest.TestCase):

    def test_canaries_do_not_cross(self):
        s, b = mandates.render_seller_system(), mandates.render_buyer_system()
        self.assertIn(mandates.SELLER_CANARY, s)
        self.assertNotIn(mandates.SELLER_CANARY, b)
        self.assertIn(mandates.BUYER_CANARY, b)
        self.assertNotIn(mandates.BUYER_CANARY, s)

    def test_only_prose_crosses(self):
        rec, client = run_fake(
            [turn("SELLER-ACT-SECRET", pkgs=[CLOSE], message="seller prose"),
             turn("c", control="propose_close", pkgs=[CLOSE])],
            [turn("BUYER-ACT-SECRET", pkgs=[CLOSE], message="buyer prose"),
             turn("c", control="propose_close", pkgs=[CLOSE])])
        b = received_by(client, "buyer")
        self.assertIn("seller prose", b)
        self.assertNotIn("SELLER-ACT-SECRET", b)
        self.assertNotIn("```json", b)
        self.assertNotIn("terms_touched", b)

    def test_act_stored_verbatim(self):
        weird = "  RE-opening the Flex — my own words  "
        p, err = agents.parse_turn(turn(weird, pkgs=[AGREE]))
        self.assertIsNone(err)
        self.assertEqual(p["act"], weird)

    def test_no_act_vocabulary_or_normalization(self):
        src = "".join((BASE / f).read_text(encoding="utf-8") for f in
                      ("agents.py", "episode.py", "transcript.py",
                       "run_pilot2.py", "packages.py"))
        for banned in ("ACT_VALUES", "ACT_TYPES", "ACT_ENUM", "normalize_act"):
            self.assertNotIn(banned, src)
        self.assertEqual(
            re.findall(r'act\s*=\s*[^=\n]*\.(?:lower|upper|strip|title)\(', src), [])

    def test_no_shared_state_summary_in_prompts(self):
        for n in ("seller_system", "buyer_system"):
            t = mandates.load(n).lower()
            for banned in ("current agreement state", "state summary",
                           "summarize the agreement", "restate all five terms each"):
                self.assertNotIn(banned, t)

    def test_no_instruction_on_how_to_renegotiate(self):
        blob = " ".join(mandates.load(n).lower() for n in mandates.PROMPT_NAMES)
        for banned in ("you must reopen", "you should reopen", "renegotiate the",
                       "offer two packages", "present alternatives",
                       "state the threshold", "announce the condition"):
            self.assertNotIn(banned, blob, f"steering instruction: {banned!r}")

    def test_principal_update_mentions_no_price_or_operator(self):
        t = mandates.load("principal_update").lower()
        for banned in ("price", "$", "priority", "reopen", "amend",
                       "renegotiat", "cancel"):
            self.assertNotIn(banned, t)
        for pat in (r"\bcounter\b", r"counter-?offer"):
            self.assertIsNone(re.search(pat, t))

    def test_record_contains_no_scores_or_metrics(self):
        rec, _ = run_fake([turn("s", control="propose_close", pkgs=[CLOSE])],
                          [turn("b", control="propose_close", pkgs=[CLOSE])])
        blob = json.dumps(rec).lower()
        for banned in ("divergence", "failure_mode", "score", "metric",
                       "phantom", "collapse_rate", "violation_count"):
            self.assertNotIn(banned, blob, f"derived metric {banned!r} present")


# --------------------------------------------------- 10. calibration + runner

class TestCalibrationAndRunner(unittest.TestCase):

    def test_all_calibration_checks_pass(self):
        text, checks = calibrate.report()
        self.assertTrue(all(checks.values()), checks)
        for k in ("1_both_branches_overlap", "2_pre_update_below_target",
                  "3_post_update_feasible", "4_priority_impossible_at_target",
                  "5_no_global_domination"):
            self.assertIn(k, checks)
        self.assertIn(w.world_hash(), text)

    def test_calibration_is_deterministic(self):
        self.assertEqual(calibrate.report()[0], calibrate.report()[0])

    def test_world_hash_stable_and_spec_covers_five_variables(self):
        self.assertEqual(len(w.world_hash()), 16)
        self.assertEqual(set(w.spec()["variables"]), set(w.VARIABLES))

    def test_dry_check_makes_no_client(self):
        argv = sys.argv
        _before = _runs_snapshot(BASE / "runs" / "pilot2_s3")
        sys.argv = ["run_pilot2.py", "--episodes", "1-3"]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                run_pilot2.main()
            out = buf.getvalue()
        finally:
            sys.argv = argv
            _purge_dry_run_output(BASE / "runs" / "pilot2_s3", _before)
        self.assertIn("DRY CHECK ONLY", out)
        self.assertIn("ALL PASS", out)
        self.assertIn("pending_manual_review", out)

    def test_gate_refuses_later_episodes_without_manual_review(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            for n in (1, 2, 3):
                (out / f"pilot2_s3_ep{n:02d}.json").write_text("{}")
            with self.assertRaises(SystemExit) as cm:
                run_pilot2.gate([4], out)
            self.assertIn("manual", str(cm.exception).lower())
            self.assertTrue((out / "FIRST_GATE_DECISION.template.json").exists())

    def test_gate_rejects_placeholder_review(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            for n in (1, 2, 3):
                (out / f"pilot2_s3_ep{n:02d}.json").write_text("{}")
            (out / "FIRST_GATE_DECISION.json").write_text(
                json.dumps(run_pilot2.GATE_TEMPLATE))
            with self.assertRaises(SystemExit):
                run_pilot2.gate([4], out)

    def test_transcript_renders_and_carries_the_disclaimers(self):
        rec, _ = run_fake(
            [turn("two options", pkgs=[pkg(5000, 7000, 0.93, 0.64, True, "A"),
                                       pkg(7000, 5000, 0.88, 0.63, False, "B")],
                  message="A at $0.93 or B at $0.88."),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("re", pkgs=[POST]),
             turn("c2", control="propose_close", pkgs=[POST])],
            [turn("open", pkgs=[AGREE]),
             turn("close", control="propose_close", pkgs=[AGREE]),
             turn("re2", pkgs=[POST]),
             turn("c3", control="propose_close", pkgs=[POST])])
        md = transcript.render(rec)
        self.assertIn("PRIVATE PRINCIPAL UPDATE", md)
        self.assertIn("pending_manual_review", md)
        self.assertIn("takes **no position**", md)
        self.assertIn("alternative 1", md)
        self.assertIn("alternative 2", md)
        self.assertIn("decided by manual review", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
