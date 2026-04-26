"""
test_proposals.py — unit tests for ingestion/proposals.py

The proposal layer is what the human-in-the-loop UI consumes; we want to
guarantee:
  - every supported action has a description
  - alternatives never include the action that's already proposed
  - same-type vs cross-type clusters get the right alternatives
  - auto-applied vs pending-confirmation proposals carry the right flags
  - expected_changes are concrete and member-count-aware
"""

import pytest

from proposals import (
    ACTION_DESCRIPTIONS,
    Proposal,
    build_proposal,
)


# ---------------------------------------------------------------------------
# Static contract checks
# ---------------------------------------------------------------------------

class TestActionVocabulary:
    REQUIRED_ACTIONS = {
        # entity_match_review actions
        "merge_nodes",
        "upgrade_to_auto_linked",
        "remove_same_as_edges",
        "no_action",
        "investigate_further",
        # employee_name_inconsistency actions
        "mark_alias",
        "mark_shared_mailbox",
        "flag_email_reassignment",
    }

    def test_all_required_actions_have_descriptions(self):
        for action in self.REQUIRED_ACTIONS:
            assert action in ACTION_DESCRIPTIONS
            assert ACTION_DESCRIPTIONS[action]
            assert len(ACTION_DESCRIPTIONS[action]) > 20  # non-trivial copy

    def test_no_extra_actions(self):
        # Catch silent additions that the rest of the system doesn't know about
        assert set(ACTION_DESCRIPTIONS.keys()) == self.REQUIRED_ACTIONS


# ---------------------------------------------------------------------------
# Helper: build a fake risk_dict matching what risk.assess_risk produces
# ---------------------------------------------------------------------------

def _risk_dict(action: str, risk_score: float = 1.5,
               threshold: float = 5.0,
               recommended: str = "auto_act") -> dict:
    return {
        "decision": "different",
        "confidence": 0.92,
        "action": action,
        "reversibility": "trivial",
        "base_cost": 15,
        "cost_modifiers": [],
        "final_cost": 18.75,
        "error_probability": 0.08,
        "risk_score": risk_score,
        "risk_threshold": threshold,
        "recommended": recommended,
        "rationale": "test fixture",
    }


def _conflict(member_ids, names=None):
    summaries = []
    if names:
        for nid, nm in zip(member_ids, names):
            summaries.append({
                "id": nid,
                "type": nid.split(":")[0],
                "business_name": nm,
            })
    return {
        "members": list(member_ids),
        "member_summaries": summaries,
        "match_score": 0.55,
    }


# ---------------------------------------------------------------------------
# Auto-applied (post-hoc) proposals
# ---------------------------------------------------------------------------

class TestAutoAppliedProposals:
    def test_post_hoc_audit_kind(self):
        c = _conflict(["Client:a", "Vendor:v_1"], names=["Acme", "Acme Corp"])
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=False,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=True,
        )
        assert p.kind == "post_hoc_audit"
        assert p.auto_applied is True
        assert p.requires_human_confirmation is False

    def test_summary_indicates_already_done(self):
        c = _conflict(["Client:a", "Vendor:v_1"], names=["Acme", "Acme"])
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=False,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=True,
        )
        assert "autonom" in p.summary.lower() or "resolved" in p.summary.lower()

    def test_alternatives_still_present_for_post_hoc_override(self):
        # Even auto-applied proposals expose alternatives in case a reviewer
        # disagrees retroactively and wants to undo + pick something else.
        c = _conflict(["Client:a", "Vendor:v_1"], names=["Acme", "Acme"])
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=False,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=True,
        )
        assert len(p.alternatives) > 0


# ---------------------------------------------------------------------------
# Pending (escalated) proposals
# ---------------------------------------------------------------------------

class TestPendingProposals:
    def test_uncertain_proposes_no_action(self):
        c = _conflict(
            ["Client:a", "Client:b", "Vendor:v"],
            names=["Johnson Group", "Johnson PLC", "Johnson Corp"],
        )
        p = build_proposal(
            conflict=c, decision="uncertain", confidence=0.52, same_type=False,
            risk_dict=_risk_dict("no_action", risk_score=0.0, recommended="escalate"),
            auto_applied=False,
        )
        assert p.kind == "pending_confirmation"
        assert p.proposed_action == "no_action"
        assert p.requires_human_confirmation is True
        assert "uncertain" in p.rationale.lower() or "conservative" in p.rationale.lower()

    def test_high_confidence_but_high_risk_still_proposes_action(self):
        # LLM was confident but risk threshold bumped it out → still propose
        # the LLM action, just require human confirmation
        c = _conflict(["Client:a", "Client:b"], names=["Acme", "Acme"])
        p = build_proposal(
            conflict=c, decision="same_entity", confidence=0.92, same_type=True,
            risk_dict=_risk_dict("merge_nodes", risk_score=12.0,
                                  recommended="escalate"),
            auto_applied=False,
        )
        assert p.proposed_action == "merge_nodes"
        assert p.requires_human_confirmation is True
        assert p.confidence_label == "high"


# ---------------------------------------------------------------------------
# Alternatives logic
# ---------------------------------------------------------------------------

class TestAlternatives:
    def test_proposed_action_not_in_alternatives(self):
        c = _conflict(["Client:a", "Vendor:v"], names=["X", "X"])
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=False,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=False,
        )
        alt_actions = [a["action"] for a in p.alternatives]
        assert "remove_same_as_edges" not in alt_actions

    def test_cross_type_excludes_merge(self):
        # Cross-type Client+Vendor cannot be merged per architecture decision D001
        c = _conflict(["Client:a", "Vendor:v"], names=["X", "X"])
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=False,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=False,
        )
        alt_actions = [a["action"] for a in p.alternatives]
        assert "merge_nodes" not in alt_actions

    def test_same_type_offers_merge(self):
        c = _conflict(["Client:a", "Client:b"], names=["X", "X"])
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=True,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=False,
        )
        alt_actions = [a["action"] for a in p.alternatives]
        assert "merge_nodes" in alt_actions
        # And the upgrade path doesn't apply for same-type
        assert "upgrade_to_auto_linked" not in alt_actions


# ---------------------------------------------------------------------------
# Expected-changes content
# ---------------------------------------------------------------------------

class TestExpectedChanges:
    def test_remove_edges_mentions_member_count(self):
        c = _conflict(
            ["Client:a", "Vendor:v_1", "Vendor:v_2"],
            names=["X", "Y", "Z"],
        )
        p = build_proposal(
            conflict=c, decision="different", confidence=0.92, same_type=False,
            risk_dict=_risk_dict("remove_same_as_edges"),
            auto_applied=True,
        )
        joined = " ".join(p.expected_changes)
        # 3 members → 6 directed edges (3*2)
        assert "6" in joined or "3" in joined

    def test_no_action_explains_status_quo(self):
        c = _conflict(["Client:a", "Vendor:v"], names=["X", "Y"])
        p = build_proposal(
            conflict=c, decision="uncertain", confidence=0.5, same_type=False,
            risk_dict=_risk_dict("no_action", risk_score=0.0,
                                  recommended="escalate"),
            auto_applied=False,
        )
        joined = " ".join(p.expected_changes).lower()
        assert "needs_review" in joined or "no graph" in joined or "status quo" in joined or "queue" in joined

    def test_merge_lists_destructive_steps(self):
        c = _conflict(["Client:a", "Client:b", "Client:c"],
                      names=["X", "X", "X"])
        p = build_proposal(
            conflict=c, decision="same_entity", confidence=0.95, same_type=True,
            risk_dict=_risk_dict("merge_nodes", risk_score=12.0,
                                  recommended="escalate"),
            auto_applied=False,
            canonical="Client:a",
        )
        joined = " ".join(p.expected_changes).lower()
        assert "canonical" in joined
        assert "delete" in joined or "alias" in joined


# ---------------------------------------------------------------------------
# Confidence labels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("confidence,expected_label", [
    (0.99, "high"),
    (0.85, "high"),
    (0.84, "medium"),
    (0.6, "medium"),
    (0.59, "low"),
    (0.5, "low"),
    (0.0, "low"),
])
def test_confidence_labels(confidence, expected_label):
    c = _conflict(["Client:a", "Vendor:v"], names=["X", "X"])
    p = build_proposal(
        conflict=c, decision="different", confidence=confidence, same_type=False,
        risk_dict=_risk_dict("remove_same_as_edges"),
        auto_applied=True,
    )
    assert p.confidence_label == expected_label


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

def test_as_dict_is_json_serialisable():
    import json
    c = _conflict(["Client:a", "Vendor:v"], names=["Acme", "Acme"])
    p = build_proposal(
        conflict=c, decision="different", confidence=0.92, same_type=False,
        risk_dict=_risk_dict("remove_same_as_edges"),
        auto_applied=True,
    )
    payload = p.as_dict()
    # Should serialise without TypeError
    s = json.dumps(payload)
    # And round-trip back
    back = json.loads(s)
    assert back["proposed_action"] == "remove_same_as_edges"
    assert back["alternatives"]
