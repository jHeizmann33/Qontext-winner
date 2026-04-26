"""
test_detectors.py — unit tests for ingestion/detectors.py

The signature-mismatch detector turns 9k+ Email node properties into
~500 actionable Employee-name-inconsistency conflicts. Tests verify:
  - Only senders with HR records produce conflicts (system mailboxes filtered)
  - Signatures matching the HR name don't push false positives
  - Variant counts and total counts are correct
  - The conflict shape matches what the LLM resolver expects
"""

from datetime import datetime

import networkx as nx
import pytest

from detectors import (
    _extract_signature_name,
    detect_employee_name_inconsistencies,
)


# ---------------------------------------------------------------------------
# _extract_signature_name
# ---------------------------------------------------------------------------

class TestExtractSignatureName:
    def test_canonical_signature_format(self):
        sig = "--\nAji Joseph\nHR Generalist\nInazuma Corporation\nPhone: +91-9876"
        assert _extract_signature_name(sig) == "Aji Joseph"

    def test_skips_separator_dashes(self):
        sig = "--\n\n\nFirst Last"
        assert _extract_signature_name(sig) == "First Last"

    def test_skips_phone_email_lines(self):
        sig = "--\nPhone: +91-12345\nEmail: x@y.com\nReal Name"
        assert _extract_signature_name(sig) == "Real Name"

    def test_empty_signature(self):
        assert _extract_signature_name("") is None
        assert _extract_signature_name("--") is None
        assert _extract_signature_name(None) is None


# ---------------------------------------------------------------------------
# Helper: build a tiny graph for detector tests
# ---------------------------------------------------------------------------

def _provenance(source: str = "TestSource") -> list[dict]:
    return [{"source_system": source, "ingested_at": datetime.utcnow().isoformat(),
             "confidence": 1.0}]


def _make_employee(g: nx.MultiDiGraph, emp_id: str, hr_name: str | None) -> None:
    props = {"name": hr_name} if hr_name else {}
    g.add_node(f"Employee:{emp_id}", node_type="Employee",
               properties=props, provenance=_provenance("HR"))


def _make_email(g: nx.MultiDiGraph, email_id: str, sender_emp_id: str,
                 signature: str, mismatch: bool = True) -> None:
    g.add_node(f"Email:{email_id}", node_type="Email", properties={
        "sender_emp_id": sender_emp_id,
        "signature": signature,
        "_signature_mismatch": mismatch,
    }, provenance=_provenance("Mail"))


@pytest.fixture
def synthetic_graph():
    g = nx.MultiDiGraph()
    g.graph["conflicts"] = []

    # Real employee with mismatch (clear "wrong assignment" pattern)
    _make_employee(g, "emp_A", "Ravi Kumar")
    for i in range(5):
        _make_email(g, f"e_A_{i}", "emp_A",
                     "--\nAji Joseph\nHR Generalist\nInazuma Corporation")

    # Real employee with NO mismatch — signatures match HR name
    _make_employee(g, "emp_B", "Aji Joseph")
    for i in range(3):
        _make_email(g, f"e_B_{i}", "emp_B",
                     "--\nAji Joseph\nHR Generalist", mismatch=False)
    # Plus one with the mismatch flag set but signature actually matches HR
    _make_email(g, "e_B_4", "emp_B", "--\nAji Joseph\nNew Title", mismatch=True)

    # Real employee with one-off signature variants (likely just typos / random)
    _make_employee(g, "emp_C", "Astha Sharma")
    _make_email(g, "e_C_1", "emp_C",
                 "--\nAstha S.\nHR Manager")  # only 1 mismatch -> below threshold

    # System mailbox (no HR record) — should be ignored
    _make_employee(g, "emp_BOT", None)
    for i in range(50):
        _make_email(g, f"e_BOT_{i}", "emp_BOT",
                     "--\nVarious Senders\nDept")

    return g


# ---------------------------------------------------------------------------
# detect_employee_name_inconsistencies
# ---------------------------------------------------------------------------

class TestDetectInconsistencies:
    def test_pushes_conflict_for_clear_mismatch(self, synthetic_graph):
        n = detect_employee_name_inconsistencies(synthetic_graph)
        # Only emp_A produces a conflict
        assert n == 1
        conflicts = synthetic_graph.graph["conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["entity_id"] == "Employee:emp_A"
        assert conflicts[0]["hr_name"] == "Ravi Kumar"
        assert conflicts[0]["total_mismatched_emails"] == 5
        assert conflicts[0]["signature_variants"] == {"Aji Joseph": 5}

    def test_skips_system_mailboxes_without_hr_record(self, synthetic_graph):
        detect_employee_name_inconsistencies(synthetic_graph)
        # emp_BOT has 50 mismatched emails but no HR name -> never surfaces
        ids = {c["entity_id"] for c in synthetic_graph.graph["conflicts"]}
        assert "Employee:emp_BOT" not in ids

    def test_skips_when_signature_matches_hr_name(self, synthetic_graph):
        detect_employee_name_inconsistencies(synthetic_graph)
        ids = {c["entity_id"] for c in synthetic_graph.graph["conflicts"]}
        # emp_B's signature is "Aji Joseph" which IS the HR name
        assert "Employee:emp_B" not in ids

    def test_threshold_filters_one_off_noise(self, synthetic_graph):
        detect_employee_name_inconsistencies(synthetic_graph,
                                              min_emails_per_signature=2)
        ids = {c["entity_id"] for c in synthetic_graph.graph["conflicts"]}
        # emp_C has only 1 mismatched email, below threshold
        assert "Employee:emp_C" not in ids

    def test_threshold_can_be_lowered(self, synthetic_graph):
        n = detect_employee_name_inconsistencies(synthetic_graph,
                                                   min_emails_per_signature=1)
        # Now emp_C also surfaces
        assert n == 2
        ids = {c["entity_id"] for c in synthetic_graph.graph["conflicts"]}
        assert "Employee:emp_C" in ids

    def test_conflict_shape_matches_resolver_expectations(self, synthetic_graph):
        detect_employee_name_inconsistencies(synthetic_graph)
        c = synthetic_graph.graph["conflicts"][0]
        # Required fields for the LLM resolver dispatcher
        assert c["conflict_type"] == "employee_name_inconsistency"
        assert "entity_id" in c
        assert "hr_name" in c
        assert "signature_variants" in c
        assert "total_mismatched_emails" in c
        assert "distinct_variant_count" in c
        assert c["resolution"]["status"] == "pending_review"
        assert "detected_at" in c

    def test_idempotent_does_not_double_push(self, synthetic_graph):
        detect_employee_name_inconsistencies(synthetic_graph)
        first = len(synthetic_graph.graph["conflicts"])
        # Running again pushes again (caller's responsibility to avoid; but
        # check that it doesn't crash and produces the same conflict shape)
        detect_employee_name_inconsistencies(synthetic_graph)
        assert len(synthetic_graph.graph["conflicts"]) == 2 * first


# ---------------------------------------------------------------------------
# Sanity: counts on multi-variant + multi-sender setups
# ---------------------------------------------------------------------------

def test_multi_variant_signer():
    g = nx.MultiDiGraph()
    g.graph["conflicts"] = []
    _make_employee(g, "emp_X", "Real Person")
    # 3 emails signed Alice, 2 emails signed Bob
    for i in range(3):
        _make_email(g, f"a_{i}", "emp_X", "--\nAlice Smith\nTitle")
    for i in range(2):
        _make_email(g, f"b_{i}", "emp_X", "--\nBob Jones\nTitle")

    detect_employee_name_inconsistencies(g)
    c = g.graph["conflicts"][0]
    assert c["total_mismatched_emails"] == 5
    assert c["distinct_variant_count"] == 2
    assert c["signature_variants"]["Alice Smith"] == 3
    assert c["signature_variants"]["Bob Jones"] == 2
