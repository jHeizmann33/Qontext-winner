"""
detectors.py — Post-ingestion conflict detectors that don't fit the
pair-matching pattern of resolver.py.

Where resolver.py asks "do these two records refer to the same entity?",
detectors here ask "is this single entity's data internally consistent across
the sources that touched it?". Output is the same conflict_type pattern in
graph.conflicts so the LLM resolver and proposals layer can handle them
identically downstream.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import networkx as nx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_signature_name(signature: str) -> str | None:
    """Pull the first non-empty, non-separator line from an email signature.
    Most signatures follow `--\\nFirst Last\\nTitle\\n...`."""
    if not signature:
        return None
    for line in signature.split("\n"):
        s = line.strip()
        if not s or s == "--":
            continue
        # Skip lines that look like a contact line (Phone:, Email:, etc.)
        if any(s.lower().startswith(prefix) for prefix in
               ("phone:", "email:", "tel:", "mobile:", "fax:")):
            continue
        return s
    return None


# ---------------------------------------------------------------------------
# Detector: Employee name inconsistency from email signatures
# ---------------------------------------------------------------------------

def detect_employee_name_inconsistencies(graph: nx.MultiDiGraph,
                                          min_emails_per_signature: int = 2,
                                          verbose: bool = False) -> int:
    """For every Employee node that has a HR-canonical name, look at all
    emails sent under their `sender_emp_id`. If the dominant signature name(s)
    don't match the HR name, push an `employee_name_inconsistency` conflict
    so the LLM resolver can decide:

        - "alias"               — same person, just signs differently
        - "shared_mailbox"      — emp_id is a shared mailbox, multiple people
        - "wrong_assignment"    — sender_emp_id is wrong; the signed person is real
        - "uncertain"           — needs human

    Returns the number of conflicts pushed.
    """
    # Build emp_id -> HR name lookup (only Employees with a HR-canonical name)
    hr_names: dict[str, str] = {}
    for nid, data in graph.nodes(data=True):
        if data.get("node_type") != "Employee":
            continue
        nm = (data.get("properties", {}) or {}).get("name")
        if nm:
            emp_id = nid.split(":", 1)[1] if ":" in nid else nid
            hr_names[emp_id] = nm

    # Group mismatched emails by sender_emp_id
    sender_signatures: dict[str, list[dict]] = defaultdict(list)
    for nid, data in graph.nodes(data=True):
        if data.get("node_type") != "Email":
            continue
        props = data.get("properties", {}) or {}
        if not props.get("_signature_mismatch"):
            continue
        sender_id = props.get("sender_emp_id")
        signature = props.get("signature", "")
        if not sender_id or not signature:
            continue
        sender_signatures[sender_id].append({
            "email_id": nid,
            "signature": signature,
            "signed_name": _extract_signature_name(signature),
        })

    pushed = 0
    for sender_id, emails in sender_signatures.items():
        # Only act on senders that exist in HR — otherwise it's a system mailbox
        # we can't diagnose against any canonical name.
        hr_name = hr_names.get(sender_id)
        if not hr_name:
            continue

        # Count distinct signed names (excluding the HR name itself)
        signed_name_counts: Counter[str] = Counter()
        for e in emails:
            sn = (e["signed_name"] or "").strip()
            if sn:
                signed_name_counts[sn] += 1

        # Filter out signatures that exactly match HR name
        foreign_signatures = Counter({
            n: c for n, c in signed_name_counts.items()
            if n.lower() != hr_name.lower()
        })

        if not foreign_signatures:
            continue

        # If only one foreign signature with too few emails, skip noise
        total_foreign = sum(foreign_signatures.values())
        if total_foreign < min_emails_per_signature:
            continue

        # Build the conflict
        conflict = {
            "conflict_type": "employee_name_inconsistency",
            "entity_id": f"Employee:{sender_id}",
            "entity_type": "Employee",
            "hr_name": hr_name,
            "signature_variants": dict(foreign_signatures.most_common(20)),
            "total_mismatched_emails": total_foreign,
            "distinct_variant_count": len(foreign_signatures),
            "sample_email_ids": [e["email_id"] for e in emails[:5]],
            "detected_at": datetime.utcnow().isoformat(),
            "resolution": {"status": "pending_review"},
        }
        graph.graph.setdefault("conflicts", []).append(conflict)
        pushed += 1

        if verbose and pushed <= 5:
            top = list(foreign_signatures.most_common(3))
            print(f"  [{pushed}] Employee:{sender_id} (HR='{hr_name}') "
                  f"-> {total_foreign} mismatched emails, top variants: {top}")

    if verbose:
        print(f"  Employee-name-inconsistency conflicts pushed: {pushed}")
    return pushed


# ---------------------------------------------------------------------------
# Public entry point — runs all detectors on the graph
# ---------------------------------------------------------------------------

def detect_all(graph: nx.MultiDiGraph, verbose: bool = False) -> dict[str, int]:
    """Run every detector. Modifies graph.conflicts in place. Returns counts."""
    counts: dict[str, int] = {}
    if verbose:
        print("=" * 60)
        print("Running post-ingestion conflict detectors")
        print("=" * 60)
    counts["employee_name_inconsistency"] = detect_employee_name_inconsistencies(
        graph, verbose=verbose
    )
    if verbose:
        total = sum(counts.values())
        print(f"  Total conflicts pushed: {total}")
        print()
    return counts
