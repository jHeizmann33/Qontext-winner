"""
resolver.py — Cross-source entity resolution for the Qontext knowledge graph.

Runs AFTER all source ingesters. The standard `add_node()` in graph_utils.py
only catches conflicts when the *same* node_id is added twice. This module
catches the harder case: two records with *different* node_ids that refer to
the same real-world entity.

    Example: Client:3a578a8e-... (UUID from clients.json)
             Vendor:CLNT-0286    (short code from vendors.json)
             Both are "Hickman Ltd" — same business, different roles.

Decision per cluster (respects DECISIONS.md D001 — keep entity types distinct):

    - Same-type pair (Client+Client, Vendor+Vendor)
        - high confidence  -> MERGE (combine properties, append provenance,
                              rewire edges, drop the non-canonical node)
        - medium           -> SAME_AS edge + flag for review
        - low              -> ignore

    - Cross-type pair (Client+Vendor)
        - high confidence  -> SAME_AS edge (never merge across types)
        - medium           -> SAME_AS edge + flag for review
        - low              -> ignore

All review-flagged clusters land in `graph.graph["conflicts"]` with
`conflict_type = "entity_match_review"` for the human-review queue.

Usage as a library:
    from resolver import resolve_entities
    stats = resolve_entities(graph, rule_name="business_orgs")

Usage standalone:
    python resolver.py --graph graph.json --output graph_resolved.json
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

# Allow running this file directly (python resolver.py) and also as a module
# (from .resolver import ...). Both work.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from graph_utils import (  # type: ignore
        load_graph,
        save_graph,
        make_provenance,
    )
    from normalize import (  # type: ignore
        extract_zip,
        normalize_address,
        normalize_business_name,
        normalize_email,
        normalize_phone,
        similarity,
    )
else:
    from .graph_utils import load_graph, save_graph, make_provenance
    from .normalize import (
        extract_zip,
        normalize_address,
        normalize_business_name,
        normalize_email,
        normalize_phone,
        similarity,
    )

import networkx as nx


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

AUTO_MERGE_THRESHOLD = 0.85   # same-type, only above this we silently merge
LINK_THRESHOLD = 0.50          # below this we ignore (no signal)
HIGH_CONFIDENCE_LINK = 0.75    # cross-type same_as edges added without review

# Identifier fields where a *conflict* is a strong negative signal (different
# values mean these are probably NOT the same entity).
IDENTIFIER_FIELDS = {"tax_id"}


# ---------------------------------------------------------------------------
# Resolver rules — declarative configuration per resolve pass
# ---------------------------------------------------------------------------

@dataclass
class ResolverRule:
    """Configuration for one resolve pass.

    Multiple rules can be applied to the same graph. Each rule defines:
      - which entity types are in scope
      - which fields contribute matching signals (and how)
      - how to block records to avoid O(n^2) on large graphs
    """
    name: str
    types: list[str]                                  # e.g. ["Client", "Vendor"]
    blocking_field: str = "business_name"
    blocking_normalize: str = "business_name"
    blocking_prefix_len: int = 4


BUSINESS_ORG_RULE = ResolverRule(
    name="business_orgs",
    types=["Client", "Vendor"],
    blocking_field="business_name",
    blocking_normalize="business_name",
    blocking_prefix_len=4,
)


# ---------------------------------------------------------------------------
# Match strategies
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    score: float
    reason: str


def _props(node_data: dict) -> dict:
    return node_data.get("properties", {}) or {}


def _strat_tax_id(a: dict, b: dict) -> Optional[Signal]:
    ta = (_props(a).get("tax_id") or "").strip()
    tb = (_props(b).get("tax_id") or "").strip()
    if ta and tb and ta == tb:
        return Signal(1.0, f"Identical tax_id ({ta})")
    return None


def _strat_business_name_exact(a: dict, b: dict) -> Optional[Signal]:
    na = normalize_business_name(_props(a).get("business_name"))
    nb = normalize_business_name(_props(b).get("business_name"))
    if na and nb and na == nb:
        original_a = _props(a).get("business_name")
        return Signal(0.55, f"Exact normalized business_name ({original_a})")
    return None


def _strat_business_name_fuzzy(a: dict, b: dict) -> Optional[Signal]:
    na = normalize_business_name(_props(a).get("business_name"))
    nb = normalize_business_name(_props(b).get("business_name"))
    if not na or not nb or na == nb:
        return None
    sim = similarity(na, nb)
    if sim >= 0.92:
        return Signal(0.45,
            f"Near-exact name match ({sim:.0%}): "
            f"'{_props(a).get('business_name')}' vs '{_props(b).get('business_name')}'")
    if sim >= 0.80:
        return Signal(0.25, f"Fuzzy name match ({sim:.0%})")
    return None


def _strat_address(a: dict, b: dict) -> Optional[Signal]:
    aa = _props(a).get("registered_address") or ""
    ab = _props(b).get("registered_address") or ""
    if not aa or not ab:
        return None
    na = normalize_address(aa)
    nb = normalize_address(ab)
    if na and na == nb:
        return Signal(0.7, "Identical registered_address")
    sim = similarity(na, nb)
    za = extract_zip(aa)
    zb = extract_zip(ab)
    if sim >= 0.85:
        return Signal(0.5, f"Near-identical address ({sim:.0%})")
    if za and zb and za == zb and sim >= 0.6:
        return Signal(0.35, f"Same ZIP ({za}) + similar address ({sim:.0%})")
    return None


def _strat_industry(a: dict, b: dict) -> Optional[Signal]:
    ia = (_props(a).get("industry") or "").strip().lower()
    ib = (_props(b).get("industry") or "").strip().lower()
    if ia and ib and ia == ib:
        return Signal(0.1, f"Same industry ({ia})")
    return None


def _strat_email(a: dict, b: dict) -> Optional[Signal]:
    ea = normalize_email(_props(a).get("contact_email"))
    eb = normalize_email(_props(b).get("contact_email"))
    if ea and eb and ea == eb:
        return Signal(0.8, f"Same contact_email ({ea})")
    return None


def _strat_phone(a: dict, b: dict) -> Optional[Signal]:
    pa = normalize_phone(_props(a).get("phone_number"))
    pb = normalize_phone(_props(b).get("phone_number"))
    if pa and pb and pa == pb:
        return Signal(0.7, f"Same phone ({pa})")
    return None


def _strat_representative(a: dict, b: dict) -> Optional[Signal]:
    """Same business representative employee_id is a strong signal — that
    employee is the relationship owner, unlikely to handle two distinct
    businesses with similar names by coincidence."""
    ra = (_props(a).get("representative_emp_id") or
          _props(a).get("management_representative_employee") or "").strip()
    rb = (_props(b).get("representative_emp_id") or
          _props(b).get("management_representative_employee") or "").strip()
    if ra and rb and ra == rb:
        return Signal(0.75, f"Same representative employee ({ra})")
    return None


STRATEGIES: list[Callable[[dict, dict], Optional[Signal]]] = [
    _strat_tax_id,
    _strat_business_name_exact,
    _strat_business_name_fuzzy,
    _strat_address,
    _strat_industry,
    _strat_email,
    _strat_phone,
    _strat_representative,
]


def score_pair(a: dict, b: dict) -> tuple[float, list[str]]:
    """Combine all strategy signals using noisy-OR. Returns (score, reasons)."""
    signals: list[Signal] = []
    for strat in STRATEGIES:
        s = strat(a, b)
        if s is not None:
            signals.append(s)
    if not signals:
        return 0.0, []
    combined = 1.0
    for s in signals:
        combined *= 1.0 - s.score
    return 1.0 - combined, [s.reason for s in signals]


# ---------------------------------------------------------------------------
# Identifier-conflict detection
# ---------------------------------------------------------------------------

def has_identifier_conflict(a: dict, b: dict) -> Optional[str]:
    """Return a description if a and b have *different* values for an
    identifier field (e.g. different tax_ids). This down-weights any match."""
    pa, pb = _props(a), _props(b)
    for field_name in IDENTIFIER_FIELDS:
        va = (pa.get(field_name) or "").strip()
        vb = (pb.get(field_name) or "").strip()
        if va and vb and va != vb:
            return f"{field_name} disagrees: '{va}' vs '{vb}'"
    return None


# ---------------------------------------------------------------------------
# Union-find for clustering
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for k in self.parent:
            out[self.find(k)].append(k)
        return dict(out)


# ---------------------------------------------------------------------------
# Graph mutations: merge, link, flag
# ---------------------------------------------------------------------------

def _node_type(graph: nx.MultiDiGraph, node_id: str) -> str:
    return graph.nodes[node_id].get("node_type", "Unknown")


def _pick_canonical(graph: nx.MultiDiGraph, ids: list[str]) -> str:
    """For a same-type cluster, pick the canonical node by oldest provenance
    (earliest ingested_at), ties broken by lexicographic id."""
    def ingest_ts(nid: str) -> str:
        provs = graph.nodes[nid].get("provenance", [])
        if not provs:
            return "9999"
        return min(p.get("ingested_at", "9999") for p in provs)
    return sorted(ids, key=lambda nid: (ingest_ts(nid), nid))[0]


def merge_nodes(graph: nx.MultiDiGraph, canonical: str, alias: str,
                match_score: float, reasons: list[str]) -> None:
    """Merge `alias` into `canonical`. Properties are combined (per-field
    conflicts pushed onto graph.graph['conflicts']). Edges are rewired.
    Provenance is appended. The alias node is removed.
    """
    canon_data = graph.nodes[canonical]
    alias_data = graph.nodes[alias]
    canon_props = canon_data.setdefault("properties", {})
    alias_props = alias_data.get("properties", {})

    # Merge properties — register any disagreements as field-level conflicts
    for k, v_alias in alias_props.items():
        if k in canon_props and canon_props[k] != v_alias:
            graph.graph.setdefault("conflicts", []).append({
                "conflict_type": "field_after_merge",
                "entity_id": canonical,
                "entity_type": _node_type(graph, canonical),
                "field": k,
                "existing_value": canon_props[k],
                "merged_value": v_alias,
                "merged_from": alias,
                "match_score": round(match_score, 3),
                "match_reasons": reasons,
                "detected_at": datetime.utcnow().isoformat(),
                "resolution": {"status": "pending_review"},
            })
            # Keep canonical value as-is; conflict surfaced for human
        else:
            canon_props[k] = v_alias

    # Append provenance + record what was merged in
    canon_data.setdefault("provenance", []).extend(alias_data.get("provenance", []))
    canon_data.setdefault("provenance", []).append({
        "source_system": "resolver",
        "operation": "merged_in",
        "merged_alias": alias,
        "match_score": round(match_score, 3),
        "match_reasons": reasons,
        "ingested_at": datetime.utcnow().isoformat(),
        "confidence": match_score,
    })

    # Rewire edges: anything pointing at alias now points at canonical, and
    # anything alias was pointing at now comes from canonical. Self-loops are dropped.
    for src, _, key, data in list(graph.in_edges(alias, data=True, keys=True)):
        if src == canonical:
            continue
        graph.add_edge(src, canonical, key=key, **data)
    for _, dst, key, data in list(graph.out_edges(alias, data=True, keys=True)):
        if dst == canonical:
            continue
        graph.add_edge(canonical, dst, key=key, **data)

    graph.remove_node(alias)


def add_same_as_edge(graph: nx.MultiDiGraph, a: str, b: str,
                     score: float, reasons: list[str], status: str) -> None:
    """Add a bidirectional same_as edge between two nodes."""
    edge_props = {
        "match_score": round(score, 3),
        "match_reasons": reasons,
        "status": status,
    }
    prov = make_provenance(
        source_system="resolver",
        file="resolver.py",
        record_id=f"{a}|{b}",
        confidence=score,
    )
    graph.add_edge(a, b, key="same_as",
                   rel_type="same_as", properties=edge_props, provenance=[prov])
    graph.add_edge(b, a, key="same_as",
                   rel_type="same_as", properties=edge_props, provenance=[prov])


def flag_review(graph: nx.MultiDiGraph, member_ids: list[str],
                score: float, reasons: list[str], reason_text: str) -> None:
    """Push an entity-match cluster onto the conflicts queue for human review."""
    entry = {
        "conflict_type": "entity_match_review",
        "members": member_ids,
        "member_types": [_node_type(graph, mid) for mid in member_ids],
        "member_summaries": [
            {
                "id": mid,
                "type": _node_type(graph, mid),
                "business_name": _props(graph.nodes[mid]).get("business_name"),
                "tax_id": _props(graph.nodes[mid]).get("tax_id"),
                "registered_address": _props(graph.nodes[mid]).get("registered_address"),
                "industry": _props(graph.nodes[mid]).get("industry"),
            }
            for mid in member_ids
        ],
        "match_score": round(score, 3),
        "match_reasons": reasons,
        "review_reason": reason_text,
        "detected_at": datetime.utcnow().isoformat(),
        "resolution": {"status": "pending_review"},
    }
    graph.graph.setdefault("conflicts", []).append(entry)


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

def _block_key(props: dict, rule: ResolverRule) -> str:
    raw = props.get(rule.blocking_field)
    if rule.blocking_normalize == "business_name":
        norm = normalize_business_name(raw)
    elif rule.blocking_normalize == "address":
        norm = normalize_address(raw)
    else:
        norm = (raw or "").strip().lower()
    return norm[: rule.blocking_prefix_len] if len(norm) >= rule.blocking_prefix_len else norm


def block_nodes(graph: nx.MultiDiGraph, rule: ResolverRule,
                node_ids: list[str]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = defaultdict(list)
    for nid in node_ids:
        key = _block_key(_props(graph.nodes[nid]), rule)
        blocks[key].append(nid)
    return dict(blocks)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@dataclass
class ResolverStats:
    rule: str
    types_in_scope: list[str]
    nodes_considered: int
    pairs_compared: int
    pairs_above_threshold: int
    clusters_found: int
    merges_performed: int = 0
    same_as_edges_added: int = 0
    review_flags_added: int = 0
    suppressed_by_identifier_conflict: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "types_in_scope": self.types_in_scope,
            "nodes_considered": self.nodes_considered,
            "pairs_compared": self.pairs_compared,
            "pairs_above_threshold": self.pairs_above_threshold,
            "clusters_found": self.clusters_found,
            "merges_performed": self.merges_performed,
            "same_as_edges_added": self.same_as_edges_added,
            "review_flags_added": self.review_flags_added,
            "suppressed_by_identifier_conflict": self.suppressed_by_identifier_conflict,
            **self.extra,
        }


def resolve_entities(graph: nx.MultiDiGraph,
                     rule: ResolverRule = BUSINESS_ORG_RULE,
                     verbose: bool = False) -> ResolverStats:
    """Run one entity-resolution pass on the graph. Modifies in place."""
    print("=" * 60)
    print(f"Resolving entities — rule: {rule.name}")
    print(f"  Types in scope: {', '.join(rule.types)}")
    print("=" * 60)

    # Collect candidate nodes
    candidate_ids = [
        nid for nid, data in graph.nodes(data=True)
        if data.get("node_type") in rule.types
    ]

    stats = ResolverStats(
        rule=rule.name,
        types_in_scope=list(rule.types),
        nodes_considered=len(candidate_ids),
        pairs_compared=0,
        pairs_above_threshold=0,
        clusters_found=0,
    )

    if not candidate_ids:
        print(f"  No nodes of type {rule.types} found. Skipping.")
        return stats

    # Block to avoid O(n^2)
    blocks = block_nodes(graph, rule, candidate_ids)
    if verbose:
        print(f"  Blocking: {len(blocks)} blocks, "
              f"max block = {max(len(v) for v in blocks.values())}, "
              f"avg block = {sum(len(v) for v in blocks.values()) / len(blocks):.1f}")

    # Score pairs and union them
    uf = UnionFind()
    for nid in candidate_ids:
        uf.add(nid)

    pair_scores: dict[tuple[str, str], tuple[float, list[str], Optional[str]]] = {}

    for block_ids in blocks.values():
        n = len(block_ids)
        if n < 2:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                a_id, b_id = block_ids[i], block_ids[j]
                a_data = graph.nodes[a_id]
                b_data = graph.nodes[b_id]
                stats.pairs_compared += 1
                score, reasons = score_pair(a_data, b_data)
                if score < LINK_THRESHOLD:
                    continue
                ident_conflict = has_identifier_conflict(a_data, b_data)
                if ident_conflict:
                    stats.suppressed_by_identifier_conflict += 1
                    # Heavy penalty: ID disagreement is almost certainly a non-match
                    score = min(score, 0.55)
                stats.pairs_above_threshold += 1
                key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                pair_scores[key] = (score, reasons, ident_conflict)
                uf.union(a_id, b_id)

    print(f"  Compared {stats.pairs_compared} pairs in-block, "
          f"{stats.pairs_above_threshold} above link threshold "
          f"({LINK_THRESHOLD:.0%})")

    # Process each cluster
    groups = uf.groups()
    multi_clusters = {gid: ids for gid, ids in groups.items() if len(ids) > 1}
    stats.clusters_found = len(multi_clusters)
    print(f"  Found {len(multi_clusters)} multi-member clusters "
          f"(out of {len(groups)} total groups)")

    for cluster_ids in multi_clusters.values():
        # Aggregate within-cluster info
        cluster_max_score = 0.0
        cluster_reasons: list[str] = []
        any_ident_conflict: Optional[str] = None
        for i in range(len(cluster_ids)):
            for j in range(i + 1, len(cluster_ids)):
                a_id, b_id = cluster_ids[i], cluster_ids[j]
                key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                if key in pair_scores:
                    s, rs, ic = pair_scores[key]
                    if s > cluster_max_score:
                        cluster_max_score = s
                    for r in rs:
                        if r not in cluster_reasons:
                            cluster_reasons.append(r)
                    if ic and not any_ident_conflict:
                        any_ident_conflict = ic

        types_in_cluster = {_node_type(graph, nid) for nid in cluster_ids}
        is_same_type = len(types_in_cluster) == 1

        # Decision
        if cluster_max_score >= AUTO_MERGE_THRESHOLD and is_same_type and not any_ident_conflict:
            # Merge same-type cluster
            canon = _pick_canonical(graph, cluster_ids)
            for alias in cluster_ids:
                if alias == canon:
                    continue
                merge_nodes(graph, canon, alias,
                            match_score=cluster_max_score, reasons=cluster_reasons)
                stats.merges_performed += 1
        elif cluster_max_score >= HIGH_CONFIDENCE_LINK and not is_same_type and not any_ident_conflict:
            # Cross-type strong match: add same_as edges, no review needed
            canonical_pairs = [(cluster_ids[i], cluster_ids[j])
                               for i in range(len(cluster_ids))
                               for j in range(i + 1, len(cluster_ids))]
            for a, b in canonical_pairs:
                add_same_as_edge(graph, a, b,
                                 score=cluster_max_score,
                                 reasons=cluster_reasons,
                                 status="auto_linked")
                stats.same_as_edges_added += 2  # bidirectional
        else:
            # Ambiguous — flag for review
            review_reason = (
                any_ident_conflict
                or f"Match confidence {cluster_max_score:.0%} below "
                   f"auto-{'merge' if is_same_type else 'link'} threshold"
            )
            flag_review(graph, cluster_ids,
                        score=cluster_max_score,
                        reasons=cluster_reasons,
                        reason_text=review_reason)
            stats.review_flags_added += 1
            # Still add same_as edges with status="needs_review" so the
            # relationship is queryable while the human decides
            for i in range(len(cluster_ids)):
                for j in range(i + 1, len(cluster_ids)):
                    add_same_as_edge(graph, cluster_ids[i], cluster_ids[j],
                                     score=cluster_max_score,
                                     reasons=cluster_reasons,
                                     status="needs_review")
                    stats.same_as_edges_added += 2

    # Persist run stats on the graph
    graph.graph.setdefault("resolver_runs", []).append({
        "ran_at": datetime.utcnow().isoformat(),
        **stats.as_dict(),
    })

    print(f"  -> {stats.merges_performed} merges, "
          f"{stats.same_as_edges_added} same_as edges added, "
          f"{stats.review_flags_added} clusters flagged for review")
    print()
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run cross-source entity resolution on a Qontext graph.")
    parser.add_argument("--graph", required=True,
                        help="Path to input graph.json (produced by run_all.py)")
    parser.add_argument("--output", default=None,
                        help="Path to write resolved graph (default: <graph>.resolved.json)")
    parser.add_argument("--rule", default="business_orgs",
                        choices=["business_orgs"],
                        help="Which resolver rule to apply")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    out_path = args.output or args.graph.replace(".json", ".resolved.json")

    graph = load_graph(args.graph)
    print(f"Loaded graph: {graph.number_of_nodes()} nodes, "
          f"{graph.number_of_edges()} edges, "
          f"{len(graph.graph.get('conflicts', []))} pre-existing conflicts")
    print()

    rule = {"business_orgs": BUSINESS_ORG_RULE}[args.rule]
    stats = resolve_entities(graph, rule=rule, verbose=args.verbose)

    save_graph(graph, out_path)

    print()
    print("=" * 60)
    print("RESOLVER COMPLETE")
    print("=" * 60)
    import json
    print(json.dumps(stats.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
