"""
llm_resolver.py — LLM-driven resolution of conflicts surfaced by resolver.py.

The rules-based resolver (resolver.py) finds candidate entity-match clusters
but, by design, refuses to merge or remove any of them when an identifier
disagrees (e.g. mismatched tax_ids). This module asks an LLM to make the
human-judgement call on each ambiguous cluster, then ACTS:

    decision == "same_entity"  AND confidence >= HIGH_THRESHOLD
        -> autonomous action:
             same-type cluster   -> merge nodes (collapse into canonical)
             cross-type cluster  -> upgrade `same_as` edges to "auto_linked"
             cluster removed from review queue
             full audit entry appended to graph.graph["resolver_actions"]

    decision == "different"    AND confidence >= HIGH_THRESHOLD
        -> autonomous action:
             remove the `same_as` edges that the rules layer added
             cluster removed from review queue (false positive)
             full audit entry appended

    decision == "uncertain"    OR confidence < HIGH_THRESHOLD
        -> NO mutation; conflict stays in review queue, enriched with the
           LLM's reasoning and confidence so a human can act faster.

LLM backend is Ollama running locally on http://localhost:11434, no API key.

Usage:
    python llm_resolver.py --graph bm_graph.resolved.json \
                           --output bm_graph.llm_resolved.json \
                           --model llama3.2:3b
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import requests

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from graph_utils import load_graph, save_graph  # type: ignore
    from prompts import (  # type: ignore
        build_chat_messages,
        build_employee_name_chat_messages,
    )
    from risk import RiskAssessment, assess_risk  # type: ignore
    from proposals import build_proposal  # type: ignore
else:
    from .graph_utils import load_graph, save_graph
    from .prompts import (
        build_chat_messages,
        build_employee_name_chat_messages,
    )
    from .risk import RiskAssessment, assess_risk
    from .proposals import build_proposal

import networkx as nx


HIGH_CONFIDENCE_THRESHOLD = 0.85       # legacy / compatibility — see risk.py
DEFAULT_RISK_THRESHOLD = 5.0           # autonomous if risk_score < threshold
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_TIMEOUT = 300  # seconds per LLM call (3B model on CPU is slow on cold start)
DEFAULT_CACHE_FILE = ".llm_resolver_cache.json"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

@dataclass
class LLMDecision:
    decision: str          # "same_entity" | "different" | "uncertain"
    confidence: float
    reasoning: str
    key_signals: list[str]
    open_questions: list[str]
    raw_response: str
    model: str
    elapsed_s: float


def call_ollama(messages: list[dict[str, str]],
                model: str = DEFAULT_MODEL,
                ollama_url: str = DEFAULT_OLLAMA_URL,
                timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """POST to Ollama /api/chat with format=json. Returns the parsed body."""
    url = ollama_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,    # near-deterministic for entity resolution
            "num_ctx": 4096,
        },
    }
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_decision(raw_text: str) -> dict[str, Any]:
    """Parse the JSON payload the LLM returned. Tolerant of stray prose."""
    txt = raw_text.strip()
    # If the model wrapped it in a code fence, strip it
    if txt.startswith("```"):
        # remove first line (```json) and trailing ```
        lines = txt.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        txt = "\n".join(lines).strip()
    # Try direct parse first; fall back to first {...} block
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        start = txt.find("{")
        end = txt.rfind("}")
        if start >= 0 and end > start:
            return json.loads(txt[start : end + 1])
        raise


def resolve_cluster_with_llm(cluster_payload: dict[str, Any],
                              model: str,
                              ollama_url: str,
                              prompt_kind: str = "entity_match") -> LLMDecision:
    """Send a payload to the LLM, parse its JSON verdict.

    `prompt_kind` selects which system prompt + few-shot context to use:
        - "entity_match"          : same_entity / different / uncertain
        - "employee_name_mismatch": alias / shared_mailbox / wrong_assignment / uncertain
    """
    if prompt_kind == "employee_name_mismatch":
        messages = build_employee_name_chat_messages(cluster_payload)
    else:
        messages = build_chat_messages(cluster_payload)
    started = time.time()
    body = call_ollama(messages, model=model, ollama_url=ollama_url)
    elapsed = time.time() - started

    raw_content = body.get("message", {}).get("content", "")
    parsed = parse_decision(raw_content)

    return LLMDecision(
        decision=str(parsed.get("decision", "uncertain")),
        confidence=float(parsed.get("confidence", 0.0)),
        reasoning=str(parsed.get("reasoning", "")),
        key_signals=list(parsed.get("key_signals", []) or []),
        open_questions=list(parsed.get("open_questions", []) or []),
        raw_response=raw_content,
        model=model,
        elapsed_s=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Build the cluster payload that the LLM sees
# ---------------------------------------------------------------------------

def _node_props(graph: nx.MultiDiGraph, node_id: str) -> dict[str, Any]:
    if not graph.has_node(node_id):
        return {}
    return graph.nodes[node_id].get("properties", {}) or {}


def _node_type(graph: nx.MultiDiGraph, node_id: str) -> str:
    if not graph.has_node(node_id):
        return "Unknown"
    return graph.nodes[node_id].get("node_type", "Unknown")


# Fields surfaced to the LLM. Keep this lean — too much noise hurts quality.
LLM_FIELDS = [
    "business_name",
    "tax_id",
    "registered_address",
    "industry",
    "business_type",
    "contact_email",
    "phone_number",
    "monthly_revenue",
    "onboarding_date",
    "current_poc_product",
    "poc_status",
    "engagement_description",
    "relationship_description",
    "representative_emp_id",
    "management_representative_employee",
]


def build_employee_name_payload(graph: nx.MultiDiGraph,
                                  conflict: dict[str, Any]) -> dict[str, Any]:
    """Compact payload for employee_name_inconsistency conflicts."""
    return {
        "entity_id": conflict.get("entity_id"),
        "hr_name": conflict.get("hr_name"),
        "total_mismatched_emails": conflict.get("total_mismatched_emails"),
        "distinct_variant_count": conflict.get("distinct_variant_count"),
        "signature_variants": conflict.get("signature_variants", {}),
    }


def build_cluster_payload(graph: nx.MultiDiGraph,
                           conflict: dict[str, Any]) -> dict[str, Any]:
    members_payload = []
    for nid in conflict.get("members", []):
        props = _node_props(graph, nid)
        member = {"id": nid, "type": _node_type(graph, nid)}
        for k in LLM_FIELDS:
            if k in props and props[k] not in (None, ""):
                member[k] = props[k]
        members_payload.append(member)

    return {
        "cluster_id": "+".join(sorted(conflict.get("members", []))),
        "rules_score": conflict.get("match_score"),
        "rules_match_reasons": conflict.get("match_reasons", []),
        "rules_review_reason": conflict.get("review_reason"),
        "members": members_payload,
    }


# ---------------------------------------------------------------------------
# Acting on the LLM decision (graph mutations)
# ---------------------------------------------------------------------------

def _is_same_type(graph: nx.MultiDiGraph, member_ids: list[str]) -> bool:
    types = {_node_type(graph, nid) for nid in member_ids if graph.has_node(nid)}
    return len(types) == 1


def _pick_canonical(graph: nx.MultiDiGraph, ids: list[str]) -> str:
    """Pick the oldest provenance, ties broken by lexicographic id."""
    def ingest_ts(nid: str) -> str:
        provs = graph.nodes[nid].get("provenance", [])
        return min((p.get("ingested_at", "9999") for p in provs), default="9999")
    return sorted(ids, key=lambda nid: (ingest_ts(nid), nid))[0]


def _mark_alias(graph: nx.MultiDiGraph, entity_id: str,
                 alias_names: list[str], audit_tag: dict) -> None:
    """Add a list of foreign signature names to the Employee node's `aliases`."""
    if not graph.has_node(entity_id):
        return
    props = graph.nodes[entity_id].setdefault("properties", {})
    existing = list(props.get("aliases", []) or [])
    for nm in alias_names:
        if nm and nm not in existing:
            existing.append(nm)
    props["aliases"] = existing
    graph.nodes[entity_id].setdefault("provenance", []).append({
        "source_system": "llm_resolver",
        "operation": "mark_alias",
        "ingested_at": datetime.utcnow().isoformat(),
        "confidence": audit_tag.get("llm_confidence"),
        "model": audit_tag.get("model"),
        "audit_tag": audit_tag,
    })


def _mark_shared_mailbox(graph: nx.MultiDiGraph, entity_id: str,
                          audit_tag: dict) -> None:
    if not graph.has_node(entity_id):
        return
    props = graph.nodes[entity_id].setdefault("properties", {})
    props["is_shared_mailbox"] = True
    graph.nodes[entity_id].setdefault("provenance", []).append({
        "source_system": "llm_resolver",
        "operation": "mark_shared_mailbox",
        "ingested_at": datetime.utcnow().isoformat(),
        "confidence": audit_tag.get("llm_confidence"),
        "model": audit_tag.get("model"),
        "audit_tag": audit_tag,
    })


def _flag_email_reassignment(graph: nx.MultiDiGraph, entity_id: str,
                              suggested_signer: str | None,
                              audit_tag: dict) -> int:
    """Mark all emails sent under entity_id with `_sender_assignment_disputed=True`.
    Does NOT actually rewire — that's a follow-up step.
    Returns the number of emails flagged."""
    flagged = 0
    sender_emp_id = entity_id.split(":", 1)[1] if ":" in entity_id else entity_id
    for nid, data in graph.nodes(data=True):
        if data.get("node_type") != "Email":
            continue
        props = data.get("properties", {}) or {}
        if props.get("sender_emp_id") != sender_emp_id:
            continue
        if not props.get("_signature_mismatch"):
            continue
        props["_sender_assignment_disputed"] = True
        if suggested_signer:
            props["_suggested_actual_sender"] = suggested_signer
        flagged += 1
    if flagged:
        graph.nodes[entity_id].setdefault("provenance", []).append({
            "source_system": "llm_resolver",
            "operation": "flag_email_reassignment",
            "flagged_email_count": flagged,
            "suggested_signer": suggested_signer,
            "ingested_at": datetime.utcnow().isoformat(),
            "confidence": audit_tag.get("llm_confidence"),
            "model": audit_tag.get("model"),
            "audit_tag": audit_tag,
        })
    return flagged


def _remove_same_as_edges(graph: nx.MultiDiGraph, member_ids: list[str]) -> int:
    """Remove all same_as edges between the given member nodes."""
    removed = 0
    for i in range(len(member_ids)):
        for j in range(len(member_ids)):
            if i == j:
                continue
            a, b = member_ids[i], member_ids[j]
            if graph.has_edge(a, b, key="same_as"):
                graph.remove_edge(a, b, key="same_as")
                removed += 1
    return removed


def _upgrade_same_as_edges(graph: nx.MultiDiGraph,
                            member_ids: list[str],
                            new_status: str,
                            new_score: float,
                            new_reasons: list[str]) -> int:
    """Upgrade existing same_as edges between members (status + score + reasons)."""
    upgraded = 0
    for i in range(len(member_ids)):
        for j in range(len(member_ids)):
            if i == j:
                continue
            a, b = member_ids[i], member_ids[j]
            if graph.has_edge(a, b, key="same_as"):
                edge = graph[a][b]["same_as"]
                props = edge.setdefault("properties", {})
                props["status"] = new_status
                props["llm_match_score"] = round(new_score, 3)
                props["llm_match_reasons"] = new_reasons
                upgraded += 1
    return upgraded


def _merge_nodes(graph: nx.MultiDiGraph, canonical: str, alias: str,
                 audit_tag: dict) -> None:
    """Merge alias into canonical. Property conflicts logged separately."""
    canon = graph.nodes[canonical]
    aliasn = graph.nodes[alias]
    canon_props = canon.setdefault("properties", {})
    alias_props = aliasn.get("properties", {})

    for k, v in alias_props.items():
        if k in canon_props and canon_props[k] != v:
            graph.graph.setdefault("conflicts", []).append({
                "conflict_type": "field_after_llm_merge",
                "entity_id": canonical,
                "entity_type": _node_type(graph, canonical),
                "field": k,
                "existing_value": canon_props[k],
                "merged_value": v,
                "merged_from": alias,
                "decided_by": "llm",
                "audit_tag": audit_tag,
                "detected_at": datetime.utcnow().isoformat(),
                "resolution": {"status": "pending_review"},
            })
        else:
            canon_props[k] = v

    canon.setdefault("provenance", []).extend(aliasn.get("provenance", []))
    canon.setdefault("provenance", []).append({
        "source_system": "llm_resolver",
        "operation": "merged_in",
        "merged_alias": alias,
        "ingested_at": datetime.utcnow().isoformat(),
        "confidence": audit_tag.get("llm_confidence"),
        "model": audit_tag.get("model"),
    })

    for src, _, key, data in list(graph.in_edges(alias, data=True, keys=True)):
        if src == canonical:
            continue
        graph.add_edge(src, canonical, key=key, **data)
    for _, dst, key, data in list(graph.out_edges(alias, data=True, keys=True)):
        if dst == canonical:
            continue
        graph.add_edge(canonical, dst, key=key, **data)

    graph.remove_node(alias)


def _log_action(graph: nx.MultiDiGraph, entry: dict[str, Any]) -> None:
    graph.graph.setdefault("resolver_actions", []).append(entry)


def _annotate_conflict(conflict: dict[str, Any], decision: LLMDecision,
                        new_status: str,
                        risk: Optional[RiskAssessment] = None,
                        same_type: bool = True,
                        auto_applied: bool = False,
                        canonical: Optional[str] = None) -> None:
    entry = {
        "model": decision.model,
        "decision": decision.decision,
        "confidence": round(decision.confidence, 3),
        "reasoning": decision.reasoning,
        "key_signals": decision.key_signals,
        "open_questions": decision.open_questions,
        "elapsed_s": decision.elapsed_s,
        "reviewed_at": datetime.utcnow().isoformat(),
    }
    if risk is not None:
        entry["risk"] = risk.as_dict()
        proposal = build_proposal(
            conflict=conflict,
            decision=decision.decision,
            confidence=decision.confidence,
            same_type=same_type,
            risk_dict=risk.as_dict(),
            auto_applied=auto_applied,
            canonical=canonical,
        )
        entry["proposal"] = proposal.as_dict()
        # Mirror proposal at the top level so review-queue consumers
        # don't need to dig into the latest llm_review entry.
        conflict["proposal"] = proposal.as_dict()
    conflict.setdefault("llm_review", []).append(entry)
    conflict.setdefault("resolution", {})["status"] = new_status


# ---------------------------------------------------------------------------
# Cache (avoid re-paying inference time when re-running)
# ---------------------------------------------------------------------------

def _load_cache(path: str) -> dict[str, dict]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_cache(path: str, cache: dict[str, dict]) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _decision_to_dict(d: LLMDecision) -> dict[str, Any]:
    return {
        "decision": d.decision,
        "confidence": d.confidence,
        "reasoning": d.reasoning,
        "key_signals": d.key_signals,
        "open_questions": d.open_questions,
        "raw_response": d.raw_response,
        "model": d.model,
        "elapsed_s": d.elapsed_s,
    }


def _decision_from_dict(d: dict[str, Any]) -> LLMDecision:
    return LLMDecision(
        decision=d["decision"],
        confidence=float(d["confidence"]),
        reasoning=d.get("reasoning", ""),
        key_signals=list(d.get("key_signals", []) or []),
        open_questions=list(d.get("open_questions", []) or []),
        raw_response=d.get("raw_response", ""),
        model=d.get("model", "?"),
        elapsed_s=float(d.get("elapsed_s", 0.0)),
    )


# ---------------------------------------------------------------------------
# Main pass
# ---------------------------------------------------------------------------

@dataclass
class LLMResolverStats:
    model: str
    risk_threshold: float
    total_review_clusters: int
    decisions_attempted: int = 0
    decisions_failed: int = 0
    cached_hits: int = 0
    autonomous_merges: int = 0
    autonomous_links_upgraded: int = 0
    autonomous_false_positives_removed: int = 0
    autonomous_aliases_marked: int = 0
    autonomous_shared_mailboxes_marked: int = 0
    autonomous_emails_flagged_for_reassignment: int = 0
    flagged_for_human: int = 0
    by_decision: dict[str, int] = field(default_factory=dict)
    by_recommended: dict[str, int] = field(default_factory=dict)
    risk_score_p50: float = 0.0
    risk_score_p95: float = 0.0
    risk_score_max: float = 0.0
    avg_call_seconds: float = 0.0
    total_seconds: float = 0.0

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def llm_resolve_pending(graph: nx.MultiDiGraph,
                         model: str = DEFAULT_MODEL,
                         ollama_url: str = DEFAULT_OLLAMA_URL,
                         risk_threshold: float = DEFAULT_RISK_THRESHOLD,
                         cache_file: Optional[str] = DEFAULT_CACHE_FILE,
                         max_clusters: Optional[int] = None,
                         verbose: bool = False,
                         high_threshold: Optional[float] = None) -> LLMResolverStats:
    """Walk the graph's review queue and let the LLM decide. Modify in place.

    Each decision is fed into a risk assessment (`risk.assess_risk`) that
    weighs the LLM's confidence against the cost of being wrong about the
    specific action that decision would trigger. Acts autonomously only when
    `risk_score < risk_threshold`; otherwise routes to the human queue with
    the assessment attached.

    `high_threshold` is kept as a back-compat shim — if provided, it is
    ignored in favour of the risk policy but logged so callers know.
    """
    if high_threshold is not None:
        print(f"  (note: --threshold/--high-threshold is deprecated in favour "
              f"of --risk-threshold; ignoring value {high_threshold})")
    print("=" * 60)
    print(f"LLM Resolver — model: {model}")
    print(f"  Endpoint: {ollama_url}")
    print(f"  Risk threshold: {risk_threshold} (lower = stricter; act autonomously when risk < this)")
    print("=" * 60)

    cache = _load_cache(cache_file) if cache_file else {}

    pending = [
        c for c in graph.graph.get("conflicts", [])
        if c.get("conflict_type") in ("entity_match_review",
                                        "employee_name_inconsistency")
        and c.get("resolution", {}).get("status") == "pending_review"
    ]
    if max_clusters:
        pending = pending[:max_clusters]

    stats = LLMResolverStats(
        model=model,
        risk_threshold=risk_threshold,
        total_review_clusters=len(pending),
    )
    if not pending:
        print("  No pending review clusters. Nothing to do.")
        return stats

    print(f"  Pending review clusters: {len(pending)}")
    print()

    elapsed_total = 0.0

    for idx, conflict in enumerate(pending, 1):
        ctype = conflict.get("conflict_type")

        # ----- Build payload + identify the cluster + pick prompt kind -----
        if ctype == "entity_match_review":
            member_ids = conflict.get("members", [])
            if not member_ids:
                continue
            cluster_id = "+".join(sorted(member_ids))
            payload = build_cluster_payload(graph, conflict)
            prompt_kind = "entity_match"
        elif ctype == "employee_name_inconsistency":
            entity_id = conflict.get("entity_id")
            if not entity_id:
                continue
            member_ids = [entity_id]
            cluster_id = f"emp_name:{entity_id}"
            payload = build_employee_name_payload(graph, conflict)
            prompt_kind = "employee_name_mismatch"
        else:
            continue  # unsupported conflict type

        # ----- Cache lookup or LLM call -----
        if cluster_id in cache:
            decision = _decision_from_dict(cache[cluster_id])
            stats.cached_hits += 1
            if verbose:
                print(f"  [{idx}/{len(pending)}] (cached) {decision.decision} "
                      f"conf={decision.confidence:.2f}  type={ctype}")
        else:
            try:
                decision = resolve_cluster_with_llm(payload, model, ollama_url,
                                                      prompt_kind=prompt_kind)
                cache[cluster_id] = _decision_to_dict(decision)
                stats.decisions_attempted += 1
                elapsed_total += decision.elapsed_s
                if verbose:
                    print(f"  [{idx}/{len(pending)}] {decision.decision} "
                          f"conf={decision.confidence:.2f} ({decision.elapsed_s:.1f}s) "
                          f"type={ctype}")
            except Exception as exc:
                stats.decisions_failed += 1
                print(f"  [{idx}/{len(pending)}] LLM call FAILED: {exc}")
                conflict.setdefault("llm_review", []).append({
                    "model": model,
                    "error": str(exc),
                    "reviewed_at": datetime.utcnow().isoformat(),
                })
                continue

        stats.by_decision[decision.decision] = stats.by_decision.get(decision.decision, 0) + 1

        same_type = _is_same_type(graph, member_ids) if len(member_ids) > 1 else True
        rules_review_reason = conflict.get("review_reason") or ""
        has_id_conflict = (
            "tax_id" in rules_review_reason.lower()
            or "disagree" in rules_review_reason.lower()
            or "_id" in rules_review_reason.lower()
        )

        # ---- RISK ASSESSMENT — what would it cost us to be wrong here? ----
        risk = assess_risk(
            decision=decision.decision,
            confidence=decision.confidence,
            same_type=same_type,
            cluster_size=len(member_ids),
            has_identifier_conflict=has_id_conflict,
            model=decision.model,
            risk_threshold=risk_threshold,
        )
        stats.by_recommended[risk.recommended] = (
            stats.by_recommended.get(risk.recommended, 0) + 1
        )

        # ---- ACT on the decision (only if risk says it's safe) ----
        audit_tag = {
            "decided_by": "llm",
            "model": decision.model,
            "llm_decision": decision.decision,
            "llm_confidence": decision.confidence,
            "llm_reasoning": decision.reasoning,
            "decided_at": datetime.utcnow().isoformat(),
            "members": member_ids,
            "risk": risk.as_dict(),
        }

        canonical_node: Optional[str] = None

        if risk.recommended == "auto_act":
            if decision.decision == "same_entity":
                if same_type and len(member_ids) > 1:
                    canon = _pick_canonical(graph, member_ids)
                    canonical_node = canon
                    for alias in member_ids:
                        if alias == canon or not graph.has_node(alias):
                            continue
                        _merge_nodes(graph, canon, alias,
                                      {**audit_tag, "canonical": canon})
                        stats.autonomous_merges += 1
                    audit_tag["action_taken"] = "merged_same_type"
                    audit_tag["canonical"] = canon
                else:
                    upgraded = _upgrade_same_as_edges(
                        graph, member_ids,
                        new_status="auto_linked",
                        new_score=decision.confidence,
                        new_reasons=[f"LLM ({decision.model}): {decision.reasoning}"],
                    )
                    stats.autonomous_links_upgraded += upgraded
                    audit_tag["action_taken"] = "upgraded_same_as"
                    audit_tag["edges_upgraded"] = upgraded
                _annotate_conflict(conflict, decision,
                                    new_status="auto_resolved_by_llm",
                                    risk=risk,
                                    same_type=same_type,
                                    auto_applied=True,
                                    canonical=canonical_node)

            elif decision.decision == "different":
                removed = _remove_same_as_edges(graph, member_ids)
                stats.autonomous_false_positives_removed += removed
                audit_tag["action_taken"] = "removed_false_positive_same_as"
                audit_tag["edges_removed"] = removed
                _annotate_conflict(conflict, decision,
                                    new_status="auto_resolved_by_llm",
                                    risk=risk,
                                    same_type=same_type,
                                    auto_applied=True)

            # ---- New: employee_name_inconsistency decisions ----
            elif decision.decision == "alias":
                alias_names = list(conflict.get("signature_variants", {}).keys())
                _mark_alias(graph, member_ids[0], alias_names, audit_tag)
                stats.autonomous_aliases_marked += 1
                audit_tag["action_taken"] = "marked_alias"
                audit_tag["aliases_added"] = alias_names
                _annotate_conflict(conflict, decision,
                                    new_status="auto_resolved_by_llm",
                                    risk=risk, same_type=True, auto_applied=True)

            elif decision.decision == "shared_mailbox":
                _mark_shared_mailbox(graph, member_ids[0], audit_tag)
                stats.autonomous_shared_mailboxes_marked += 1
                audit_tag["action_taken"] = "marked_shared_mailbox"
                _annotate_conflict(conflict, decision,
                                    new_status="auto_resolved_by_llm",
                                    risk=risk, same_type=True, auto_applied=True)

            elif decision.decision == "wrong_assignment":
                # The LLM's reasoning often names the actual signer; pull from
                # signature_variants (top-1 signer is the most likely actual sender).
                top_signer = None
                variants = conflict.get("signature_variants", {})
                if variants:
                    top_signer = max(variants.items(), key=lambda kv: kv[1])[0]
                flagged = _flag_email_reassignment(graph, member_ids[0],
                                                     top_signer, audit_tag)
                stats.autonomous_emails_flagged_for_reassignment += flagged
                audit_tag["action_taken"] = "flagged_email_reassignment"
                audit_tag["emails_flagged"] = flagged
                audit_tag["suggested_signer"] = top_signer
                _annotate_conflict(conflict, decision,
                                    new_status="auto_resolved_by_llm",
                                    risk=risk, same_type=True, auto_applied=True)

            else:
                # Shouldn't reach here — risk module returns 'escalate' for uncertain
                _annotate_conflict(conflict, decision,
                                    new_status="pending_human_after_llm",
                                    risk=risk,
                                    same_type=same_type,
                                    auto_applied=False)
                stats.flagged_for_human += 1
                audit_tag["action_taken"] = "escalated_uncertain"
        else:
            # Risk too high (low confidence × destructive action, or uncertain) — escalate
            _annotate_conflict(conflict, decision,
                                new_status="pending_human_after_llm",
                                risk=risk,
                                same_type=same_type,
                                auto_applied=False)
            stats.flagged_for_human += 1
            audit_tag["action_taken"] = "escalated_high_risk"
            audit_tag["escalation_reason"] = risk.rationale

        _log_action(graph, audit_tag)

        if verbose:
            print(f"        risk={risk.risk_score} action={audit_tag['action_taken']} "
                  f"(would_be={risk.action}, reversibility={risk.reversibility})")

    if cache_file:
        _save_cache(cache_file, cache)

    if stats.decisions_attempted:
        stats.avg_call_seconds = round(elapsed_total / stats.decisions_attempted, 2)
    stats.total_seconds = round(elapsed_total, 2)

    # Aggregate risk-score distribution from the conflicts we just touched
    risk_scores: list[float] = []
    for c in pending:
        rev = c.get("llm_review", [])
        if rev and "risk" in rev[-1]:
            risk_scores.append(rev[-1]["risk"]["risk_score"])
    if risk_scores:
        risk_scores.sort()
        n = len(risk_scores)
        stats.risk_score_p50 = round(risk_scores[n // 2], 2)
        stats.risk_score_p95 = round(risk_scores[min(n - 1, int(n * 0.95))], 2)
        stats.risk_score_max = round(risk_scores[-1], 2)

    print()
    print(f"  Done. attempts={stats.decisions_attempted} cached={stats.cached_hits} "
          f"failed={stats.decisions_failed}")
    print(f"  Autonomous: {stats.autonomous_merges} merges, "
          f"{stats.autonomous_links_upgraded} link upgrades, "
          f"{stats.autonomous_false_positives_removed} false-positive removals")
    print(f"  Flagged for human: {stats.flagged_for_human}")
    print(f"  Decision mix: {stats.by_decision}")
    print(f"  Risk-recommended mix: {stats.by_recommended}")
    print(f"  Risk-score distribution: p50={stats.risk_score_p50} "
          f"p95={stats.risk_score_p95} max={stats.risk_score_max} "
          f"(threshold={risk_threshold})")
    print(f"  Total inference time: {stats.total_seconds}s "
          f"(avg {stats.avg_call_seconds}s/cluster)")
    print()

    graph.graph.setdefault("llm_resolver_runs", []).append({
        "ran_at": datetime.utcnow().isoformat(),
        **stats.as_dict(),
    })
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the LLM-driven resolver on review-queue clusters.")
    parser.add_argument("--graph", required=True,
                        help="Input graph (output of resolver.py)")
    parser.add_argument("--output", default=None,
                        help="Where to write the LLM-enriched graph "
                             "(default: <graph>.llm_resolved.json)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Ollama model name (default: {DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--risk-threshold", type=float, default=DEFAULT_RISK_THRESHOLD,
                        help="Maximum risk score (error_probability x cost_of_error) "
                             "tolerated for autonomous action; lower = stricter. "
                             f"Default: {DEFAULT_RISK_THRESHOLD}")
    parser.add_argument("--threshold", type=float, default=None,
                        help="DEPRECATED: legacy confidence threshold; ignored, "
                             "use --risk-threshold instead.")
    parser.add_argument("--cache-file", default=DEFAULT_CACHE_FILE,
                        help="JSON cache to skip re-running clusters")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable the decision cache")
    parser.add_argument("--max-clusters", type=int, default=None,
                        help="Cap clusters processed (handy for smoke tests)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    out_path = args.output or args.graph.replace(".json", ".llm_resolved.json")
    cache_file = None if args.no_cache else args.cache_file

    graph = load_graph(args.graph)
    print(f"Loaded graph: {graph.number_of_nodes()} nodes, "
          f"{graph.number_of_edges()} edges, "
          f"{len(graph.graph.get('conflicts', []))} conflicts")
    print()

    stats = llm_resolve_pending(
        graph,
        model=args.model,
        ollama_url=args.ollama_url,
        risk_threshold=args.risk_threshold,
        high_threshold=args.threshold,
        cache_file=cache_file,
        max_clusters=args.max_clusters,
        verbose=args.verbose,
    )

    save_graph(graph, out_path)
    print()
    print("=" * 60)
    print("LLM RESOLVER COMPLETE")
    print("=" * 60)
    print(json.dumps(stats.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
