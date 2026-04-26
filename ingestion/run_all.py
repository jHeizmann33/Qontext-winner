"""
run_all.py — Orchestrator for the ingestion pipeline.

Runs all ingesters in the correct order and produces the final graph.

Usage:
    python run_all.py --data-dir ./Dataset --output ./graph.json

The order matters:
    1. HR — establishes Employee + Department backbone
    2. CRM — establishes Customer + Product + Sale entities
    3. B&M — establishes Client + Vendor entities (TODO)
    4. Communications — Emails, Conversations, IT Tickets (TODO)
    5. GitHub, Overflow, Social (TODO)
    6. Support + Sentiment (TODO)
    7. PDFs (TODO)
"""

import argparse
import os
import time
from graph_utils import create_graph, save_graph, get_stats
from ingest_hr import ingest_hr
from ingest_crm import ingest_crm
from ingest_bm import ingest_bm
from ingest_communications import ingest_communications
from resolver import resolve_entities, BUSINESS_ORG_RULE, PRODUCT_RULE, POLICY_RULE
from detectors import detect_all
from ingest_policies import ingest_policies
from llm_resolver import (
    llm_resolve_pending,
    DEFAULT_MODEL as LLM_DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_RISK_THRESHOLD,
)
# Future imports:
# from ingest_github import ingest_github
# from ingest_overflow import ingest_overflow
# from ingest_social import ingest_social
# from ingest_support import ingest_support
# from ingest_pdfs import ingest_pdfs


def main():
    parser = argparse.ArgumentParser(description="Run full ingestion pipeline")
    parser.add_argument("--data-dir", required=True, help="Path to Dataset folder")
    parser.add_argument("--output", default="graph.json", help="Output graph file")
    parser.add_argument("--skip-resolver", action="store_true",
                        help="Skip the rules-based cross-source resolver (Phase 5b)")
    parser.add_argument("--llm-resolve", action="store_true",
                        help="Also run the LLM resolver (Phase 5c) on the "
                             "review queue. Requires Ollama running locally.")
    parser.add_argument("--llm-model", default=LLM_DEFAULT_MODEL,
                        help=f"Ollama model name (default: {LLM_DEFAULT_MODEL})")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL,
                        help=f"Ollama endpoint (default: {DEFAULT_OLLAMA_URL})")
    parser.add_argument("--llm-risk-threshold", type=float,
                        default=DEFAULT_RISK_THRESHOLD,
                        help=f"Max risk score (error_prob x cost_of_error) for "
                             f"autonomous action; lower = stricter "
                             f"(default: {DEFAULT_RISK_THRESHOLD})")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output (e.g. resolver blocking stats)")
    args = parser.parse_args()
    
    start_time = time.time()
    
    print("=" * 60)
    print("QONTEXT — Knowledge Graph Ingestion Pipeline")
    print("=" * 60)
    print(f"Data directory: {args.data_dir}")
    print(f"Output file: {args.output}")
    print()
    
    # Phase 1: Core entities
    graph = create_graph()
    ingest_hr(graph, args.data_dir)
    ingest_crm(graph, args.data_dir)
    ingest_bm(graph, args.data_dir)
    
    # Phase 2: Communication sources
    ingest_communications(graph, args.data_dir)

    # Phase 2b: Policy documents (markdown)
    ingest_policies(graph, args.data_dir, verbose=args.verbose)
    
    # Phase 3: Knowledge sources
    # ingest_github(graph, args.data_dir)
    # ingest_overflow(graph, args.data_dir)
    # ingest_social(graph, args.data_dir)
    
    # Phase 4: Cross-reference sources
    # ingest_support(graph, args.data_dir)   # support chats + sentiment
    
    # Phase 5: PDF extraction
    # ingest_pdfs(graph, args.data_dir)      # order PDFs + policy PDFs

    # Phase 5b: Cross-source entity resolution (rules-based)
    # Identifies records with different node_ids that refer to the same
    # real-world entity (e.g. a Client UUID matching a Vendor short-code).
    # Same-type pairs above threshold are merged; cross-type pairs become
    # `same_as` edges; ambiguous clusters are flagged in graph.conflicts.
    if not args.skip_resolver:
        resolve_entities(graph, rule=BUSINESS_ORG_RULE, verbose=args.verbose)
        resolve_entities(graph, rule=PRODUCT_RULE, verbose=args.verbose)
        resolve_entities(graph, rule=POLICY_RULE, verbose=args.verbose)
        # Phase 5b.2: post-ingestion conflict detectors (signature mismatches etc.)
        detect_all(graph, verbose=args.verbose)

    # Phase 5c: LLM-driven resolution of the rules layer's review queue
    # Walks `graph.conflicts[entity_match_review]`, asks a local LLM
    # (Ollama) for a same-entity / different / uncertain decision. High-
    # confidence decisions (>= --llm-threshold) are acted on autonomously
    # (merge, edge upgrade, or false-positive removal) with full audit log.
    # Lower-confidence decisions stay in the queue, enriched with the LLM's
    # reasoning so a human can act faster.
    if args.llm_resolve:
        llm_resolve_pending(
            graph,
            model=args.llm_model,
            ollama_url=args.ollama_url,
            risk_threshold=args.llm_risk_threshold,
            verbose=args.verbose,
        )

    # Save final graph
    save_graph(graph, args.output)
    
    # Print summary
    elapsed = time.time() - start_time
    stats = get_stats(graph)
    
    print("=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print(f"Time: {elapsed:.1f}s")
    print(f"Nodes: {stats['total_nodes']}")
    print(f"Edges: {stats['total_edges']}")
    print(f"Conflicts: {stats['total_conflicts']}")
    print()
    print("Nodes by type:")
    for node_type, count in sorted(stats["nodes_by_type"].items()):
        print(f"  {node_type}: {count}")
    print()
    print("Edges by type:")
    for rel_type, count in sorted(stats["edges_by_type"].items()):
        print(f"  {rel_type}: {count}")
    print()
    
    # Print conflict summary
    conflicts = graph.graph.get("conflicts", [])
    if conflicts:
        auto_resolved = sum(1 for c in conflicts if c.get("resolution", {}).get("status") == "auto_resolved")
        pending = sum(1 for c in conflicts if c.get("resolution", {}).get("status") == "pending_review")
        entity_review = sum(1 for c in conflicts if c.get("conflict_type") == "entity_match_review")
        print(f"Conflicts: {auto_resolved} auto-resolved, {pending} pending human review")
        if entity_review:
            print(f"  ({entity_review} of pending are cross-source entity-match reviews from the resolver)")

    # Print resolver summary
    resolver_runs = graph.graph.get("resolver_runs", [])
    for run in resolver_runs:
        print(f"Resolver `{run['rule']}`: "
              f"{run['nodes_considered']} nodes -> "
              f"{run['merges_performed']} merges, "
              f"{run['same_as_edges_added']} same_as edges, "
              f"{run['review_flags_added']} review-flagged clusters")


if __name__ == "__main__":
    main()
