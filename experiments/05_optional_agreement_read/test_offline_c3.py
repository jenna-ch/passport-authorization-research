# test_offline_c3.py — deterministic offline gates for Phase 2 cell C3 (S3-A).
# usage: python test_offline_c3.py        NO API CALLS.
#
# implements the four GO gates in the Phase 2 C1/C3 design of record, section 13.
# (That document is not in this handoff repo; it is preserved in the archival
# backup of the original working tree.)
import json
import pathlib
import re

import agreement
import episode_read
import mandates
import run_c3
import world as w

PASS = 0
BASE = pathlib.Path(__file__).resolve().parent


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"ok: {name}")


PKG_PRE = {"label": "A", "volume_A": 5000, "volume_B": 5000,
           "price_A": 0.94, "price_B": 0.66, "priority_allocation": True}
PKG_POST = {"label": "A", "volume_A": 7000, "volume_B": 5000,
            "price_A": 0.92, "price_B": 0.66, "priority_allocation": False}


def turn(control, pkg=None, msg="here is where we are.", act="proposing"):
    return {"act": act, "control": control,
            "packages": [pkg] if pkg else [],
            "terms_touched": [], "message": msg}


def as_text(obj):
    return obj["message"] + "\n\n```json\n" + json.dumps(obj, indent=2) + "\n```"


TOOL = "TOOL"     # script marker: emit a tool_use block, then continue


class MockClient:
    """scripted replies. an entry ("TOOL", {...}) emits a tool_use block on
    that api call; the NEXT entry answers on the following call, which is how
    the real loop behaves."""

    def __init__(self, scripts):
        self.scripts = scripts
        self.idx = {"seller": 0, "buyer": 0}
        self.calls = {"seller": 0, "buyer": 0}
        self.tools_seen = {"seller": [], "buyer": []}
        self._uid = 0

    class _Resp:
        def __init__(self, blocks):
            self.model = "mock-model"
            self.content = blocks
            self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    def _role(self, system):
        return "buyer" if mandates.BUYER_CANARY in system else "seller"

    @property
    def messages(self):
        outer = self

        class M:
            def create(self, model, system, messages, temperature, max_tokens,
                       tools=None):
                role = outer._role(system)
                outer.calls[role] += 1
                outer.tools_seen[role].append(
                    None if tools is None else [t["name"] for t in tools])
                script = outer.scripts[role]
                e = script[min(outer.idx[role], len(script) - 1)]
                outer.idx[role] += 1
                if isinstance(e, tuple) and e[0] == TOOL:
                    outer._uid += 1
                    blk = type("B", (), {"type": "tool_use",
                                         "id": f"tu_{outer._uid}",
                                         "name": agreement.TOOL_NAME,
                                         "input": e[1]})()
                    return outer._Resp([blk])
                text = e if isinstance(e, str) else as_text(e)
                return outer._Resp(
                    [type("B", (), {"type": "text", "text": text})()])
        return M()


cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
prompts = {n: mandates.load(n) for n in mandates.PROMPT_NAMES}
seller_system = mandates.render_seller_system()
buyer_system = mandates.render_buyer_system()
PROBES = ["probe answer one.", "probe answer two.", "probe answer three."]


def run(seller_script, buyer_script, eid="t_ep01"):
    client = MockClient({"seller": seller_script + PROBES,
                         "buyer": buyer_script + PROBES})
    rec = episode_read.run_episode_read(eid, cfg, prompts, client,
                                        seller_system, buyer_system)
    return rec, client


# clean two-phase close, ZERO tool calls
CLEAN_BUYER = [turn("propose_close", PKG_PRE, "let us close on this."),
               turn("propose_close", PKG_POST, "volume A moves to 7,000.")]
CLEAN_SELLER = [turn("propose_close", PKG_PRE, "agreed, closing."),
                turn("propose_close", PKG_POST, "agreed at the new volume.")]

# =====================================================================
# GATE 2 — an episode can close correctly with ZERO tool calls
# =====================================================================
print("\n--- gate 2: the tool is genuinely optional ---")
rec0, c0 = run(CLEAN_SELLER, CLEAN_BUYER)
check("gate2: episode terminates on a mutual close",
      rec0["termination"]["mode"] == "mutual_close")
check("gate2: zero tool reads", rec0["agreement_record"]["reads_total"] == 0)
check("gate2: the first agreement was still committed as version 1",
      rec0["first_agreement"]["committed_version"] == 1)
check("gate2: the principal update was delivered to the buyer only",
      rec0["principal_update"]["delivered"] is True
      and rec0["principal_update"]["recipient"] == "buyer")
check("gate2: a second version was committed at the second mutual close",
      rec0["agreement_record"]["versions_committed"] == 2)
check("gate2: version 2 carries the updated volume_A",
      rec0["agreement_record"]["versions"][1]["terms"]["volume_A"] == 7000)
check("gate2: version 1 carries the originally agreed volume_A",
      rec0["agreement_record"]["versions"][0]["terms"]["volume_A"] == 5000)
check("gate2: all six post-close probes were asked",
      len(rec0["post_close_probes"]["seller"]) == 3
      and len(rec0["post_close_probes"]["buyer"]) == 3)
check("gate2: eligibility is still a human decision",
      rec0["study3_eligibility"] == "pending_manual_review")
check("gate2: every turn records n_tool_calls = 0",
      all(t["n_tool_calls"] == 0 for t in rec0["turns"]))
check("gate2: the tool was offered on every negotiation call",
      all(x == [agreement.TOOL_NAME] for x in c0.tools_seen["buyer"][:2]))
check("gate2: the tool was withdrawn for the probes",
      c0.tools_seen["buyer"][-3:] == [None, None, None]
      and c0.tools_seen["seller"][-3:] == [None, None, None]
      and rec0["tool_available_during_probes"] is False)

# =====================================================================
# GATE 1 — no agreement state in any system prompt or any turn message
# =====================================================================
print("\n--- gate 1: nothing is injected ---")
STATE_MARKERS = ("agr_t_ep01", "agreement_id", "current_version",
                 "committed_at_turn", "get_agreement", "committed version")
prompt_blob = "\n".join(
    (BASE / "prompts" / f"{n}.txt").read_text(encoding="utf-8")
    for n in mandates.PROMPT_NAMES)
check("gate1: no marker appears in any of the nine prompt files",
      not any(m in prompt_blob for m in STATE_MARKERS))
check("gate1: no marker appears in either rendered system prompt",
      not any(m in seller_system or m in buyer_system for m in STATE_MARKERS))
incoming_blob = "\n".join(str(t["incoming_text"] or "") for t in rec0["turns"])
check("gate1: no marker appears in any turn's incoming text",
      not any(m in incoming_blob for m in STATE_MARKERS))
check("gate1: the buyer's update text mentions only volume_A, not the record",
      not any(m in rec0["principal_update"]["rendered_text"]
              for m in STATE_MARKERS))
probe_blob = "\n".join(p["prompt"] for who in ("seller", "buyer")
                       for p in rec0["post_close_probes"][who])
check("gate1: no marker appears in any probe prompt",
      not any(m in probe_blob for m in STATE_MARKERS))
check("gate1: the tool description lives in the tools parameter, not a prompt",
      agreement.TOOL_SPEC["description"] not in prompt_blob)
check("gate1: the tool description says what it returns, not when to use it",
      not re.search(r"(before|should|use this to|make sure|remember|check)",
                    agreement.TOOL_SPEC["description"], re.I))
check("gate1: no commit notification is delivered to either side",
      all("version" not in str(d.get("delivered_text", ""))
          for d in rec0["final_message_deliveries"]))
check("gate1: the object holds only the five agreed terms",
      set(rec0["agreement_record"]["versions"][0]["terms"])
      == set(w.VARIABLES))
check("gate1: no floor, ceiling or threshold is in the object",
      not any(k in json.dumps(rec0["agreement_record"]["versions"])
              for k in ("floor", "ceiling", "seller_", "buyer_ceiling",
                        "reserve")))

# =====================================================================
# GATE 3 — null before commit, correct versions after, recorded verbatim
# =====================================================================
print("\n--- gate 3: what the read returns, and that it is recorded ---")
st = agreement.AgreementStore("probe_ep")
check("gate3: current returns null before any commit",
      st.read("current") == agreement.NO_AGREEMENT)
check("gate3: history returns null before any commit",
      st.read("history")["agreement"] is None)
check("gate3: version returns null before any commit",
      st.read("version", 1)["agreement"] is None)
st.commit({f: PKG_PRE[f] for f in w.VARIABLES}, 4, "first_agreement")
cur = st.read("current")
check("gate3: current returns version 1 and the committed terms",
      cur["current_version"] == 1
      and cur["terms"]["volume_A"] == 5000
      and cur["committed_at_turn"] == 4)
st.commit({f: PKG_POST[f] for f in w.VARIABLES}, 9, "subsequent_agreement")
hist = st.read("history")
check("gate3: history returns both versions in order",
      [v["version"] for v in hist["versions"]] == [1, 2])
check("gate3: history preserves the superseded version's terms",
      hist["versions"][0]["terms"]["volume_A"] == 5000)
check("gate3: current follows the latest commit",
      st.read("current")["current_version"] == 2)
check("gate3: version 1 is still retrievable specifically",
      st.read("version", 1)["terms"]["volume_A"] == 5000)
check("gate3: an unknown version is an error, not a guess",
      "error" in st.read("version", 9))
check("gate3: view is required to be one of the three",
      "error" in st.read("sideways"))
check("gate3: the store never returns private mandate content",
      not any(k in json.dumps(st.read("history"))
              for k in ("0.88", "0.99", "floor", "ceiling")))
check("gate3: a read never mutates the record",
      len(st.versions) == 2 and st.read("current")["current_version"] == 2)

# a live episode where both sides read: buyer before any commit, seller after
rec3, c3 = run(
    seller_script=[turn("propose_close", PKG_PRE, "agreed, closing."),
                   (TOOL, {"view": "history"}),
                   turn("propose_close", PKG_POST, "agreed at 7,000.")],
    buyer_script=[(TOOL, {"view": "current"}),
                  turn("propose_close", PKG_PRE, "let us close on this."),
                  turn("propose_close", PKG_POST, "volume A moves to 7,000.")])
reads = rec3["agreement_record"]["reads"]
check("gate3: both reads were captured", len(reads) == 2)
check("gate3: the pre-commit read returned null and is flagged",
      reads[0]["caller"] == "buyer" and reads[0]["returned_null"] is True
      and reads[0]["committed_versions_at_call"] == 0)
check("gate3: the post-commit read returned the committed history",
      reads[1]["caller"] == "seller"
      and reads[1]["arguments"] == {"view": "history"}
      and reads[1]["result"]["versions"][0]["terms"]["volume_A"] == 5000)
check("gate3: every read records the calling turn and phase",
      reads[0]["turn_index"] == 1 and reads[0]["negotiation_phase"] == "pre_update"
      and reads[1]["negotiation_phase"] == "post_update")
check("gate3: every read records the tool_use id verbatim",
      all(isinstance(r["tool_use_id"], str) and r["tool_use_id"]
          for r in reads))
check("gate3: reads are attributed per caller",
      rec3["agreement_record"]["reads_by_caller"]
      == {"seller": 1, "buyer": 1})
check("gate3: views requested are recorded",
      rec3["agreement_record"]["views_requested"] == ["current", "history"])
check("gate3: the turn record carries its own tool calls",
      rec3["turns"][0]["n_tool_calls"] == 1
      and rec3["turns"][0]["tool_calls"][0]["arguments"] == {"view": "current"})
check("gate3: reading does not consume a negotiation turn",
      len(rec3["turns"]) == len(rec0["turns"]))
check("gate3: strict alternation is unchanged by reads",
      [t["speaker"] for t in rec3["turns"]]
      == [t["speaker"] for t in rec0["turns"]])
check("gate3: the read cost one extra api call, not one extra turn",
      c3.calls["buyer"] == c0.calls["buyer"] + 1)
check("gate3: the episode still closed on a mutual close",
      rec3["termination"]["mode"] == "mutual_close"
      and rec3["agreement_record"]["versions_committed"] == 2)
check("gate3: reads_returning_null counted",
      rec3["agreement_record"]["reads_returning_null"] == 1)

# =====================================================================
# GATE 4 — world hash, nine prompt hashes, update target, threshold
# =====================================================================
print("\n--- gate 4: S3-N baseline comparison ---")
cmp_ = run_c3.baseline_comparison()
for r in cmp_["rows"]:
    check(f"gate4: {r['item']} == S3-N ({r['here']})", r["ok"])
check("gate4: world hash is 96fea605d7446f37",
      w.world_hash() == "96fea605d7446f37")
check("gate4: all nine prompt hashes present and compared",
      len(mandates.prompt_hashes()) == 9)
check("gate4: the whole comparison passes", cmp_["all_ok"])

print("\n--- recorded labels ---")
check("the arm is labelled a simulated interface",
      rec0["simulated_primitive"]
      == "simulated Passport primitive interfaces based on current design "
         "materials")
src = pathlib.Path("agreement.py").read_text(encoding="utf-8")
check("agreement.py takes no position on agreement semantics",
      "takes no position on agreement SEMANTICS" in src)
check("agreement.py names what it refuses to decide",
      all(k in src for k in ("lapsed", "renegotiated", "still binds")))

print(f"\nall {PASS} checks passed")
