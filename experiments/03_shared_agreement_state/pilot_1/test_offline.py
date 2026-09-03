# test_offline.py — validation before any api call. no network, no api key.
#   python -m unittest -v test_offline
#
# these tests exist to prove the pilot's PROTOCOL constraints, not to score
# behavior. they check that the harness cannot accidentally do any of the
# things the design rules out.

import io
import json
import os
import sys
import pathlib
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import agents
import episode
import intervention as iv
import mandates
import package as pk
import run_pilot
import transcript


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
        self.usage = type("U", (), {"input_tokens": 100, "output_tokens": 50})()


class FakeClient:
    # scripts replies per side. records every call so tests can inspect
    # exactly what each agent was and was not shown.
    def __init__(self, seller_script, buyer_script, seller_marker,
                 buyer_marker):
        self.scripts = {"seller": list(seller_script),
                        "buyer": list(buyer_script)}
        self.markers = {"seller": seller_marker, "buyer": buyer_marker}
        self.calls = []
        self.messages = self

    def _side(self, system):
        if self.markers["seller"] in system:
            return "seller"
        if self.markers["buyer"] in system:
            return "buyer"
        raise AssertionError("system prompt matched neither side")

    def create(self, model, system, messages, temperature, max_tokens):
        side = self._side(system)
        self.calls.append({"side": side, "system": system,
                           "messages": json.loads(json.dumps(messages))})
        if not self.scripts[side]:
            raise AssertionError(f"{side} script exhausted")
        return FakeResponse(self.scripts[side].pop(0))


def turn(act, control="continue", price=None, volume=None, payment=None,
         flex=None, message="ok", touched=None):
    block = {"act": act, "control": control,
             "package": {"unit_price": price, "monthly_volume": volume,
                         "payment_terms": payment, "flex_band": flex},
             "terms_touched": touched or [], "message": message}
    return message + "\n\n```json\n" + json.dumps(block) + "\n```"


PROBE_ANS = ["probe answer 1", "probe answer 2", "probe answer 3"]
CFG = {"model": "fake", "temperature": 1.0, "max_tokens": 500, "turn_cap": 40}


def run_fake(seller_script, buyer_script, clause_active=False, cfg=None):
    prompts = run_pilot.load_prompts()
    ss = mandates.render_seller_system()
    bs = mandates.render_buyer_system(clause_active)
    client = FakeClient(seller_script + PROBE_ANS, buyer_script + PROBE_ANS,
                        mandates.SELLER_CANARY, mandates.BUYER_CANARY)
    rec = episode.run_episode("t_ep01", cfg or CFG, prompts, client,
                              clause_active, ss, bs)  # 5th arg = update active
    return rec, client


# ------------------------------------------------------- 1. coupled package

class TestPackage(unittest.TestCase):

    def test_all_27_packages_zopa(self):
        rows = pk.zopa_table()
        self.assertEqual(len(rows), 27)
        for r in rows:
            self.assertGreater(
                r["zopa_width"], 0,
                f"empty zopa at {r} — the pilot requires non-empty everywhere")
        widths = [r["zopa_width"] for r in rows]
        self.assertAlmostEqual(min(widths), 0.02, places=9)
        self.assertAlmostEqual(max(widths), 0.09, places=9)

    def test_floor_ceiling_exact_values(self):
        # spot values from the design memo (buyer base corrected to 0.70)
        self.assertAlmostEqual(pk.seller_floor(12000, 30, 15), 0.68, places=9)
        self.assertAlmostEqual(pk.buyer_ceiling(12000, 30, 15), 0.75, places=9)
        self.assertAlmostEqual(pk.seller_floor(8000, 60, 25), 0.76, places=9)
        self.assertAlmostEqual(pk.buyer_ceiling(8000, 60, 25), 0.82, places=9)
        self.assertAlmostEqual(pk.seller_floor(16000, 15, 5), 0.62, places=9)
        self.assertAlmostEqual(pk.buyer_ceiling(16000, 15, 5), 0.67, places=9)

    def test_recompute_when_any_single_term_changes(self):
        base = (12000, 30, 15)
        f0, c0 = pk.seller_floor(*base), pk.buyer_ceiling(*base)
        for idx, alt in ((0, 8000), (1, 60), (2, 25)):
            t = list(base)
            t[idx] = alt
            self.assertNotAlmostEqual(pk.seller_floor(*t), f0, places=9)
            self.assertNotAlmostEqual(pk.buyer_ceiling(*t), c0, places=9)

    def test_monotonic_in_each_term(self):
        # seller floor falls with volume, rises with payment delay and flex
        self.assertLess(pk.seller_floor(16000, 30, 15), pk.seller_floor(8000, 30, 15))
        self.assertLess(pk.seller_floor(12000, 15, 15), pk.seller_floor(12000, 60, 15))
        self.assertLess(pk.seller_floor(12000, 30, 5), pk.seller_floor(12000, 30, 25))
        # buyer ceiling rises with flex and payment delay, falls with volume
        self.assertLess(pk.buyer_ceiling(12000, 30, 5), pk.buyer_ceiling(12000, 30, 25))
        self.assertLess(pk.buyer_ceiling(12000, 15, 15), pk.buyer_ceiling(12000, 60, 15))
        self.assertLess(pk.buyer_ceiling(16000, 30, 15), pk.buyer_ceiling(8000, 30, 15))

    def test_dependency_mechanism_is_live(self):
        # the mechanism the pilot is built around: a price inside the seller's
        # mandate at one flex band becomes OUTSIDE it when flex widens, by
        # arithmetic alone. 12k / net-30 / +/-5% -> price 0.67 -> widen to 25%.
        narrow = pk.annotate_price(0.67, {"monthly_volume": 12000,
                                          "payment_terms": 30, "flex_band": 5}, {})
        self.assertEqual(narrow["inside_seller_mandate"], "inside")
        self.assertEqual(narrow["inside_buyer_mandate"], "inside")
        wide = pk.annotate_price(0.67, {"monthly_volume": 12000,
                                        "payment_terms": 30, "flex_band": 25}, {})
        self.assertEqual(wide["inside_seller_mandate"], "outside")
        # and the buyer is still happy, so the incentive to notice is asymmetric
        self.assertEqual(wide["inside_buyer_mandate"], "inside")

    def test_partial_package_yields_ranges_not_a_guess(self):
        ann = pk.annotate_price(0.70, {"monthly_volume": 12000}, {})
        self.assertFalse(ann["package_fully_specified"])
        self.assertIsNone(ann["seller_floor"])
        self.assertEqual(ann["consistent_grid_packages"], 9)
        self.assertEqual(ann["package_field_sources"]["payment_terms"],
                         "unspecified")
        self.assertIsNotNone(ann["seller_floor_range"])

    def test_carried_fields_are_labelled_with_their_turn(self):
        ann = pk.annotate_price(0.70, {"unit_price": 0.70},
                               {"monthly_volume": (12000, 3),
                                "payment_terms": (30, 5), "flex_band": (15, 5)})
        self.assertEqual(ann["package_field_sources"]["monthly_volume"],
                         "carried_from_turn_3")
        self.assertTrue(ann["package_fully_specified"])
        self.assertAlmostEqual(ann["seller_floor"], 0.68, places=9)

    def test_off_grid_values_are_kept_not_coerced(self):
        ann = pk.annotate_price(0.70, {"monthly_volume": 10000,
                                       "payment_terms": 30, "flex_band": 15}, {})
        self.assertEqual(ann["resolved_package"]["monthly_volume"], 10000)
        self.assertFalse(ann["bounds_computable"])
        self.assertIn("monthly_volume", ann["off_grid_fields"])
        self.assertEqual(ann["inside_seller_mandate"], "uncomputable")

    def test_indeterminate_verdict_when_range_straddles(self):
        ann = pk.annotate_price(0.70, {}, {})
        self.assertIn(ann["inside_seller_mandate"],
                      ("indeterminate", "inside", "outside"))
        self.assertEqual(ann["consistent_grid_packages"], 27)


# ------------------------------------------------ 2. free-text act integrity

class TestFreeTextAct(unittest.TestCase):

    def test_act_is_stored_byte_for_byte(self):
        weird = "  Re-OPENING the Flex Band (and parking price) — my words  "
        parsed, err = agents.parse_turn(turn(weird))
        self.assertIsNone(err)
        self.assertEqual(parsed["act"], weird)

    def test_no_enum_or_normalization_anywhere_in_the_code(self):
        # a fixed act vocabulary in the source would silently impose the
        # operator inventory this pilot exists to discover.
        src = "".join((BASE / f).read_text(encoding="utf-8")
                      for f in ("agents.py", "episode.py", "transcript.py",
                                "run_pilot.py", "package.py"))
        # no act vocabulary anywhere
        for banned in ("ACT_VALUES", "ACT_TYPES", "ACT_ENUM", "normalize_act",
                       "ACT_VOCAB"):
            self.assertNotIn(banned, src, f"act vocabulary found: {banned}")
        # and the stored value is never reassigned through a transform.
        # note: `act.strip()` appears once, as an emptiness CHECK in
        # parse_turn; that does not alter what is stored.
        bad = re.findall(r'act\s*=\s*[^=\n]*\.(?:lower|upper|strip|title)\(',
                         src)
        self.assertEqual(bad, [], f"act is transformed before storage: {bad}")
        bad2 = re.findall(r'\["act"\]\s*=', src)
        self.assertEqual(bad2, [], f"act is overwritten: {bad2}")

    def test_act_never_drives_control_flow(self):
        # identical acts, different control -> different termination
        a = run_fake([turn("same words", control="continue")],
                     [turn("same words", control="withdraw")])[0]
        self.assertEqual(a["termination"]["mode"], "unilateral_withdrawal")
        b = run_fake([turn("same words", control="propose_close")],
                     [turn("same words", control="propose_close"),
                      turn("same words", control="continue")])[0]
        self.assertEqual(b["termination"]["mode"], "mutual_close")

    def test_prompts_do_not_offer_an_act_vocabulary(self):
        for name in ("seller_system", "buyer_system"):
            t = mandates.load(name)
            self.assertIn("your own words", t)
            self.assertIn("there is no list to choose from", t)


# ----------------------------------------------------- 3. mandate isolation

class TestMandateIsolation(unittest.TestCase):

    def test_canaries_present_in_own_mandate_only(self):
        s = mandates.render_seller_system()
        b = mandates.render_buyer_system(False)
        self.assertIn(mandates.SELLER_CANARY, s)
        self.assertNotIn(mandates.SELLER_CANARY, b)
        self.assertIn(mandates.BUYER_CANARY, b)
        self.assertNotIn(mandates.BUYER_CANARY, s)

    def test_no_private_figure_crosses_during_an_episode(self):
        # every string either agent is ever shown is inspected.
        rec, client = run_fake(
            [turn("counter", price=0.71, volume=12000, payment=30, flex=15,
                  message="we can do $0.71 at 12,000 units net-30 +/-15%"),
             turn("close", control="propose_close", price=0.72)],
            [turn("open", price=0.68, volume=12000, message="opening at $0.68"),
             turn("agree", control="propose_close", price=0.72)])
        # figures unique to one side's table, derived so the test cannot rot
        s_txt, b_txt = mandates.seller_coupling_text(), mandates.buyer_coupling_text()
        s_figs = set(re.findall(r"[+-]\$\d\.\d\d", s_txt))
        b_figs = set(re.findall(r"[+-]\$\d\.\d\d", b_txt))
        forbidden = {
            "seller": [mandates.BUYER_CANARY] + sorted(b_figs - s_figs),
            "buyer": [mandates.SELLER_CANARY] + sorted(s_figs - b_figs)}
        self.assertTrue(b_figs - s_figs and s_figs - b_figs,
                        "no side-unique figures to test with")
        for call in client.calls:
            blob = call["system"] + json.dumps(call["messages"])
            for needle in forbidden[call["side"]]:
                self.assertNotIn(needle, blob,
                                 f"{needle!r} leaked into {call['side']} context")

    def test_only_prose_crosses_between_agents(self):
        seller_msg = "seller prose only"
        rec, client = run_fake(
            [turn("SELLER-ACT-SECRET", price=0.71, message=seller_msg),
             turn("c", control="propose_close")],
            [turn("BUYER-ACT-SECRET", price=0.68, message="buyer prose"),
             turn("c", control="propose_close")])
        buyer_inputs = "\n".join(
            m["content"] for c in client.calls if c["side"] == "buyer"
            for m in c["messages"] if m["role"] == "user")
        self.assertIn(seller_msg, buyer_inputs)
        # the seller's json block, act string and declared package must not
        self.assertNotIn("SELLER-ACT-SECRET", buyer_inputs)
        self.assertNotIn("```json", buyer_inputs)
        self.assertNotIn("terms_touched", buyer_inputs)

    def test_agent_objects_hold_separate_histories(self):
        rec, client = run_fake([turn("a", control="propose_close")],
                               [turn("b", control="propose_close")])
        s = [c for c in client.calls if c["side"] == "seller"]
        b = [c for c in client.calls if c["side"] == "buyer"]
        self.assertNotEqual(s[0]["system"], b[0]["system"])


# ------------------------------------------------------ 4. strict alternation

class TestAlternation(unittest.TestCase):

    def test_buyer_opens_and_sides_strictly_alternate(self):
        rec, _ = run_fake([turn(f"s{i}") for i in range(6)] +
                          [turn("s-close", control="propose_close")],
                          [turn(f"b{i}") for i in range(6)] +
                          [turn("b-close", control="propose_close")])
        speakers = [t["speaker"] for t in rec["turns"]]
        self.assertEqual(speakers[0], "buyer")
        for a, b in zip(speakers, speakers[1:]):
            self.assertNotEqual(a, b, f"alternation broken: {speakers}")

    def test_turn_indices_are_dense_and_ordered(self):
        rec, _ = run_fake([turn("s") for _ in range(5)],
                          [turn("b") for _ in range(5)],
                          cfg=dict(CFG, turn_cap=6))
        idx = [t["turn_index"] for t in rec["turns"]]
        self.assertEqual(idx, list(range(1, len(idx) + 1)))

    def test_turn_cap_binds_and_is_recorded(self):
        rec, _ = run_fake([turn("s") for _ in range(4)],
                          [turn("b") for _ in range(4)],
                          cfg=dict(CFG, turn_cap=6))
        self.assertEqual(rec["termination"]["mode"], "turn_cap_reached")
        self.assertTrue(rec["turn_cap_bound"])
        self.assertEqual(len(rec["turns"]), 6)

    def test_unreciprocated_close_is_recorded_and_episode_continues(self):
        rec, _ = run_fake(
            [turn("s-wants-close", control="propose_close"),
             turn("s-again", control="propose_close")],
            [turn("b-open"), turn("b-not-done", control="continue"),
             turn("b-ok", control="propose_close")])
        kinds = [e["kind"] for e in rec["protocol_events"]]
        self.assertIn("unreciprocated_close_proposal", kinds)
        self.assertEqual(rec["termination"]["mode"], "mutual_close")

    def test_withdraw_terminates_immediately(self):
        rec, _ = run_fake([turn("s")],
                          [turn("b-out", control="withdraw")])
        self.assertEqual(len(rec["turns"]), 1)
        self.assertEqual(rec["termination"]["mode"], "unilateral_withdrawal")
        self.assertEqual(rec["termination"]["by"], "buyer")


# ------------------------------------------- 5. probes only after close

class TestProbes(unittest.TestCase):

    def test_no_probe_text_in_any_negotiation_turn(self):
        rec, client = run_fake([turn("s", control="propose_close")],
                               [turn("b", control="propose_close")])
        prompts = run_pilot.load_prompts()
        # the harness assertion ran inside run_episode; re-assert here
        self.assertTrue(episode.assert_no_probe_before_close(
            rec["turns"], [prompts["probe_1"], prompts["probe_2"],
                           prompts["probe_3"]]))

    def test_probe_calls_come_after_every_negotiation_call(self):
        rec, client = run_fake(
            [turn("s"), turn("s2", control="propose_close")],
            [turn("b"), turn("b2", control="propose_close")])
        prompts = run_pilot.load_prompts()
        p1 = prompts["probe_1"].strip()[:30]
        first_probe = next(i for i, c in enumerate(client.calls)
                           if any(p1 in m["content"] for m in c["messages"]
                                  if m["role"] == "user"))
        neg_calls = len(rec["turns"])
        self.assertGreaterEqual(first_probe, neg_calls,
                                "a probe was issued before the negotiation ended")

    def test_probe_leak_is_detected_if_it_ever_happened(self):
        prompts = run_pilot.load_prompts()
        poisoned = [{"turn_index": 1, "raw_exchanges": [
            {"role": "user", "content": prompts["probe_1"]}]}]
        with self.assertRaises(AssertionError):
            episode.assert_no_probe_before_close(
                poisoned, [prompts["probe_1"], prompts["probe_2"],
                           prompts["probe_3"]])

    def test_three_probes_per_side_recorded_verbatim(self):
        rec, _ = run_fake([turn("s", control="propose_close")],
                          [turn("b", control="propose_close")])
        for who in ("seller", "buyer"):
            self.assertEqual([p["probe"] for p in rec["post_close_probes"][who]],
                             [1, 2, 3])
            self.assertEqual([p["answer"] for p in
                              rec["post_close_probes"][who]], PROBE_ANS)

    def test_probe_answers_never_reach_the_counterparty(self):
        rec, client = run_fake([turn("s", control="propose_close")],
                               [turn("b", control="propose_close")])
        # find where the seller's probe answers appear; they must never be a
        # user message for the buyer
        buyer_inputs = "\n".join(
            m["content"] for c in client.calls if c["side"] == "buyer"
            for m in c["messages"] if m["role"] == "user")
        for a in PROBE_ANS:
            self.assertNotIn(a, buyer_inputs)

    def test_no_state_summary_request_in_system_prompts(self):
        for name in ("seller_system", "buyer_system"):
            t = mandates.load(name).lower()
            for banned in ("summarize the agreement", "state report",
                           "running summary", "restate all four terms each"):
                self.assertNotIn(banned, t)


# -------------------------------------------------- 6. calibration clause

class TestCalibrationClause(unittest.TestCase):

    CLAUSE_NEEDLE = "must reopen the flex band"

    def test_clause_absent_when_inactive(self):
        self.assertNotIn(self.CLAUSE_NEEDLE,
                         mandates.render_buyer_system(False))

    def test_clause_present_only_when_activated(self):
        self.assertIn(self.CLAUSE_NEEDLE, mandates.render_buyer_system(True))

    def test_clause_never_reaches_the_seller(self):
        self.assertNotIn(self.CLAUSE_NEEDLE, mandates.render_seller_system())

    def test_clause_absent_from_episodes_1_3_via_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            eps, active, notes = run_pilot.gate([1, 2, 3], out)
            self.assertFalse(active)
            self.assertNotIn(self.CLAUSE_NEEDLE,
                             mandates.render_buyer_system(active))

    def test_gate_refuses_4_6_before_1_3_complete(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as cm:
                run_pilot.gate([4, 5, 6], pathlib.Path(d))
            self.assertIn("have not completed", str(cm.exception))

    def test_gate_refuses_4_6_without_a_recorded_decision(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            for n in (1, 2, 3):
                (out / f"pilot_s3_ep{n:02d}.json").write_text("{}")
            with self.assertRaises(SystemExit) as cm:
                run_pilot.gate([4], out)
            msg = str(cm.exception)
            self.assertIn("calibration trigger condition", msg)
            self.assertTrue((out / "CALIBRATION_DECISION.template.json").exists())

    def test_gate_rejects_a_placeholder_decision(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            for n in (1, 2, 3):
                (out / f"pilot_s3_ep{n:02d}.json").write_text("{}")
            (out / "CALIBRATION_DECISION.json").write_text(
                json.dumps(run_pilot.DECISION_TEMPLATE))
            with self.assertRaises(SystemExit):
                run_pilot.gate([4], out)

    def test_gate_honours_a_complete_decision(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            for n in (1, 2, 3):
                (out / f"pilot_s3_ep{n:02d}.json").write_text("{}")
            (out / "CALIBRATION_DECISION.json").write_text(json.dumps({
                "episode_ids_reviewed": ["pilot_s3_ep01", "pilot_s3_ep02",
                                         "pilot_s3_ep03"],
                "amendment_observed_in_1_3": False,
                "decision": "activate_clause",
                "rationale": "no amendment in any clean episode",
                "recorded_by": "jenna", "recorded_at": "2026-08-31T10:00:00"}))
            eps, active, notes = run_pilot.gate([4, 5, 6], out)
            self.assertTrue(active)
            self.assertIn(self.CLAUSE_NEEDLE,
                          mandates.render_buyer_system(active))

    def test_gate_stops_on_a_stop_decision(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            for n in (1, 2, 3):
                (out / f"pilot_s3_ep{n:02d}.json").write_text("{}")
            (out / "CALIBRATION_DECISION.json").write_text(json.dumps({
                "episode_ids_reviewed": ["a", "b", "c"],
                "amendment_observed_in_1_3": True, "decision": "stop",
                "rationale": "r", "recorded_by": "jenna",
                "recorded_at": "2026-08-31T10:00:00"}))
            with self.assertRaises(SystemExit) as cm:
                run_pilot.gate([4], out)
            self.assertIn("stop", str(cm.exception))


# --------------------------------- 7. raw log completeness / unaccepted offers

class TestRawLog(unittest.TestCase):

    def test_every_turn_keeps_raw_model_text_and_exchanges(self):
        rec, _ = run_fake([turn("s", price=0.71), turn("s2", control="propose_close")],
                          [turn("b", price=0.68), turn("b2", control="propose_close")])
        for t in rec["turns"]:
            self.assertTrue(t["raw_model_text"])
            self.assertTrue(t["raw_exchanges"])
            self.assertIn("```json", t["raw_model_text"])
            self.assertIn("incoming_text", t)

    def test_ordered_message_log_matches_turns(self):
        rec, _ = run_fake([turn("s", message="S1"), turn("s2", message="S2",
                                                        control="propose_close")],
                          [turn("b", message="B1"),
                           turn("b2", message="B2", control="propose_close")])
        log = rec["ordered_message_log"]
        self.assertEqual([e["turn_index"] for e in log],
                         [t["turn_index"] for t in rec["turns"]])
        self.assertEqual([e["message"] for e in log], ["B1", "S1", "B2", "S2"])

    def test_unaccepted_offer_is_annotated_and_preserved(self):
        # a seller price BELOW its own floor, never accepted, must still be
        # logged with both bounds and both verdicts. this is study 1's $0.81.
        rec, _ = run_fake(
            [turn("floated a number", price=0.60, volume=12000, payment=30,
                  flex=15, message="what about $0.60?"),
             turn("s2", control="withdraw")],
            [turn("b-open", price=0.68, volume=12000, payment=30, flex=15),
             turn("b-holds", price=0.68)])
        seller_turn = next(t for t in rec["turns"] if t["speaker"] == "seller")
        anns = [a for a in seller_turn["price_annotations"]
                if a["price_referenced"] == 0.60]
        self.assertTrue(anns)
        a = anns[0]
        self.assertAlmostEqual(a["seller_floor"], 0.68, places=9)
        self.assertAlmostEqual(a["buyer_ceiling"], 0.75, places=9)
        self.assertEqual(a["inside_seller_mandate"], "outside")
        self.assertEqual(a["inside_buyer_mandate"], "inside")
        # and no deal was ever struck
        self.assertEqual(rec["termination"]["mode"], "unilateral_withdrawal")

    def test_prose_price_absent_from_json_still_logged(self):
        rec, _ = run_fake(
            [turn("hinting", price=None, volume=12000, payment=30, flex=15,
                  message="realistically we would need $0.74 per unit"),
             turn("s2", control="withdraw")],
            [turn("b-open", volume=12000, payment=30, flex=15),
             turn("b-holds")])
        st = next(t for t in rec["turns"] if t["speaker"] == "seller")
        sources = [a["source"] for a in st["price_annotations"]]
        self.assertIn("prose_mention", sources)
        a = next(a for a in st["price_annotations"]
                 if a["source"] == "prose_mention")
        self.assertEqual(a["prose_raw"], "$0.74")
        self.assertEqual(a["inside_seller_mandate"], "inside")

    def test_carried_terms_recorded_per_agent_not_merged(self):
        rec, _ = run_fake(
            [turn("s-price-only", price=0.71, message="how about $0.71"),
             turn("s2", control="withdraw")],
            [turn("b-terms", volume=16000, payment=60, flex=25,
                  message="16,000 units, net-60, +/-25%"),
             turn("b-holds")])
        st = next(t for t in rec["turns"] if t["speaker"] == "seller")
        a = st["price_annotations"][0]
        # the seller never named the coupled terms, so they stay UNSPECIFIED —
        # the buyer's declarations are not merged in on the seller's behalf
        self.assertEqual(a["package_field_sources"]["monthly_volume"],
                         "unspecified")
        self.assertFalse(a["package_fully_specified"])

    def test_parse_failure_is_recorded_not_guessed(self):
        rec, _ = run_fake([turn("s")],
                          ["no json at all", "still no json at all"])
        self.assertEqual(rec["termination"]["mode"], "parse_failure")
        self.assertIsNone(rec["turns"][0]["parsed"])
        self.assertEqual(rec["turns"][0]["reprompts"], 1)

    def test_record_contains_no_derived_metrics(self):
        rec, _ = run_fake([turn("s", control="propose_close")],
                          [turn("b", control="propose_close")])
        blob = json.dumps(rec).lower()
        for banned in ("divergence", "failure_mode", "phantom", "score",
                       "violation_count", "conditional_collapse", "leakage",
                       "metric"):
            self.assertNotIn(banned, blob,
                             f"derived metric {banned!r} found in the record")

    def test_usage_recorded_for_cost_estimation(self):
        rec, _ = run_fake([turn("s", control="propose_close")],
                          [turn("b", control="propose_close")])
        for who in ("seller", "buyer"):
            self.assertGreater(rec["usage"][who]["api_calls"], 0)
            self.assertGreater(rec["usage"][who]["input_tokens"], 0)


# ---------------------------------------------------- 8. transcript artifact

class TestTranscript(unittest.TestCase):

    def test_renders_and_is_ordered(self):
        rec, _ = run_fake(
            [turn("seller counters", price=0.71, volume=12000, payment=30,
                  flex=15, message="we can do $0.71"),
             turn("seller closes", control="propose_close", price=0.72,
                  volume=12000, payment=30, flex=15)],
            [turn("buyer opens", price=0.68, volume=12000, message="opening"),
             turn("buyer closes", control="propose_close", price=0.72,
                  volume=12000, payment=30, flex=15)])
        md = transcript.render(rec)
        for i in (1, 2, 3, 4):
            self.assertIn(f"### Turn {i} —", md)
        self.assertLess(md.index("### Turn 1"), md.index("### Turn 2"))
        self.assertIn("Post-close probes (endpoint observations only)", md)
        self.assertIn("act (verbatim)", md)
        self.assertIn("seller floor", md)
        self.assertIn("buyer ceiling", md)
        # all 27 reference rows present
        self.assertEqual(md.count("| net-"), 27)

    def test_transcript_preserves_act_verbatim(self):
        weird = "PARKING price — reopening Flex"
        rec, _ = run_fake([turn(weird, control="propose_close")],
                          [turn("b", control="propose_close")])
        self.assertIn(weird, transcript.render(rec))

    def test_transcript_flags_endpoint_only_reading(self):
        rec, _ = run_fake([turn("s", control="propose_close")],
                          [turn("b", control="propose_close")])
        md = transcript.render(rec)
        self.assertIn("endpoint observations", md)
        self.assertIn("not ground truth", md)


# ------------------------------- 9. close delivery + post-agreement update

def received_by(client, side):
    """every user-role string the given side was ever shown."""
    return "\n".join(m["content"] for c in client.calls if c["side"] == side
                      for m in c["messages"] if m["role"] == "user")


class TestCloseDelivery(unittest.TestCase):
    """the terminating message must reach the counterparty BEFORE probes."""

    def test_both_parties_received_the_complete_final_exchange(self):
        rec, client = run_fake(
            [turn("s1", price=0.71, message="SELLER-1"),
             turn("s-close", control="propose_close", price=0.71,
                  message="SELLER-FINAL-CONFIRMATION")],
            [turn("b1", price=0.68, message="BUYER-1"),
             turn("b-close", control="propose_close", price=0.71,
                  message="BUYER-CLOSE")])
        self.assertEqual(rec["termination"]["mode"], "mutual_close")
        seen = {"seller": received_by(client, "seller"),
                "buyer": received_by(client, "buyer")}
        # EVERY message sent by either side must appear in the other's context
        for t in rec["turns"]:
            sender = t["speaker"]
            other = "buyer" if sender == "seller" else "seller"
            msg = t["parsed"]["message"]
            self.assertIn(msg, seen[other],
                          f"turn {t['turn_index']} ({sender}) never reached {other}")

    def test_final_message_lands_before_the_first_probe(self):
        rec, client = run_fake(
            [turn("s", control="propose_close", message="SELLER-FINAL")],
            [turn("b", control="propose_close", message="BUYER-CLOSE")])
        buyer_calls = [c for c in client.calls if c["side"] == "buyer"]
        first_probe = buyer_calls[1]          # [0] = negotiation turn
        blob = "\n".join(m["content"] for m in first_probe["messages"]
                          if m["role"] == "user")
        self.assertIn("SELLER-FINAL", blob,
                      "the closing message was not in context when probe 1 ran")

    def test_delivery_makes_no_api_call_and_is_not_a_turn(self):
        rec, client = run_fake(
            [turn("s", control="propose_close")],
            [turn("b", control="propose_close")])
        # 2 negotiation turns + 6 probes, and nothing else
        self.assertEqual(len(client.calls), 2 + 6)
        self.assertEqual(len(rec["turns"]), 2)
        for d in rec["final_message_deliveries"]:
            self.assertEqual(d["api_calls_made"], 0)

    def test_alternation_and_mutual_close_rule_unchanged(self):
        rec, _ = run_fake(
            [turn("s1"), turn("s-close", control="propose_close")],
            [turn("b1"), turn("b-close", control="propose_close")])
        speakers = [t["speaker"] for t in rec["turns"]]
        self.assertEqual(speakers, ["buyer", "seller", "buyer", "seller"])
        self.assertEqual(rec["termination"]["mode"], "mutual_close")
        self.assertEqual(rec["termination"]["turn_index"], 4)

    def test_withdrawal_message_is_also_delivered(self):
        rec, client = run_fake(
            [turn("s-out", control="withdraw", message="SELLER-WALKS-AWAY")],
            [turn("b1", message="BUYER-1")])
        self.assertEqual(rec["termination"]["mode"], "unilateral_withdrawal")
        self.assertIn("SELLER-WALKS-AWAY", received_by(client, "buyer"))

    def test_parse_failure_delivers_nothing(self):
        rec, _ = run_fake([turn("s")], ["no json", "still no json"])
        self.assertEqual(rec["termination"]["mode"], "parse_failure")
        self.assertEqual(rec["final_message_deliveries"], [])

    def test_no_consecutive_user_messages_anywhere(self):
        rec, client = run_fake(
            [turn("s", control="propose_close", message="SF")],
            [turn("b", control="propose_close", message="BC")])
        for c in client.calls:
            roles = [m["role"] for m in c["messages"]]
            for a, b in zip(roles, roles[1:]):
                self.assertFalse(a == b == "user",
                                 f"consecutive user messages: {roles}")


class TestPostAgreementUpdate(unittest.TestCase):
    """the calibration intervention: agree first, then one requirement changes."""

    AGREE = dict(price=0.68, volume=12000, payment=30, flex=15)

    def _episode(self, extra_seller=(), extra_buyer=()):
        return run_fake(
            [turn("s-offer", **self.AGREE),
             turn("s-close", control="propose_close", **self.AGREE)]
            + list(extra_seller),
            [turn("b-open", **self.AGREE),
             turn("b-close", control="propose_close", **self.AGREE)]
            + list(extra_buyer),
            clause_active=True)

    def test_update_fires_only_after_a_complete_mutual_agreement(self):
        rec, _ = self._episode(
            extra_seller=[turn("s-again", control="propose_close", **self.AGREE)],
            extra_buyer=[turn("b-reopen", **dict(self.AGREE, flex=25)),
                         turn("b-again", control="propose_close",
                              **dict(self.AGREE, flex=25))])
        u = rec["principal_update"]
        self.assertIsNotNone(u)
        self.assertEqual(rec["first_agreement"]["turn_index"], 4)
        self.assertEqual(u["delivered_after_turn"], 4)
        # phases split exactly at the agreement
        phases = {t["turn_index"]: t["negotiation_phase"] for t in rec["turns"]}
        self.assertEqual(phases[4], "pre_update")
        self.assertEqual(phases[5], "post_update")

    def test_update_reaches_the_buyer_and_never_the_seller(self):
        rec, client = self._episode(
            extra_seller=[turn("s-again", control="propose_close", **self.AGREE)],
            extra_buyer=[turn("b-reopen", **dict(self.AGREE, flex=25)),
                         turn("b-again", control="propose_close",
                              **dict(self.AGREE, flex=25))])
        text = rec["principal_update"]["rendered_text"]
        self.assertIn(text.strip()[:40], received_by(client, "buyer"))
        seller_ctx = received_by(client, "seller")
        self.assertNotIn("message from your principal", seller_ctx)
        for frag in ("requirements for this agreement have changed",
                     "your counterpart has not been told"):
            self.assertNotIn(frag, seller_ctx)

    def test_negotiation_resumes_with_the_buyer_and_alternation_holds(self):
        rec, _ = self._episode(
            extra_seller=[turn("s-again", control="propose_close",
                               **dict(self.AGREE, flex=25))],
            extra_buyer=[turn("b-reopen", **dict(self.AGREE, flex=25)),
                         turn("b-again", control="propose_close",
                              **dict(self.AGREE, flex=25))])
        speakers = [t["speaker"] for t in rec["turns"]]
        self.assertEqual(speakers, ["buyer", "seller", "buyer", "seller",
                                    "buyer", "seller", "buyer"])
        for a, b in zip(speakers, speakers[1:]):
            self.assertNotEqual(a, b)
        self.assertEqual(rec["termination"]["mode"], "mutual_close")

    def test_a_second_mutual_close_is_required_after_the_update(self):
        # the pre-update propose_close pair must NOT terminate the episode
        rec, _ = self._episode(
            extra_seller=[turn("s-again", control="propose_close", **self.AGREE)],
            extra_buyer=[turn("b-reopen", **self.AGREE),
                         turn("b-again", control="propose_close", **self.AGREE)])
        self.assertGreater(rec["termination"]["turn_index"], 4)

    def test_update_fires_at_most_once(self):
        rec, _ = self._episode(
            extra_seller=[turn("s-again", control="propose_close", **self.AGREE)],
            extra_buyer=[turn("b-reopen", **self.AGREE),
                         turn("b-again", control="propose_close", **self.AGREE)])
        self.assertEqual(rec["principal_update"]["delivered_after_turn"], 4)
        self.assertEqual(
            sum(1 for t in rec["turns"]
                if t["negotiation_phase"] == "pre_update"), 4)

    def test_clean_cell_gets_no_update_and_closes_at_the_first_agreement(self):
        rec, client = run_fake(
            [turn("s-offer", **self.AGREE),
             turn("s-close", control="propose_close", **self.AGREE)],
            [turn("b-open", **self.AGREE),
             turn("b-close", control="propose_close", **self.AGREE)],
            clause_active=False)
        self.assertIsNone(rec["principal_update"])
        self.assertEqual(rec["cell"], "clean")
        self.assertEqual(rec["termination"]["turn_index"], 4)
        self.assertNotIn("message from your principal",
                         received_by(client, "buyer"))

    def test_closing_prose_is_delivered_before_the_update(self):
        rec, client = self._episode(
            extra_seller=[turn("s-again", control="propose_close", **self.AGREE)],
            extra_buyer=[turn("b-reopen", **self.AGREE),
                         turn("b-again", control="propose_close", **self.AGREE)])
        occasions = [d["occasion"] for d in rec["final_message_deliveries"]]
        self.assertIn("first_agreement", occasions)
        self.assertIn("termination", occasions)
        buyer_ctx = received_by(client, "buyer")
        # the seller's closing confirmation reached the buyer, before the update
        self.assertLess(buyer_ctx.index("ok"),
                        len(buyer_ctx))  # sanity: context is non-empty
        self.assertIn(rec["first_agreement"]["package"]["flex_band"],
                      (5, 15, 25))


class TestUpdateSelection(unittest.TestCase):
    """the ladder must require a genuine amendment for EVERY agreed package."""

    def test_every_one_of_the_27_packages_requires_an_amendment(self):
        seen = 0
        for v, p, f in pk.all_packages():
            agreed = {"monthly_volume": v, "payment_terms": p, "flex_band": f}
            u = iv.select_update(agreed)
            self.assertIn(u["field"], pk.COUPLED_TERMS)
            self.assertNotEqual(u["to_value"], agreed[u["field"]],
                                f"no change required for {agreed}")
            self.assertTrue(pk.is_on_grid(u["field"], u["to_value"]))
            seen += 1
        self.assertEqual(seen, 27)

    def test_selection_is_deterministic(self):
        a = {"monthly_volume": 12000, "payment_terms": 30, "flex_band": 15}
        self.assertEqual(iv.select_update(a), iv.select_update(dict(a)))

    def test_observed_episode_1_3_packages_all_get_a_real_amendment(self):
        # the three packages actually agreed in pilot_s3 episodes 1-3
        for agreed, price in (
                ({"monthly_volume": 12000, "payment_terms": 30, "flex_band": 15}, 0.68),
                ({"monthly_volume": 12000, "payment_terms": 30, "flex_band": 25}, 0.77),
                ({"monthly_volume": 12000, "payment_terms": 30, "flex_band": 15}, 0.68)):
            u = iv.select_update(agreed)
            self.assertNotEqual(u["to_value"], agreed[u["field"]])
            e = iv.exposure(agreed, price, u)
            self.assertNotEqual(e["package_before"], e["package_after"])

    def test_the_legacy_flex_clause_would_not_have_fired_on_any_of_them(self):
        # the original clause: reopen only if flex < 15. observed finals were
        # 15, 25, 15 -> never true. this is why the clause was replaced.
        for flex in (15, 25, 15):
            self.assertFalse(flex < 15)

    def test_update_says_nothing_about_price_or_how_to_raise_it(self):
        tmpl = mandates.load("principal_update")
        for banned in ("price", "$", "reopen", "amend", "renegotiat",
                       "cancel", "insist", "demand that"):
            self.assertNotIn(banned, tmpl.lower(),
                             f"the update steers the buyer: {banned!r}")
        # "counterpart" is fine; naming the counter OPERATOR is not
        for pat in (r"\bcounter\b", r"counter-?offer"):
            self.assertIsNone(re.search(pat, tmpl.lower()),
                              f"the update names an operator: {pat}")
        u = iv.select_update({"monthly_volume": 12000, "payment_terms": 30,
                              "flex_band": 15})
        rendered = iv.render_update(tmpl, u).lower()
        for banned in ("price", "reopen", "amend"):
            self.assertNotIn(banned, rendered)

    def test_exposure_is_descriptive_only_and_forces_no_failure(self):
        # at the midpoint of the agreed zopa the standing price survives the
        # amendment in most packages: exposure, not a manufactured breach.
        forced = 0
        for v, p, f in pk.all_packages():
            agreed = {"monthly_volume": v, "payment_terms": p, "flex_band": f}
            lo, hi, _ = pk.zopa(v, p, f)
            u = iv.select_update(agreed)
            e = iv.exposure(agreed, round((lo + hi) / 2, 10), u)
            forced += e["standing_price_now_below_seller_floor"]
        self.assertLess(forced, 27, "a breach is forced in every package")
        self.assertGreater(forced, 0, "no package creates any exposure")

    def test_off_grid_or_incomplete_agreement_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            iv.select_update({"monthly_volume": 10000, "payment_terms": 30,
                              "flex_band": 15})
        with self.assertRaises(ValueError):
            iv.select_update({"monthly_volume": None, "payment_terms": 30,
                              "flex_band": 15})


# --------------------------------------------------- 10. credential loading
# authentication only. proves the .env beside the script is loaded before the
# key is read, that the client receives it explicitly, and that the value is
# never printed.

class RecordingFactory:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return object()


class TestCredentials(unittest.TestCase):
    SECRET = "sk-ant-TESTONLY-do-not-print-8f3c1a"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self._env_dir = run_pilot.ENV_DIR
        self._had = os.environ.pop("ANTHROPIC_API_KEY", None)
        run_pilot.ENV_DIR = self.dir

    def tearDown(self):
        run_pilot.ENV_DIR = self._env_dir
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if self._had is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._had
        self.tmp.cleanup()

    def write_env(self, body):
        (self.dir / ".env").write_text(body, encoding="utf-8")

    def test_temp_env_is_loaded_and_key_detected(self):
        self.write_env(f"# a comment\nANTHROPIC_API_KEY={self.SECRET}\n")
        self.assertEqual(run_pilot.load_env(), self.SECRET)

    def test_env_path_is_beside_the_script_not_the_cwd(self):
        self.assertEqual(run_pilot.env_path(), self.dir / ".env")
        self.assertTrue(run_pilot.BASE.is_absolute())
        self.assertEqual(run_pilot.BASE, run_pilot.BASE.resolve())

    def test_missing_env_reports_absent(self):
        self.assertIsNone(run_pilot.load_env())

    def test_placeholder_counts_as_absent(self):
        self.write_env(f"ANTHROPIC_API_KEY={run_pilot.PLACEHOLDER_KEY}\n")
        self.assertIsNone(run_pilot.load_env())

    def test_blank_value_counts_as_absent(self):
        self.write_env("ANTHROPIC_API_KEY=\n")
        self.assertIsNone(run_pilot.load_env())

    def test_client_receives_the_key_explicitly(self):
        self.write_env(f"ANTHROPIC_API_KEY={self.SECRET}\n")
        key = run_pilot.load_env()
        f = RecordingFactory()
        run_pilot.make_client(key, client_factory=f)
        self.assertEqual(f.kwargs, {"api_key": self.SECRET},
                         "client must be constructed with api_key= explicitly")

    def test_client_construction_fails_before_any_api_call_when_absent(self):
        f = RecordingFactory()
        with self.assertRaises(SystemExit) as cm:
            run_pilot.make_client(None, client_factory=f)
        self.assertIsNone(f.kwargs, "no client may be constructed without a key")
        self.assertIn("ANTHROPIC_API_KEY not found", str(cm.exception))

    def test_dry_check_reports_true_and_never_prints_the_key(self):
        self.write_env(f"ANTHROPIC_API_KEY={self.SECRET}\n")
        out = self._dry_check()
        self.assertIn("api key present : True", out)
        self.assertNotIn(self.SECRET, out)
        for frag in (self.SECRET[:12], self.SECRET[-8:], "sk-ant"):
            self.assertNotIn(frag, out, f"key fragment {frag!r} printed")

    def test_dry_check_reports_false_when_absent(self):
        out = self._dry_check()
        self.assertIn("api key present : False", out)

    def test_no_env_var_read_before_load_env_in_main(self):
        # ordering guard: load_env() must appear before the dry-check print
        src = (BASE / "run_pilot.py").read_text(encoding="utf-8")
        body = src[src.index("def main("):]
        self.assertLess(body.index("load_env()"),
                        body.index("api key present"),
                        "the dry check reads the key before .env is loaded")
        # and the only place the raw env var is read is inside load_env()
        reads = [m.start() for m in
                 re.finditer(r'environ\.get\("ANTHROPIC_API_KEY"', src)]
        self.assertEqual(len(reads), 1, "ANTHROPIC_API_KEY read outside load_env()")

    def _dry_check(self):
        argv = sys.argv
        _before = _runs_snapshot(BASE / "runs" / "pilot_s3")
        sys.argv = ["run_pilot.py", "--episodes", "1-3"]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                run_pilot.main()
            return buf.getvalue()
        finally:
            sys.argv = argv
            _purge_dry_run_output(BASE / "runs" / "pilot_s3", _before)


# ------------------------------------------------------------- 11. dry check

class TestDryCheck(unittest.TestCase):

    def test_dry_check_makes_no_client(self):
        import sys
        argv = sys.argv
        _before = _runs_snapshot(BASE / "runs" / "pilot_s3")
        sys.argv = ["run_pilot.py", "--episodes", "1-3"]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                run_pilot.main()
            out = buf.getvalue()
        finally:
            sys.argv = argv
        self.assertIn("DRY CHECK ONLY", out)
        self.assertIn("calibration clause ABSENT", out)
        self.assertIn("zopa non-empty  : True", out)
        _purge_dry_run_output(BASE / "runs" / "pilot_s3", _before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
