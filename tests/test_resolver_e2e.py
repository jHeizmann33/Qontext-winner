"""
test_resolver_e2e.py — end-to-end tests against a synthetic mini-graph.

Builds a tiny in-memory graph with three deterministic clusters:
  1. Two same-type nodes that should clearly merge (high-confidence "same_entity")
  2. A cross-type pair the LLM rejects ("different")
  3. An ambiguous cluster the LLM marks "uncertain"

Mocks the Ollama HTTP call so the test runs offline and deterministically.
Verifies the full pipeline:
  rules detection -> LLM verdict -> risk assessment -> proposal -> action -> graph mutation.
"""

import json
from datetime import datetime
from unittest.mock import patch

import networkx as nx
import pytest

import llm_resolver
from llm_resolver import LLMDecision, llm_resolve_pending


# ---------------------------------------------------------------------------
# Synthetic graph builder — replaces a real ingestion + rules-resolver pass
# ---------------------------------------------------------------------------

def _provenance(source: str) -> list[dict]:
    return [{
        "source_system": source,
        "ingested_at": datetime.utcnow().isoformat(),
        "confidence": 1.0,
    }]


def _add_node(g: nx.MultiDiGraph, nid: str, ntype: str, props: dict, source: str) -> None:
    g.add_node(nid, node_type=ntype, properties=props, provenance=_provenance(source))


def build_test_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.graph["conflicts"] = []

    # --- Cluster 1: same-type Client+Client, will be "same_entity" ---
    _add_node(g, "Client:c1a", "Client", {
        "business_name": "Acme Corp",
        "tax_id": "TAX-001",
        "industry": "Manufacturing",
    }, source="HR")
    _add_node(g, "Client:c1b", "Client", {
        "business_name": "Acme Corporation",
        "tax_id": "TAX-001",
        "industry": "Manufacturing",
    }, source="CRM")
    g.add_edge("Client:c1a", "Client:c1b", key="same_as",
               rel_type="same_as",
               properties={"status": "needs_review", "match_score": 0.55},
               provenance=_provenance("resolver"))
    g.add_edge("Client:c1b", "Client:c1a", key="same_as",
               rel_type="same_as",
               properties={"status": "needs_review", "match_score": 0.55},
               provenance=_provenance("resolver"))

    g.graph["conflicts"].append({
        "conflict_type": "entity_match_review",
        "members": ["Client:c1a", "Client:c1b"],
        "member_types": ["Client", "Client"],
        "member_summaries": [
            {"id": "Client:c1a", "type": "Client",
             "business_name": "Acme Corp", "tax_id": "TAX-001"},
            {"id": "Client:c1b", "type": "Client",
             "business_name": "Acme Corporation", "tax_id": "TAX-001"},
        ],
        "match_score": 0.55,
        "match_reasons": ["Exact normalized business_name (Acme Corp)"],
        "review_reason": "Match confidence below auto-resolve threshold",
        "detected_at": datetime.utcnow().isoformat(),
        "resolution": {"status": "pending_review"},
    })

    # --- Cluster 2: cross-type Client+Vendor, will be "different" ---
    _add_node(g, "Client:c2", "Client", {
        "business_name": "Globex",
        "tax_id": "TAX-EAST",
        "industry": "Logistics",
    }, source="CRM")
    _add_node(g, "Vendor:v2", "Vendor", {
        "business_name": "Globex",
        "tax_id": "TAX-WEST",
        "industry": "Software",
    }, source="VendorList")
    g.add_edge("Client:c2", "Vendor:v2", key="same_as",
               rel_type="same_as",
               properties={"status": "needs_review", "match_score": 0.55},
               provenance=_provenance("resolver"))
    g.add_edge("Vendor:v2", "Client:c2", key="same_as",
               rel_type="same_as",
               properties={"status": "needs_review", "match_score": 0.55},
               provenance=_provenance("resolver"))

    g.graph["conflicts"].append({
        "conflict_type": "entity_match_review",
        "members": ["Client:c2", "Vendor:v2"],
        "member_types": ["Client", "Vendor"],
        "member_summaries": [
            {"id": "Client:c2", "type": "Client", "business_name": "Globex",
             "tax_id": "TAX-EAST", "industry": "Logistics"},
            {"id": "Vendor:v2", "type": "Vendor", "business_name": "Globex",
             "tax_id": "TAX-WEST", "industry": "Software"},
        ],
        "match_score": 0.55,
        "match_reasons": ["Exact normalized business_name (Globex)"],
        "review_reason": "tax_id disagrees: 'TAX-EAST' vs 'TAX-WEST'",
        "detected_at": datetime.utcnow().isoformat(),
        "resolution": {"status": "pending_review"},
    })

    # --- Cluster 3: ambiguous, will be "uncertain" ---
    _add_node(g, "Client:c3a", "Client", {
        "business_name": "Smith Industries",
        "tax_id": "TAX-S1",
        "industry": "Energy",
    }, source="CRM")
    _add_node(g, "Client:c3b", "Client", {
        "business_name": "Smith Industries",
        "tax_id": "TAX-S2",
        "industry": "Construction",
    }, source="CRM")
    _add_node(g, "Vendor:v3", "Vendor", {
        "business_name": "Smith Industries",
        "tax_id": "TAX-S3",
        "industry": "Healthcare",
    }, source="VendorList")
    for a, b in [("Client:c3a","Client:c3b"), ("Client:c3a","Vendor:v3"), ("Client:c3b","Vendor:v3")]:
        for x, y in [(a,b),(b,a)]:
            g.add_edge(x, y, key="same_as", rel_type="same_as",
                       properties={"status":"needs_review","match_score":0.55},
                       provenance=_provenance("resolver"))

    g.graph["conflicts"].append({
        "conflict_type": "entity_match_review",
        "members": ["Client:c3a", "Client:c3b", "Vendor:v3"],
        "member_types": ["Client", "Client", "Vendor"],
        "member_summaries": [
            {"id": "Client:c3a", "type": "Client",
             "business_name": "Smith Industries", "tax_id": "TAX-S1",
             "industry": "Energy"},
            {"id": "Client:c3b", "type": "Client",
             "business_name": "Smith Industries", "tax_id": "TAX-S2",
             "industry": "Construction"},
            {"id": "Vendor:v3", "type": "Vendor",
             "business_name": "Smith Industries", "tax_id": "TAX-S3",
             "industry": "Healthcare"},
        ],
        "match_score": 0.55,
        "match_reasons": ["Exact normalized business_name (Smith Industries)"],
        "review_reason": "tax_id disagrees: 'TAX-S1' vs 'TAX-S2'",
        "detected_at": datetime.utcnow().isoformat(),
        "resolution": {"status": "pending_review"},
    })

    return g


# ---------------------------------------------------------------------------
# Mocked LLM — returns scripted decisions per cluster
# ---------------------------------------------------------------------------

# Map cluster_id (sorted member ids joined by '|') -> scripted LLMDecision
SCRIPTED: dict[str, dict] = {
    "Client:c1a|Client:c1b": {
        "decision": "same_entity",
        "confidence": 0.97,
        "reasoning": "Identical tax_id, near-identical name, same industry.",
        "key_signals": ["tax_id match", "name normalisation", "industry match"],
        "open_questions": [],
    },
    "Client:c2|Vendor:v2": {
        "decision": "different",
        "confidence": 0.92,
        "reasoning": "Distinct industries (Logistics vs Software), unrelated tax_ids.",
        "key_signals": ["industry mismatch", "tax_id mismatch"],
        "open_questions": [],
    },
    "Client:c3a|Client:c3b|Vendor:v3": {
        "decision": "uncertain",
        "confidence": 0.50,
        "reasoning": "Common surname business with three different industries; no decisive signal.",
        "key_signals": ["name match"],
        "open_questions": ["Are there shared contacts?"],
    },
}


def _scripted_resolve(payload, model, ollama_url, prompt_kind="entity_match"):
    """Replacement for resolve_cluster_with_llm — looks up scripted answer."""
    cid = "|".join(sorted(payload["members"][i]["id"] for i in range(len(payload["members"]))))
    spec = SCRIPTED.get(cid)
    if spec is None:
        raise AssertionError(f"No scripted answer for {cid}")
    return LLMDecision(
        decision=spec["decision"],
        confidence=spec["confidence"],
        reasoning=spec["reasoning"],
        key_signals=spec["key_signals"],
        open_questions=spec["open_questions"],
        raw_response=json.dumps(spec),
        model=model,
        elapsed_s=0.01,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def graph_with_mocked_llm(tmp_path):
    g = build_test_graph()
    cache_file = str(tmp_path / "cache.json")
    with patch.object(llm_resolver, "resolve_cluster_with_llm", _scripted_resolve):
        stats = llm_resolve_pending(
            g,
            model="llama3.2:3b",
            ollama_url="http://mocked",
            risk_threshold=5.0,
            cache_file=cache_file,
            verbose=False,
        )
    return g, stats


def test_all_three_clusters_decided(graph_with_mocked_llm):
    g, stats = graph_with_mocked_llm
    assert stats.total_review_clusters == 3
    assert stats.decisions_attempted == 3
    assert stats.decisions_failed == 0


def test_same_entity_same_type_was_merged(graph_with_mocked_llm):
    g, stats = graph_with_mocked_llm
    # One of c1a / c1b should remain (canonical), the other gone
    assert g.has_node("Client:c1a") ^ g.has_node("Client:c1b"), \
        "Exactly one of the same-type cluster members should remain after merge"
    assert stats.autonomous_merges == 1


def test_different_was_removed(graph_with_mocked_llm):
    g, _ = graph_with_mocked_llm
    # The same_as edges between c2 and v2 should be gone
    assert not g.has_edge("Client:c2", "Vendor:v2", key="same_as")
    assert not g.has_edge("Vendor:v2", "Client:c2", key="same_as")
    # The nodes themselves should still exist (different is non-destructive)
    assert g.has_node("Client:c2")
    assert g.has_node("Vendor:v2")


def test_uncertain_left_in_queue(graph_with_mocked_llm):
    g, stats = graph_with_mocked_llm
    # The Smith Industries cluster should still be flagged for human
    smith_conflicts = [
        c for c in g.graph["conflicts"]
        if "Smith Industries" in {
            s.get("business_name") for s in c.get("member_summaries", [])
        }
    ]
    assert smith_conflicts, "Smith conflict should still be present"
    smith = smith_conflicts[0]
    assert smith["resolution"]["status"] == "pending_human_after_llm"
    assert stats.flagged_for_human >= 1


def test_every_conflict_gets_proposal(graph_with_mocked_llm):
    g, _ = graph_with_mocked_llm
    for c in g.graph["conflicts"]:
        if c.get("conflict_type") != "entity_match_review":
            continue
        assert "proposal" in c, f"Missing proposal on {c.get('members')}"
        prop = c["proposal"]
        assert prop["proposed_action"] in (
            "merge_nodes", "upgrade_to_auto_linked",
            "remove_same_as_edges", "no_action", "investigate_further",
        )
        assert prop["summary"]
        assert prop["expected_changes"]


def test_auto_applied_flags_match_decision(graph_with_mocked_llm):
    g, _ = graph_with_mocked_llm
    for c in g.graph["conflicts"]:
        prop = c.get("proposal")
        if not prop:
            continue
        status = c["resolution"]["status"]
        if status == "auto_resolved_by_llm":
            assert prop["auto_applied"] is True
            assert prop["requires_human_confirmation"] is False
            assert prop["kind"] == "post_hoc_audit"
        elif status == "pending_human_after_llm":
            assert prop["auto_applied"] is False
            assert prop["requires_human_confirmation"] is True
            assert prop["kind"] == "pending_confirmation"


def test_audit_trail_logged_per_action(graph_with_mocked_llm):
    g, _ = graph_with_mocked_llm
    actions = g.graph.get("resolver_actions", [])
    # One audit entry per processed conflict (3)
    assert len(actions) == 3
    for a in actions:
        assert a["decided_by"] == "llm"
        assert "risk" in a
        assert a["risk"]["risk_score"] is not None
        assert a["llm_decision"] in ("same_entity", "different", "uncertain")
        assert a["action_taken"] in (
            "merged_same_type", "upgraded_same_as",
            "removed_false_positive_same_as", "escalated_high_risk",
            "escalated_uncertain",
        )


def test_risk_distribution_recorded(graph_with_mocked_llm):
    g, stats = graph_with_mocked_llm
    # We have decisions, so risk percentiles must be populated
    assert stats.risk_score_max >= stats.risk_score_p50
    assert stats.by_recommended.get("auto_act", 0) >= 1
    assert stats.by_recommended.get("escalate", 0) >= 1


def test_apply_proposal_confirm_flow(graph_with_mocked_llm):
    """Confirm a pending proposal via apply_proposal.apply_action()."""
    from apply_proposal import apply_action

    g, _ = graph_with_mocked_llm
    # Find the Smith pending conflict
    smith = next(
        c for c in g.graph["conflicts"]
        if c.get("resolution", {}).get("status") == "pending_human_after_llm"
    )
    prop = smith["proposal"]
    # Confirm the proposed action (no_action for this one)
    result = apply_action(
        graph=g,
        conflict=smith,
        action=prop["proposed_action"],
        decided_by="test",
        reason="confirmed by test",
    )
    assert smith["resolution"]["status"] == "human_resolved"
    assert smith["resolution"]["applied_action"] == prop["proposed_action"]
    assert result["action"] == prop["proposed_action"]


def test_apply_proposal_override_flow(graph_with_mocked_llm):
    """Override a proposal with a different action."""
    from apply_proposal import apply_action

    g, _ = graph_with_mocked_llm
    smith = next(
        c for c in g.graph["conflicts"]
        if c.get("resolution", {}).get("status") == "pending_human_after_llm"
    )
    # Override: instead of no_action, remove the edges
    apply_action(
        graph=g, conflict=smith,
        action="remove_same_as_edges",
        decided_by="test",
        reason="overridden — these are demonstrably different",
    )
    assert smith["resolution"]["applied_action"] == "remove_same_as_edges"
    # Edges between Smith members should now be gone
    assert not g.has_edge("Client:c3a", "Client:c3b", key="same_as")
    assert not g.has_edge("Client:c3b", "Vendor:v3", key="same_as")
