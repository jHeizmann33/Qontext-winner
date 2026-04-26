"""
test_risk.py — unit tests for ingestion/risk.py

Covers the cost matrix, the modifier rules, and the auto/escalate decision
boundary across realistic inputs the LLM resolver actually feeds in.
"""

import pytest

from risk import ACTION_COSTS, assess_risk, derive_action


# ---------------------------------------------------------------------------
# derive_action: maps (decision, same_type) -> concrete action
# ---------------------------------------------------------------------------

class TestDeriveAction:
    def test_different_always_removes_edges(self):
        assert derive_action("different", same_type=True) == "remove_same_as_edges"
        assert derive_action("different", same_type=False) == "remove_same_as_edges"

    def test_same_entity_same_type_merges(self):
        assert derive_action("same_entity", same_type=True) == "merge_nodes"

    def test_same_entity_cross_type_upgrades(self):
        assert derive_action("same_entity", same_type=False) == "upgrade_to_auto_linked"

    def test_uncertain_is_no_action(self):
        assert derive_action("uncertain", same_type=True) == "no_action"
        assert derive_action("uncertain", same_type=False) == "no_action"


# ---------------------------------------------------------------------------
# Cost matrix sanity
# ---------------------------------------------------------------------------

class TestCostMatrix:
    def test_merge_is_most_expensive(self):
        # The destructive action should cost more than reversible ones.
        assert ACTION_COSTS["merge_nodes"].base_cost > ACTION_COSTS["upgrade_to_auto_linked"].base_cost
        assert ACTION_COSTS["upgrade_to_auto_linked"].base_cost > ACTION_COSTS["remove_same_as_edges"].base_cost

    def test_no_action_costs_nothing(self):
        assert ACTION_COSTS["no_action"].base_cost == 0

    def test_reversibility_labels(self):
        assert ACTION_COSTS["remove_same_as_edges"].reversibility == "trivial"
        assert ACTION_COSTS["upgrade_to_auto_linked"].reversibility == "medium"
        assert ACTION_COSTS["merge_nodes"].reversibility == "hard"


# ---------------------------------------------------------------------------
# assess_risk: confidence × cost interactions
# ---------------------------------------------------------------------------

class TestAssessRisk:
    def test_high_confidence_different_auto_acts(self):
        # different at 0.92 conf, no modifiers → risk = 0.08 * 15 = 1.2 < 5
        r = assess_risk(decision="different", confidence=0.92, same_type=False)
        assert r.recommended == "auto_act"
        assert r.action == "remove_same_as_edges"
        assert r.risk_score < r.risk_threshold

    def test_low_confidence_destructive_escalates(self):
        # merge_nodes at 0.85 conf, no modifiers → risk = 0.15 * 90 = 13.5 > 5
        r = assess_risk(decision="same_entity", confidence=0.85, same_type=True)
        assert r.recommended == "escalate"
        assert r.action == "merge_nodes"
        assert r.risk_score >= r.risk_threshold

    def test_uncertain_always_escalates(self):
        # uncertain → no_action → no autonomous action ever
        r = assess_risk(decision="uncertain", confidence=0.99, same_type=True)
        assert r.recommended == "escalate"
        assert r.action == "no_action"

    def test_perfect_confidence_low_cost_action_still_low_risk(self):
        r = assess_risk(decision="different", confidence=1.0, same_type=False)
        assert r.risk_score == 0.0
        assert r.recommended == "auto_act"

    def test_zero_confidence_max_risk(self):
        r = assess_risk(decision="different", confidence=0.0, same_type=False)
        assert r.error_probability == 1.0
        # 1.0 * 15 = 15, > threshold 5 → escalate
        assert r.recommended == "escalate"


class TestRiskModifiers:
    def test_large_cluster_increases_cost(self):
        small = assess_risk("same_entity", 0.95, same_type=False, cluster_size=2)
        big = assess_risk("same_entity", 0.95, same_type=False, cluster_size=6)
        assert big.final_cost > small.final_cost
        # Modifier reason should be present
        reasons = [r for r, _ in big.cost_modifiers]
        assert any("Cluster" in r and "members" in r for r in reasons)

    def test_identifier_conflict_modifier_only_for_same_entity(self):
        # Modifier kicks in for same_entity (LLM overriding the disagreement)
        with_id_conflict = assess_risk(
            "same_entity", 0.95, same_type=False, has_identifier_conflict=True
        )
        without = assess_risk(
            "same_entity", 0.95, same_type=False, has_identifier_conflict=False
        )
        assert with_id_conflict.final_cost > without.final_cost
        # NOT for `different` — because different agrees with identifier conflict
        diff_with = assess_risk(
            "different", 0.95, same_type=False, has_identifier_conflict=True
        )
        diff_without = assess_risk(
            "different", 0.95, same_type=False, has_identifier_conflict=False
        )
        assert diff_with.final_cost == diff_without.final_cost

    def test_small_model_modifier(self):
        big_model = assess_risk("different", 0.95, same_type=False, model="qwen2.5:7b")
        small_model = assess_risk("different", 0.95, same_type=False, model="llama3.2:3b")
        assert small_model.final_cost > big_model.final_cost
        reasons = [r for r, _ in small_model.cost_modifiers]
        assert any("Small LLM" in r for r in reasons)

    def test_uncertain_modifier_doubles_cost(self):
        # uncertain → action is no_action so cost is 0; modifier doesn't matter
        # but the modifier should still appear in metadata for the audit trail
        r = assess_risk("uncertain", 0.4, same_type=True)
        reasons = [r for r, _ in r.cost_modifiers]
        assert any("uncertain" in r.lower() for r in reasons)


class TestThresholdBehaviour:
    def test_strict_threshold_blocks_more(self):
        # Same input, two thresholds: strict one escalates more
        loose = assess_risk(
            "same_entity", 0.95, same_type=False,
            has_identifier_conflict=True, model="llama3.2:3b",
            risk_threshold=10.0,
        )
        strict = assess_risk(
            "same_entity", 0.95, same_type=False,
            has_identifier_conflict=True, model="llama3.2:3b",
            risk_threshold=1.0,
        )
        assert loose.recommended == "auto_act"
        assert strict.recommended == "escalate"

    def test_rationale_mentions_threshold(self):
        r = assess_risk("different", 0.92, same_type=False, risk_threshold=5.0)
        assert "5.0" in r.rationale or "threshold" in r.rationale


# ---------------------------------------------------------------------------
# Real-world cases from the B&M run — regression guard
# ---------------------------------------------------------------------------

class TestObservedCases:
    """Lock in specific real-world risk scores so future tweaks are intentional."""

    def test_typical_different_decision(self):
        # most common case in the B&M run: different, conf=0.92
        r = assess_risk("different", 0.92, same_type=False, model="llama3.2:3b")
        assert r.recommended == "auto_act"
        assert r.risk_score < 2.0

    def test_parrish_gomez_pattern(self):
        # cross-type same_entity at 0.98 with id-conflict + small-model modifiers
        # expected risk ≈ 0.02 * 40 * 1.6 * 1.25 = 1.6
        r = assess_risk(
            "same_entity", 0.98, same_type=False,
            has_identifier_conflict=True, model="llama3.2:3b",
        )
        assert r.recommended == "auto_act"
        assert 1.0 < r.risk_score < 2.5

    def test_strict_threshold_catches_parrish_gomez(self):
        # If a user tightens to risk_threshold=1.0, Parrish/Gomez should escalate
        r = assess_risk(
            "same_entity", 0.98, same_type=False,
            has_identifier_conflict=True, model="llama3.2:3b",
            risk_threshold=1.0,
        )
        assert r.recommended == "escalate"

    def test_johnson_uncertain_cluster(self):
        # 6-member uncertain cluster
        r = assess_risk("uncertain", 0.52, same_type=False, cluster_size=6)
        assert r.recommended == "escalate"
        assert r.action == "no_action"


@pytest.mark.parametrize("decision,confidence,same_type,expected", [
    ("different", 0.92, True, "auto_act"),
    ("different", 0.92, False, "auto_act"),
    ("different", 0.5, False, "escalate"),       # 0.5*15=7.5 > 5
    ("same_entity", 0.99, False, "auto_act"),    # 0.01*40=0.4 < 5
    ("same_entity", 0.99, True, "auto_act"),     # 0.01*90=0.9 < 5  (merge OK at very high conf)
    ("same_entity", 0.90, True, "escalate"),     # 0.10*90=9.0 > 5  (merge needs > ~0.944 conf)
    ("uncertain", 0.99, True, "escalate"),       # uncertain -> no_action -> always escalate
    ("uncertain", 0.1, False, "escalate"),
])
def test_decision_boundary_table(decision, confidence, same_type, expected):
    r = assess_risk(decision, confidence, same_type)
    assert r.recommended == expected, (
        f"{decision} conf={confidence} same_type={same_type}: "
        f"got {r.recommended} (risk={r.risk_score}), expected {expected}"
    )
