"""
retrieval.py - Local hybrid retrieval for the Qontext knowledge graph.

This module keeps the Qontext graph as the canonical source of truth and adds
an application-layer retriever on top:

- graph retrieval: rewards direct matches plus graph-neighborhood evidence
- vector retrieval: sparse TF-IDF similarity over node documents
- hybrid retrieval: combines both and returns graph-grounded context

The implementation is dependency-light on purpose so the repo stays runnable
without adding a separate vector database during the hackathon.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
import math
import re
from typing import Any, Optional

try:
    from vfs_generator import (
        generate_customer_page,
        generate_employee_page,
        generate_team_page,
    )
except Exception:
    generate_customer_page = None
    generate_employee_page = None
    generate_team_page = None


TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "were", "what", "when", "where", "which", "who",
    "with",
}
TITLE_FIELDS = (
    "name",
    "business_name",
    "subject",
    "issue",
    "title",
    "summary",
)
SUMMARY_FIELDS = (
    "department",
    "level",
    "email",
    "industry",
    "category",
    "priority",
    "date_of_purchase",
    "date",
)
QUERY_TYPE_HINTS = {
    "employee": {"Employee"},
    "employees": {"Employee"},
    "people": {"Employee"},
    "team": {"Department"},
    "teams": {"Department"},
    "department": {"Department"},
    "customer": {"Customer"},
    "customers": {"Customer"},
    "client": {"Client"},
    "clients": {"Client"},
    "vendor": {"Vendor"},
    "vendors": {"Vendor"},
    "product": {"Product"},
    "products": {"Product"},
    "sale": {"Sale"},
    "sales": {"Sale"},
    "ticket": {"ITTicket"},
    "tickets": {"ITTicket"},
    "issue": {"ITTicket", "GitHubIssue"},
    "issues": {"ITTicket", "GitHubIssue"},
    "email": {"Email", "EmailThread"},
    "emails": {"Email", "EmailThread"},
    "thread": {"EmailThread"},
    "threads": {"EmailThread"},
    "conversation": {"Conversation"},
    "conversations": {"Conversation"},
    "chat": {"Conversation", "SupportChat"},
    "support": {"SupportChat"},
    "review": {"Review"},
    "reviews": {"Review"},
    "policy": {"Policy"},
    "policies": {"Policy"},
    "repo": {"GitHubRepo"},
    "repository": {"GitHubRepo"},
    "github": {"GitHubRepo", "GitHubIssue"},
}
GRAPH_ROUTE_PATTERNS = (
    re.compile(r"\bemp[_-]?\d+\b"),
    re.compile(r"\b[a-z]+:\S+\b"),
    re.compile(r"\bcustomer[_-]?[a-z0-9]+\b"),
)


def _stringify(value: Any, limit: int = 400) -> str:
    """Convert values into indexable text and trim very large fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_stringify(item, limit=120) for item in value[:20])
    if isinstance(value, dict):
        return " ".join(f"{k} {_stringify(v, limit=120)}" for k, v in list(value.items())[:20])
    return str(value)[:limit]


def tokenize(text: str) -> list[str]:
    """Lowercase tokenization with light stop-word filtering."""
    if not text:
        return []
    tokens = TOKEN_RE.findall(text.lower())
    return [token for token in tokens if token not in STOPWORDS and len(token) > 1]


def _display_title(node_id: str, node_data: dict) -> str:
    props = node_data.get("properties", {}) or {}
    for field in TITLE_FIELDS:
        value = props.get(field)
        if value:
            return _stringify(value, limit=160)
    return node_id


def _display_summary(node_data: dict) -> str:
    props = node_data.get("properties", {}) or {}
    parts = []
    for field in SUMMARY_FIELDS:
        value = props.get(field)
        if value:
            parts.append(f"{field.replace('_', ' ')}: {_stringify(value, limit=80)}")
        if len(parts) >= 3:
            break
    return " | ".join(parts)


def _filtered_properties(node_data: dict, limit: int = 8) -> dict[str, Any]:
    props = node_data.get("properties", {}) or {}
    out: dict[str, Any] = {}
    for key, value in props.items():
        if value in ("", None, [], {}):
            continue
        out[key] = value if isinstance(value, (int, float, list, dict)) else _stringify(value, limit=200)
        if len(out) >= limit:
            break
    return out


@dataclass
class IndexedNode:
    node_id: str
    node_type: str
    title: str
    summary: str
    text: str
    direct_terms: list[str]
    relation_terms: list[str]
    term_freq: Counter
    generated_view: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    norm: float = 0.0


class LocalHybridRetriever:
    """
    Graph-grounded retrieval over a Qontext graph.

    The retriever intentionally does not mutate the graph. It creates a local
    search index from node content plus lightweight neighborhood summaries.
    """

    def __init__(self, graph):
        self.graph = graph
        self.documents: list[IndexedNode] = []
        self.doc_lookup: dict[str, IndexedNode] = {}
        self.inverted_index: dict[str, set[str]] = defaultdict(set)
        self.idf: dict[str, float] = {}
        self._build_index()

    def _build_index(self) -> None:
        doc_frequencies: Counter = Counter()

        for node_id, node_data in self.graph.nodes(data=True):
            document = self._make_document(node_id, node_data)
            self.documents.append(document)
            self.doc_lookup[node_id] = document

            unique_terms = set(document.term_freq)
            for term in unique_terms:
                self.inverted_index[term].add(node_id)
            doc_frequencies.update(unique_terms)

        total_docs = max(len(self.documents), 1)
        self.idf = {
            term: math.log((1 + total_docs) / (1 + freq)) + 1.0
            for term, freq in doc_frequencies.items()
        }

        for document in self.documents:
            weights = {}
            norm_sq = 0.0
            for term, tf in document.term_freq.items():
                weight = (1.0 + math.log(tf)) * self.idf.get(term, 1.0)
                weights[term] = weight
                norm_sq += weight * weight
            document.weights = weights
            document.norm = math.sqrt(norm_sq)

    def _make_document(self, node_id: str, node_data: dict) -> IndexedNode:
        props = node_data.get("properties", {}) or {}
        node_type = node_data.get("node_type", "Unknown")
        title = _display_title(node_id, node_data)
        summary = _display_summary(node_data)
        generated_view = self._generated_view(node_id, node_data)

        property_lines = [node_type, node_id, title]
        for key, value in props.items():
            rendered = _stringify(value)
            if rendered:
                property_lines.append(f"{key.replace('_', ' ')} {rendered}")

        relation_counts = Counter()
        relation_examples = []

        for _, target, key, edge_data in self.graph.out_edges(node_id, data=True, keys=True):
            rel_type = edge_data.get("rel_type", key)
            relation_counts[rel_type] += 1
            if len(relation_examples) < 6:
                other_title = _display_title(target, self.graph.nodes[target])
                relation_examples.append(f"outgoing {rel_type} {other_title}")

        for source, _, key, edge_data in self.graph.in_edges(node_id, data=True, keys=True):
            rel_type = edge_data.get("rel_type", key)
            relation_counts[rel_type] += 1
            if len(relation_examples) < 12:
                other_title = _display_title(source, self.graph.nodes[source])
                relation_examples.append(f"incoming {rel_type} {other_title}")

        relation_summary = " ".join(
            f"{rel_type.replace('_', ' ')} {count}" for rel_type, count in relation_counts.items()
        )
        relation_text = " ".join(relation_examples + ([relation_summary] if relation_summary else []))

        direct_text = " ".join(
            part for part in (" ".join(property_lines), generated_view[:5000]) if part
        )
        combined_text = " ".join(part for part in (direct_text, relation_text) if part)

        direct_terms = tokenize(direct_text)
        relation_terms = tokenize(relation_text)
        term_freq = Counter(direct_terms + relation_terms)

        return IndexedNode(
            node_id=node_id,
            node_type=node_type,
            title=title,
            summary=summary,
            text=combined_text,
            direct_terms=direct_terms,
            relation_terms=relation_terms,
            term_freq=term_freq,
            generated_view=generated_view,
        )

    def _generated_view(self, node_id: str, node_data: dict) -> str:
        """
        Reuse the richer VFS pages when available so vector search sees the same
        stitched business context that human readers see.
        """
        node_type = node_data.get("node_type", "Unknown")
        node_key = node_id.split(":", 1)[1] if ":" in node_id else node_id

        try:
            if node_type == "Employee" and generate_employee_page:
                return generate_employee_page(self.graph, node_key) or ""
            if node_type == "Customer" and generate_customer_page:
                return generate_customer_page(self.graph, node_key) or ""
            if node_type == "Department" and generate_team_page:
                return generate_team_page(self.graph, node_key) or ""
        except Exception:
            # Retrieval must stay available even if view rendering is incomplete
            # for some node types or graph states.
            return ""
        return ""

    def _query_weights(self, query: str) -> tuple[list[str], dict[str, float], float]:
        query_terms = tokenize(query)
        query_tf = Counter(query_terms)
        weights = {}
        norm_sq = 0.0
        for term, tf in query_tf.items():
            weight = (1.0 + math.log(tf)) * self.idf.get(term, 1.0)
            weights[term] = weight
            norm_sq += weight * weight
        return query_terms, weights, math.sqrt(norm_sq)

    def _candidate_ids(self, query_terms: list[str], node_type: Optional[str]) -> set[str]:
        candidates: set[str] = set()
        for term in query_terms:
            candidates.update(self.inverted_index.get(term, set()))

        if not candidates:
            candidates = {doc.node_id for doc in self.documents}

        if node_type:
            candidates = {
                node_id for node_id in candidates
                if self.graph.nodes[node_id].get("node_type", "").lower() == node_type.lower()
            }
        return candidates

    def _vector_scores(
        self,
        query_terms: list[str],
        query_weights: dict[str, float],
        query_norm: float,
        candidate_ids: set[str],
    ) -> dict[str, float]:
        if not query_terms or not query_norm:
            return {}

        scores = {}
        for node_id in candidate_ids:
            document = self.doc_lookup[node_id]
            if not document.norm:
                continue
            dot = 0.0
            for term, q_weight in query_weights.items():
                dot += q_weight * document.weights.get(term, 0.0)
            if dot:
                scores[node_id] = dot / (query_norm * document.norm)
        return scores

    def _graph_scores(self, query: str, query_terms: list[str], candidate_ids: set[str]) -> dict[str, float]:
        if not query_terms:
            return {}

        query_lower = query.lower()
        query_set = set(query_terms)
        hinted_types = self._hinted_node_types(query_terms)
        scores = {}

        for node_id in candidate_ids:
            document = self.doc_lookup[node_id]
            direct_set = set(document.direct_terms)
            relation_set = set(document.relation_terms)

            direct_overlap = len(query_set & direct_set)
            relation_overlap = len(query_set & relation_set)
            title_overlap = len(query_set & set(tokenize(document.title)))

            coverage = direct_overlap / max(len(query_set), 1)
            relation_coverage = relation_overlap / max(len(query_set), 1)
            title_coverage = title_overlap / max(len(query_set), 1)

            exact_bonus = 0.0
            if query_lower in node_id.lower():
                exact_bonus += 0.5
            if query_lower in document.title.lower():
                exact_bonus += 0.35
            if document.node_type.lower() in query_lower:
                exact_bonus += 0.15

            type_boost = 0.0
            if document.node_type in hinted_types:
                type_boost += 0.20

            degree_bonus = min(self.graph.degree(node_id), 20) / 100.0
            score = (
                0.45 * coverage +
                0.20 * relation_coverage +
                0.20 * title_coverage +
                type_boost +
                exact_bonus +
                degree_bonus
            )

            if score > 0:
                scores[node_id] = score

        return scores

    def _collect_related(self, node_id: str, hops: int = 1, limit: int = 6) -> list[dict]:
        results = []
        visited = {node_id}
        queue = deque([(node_id, 0)])

        while queue and len(results) < limit:
            current, depth = queue.popleft()
            if depth >= hops:
                continue

            for _, target, key, edge_data in self.graph.out_edges(current, data=True, keys=True):
                rel_type = edge_data.get("rel_type", key)
                if target not in visited:
                    visited.add(target)
                    target_data = self.graph.nodes[target]
                    results.append({
                        "direction": "outgoing",
                        "rel_type": rel_type,
                        "node_id": target,
                        "node_type": target_data.get("node_type", "Unknown"),
                        "title": _display_title(target, target_data),
                        "summary": _display_summary(target_data),
                    })
                    queue.append((target, depth + 1))
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break

            for source, _, key, edge_data in self.graph.in_edges(current, data=True, keys=True):
                rel_type = edge_data.get("rel_type", key)
                if source not in visited:
                    visited.add(source)
                    source_data = self.graph.nodes[source]
                    results.append({
                        "direction": "incoming",
                        "rel_type": rel_type,
                        "node_id": source,
                        "node_type": source_data.get("node_type", "Unknown"),
                        "title": _display_title(source, source_data),
                        "summary": _display_summary(source_data),
                    })
                    queue.append((source, depth + 1))
                    if len(results) >= limit:
                        break

        return results

    def _normalize_scores(self, scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        max_score = max(scores.values()) or 1.0
        return {node_id: score / max_score for node_id, score in scores.items()}

    def _hinted_node_types(self, query_terms: list[str]) -> set[str]:
        hinted = set()
        for term in query_terms:
            hinted.update(QUERY_TYPE_HINTS.get(term, set()))
        return hinted

    def _resolve_mode(self, query: str, requested_mode: str) -> str:
        mode = (requested_mode or "hybrid").lower()
        if mode != "auto":
            return mode

        query_lower = query.lower()
        if any(pattern.search(query_lower) for pattern in GRAPH_ROUTE_PATTERNS):
            return "graph"
        query_terms = tokenize(query_lower)
        if len(query_terms) <= 2:
            return "graph"
        if len(query_terms) >= 7:
            return "hybrid"
        return "vector" if any(word in query_terms for word in ("similar", "like", "about", "overview")) else "hybrid"

    def _build_evidence(self, document: IndexedNode, related: list[dict], query_terms: list[str]) -> list[str]:
        evidence = []
        props = self.graph.nodes[document.node_id].get("properties", {}) or {}
        for key, value in props.items():
            value_text = _stringify(value, limit=120).lower()
            if any(term in value_text for term in query_terms):
                evidence.append(f"property `{key}` matched query terms")
            if len(evidence) >= 3:
                break

        if not evidence and document.generated_view:
            evidence.append("matched within generated stitched entity view")

        for rel in related[:2]:
            evidence.append(
                f"{rel['direction']} `{rel['rel_type']}` to {rel['title']} ({rel['node_type']})"
            )
        return evidence[:5]

    def search(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
        node_type: Optional[str] = None,
        expand_hops: int = 1,
        related_limit: int = 6,
    ) -> dict:
        """
        Search the graph in graph, vector, or hybrid mode.

        Returns structured, graph-grounded results that can be used directly
        for UI rendering or as context for an LLM.
        """
        requested_mode = (mode or "hybrid").lower()
        mode = self._resolve_mode(query, requested_mode)
        if mode not in {"graph", "vector", "hybrid"}:
            raise ValueError("mode must be one of: auto, graph, vector, hybrid")

        query_terms, query_weights, query_norm = self._query_weights(query)
        candidate_ids = self._candidate_ids(query_terms, node_type=node_type)

        graph_scores = self._graph_scores(query, query_terms, candidate_ids)
        vector_scores = self._vector_scores(query_terms, query_weights, query_norm, candidate_ids)

        if mode == "graph":
            final_scores = graph_scores
        elif mode == "vector":
            final_scores = vector_scores
        else:
            norm_graph = self._normalize_scores(graph_scores)
            norm_vector = self._normalize_scores(vector_scores)
            union_ids = set(norm_graph) | set(norm_vector)
            final_scores = {
                node_id: 0.55 * norm_graph.get(node_id, 0.0) + 0.45 * norm_vector.get(node_id, 0.0)
                for node_id in union_ids
            }

        ranked = sorted(final_scores.items(), key=lambda item: item[1], reverse=True)[:max(top_k, 1)]

        results = []
        context_lines = []
        for rank, (node_id, score) in enumerate(ranked, start=1):
            node_data = self.graph.nodes[node_id]
            document = self.doc_lookup[node_id]
            related = self._collect_related(node_id, hops=max(expand_hops, 0), limit=max(related_limit, 0))
            matched_terms = sorted(set(query_terms) & set(document.term_freq))
            evidence = self._build_evidence(document, related, query_terms)

            result = {
                "rank": rank,
                "node_id": node_id,
                "node_type": node_data.get("node_type", "Unknown"),
                "title": document.title,
                "summary": document.summary,
                "mode": mode,
                "score": round(score, 4),
                "graph_score": round(graph_scores.get(node_id, 0.0), 4),
                "vector_score": round(vector_scores.get(node_id, 0.0), 4),
                "matched_terms": matched_terms,
                "evidence": evidence,
                "properties": _filtered_properties(node_data),
                "provenance": node_data.get("provenance", [])[:3],
                "related": related,
            }
            results.append(result)

            context_lines.append(f"[{rank}] {document.title} ({result['node_type']})")
            if document.summary:
                context_lines.append(f"Summary: {document.summary}")
            if matched_terms:
                context_lines.append(f"Matched terms: {', '.join(matched_terms)}")
            for rel in related[:4]:
                context_lines.append(
                    f"{rel['direction']} {rel['rel_type']} -> {rel['title']} ({rel['node_type']})"
                )
            context_lines.append("")

        return {
            "query": query,
            "requested_mode": requested_mode,
            "mode": mode,
            "top_k": top_k,
            "node_type": node_type,
            "expand_hops": expand_hops,
            "related_limit": related_limit,
            "index": {
                "documents": len(self.documents),
                "unique_terms": len(self.idf),
            },
            "results": results,
            "context": "\n".join(context_lines).strip(),
        }
