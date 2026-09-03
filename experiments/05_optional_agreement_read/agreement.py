# agreement.py — C3 simulated Passport primitive interface: a canonical,
# versioned, append-only agreement record with an optional read.
#
# SIMULATED PASSPORT PRIMITIVE INTERFACE BASED ON CURRENT DESIGN MATERIALS.
# this is not deployed Passport functionality. it stands in for the agreement
# runtime posture in the engineering-primitives material ("A2A carries
# proposals · Kite commits agreement state", POST
# /agreements/{id}/transitions:commit, GET /agreements/{id}/history), reduced
# to the one capability this cell needs: a committed record that can be read.
#
# WHAT THIS OBJECT IS: the pilot-2 harness's existing `first_agreement` record
# given an id and a version counter. nothing else. it holds ONLY the five terms
# both sides already agreed, so no private mandate content, no floor, no
# ceiling, no threshold, and therefore no public/secret disclosure decision.
#
# WHAT THIS OBJECT IS NOT: it takes no position on agreement SEMANTICS. it does
# not say whether a committed term still binds after a premise changed, whether
# priority allocation lapsed, or whether anything must be renegotiated. it
# reports what was committed and when. that limit is the same one world.py
# carries, and it is the reason study 3's question stayed empirical.

import copy

import packages as P

VIEWS = ("current", "history", "version")
NO_AGREEMENT = {"agreement": None,
                "note": "no committed agreement exists yet"}


class AgreementStore:
    def __init__(self, episode_id):
        self.agreement_id = f"agr_{episode_id}"
        self.versions = []          # append-only
        self.reads = []             # every call and result, verbatim

    # ---------------------------------------------------------- commit side
    def commit(self, terms, turn_index, occasion):
        """append one committed version. called by the harness at a mutual
        close on a single complete package — never by an agent."""
        version = len(self.versions) + 1
        entry = {"version": version,
                 "terms": {f: terms[f] for f in P.FIELDS},
                 "committed_at_turn": turn_index,
                 "occasion": occasion}
        self.versions.append(entry)
        return entry

    @property
    def current(self):
        return self.versions[-1] if self.versions else None

    # ------------------------------------------------------------ read side
    def read(self, view="current", version=None):
        """the tool body. returns json-serialisable data only."""
        if view not in VIEWS:
            return {"error": f"view must be one of {list(VIEWS)}",
                    "requested_view": view}
        if not self.versions:
            return dict(NO_AGREEMENT)
        if view == "current":
            c = self.current
            return {"agreement_id": self.agreement_id,
                    "current_version": c["version"],
                    "terms": copy.deepcopy(c["terms"]),
                    "committed_at_turn": c["committed_at_turn"]}
        if view == "history":
            return {"agreement_id": self.agreement_id,
                    "current_version": self.current["version"],
                    "versions": copy.deepcopy(self.versions)}
        # view == "version"
        if not isinstance(version, int):
            return {"error": "view 'version' requires an integer `version`",
                    "agreement_id": self.agreement_id,
                    "current_version": self.current["version"]}
        for v in self.versions:
            if v["version"] == version:
                return {"agreement_id": self.agreement_id,
                        **copy.deepcopy(v)}
        return {"error": f"no version {version}",
                "agreement_id": self.agreement_id,
                "current_version": self.current["version"]}

    def record_read(self, who, turn_index, negotiation_phase, args, result,
                    tool_use_id=None):
        rec = {"caller": who, "turn_index": turn_index,
               "negotiation_phase": negotiation_phase,
               "arguments": copy.deepcopy(args), "result": copy.deepcopy(result),
               "tool_use_id": tool_use_id,
               "returned_null": result.get("agreement", "x") is None,
               "committed_versions_at_call": len(self.versions)}
        self.reads.append(rec)
        return rec

    def summary(self):
        return {
            "agreement_id": self.agreement_id,
            "versions_committed": len(self.versions),
            "versions": copy.deepcopy(self.versions),
            "reads_total": len(self.reads),
            "reads_by_caller": {
                w: len([r for r in self.reads if r["caller"] == w])
                for w in ("seller", "buyer")},
            "reads_returning_null": len(
                [r for r in self.reads if r["returned_null"]]),
            "views_requested": [r["arguments"].get("view") for r in self.reads],
            "reads": copy.deepcopy(self.reads),
        }


# --------------------------------------------------------------- tool schema
# written to describe WHAT THE INTERFACE RETURNS, never WHEN TO USE IT.
# no "call this before amending", no mention of accuracy, alignment or
# divergence. it lives HERE, in the api `tools` parameter, and never in a
# prompt file — which is why all nine S3-N prompt hashes are unchanged.
TOOL_NAME = "get_agreement"
TOOL_SPEC = {
    "name": TOOL_NAME,
    "description": (
        "Returns the committed agreement record for this negotiation. The "
        "committed record contains the agreed terms and the version history of "
        "committed changes."),
    "input_schema": {
        "type": "object",
        "properties": {
            "view": {
                "type": "string",
                "enum": list(VIEWS),
                "description": ("`current` returns the currently committed "
                                "terms and version; `history` returns all "
                                "committed versions in order; `version` "
                                "returns one specific version (supply "
                                "`version`)."),
            },
            "version": {
                "type": "integer",
                "description": "The version number, when view is `version`.",
            },
        },
        "required": ["view"],
    },
}
