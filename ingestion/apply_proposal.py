"""
apply_proposal.py — Apply (or override) the resolver's proposal for a conflict.

Pairs with proposals.py: every conflict in the LLM-resolved graph carries a
`proposal` block describing the action the resolver recommends. This script
is the "Confirm" or "Override" button in CLI form.

Usage:
    # Approve the resolver's recommendation for conflict #7:
    python apply_proposal.py --graph graph.json --conflict 7 --confirm

    # Override with a different action:
    python apply_proposal.py --graph graph.json --conflict 7 \
                             --action remove_same_as_edges --reason "verified by sales"

    # List all conflicts pending human confirmation:
    python apply_proposal.py --graph graph.json --list-pending
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from graph_utils import load_graph, save_graph  # type: ignore
else:
    from .graph_utils import load_graph, save_graph

import networkx as nx


VALID_ACTIONS = {
    "merge_nodes",
    "upgrade_to_auto_linked",
    "remove_same_as_edges",
    "no_action",
    "investigate_further",
    "mark_alias",
    "mark_shared_mailbox",
    "flag_email_reassignment",
}


# ---------------------------------------------------------------------------
# Graph mutation helpers (mirror those in llm_resolver.py)
# ---------------------------------------------------------------------------

def _node_type(graph: nx.MultiDiGraph, nid: str) -> str:
    if not graph.has_node(nid):
        return "Unknown"
    return graph.nodes[nid].get("node_type", "Unknown")


def _pick_canonical(graph: nx.MultiDiGraph, ids: list[str]) -> str:
    def ts(nid: str) -> str:
        provs = graph.nodes[nid].get("provenance", [])
        return min((p.get("ingested_at", "9999") for p in provs), default="9999")
    return sorted(ids, key=lambda nid: (ts(nid), nid))[0]


def _merge_nodes(graph: nx.MultiDiGraph, canonical: str, alias: str,
                 audit_tag: dict) -> None:
    canon = graph.nodes[canonical]
    aliasn = graph.nodes[alias]
    canon_props = canon.setdefault("properties", {})
    alias_props = aliasn.get("properties", {})
    for k, v in alias_props.items():
        if k not in canon_props or canon_props[k] == v:
            canon_props[k] = v
        else:
            graph.graph.setdefault("conflicts", []).append({
                "conflict_type": "field_after_human_merge",
                "entity_id": canonical,
                "entity_type": _node_type(graph, canonical),
                "field": k,
                "existing_value": canon_props[k],
                "merged_value": v,
                "merged_from": alias,
                "decided_by": "human",
                "audit_tag": audit_tag,
                "detected_at": datetime.utcnow().isoformat(),
                "resolution": {"status": "pending_review"},
            })
    canon.setdefault("provenance", []).extend(aliasn.get("provenance", []))
    canon.setdefault("provenance", []).append({
        "source_system": "human_apply_proposal",
        "operation": "merged_in",
        "merged_alias": alias,
        "ingested_at": datetime.utcnow().isoformat(),
        "audit_tag": audit_tag,
    })
    for src, _, key, data in list(graph.in_edges(alias, data=True, keys=True)):
        if src != canonical:
            graph.add_edge(src, canonical, key=key, **data)
    for _, dst, key, data in list(graph.out_edges(alias, data=True, keys=True)):
        if dst != canonical:
            graph.add_edge(canonical, dst, key=key, **data)
    graph.remove_node(alias)


def _remove_same_as_edges(graph: nx.MultiDiGraph, ids: list[str]) -> int:
    removed = 0
    for i in range(len(ids)):
        for j in range(len(ids)):
            if i == j:
                continue
            a, b = ids[i], ids[j]
            if graph.has_edge(a, b, key="same_as"):
                graph.remove_edge(a, b, key="same_as")
                removed += 1
    return removed


def _upgrade_same_as_edges(graph: nx.MultiDiGraph, ids: list[str],
                            new_status: str) -> int:
    upgraded = 0
    for i in range(len(ids)):
        for j in range(len(ids)):
            if i == j:
                continue
            a, b = ids[i], ids[j]
            if graph.has_edge(a, b, key="same_as"):
                edge = graph[a][b]["same_as"]
                edge.setdefault("properties", {})["status"] = new_status
                upgraded += 1
    return upgraded


# ---------------------------------------------------------------------------
# Apply a proposal (or override)
# ---------------------------------------------------------------------------

def apply_action(
    graph: nx.MultiDiGraph,
    conflict: dict,
    action: str,
    decided_by: str,
    reason: str,
) -> dict[str, Any]:
    """Execute one of VALID_ACTIONS on the cluster's members. Returns a result dict."""
    member_ids = conflict.get("members", [])
    audit_tag = {
        "decided_by": decided_by,
        "applied_action": action,
        "applied_at": datetime.utcnow().isoformat(),
        "reason": reason,
        "members": member_ids,
        "based_on_proposal": conflict.get("proposal"),
    }
    result = {"action": action, "applied_at": audit_tag["applied_at"]}

    if action == "merge_nodes":
        if len(member_ids) < 2:
            raise ValueError("merge_nodes needs >= 2 members")
        canon = _pick_canonical(graph, member_ids)
        merged = 0
        for alias in member_ids:
            if alias == canon or not graph.has_node(alias):
                continue
            _merge_nodes(graph, canon, alias, {**audit_tag, "canonical": canon})
            merged += 1
        result.update({"canonical": canon, "merged_count": merged})

    elif action == "upgrade_to_auto_linked":
        n = _upgrade_same_as_edges(graph, member_ids, new_status="auto_linked")
        result["edges_upgraded"] = n

    elif action == "remove_same_as_edges":
        n = _remove_same_as_edges(graph, member_ids)
        result["edges_removed"] = n

    elif action == "no_action":
        result["note"] = "Cluster left as-is; same_as edges retained as needs_review."

    elif action == "investigate_further":
        # Mark the conflict for follow-up — no graph mutation
        conflict.setdefault("follow_up", []).append(audit_tag)
        result["note"] = "Marked for follow-up investigation."

    elif action == "mark_alias":
        entity_id = conflict.get("entity_id") or (member_ids[0] if member_ids else None)
        if entity_id and graph.has_node(entity_id):
            props = graph.nodes[entity_id].setdefault("properties", {})
            existing = list(props.get("aliases", []) or [])
            for nm in conflict.get("signature_variants", {}).keys():
                if nm not in existing:
                    existing.append(nm)
            props["aliases"] = existing
            result["aliases_added"] = list(conflict.get("signature_variants", {}).keys())

    elif action == "mark_shared_mailbox":
        entity_id = conflict.get("entity_id") or (member_ids[0] if member_ids else None)
        if entity_id and graph.has_node(entity_id):
            graph.nodes[entity_id].setdefault("properties", {})["is_shared_mailbox"] = True
            result["marked"] = entity_id

    elif action == "flag_email_reassignment":
        entity_id = conflict.get("entity_id") or (member_ids[0] if member_ids else None)
        if entity_id:
            sender_emp_id = entity_id.split(":", 1)[1] if ":" in entity_id else entity_id
            variants = conflict.get("signature_variants", {})
            top_signer = max(variants.items(), key=lambda kv: kv[1])[0] if variants else None
            flagged = 0
            for nid, data in graph.nodes(data=True):
                if data.get("node_type") != "Email":
                    continue
                p = data.get("properties", {}) or {}
                if p.get("sender_emp_id") == sender_emp_id and p.get("_signature_mismatch"):
                    p["_sender_assignment_disputed"] = True
                    if top_signer:
                        p["_suggested_actual_sender"] = top_signer
                    flagged += 1
            result["emails_flagged"] = flagged
            result["suggested_signer"] = top_signer

    else:
        raise ValueError(f"Unknown action {action!r}")

    # Update conflict status
    conflict["resolution"] = {
        "status": "human_resolved",
        "decided_by": decided_by,
        "applied_action": action,
        "applied_at": audit_tag["applied_at"],
        "reason": reason,
    }
    graph.graph.setdefault("resolver_actions", []).append({
        **audit_tag,
        "result": result,
    })
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def list_pending(graph: nx.MultiDiGraph) -> int:
    conflicts = graph.graph.get("conflicts", [])
    pending = [(i, c) for i, c in enumerate(conflicts)
               if c.get("proposal", {}).get("requires_human_confirmation")]
    if not pending:
        print("No conflicts pending human confirmation.")
        return 0
    print(f"{len(pending)} conflict(s) pending human confirmation:\n")
    for i, c in pending:
        prop = c.get("proposal", {})
        print(f"  #{i:>4}  {prop.get('summary')}")
        print(f"         risk={prop.get('risk_score')} threshold={prop.get('risk_threshold')}")
        print(f"         proposed_action: {prop.get('proposed_action')}")
        print(f"         alternatives: {[a['action'] for a in prop.get('alternatives', [])]}")
        print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply or override the resolver's proposal for a conflict.")
    parser.add_argument("--graph", required=True,
                        help="Path to graph.json (output of llm_resolver.py)")
    parser.add_argument("--output", default=None,
                        help="Where to save the updated graph (default: in-place)")
    parser.add_argument("--list-pending", action="store_true",
                        help="List all conflicts awaiting human confirmation, then exit")
    parser.add_argument("--conflict", type=int, default=None,
                        help="Index of the conflict to act on")
    parser.add_argument("--confirm", action="store_true",
                        help="Apply the proposed_action as-is (the 'Confirm' button)")
    parser.add_argument("--action", default=None, choices=sorted(VALID_ACTIONS),
                        help="Override: apply this action instead of the proposal")
    parser.add_argument("--reason", default="",
                        help="Free-text reason recorded in the audit trail")
    parser.add_argument("--decided-by", default="cli_user",
                        help="Identifier of the deciding human (default: cli_user)")
    args = parser.parse_args()

    graph = load_graph(args.graph)

    if args.list_pending:
        return list_pending(graph)

    if args.conflict is None:
        parser.error("Specify --conflict <index> (or use --list-pending)")

    conflicts = graph.graph.get("conflicts", [])
    if args.conflict < 0 or args.conflict >= len(conflicts):
        parser.error(f"Conflict index {args.conflict} out of range (0..{len(conflicts)-1})")

    conflict = conflicts[args.conflict]
    proposal = conflict.get("proposal")
    if proposal is None:
        parser.error(f"Conflict #{args.conflict} has no proposal block; run llm_resolver.py first.")
    if conflict.get("resolution", {}).get("status") in ("auto_resolved_by_llm", "human_resolved"):
        print(f"Note: conflict #{args.conflict} already in status "
              f"`{conflict['resolution']['status']}`. Re-applying anyway.")

    if args.action:
        chosen = args.action
        decided_via = "override"
    elif args.confirm:
        chosen = proposal["proposed_action"]
        decided_via = "confirm_proposal"
    else:
        parser.error("Pass either --confirm or --action <name>")

    print(f"Conflict #{args.conflict}: {proposal.get('summary')}")
    print(f"  Proposed action: {proposal.get('proposed_action')}")
    print(f"  Chosen action:   {chosen} ({decided_via})")
    if args.reason:
        print(f"  Reason: {args.reason}")
    print()

    result = apply_action(graph, conflict,
                           action=chosen,
                           decided_by=args.decided_by,
                           reason=args.reason or f"{decided_via} via CLI")
    print("Result:", json.dumps(result, indent=2, default=str))

    out_path = args.output or args.graph
    save_graph(graph, out_path)
    print(f"\nGraph saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
