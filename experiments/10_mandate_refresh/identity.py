# identity.py — the PRE-UPDATE IDENTITY fingerprint.
#
# Nothing about an arm exists before the principal update fires. This module
# makes that testable rather than asserted: it reduces an episode record to
# everything that is observable up to and including the moment the update is
# delivered, and the offline gate replays all 12 frozen Study 3 pilot-2 worlds
# in all three arms and requires the fingerprints to be equal.
#
# Any post-update field is deliberately absent. If a field could differ by arm
# BEFORE the update, either the design is wrong or this fingerprint is
# incomplete, and the gate is the place that fails.

import hashlib
import json

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "frozen"))

import agents as frozen_agents
import agents_p3d2 as AP
import mandate as M

PRE = "pre_update"


def _h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()[:16]


def pre_update_fingerprint(out, prompt_set):
    """everything observable before the update, as one comparable dict."""
    pre = [t for t in out["turns"] if t["negotiation_phase"] == PRE]
    agr = out.get("agreement_at_update")

    transcript = [{"turn_index": t["turn_index"], "speaker": t["speaker"],
                   "incoming_text": t["incoming_text"],
                   "raw_model_text": t["raw_model_text"],
                   "control": (t["parsed"] or {}).get("control"),
                   "packages": (t["parsed"] or {}).get("packages"),
                   "state_block_rendered": t["state_block_rendered"]}
                  for t in pre]

    # what the PROVIDER (counterparty) ever saw, pre-update
    provider_visible = [t["incoming_text"] for t in pre
                        if t["speaker"] == "seller" and t["incoming_text"]]
    provider_declarations = [a["package"] for t in pre
                             if t["speaker"] == "seller"
                             for a in (t.get("alternatives") or [])]

    return {
        "transcript_hash": _h(transcript),
        "n_pre_update_turns": len(pre),
        "model_visible_prompts": {
            "seller_system": _h(prompt_set["seller_system"]),
            "buyer_system": _h(prompt_set["buyer_system"]),
            "buyer_opening": _h(prompt_set["buyer_opening"]),
            "reprompt": _h(prompt_set["reprompt"]),
        },
        "state_blocks_rendered_pre_update": sum(
            1 for t in pre if t["state_block_rendered"]),
        "agreement_package": (agr or {}).get("package"),
        "agreement_version": (agr or {}).get("agreement_version"),
        "agreement_hash": (agr or {}).get("agreement_hash"),
        "agreement_formed_at_turn": (agr or {}).get("formed_at_turn"),
        "mandate_version_in_force": M.V1,
        "mandate_v1_ceiling_on_the_agreement": (
            None if not agr else M.ceiling_A(M.V1, agr["package"])),
        "spec_minimum_in_force": [t["spec_minimum_in_force"] for t in pre][:1],
        "provider_visible_transcript_hash": _h(provider_visible),
        "provider_declarations_hash": _h(provider_declarations),
        "action_space_seller": list(frozen_agents.CONTROL_VALUES),
        "action_space_buyer": list(AP.CONTROL_VALUES_P3D2),
        # the control plane's VERSION STATE at the first turn. the arm LABEL
        # is stripped: it is the name of the condition, not a behavioural
        # difference, and every arm must start at v1/v1 with no refresh
        # pending.
        "control_plane_version_state_at_first_turn": [
            {k: v for k, v in t["control_plane"].items() if k != "arm"}
            for t in pre][:1],
        "world_hash": out["world_hash"],
    }


def equality_row(world_name, fps):
    """one row of the 12-world equality table. `fps` maps arm -> fingerprint."""
    arms = sorted(fps)
    ref = fps[arms[0]]
    fields = ["transcript_hash", "model_visible_prompts", "agreement_package",
              "agreement_version", "agreement_hash",
              "mandate_version_in_force", "provider_declarations_hash",
              "provider_visible_transcript_hash", "n_pre_update_turns",
              "action_space_buyer", "action_space_seller",
              "control_plane_version_state_at_first_turn",
              "state_blocks_rendered_pre_update", "spec_minimum_in_force",
              "mandate_v1_ceiling_on_the_agreement", "world_hash",
              "agreement_formed_at_turn"]
    per_field = {f: len({_h(fps[a][f]) for a in arms}) == 1 for f in fields}
    return {
        "world": world_name,
        "agreement_package": ref["agreement_package"],
        "agreement_version": ref["agreement_version"],
        "agreement_hash": ref["agreement_hash"],
        "turns": ref["n_pre_update_turns"],
        "v1_ceiling": ref["mandate_v1_ceiling_on_the_agreement"],
        "state_blocks_pre_update": {a: fps[a]["state_blocks_rendered_pre_update"]
                                    for a in arms},
        "per_field_equal": per_field,
        "all_equal": all(per_field.values()) and len(
            {_h(fps[a]) for a in arms}) == 1,
    }
