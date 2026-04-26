"""
proposals.py — Confirmable action proposals for the human-in-the-loop queue.

Every conflict the resolver touches gets a `proposal` block. For conflicts
that were resolved autonomously (low risk), the proposal is a post-hoc
audit record explaining what was done and why. For conflicts that escalated
(high risk or the LLM was uncertain), the proposal is a *pre-action*
recommendation: "I think you should do X — confirm to apply."

This means a human reviewer never has to figure out *what* to do — they
only ever have to **confirm or override** a concrete suggestion. The UI
contract is: render `proposal.summary`, show `proposal.alternatives` as
overrides, and POST to `/conflicts/{i}/confirm` to apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Action vocabulary the human reviewer can pick from
# ---------------------------------------------------------------------------

# What each action concretely means; rendered in the UI.
ACTION_DESCRIPTIONS: dict[str, str] = {
    "merge_nodes": (
        "Merge into a single canonical node — properties combined, edges "
        "rewired, alias node deleted. DESTRUCTIVE; hard to reverse."
    ),
    "upgrade_to_auto_linked": (
        "Confirm these are the same real-world entity in two roles — keep "
        "both nodes, mark the same_as edge as auto_linked."
    ),
    "remove_same_as_edges": (
        "Mark as a false positive — drop the same_as edges between members. "
        "Records remain as separate entities."
    ),
    "no_action": (
        "Leave records as separate entities (status quo). The same_as edges "
        "(if any) stay marked as needs_review for a future pass."
    ),
    "investigate_further": (
        "Defer the decision; flag this cluster for follow-up data gathering "
        "(e.g. check email signatures, contact records, external registry)."
    ),
    "mark_alias": (
        "Record the foreign signature names as `aliases` on the Employee "
        "node — same person, just signs differently. Easily reversible."
    ),
    "mark_shared_mailbox": (
        "Set `is_shared_mailbox=True` on the Employee node — emp_id is a "
        "team mailbox, not an individual. Downstream queries should treat "
        "it accordingly."
    ),
    "flag_email_reassignment": (
        "Mark the affected emails as `_sender_assignment_disputed=True` "
        "with a suggested actual sender. Does NOT rewire sent_email edges; "
        "a follow-up step / human applies the correction."
    ),
}


def _alternatives_for(action: str, same_type: bool,
                       conflict_kind: str = "entity_match") -> list[str]:
    """Return the other actions a human reviewer can pick instead.

    `conflict_kind` switches the action menu between entity-match conflicts
    and employee-name conflicts so the reviewer doesn't get nonsense options.
    """
    if conflict_kind == "employee_name":
        base = ["mark_alias", "mark_shared_mailbox",
                "flag_email_reassignment", "no_action", "investigate_further"]
    else:
        base = ["merge_nodes", "upgrade_to_auto_linked",
                "remove_same_as_edges", "no_action", "investigate_further"]
        if not same_type and "merge_nodes" in base:
            base.remove("merge_nodes")
        if same_type and "upgrade_to_auto_linked" in base:
            base.remove("upgrade_to_auto_linked")
    return [a for a in base if a != action]


# ---------------------------------------------------------------------------
# Proposal data structure
# ---------------------------------------------------------------------------

@dataclass
class Proposal:
    kind: str                              # "post_hoc_audit" | "pending_confirmation"
    proposed_action: str                   # one of ACTION_DESCRIPTIONS
    summary: str                           # one-line, UI-ready
    rationale: str                         # 1-3 sentences, why this action
    auto_applied: bool                     # True if already executed
    requires_human_confirmation: bool      # True if pending in review queue
    confidence_label: str                  # "high" | "medium" | "low"
    alternatives: list[dict[str, str]] = field(default_factory=list)
    expected_changes: list[str] = field(default_factory=list)
    risk_score: Optional[float] = None
    risk_threshold: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "proposed_action": self.proposed_action,
            "summary": self.summary,
            "rationale": self.rationale,
            "auto_applied": self.auto_applied,
            "requires_human_confirmation": self.requires_human_confirmation,
            "confidence_label": self.confidence_label,
            "alternatives": self.alternatives,
            "expected_changes": self.expected_changes,
            "risk_score": self.risk_score,
            "risk_threshold": self.risk_threshold,
        }


# ---------------------------------------------------------------------------
# Helpers — describe the action in concrete terms for the cluster at hand
# ---------------------------------------------------------------------------

def _describe_changes(action: str, member_ids: list[str], same_type: bool,
                       canonical: Optional[str] = None,
                       conflict: Optional[dict[str, Any]] = None) -> list[str]:
    """Render concrete bullet points: what would happen if approved."""
    n_members = len(member_ids)
    if action == "mark_alias":
        variants = (conflict or {}).get("signature_variants", {})
        names = list(variants.keys())[:5]
        return [
            f"Add `aliases` property to {member_ids[0] if member_ids else '?'}",
            f"Aliases to add: {', '.join(repr(n) for n in names)}",
            "No edges modified; no nodes destroyed.",
        ]
    if action == "mark_shared_mailbox":
        return [
            f"Set `is_shared_mailbox=True` on {member_ids[0] if member_ids else '?'}",
            "Downstream queries will treat this emp_id as a team mailbox.",
            "No edges modified; no nodes destroyed.",
        ]
    if action == "flag_email_reassignment":
        n = (conflict or {}).get("total_mismatched_emails", "?")
        variants = (conflict or {}).get("signature_variants", {})
        top = max(variants.items(), key=lambda kv: kv[1])[0] if variants else "?"
        return [
            f"Mark all {n} signature-mismatched emails sent under "
            f"{member_ids[0] if member_ids else '?'} as `_sender_assignment_disputed=True`",
            f"Suggest actual sender: {top!r}",
            "Does NOT actually rewire sent_email edges (too risky autonomous).",
            "Follow-up step (human or batch job) applies the correction.",
        ]
    if action == "merge_nodes":
        canon = canonical or (sorted(member_ids)[0] if member_ids else "?")
        aliases = [m for m in member_ids if m != canon]
        return [
            f"Keep `{canon}` as canonical node",
            f"Move properties + edges from {len(aliases)} alias node(s) into the canonical",
            f"Delete alias node(s): {', '.join(f'`{a}`' for a in aliases)}",
            "Append merged_in provenance to canonical so the merge is auditable",
        ]
    if action == "upgrade_to_auto_linked":
        n_pairs = n_members * (n_members - 1)
        return [
            f"Update {n_pairs} same_as edge(s) between the {n_members} members",
            "Set status from `needs_review` to `auto_linked`",
            "Both nodes stay distinct (cross-type — different entity kinds)",
        ]
    if action == "remove_same_as_edges":
        n_pairs = n_members * (n_members - 1)
        return [
            f"Delete {n_pairs} same_as edge(s) between the {n_members} members",
            "Records remain in graph as fully independent entities",
            "Conflict marked resolved as false-positive",
        ]
    if action == "no_action":
        return [
            "Keep same_as edges as `needs_review` (no graph mutation)",
            "Conflict stays in human queue for later inspection",
        ]
    if action == "investigate_further":
        return [
            "Mark conflict for follow-up; don't change graph state",
            "Suggested next step: check additional data sources (email "
            "signatures, contact records, external registry)",
        ]
    return ["No concrete changes defined for this action."]


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _short_summary(action: str, decision: str, n_members: int,
                    headline_name: Optional[str]) -> str:
    name = f"`{headline_name}`" if headline_name else f"{n_members}-member cluster"
    if action == "merge_nodes":
        return f"Merge {name} (LLM: same entity)"
    if action == "upgrade_to_auto_linked":
        return f"Confirm cross-type link for {name} (LLM: same entity, distinct roles)"
    if action == "remove_same_as_edges":
        return f"Reject match for {name} as false positive (LLM: different)"
    if action == "no_action":
        if decision == "uncertain":
            return f"Keep {name} separate (LLM was uncertain — conservative default)"
        return f"Keep {name} as-is for now"
    if action == "investigate_further":
        return f"Defer {name} for further investigation"
    if action == "mark_alias":
        return f"Mark {name} as alias (LLM: same person, different signing name)"
    if action == "mark_shared_mailbox":
        return f"Mark {name} as shared mailbox (LLM: multiple people send through this emp_id)"
    if action == "flag_email_reassignment":
        return f"Flag emails under {name} for re-attribution (LLM: wrong sender_emp_id)"
    return f"Review {name}"


def _headline_name(conflict: dict[str, Any]) -> Optional[str]:
    summaries = conflict.get("member_summaries", [])
    if not summaries:
        return None
    name_counts: dict[str, int] = {}
    for s in summaries:
        nm = s.get("business_name") or s.get("name")
        if nm:
            name_counts[nm] = name_counts.get(nm, 0) + 1
    if not name_counts:
        return None
    # Most common name in the cluster
    return max(name_counts.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_proposal(
    conflict: dict[str, Any],
    decision: str,
    confidence: float,
    same_type: bool,
    risk_dict: dict[str, Any],
    auto_applied: bool,
    canonical: Optional[str] = None,
) -> Proposal:
    """Build a confirmable proposal for one conflict.

    `auto_applied=True` means the resolver already executed it (low-risk
    autonomous action) and this proposal is a post-hoc audit. `False` means
    the conflict is pending in the human queue and the proposal is what we
    recommend the reviewer click "Confirm" on.
    """
    ctype = conflict.get("conflict_type", "entity_match_review")
    if ctype == "employee_name_inconsistency":
        member_ids = [conflict.get("entity_id")] if conflict.get("entity_id") else []
        headline = conflict.get("hr_name") or conflict.get("entity_id")
        conflict_kind = "employee_name"
    else:
        member_ids = conflict.get("members", [])
        headline = _headline_name(conflict)
        conflict_kind = "entity_match"
    risk_action = risk_dict.get("action", "no_action")

    # For "uncertain" decisions, the safe default is no_action.
    # For confident-but-too-risky decisions, propose what the LLM would do
    # but require human confirmation.
    if decision == "uncertain":
        proposed_action = "no_action"
    else:
        proposed_action = risk_action if risk_action != "no_action" else "no_action"

    if auto_applied:
        kind = "post_hoc_audit"
        summary = (
            f"Resolved autonomously: "
            + _short_summary(proposed_action, decision, len(member_ids), headline)
        )
        rationale = (
            f"Acted automatically because risk_score={risk_dict.get('risk_score')} "
            f"< threshold={risk_dict.get('risk_threshold')}. "
            f"{risk_dict.get('rationale', '')}"
        )
        requires_confirm = False
    else:
        kind = "pending_confirmation"
        summary = _short_summary(proposed_action, decision, len(member_ids), headline)
        if decision == "uncertain":
            rationale = (
                "LLM could not decide between same_entity / different given the "
                "evidence available. The conservative default is to keep records "
                "separate; override below if you have additional context."
            )
        else:
            rationale = (
                f"LLM thinks `{decision}` (confidence={confidence:.2f}), but the "
                f"risk score for the matching action ({proposed_action}) is "
                f"{risk_dict.get('risk_score')}, above the autonomous-action "
                f"threshold of {risk_dict.get('risk_threshold')}. Confirm to "
                f"apply, or pick an alternative."
            )
        requires_confirm = True

    expected_changes = _describe_changes(proposed_action, member_ids,
                                          same_type, canonical, conflict)
    alternatives = [
        {"action": a, "description": ACTION_DESCRIPTIONS.get(a, a)}
        for a in _alternatives_for(proposed_action, same_type, conflict_kind)
    ]

    return Proposal(
        kind=kind,
        proposed_action=proposed_action,
        summary=summary,
        rationale=rationale,
        auto_applied=auto_applied,
        requires_human_confirmation=requires_confirm,
        confidence_label=_confidence_label(confidence),
        alternatives=alternatives,
        expected_changes=expected_changes,
        risk_score=risk_dict.get("risk_score"),
        risk_threshold=risk_dict.get("risk_threshold"),
    )
