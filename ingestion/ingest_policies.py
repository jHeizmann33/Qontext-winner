"""
ingest_policies.py — Ingest Policy_Documents (markdown) into the knowledge graph.

Each .md file becomes a Policy node with full content + extracted title.
The resolver can then detect within-source duplicates (e.g. "Information
Security Policy v1.md" vs "Information Security Policy.md") and a follow-up
LLM pass can flag cross-policy semantic conflicts (different retention
periods etc.).

Usage:
    python ingest_policies.py --data-dir <Dataset path> [--graph existing.json] --output graph.json
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from graph_utils import (  # type: ignore
        create_graph, load_graph, save_graph,
        make_node_id, add_node, make_provenance, get_stats,
    )
else:
    from .graph_utils import (
        create_graph, load_graph, save_graph,
        make_node_id, add_node, make_provenance, get_stats,
    )


SOURCE_SYSTEM = "Policy_Documents"
POLICY_SUBDIR = "Policy_Documents_md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NON_TITLE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """Stable slug for a filename — used as node_id key."""
    base = os.path.splitext(name)[0]
    s = _NON_TITLE.sub("-", base.lower()).strip("-")
    return s or "policy"


def _extract_title(markdown: str, fallback: str) -> str:
    """First non-empty heading or first non-empty line; else fallback."""
    for line in markdown.splitlines():
        s = line.strip()
        if not s:
            continue
        # Strip leading # symbols
        if s.startswith("#"):
            s = s.lstrip("#").strip()
        if s:
            return s[:200]
    return fallback


def _summarise(markdown: str, max_chars: int = 400) -> str:
    """Take the first paragraph(s) up to max_chars, skipping headings."""
    out: list[str] = []
    used = 0
    for line in markdown.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if used + len(s) > max_chars:
            out.append(s[: max_chars - used])
            break
        out.append(s)
        used += len(s) + 1
    return " ".join(out).strip()


def _category_from_name(name: str) -> Optional[str]:
    """Heuristic policy category from the filename."""
    n = name.lower()
    if "data" in n or "privacy" in n or "gdpr" in n:
        return "Data & Privacy"
    if "security" in n or "password" in n or "breach" in n or "information security" in n:
        return "Security"
    if "leave" in n or "medical" in n or "health" in n or "harassment" in n or "ethics" in n:
        return "People & HR"
    if "code" in n or "compliance" in n or "governance" in n:
        return "Compliance"
    if "expense" in n or "travel" in n or "reimbursement" in n:
        return "Finance"
    if "sdlc" in n or "software development" in n or "asset" in n:
        return "Engineering & IT"
    if "social" in n or "acceptable use" in n or "aup" in n:
        return "Communication"
    if "environment" in n or "sustainab" in n or "ecological" in n:
        return "ESG"
    if "performance" in n:
        return "Performance"
    if "risk" in n:
        return "Risk"
    return None


# ---------------------------------------------------------------------------
# Main ingester
# ---------------------------------------------------------------------------

def ingest_policies(graph, data_dir: str, verbose: bool = False) -> int:
    """Ingest all .md files in <data_dir>/Policy_Documents_md/. Returns count."""
    print("=" * 60)
    print(f"Ingesting: {SOURCE_SYSTEM}")
    print("=" * 60)

    folder = os.path.join(data_dir, POLICY_SUBDIR)
    if not os.path.isdir(folder):
        print(f"  Folder not found: {folder} — skipping")
        return 0

    # Only files that look like policy documents — skip invoices, READMEs, etc.
    def _looks_like_policy(name: str) -> bool:
        n = name.lower()
        if not n.endswith(".md") or n.startswith("."):
            return False
        if n.startswith(("invoice", "purchase_order", "shipping_order", "readme")):
            return False
        return True

    files = sorted(f for f in os.listdir(folder) if _looks_like_policy(f))
    skipped = [f for f in os.listdir(folder)
               if f.lower().endswith(".md") and not _looks_like_policy(f)]
    if skipped and verbose:
        print(f"  Skipping {len(skipped)} non-policy files: {skipped}")
    if not files:
        print(f"  No .md files found in {folder}")
        return 0

    ingested = 0
    for fname in files:
        path = os.path.join(folder, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            print(f"  ⚠ skipped {fname}: {exc}")
            continue
        if not content.strip():
            if verbose:
                print(f"  ⚠ skipped {fname}: empty file")
            continue

        slug = _slug(fname)
        node_id = make_node_id("Policy", slug)
        title = _extract_title(content, fallback=os.path.splitext(fname)[0])
        category = _category_from_name(fname)

        properties = {
            "title": title,
            "filename": fname,
            "category": category,
            "summary": _summarise(content),
            "content": content,
            "char_count": len(content),
            "line_count": content.count("\n") + 1,
            "source_format": "markdown",
        }
        properties = {k: v for k, v in properties.items() if v is not None}

        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file=fname,
            record_id=slug,
            confidence=1.0,
        )
        add_node(graph, node_id, "Policy", properties, provenance)
        ingested += 1

        if verbose:
            print(f"  + {node_id:<60} category={category!r:<25} chars={len(content)}")

    stats = get_stats(graph)
    graph.graph.setdefault("stats", {})["policies"] = {"ingested": ingested}
    print(f"  Ingested {ingested} policies")
    print(f"  Graph state: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print()
    return ingested


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest policy markdown files")
    parser.add_argument("--data-dir", required=True, help="Path to Dataset folder")
    parser.add_argument("--graph", default=None,
                        help="Existing graph file to extend (optional)")
    parser.add_argument("--output", default="graph.json", help="Output graph file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.graph and os.path.exists(args.graph):
        graph = load_graph(args.graph)
        print(f"Loaded existing graph: {graph.number_of_nodes()} nodes")
    else:
        graph = create_graph()

    ingest_policies(graph, args.data_dir, verbose=args.verbose)
    save_graph(graph, args.output)
