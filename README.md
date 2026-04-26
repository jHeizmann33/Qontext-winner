# Qontext

A persistent, inspectable **company context base** built from the AST-FRI / EnterpriseBench dataset.

This repo consolidates the work originally split across:
- `Jannik098/qontext` (backend ingestion + graph)
- `jHeizmann33/qontext-enhanced` (React frontend)
- `jHeizmann33/Qontext-winner` (entity-resolution submission, archived on the `legacy-hackathon` branch)

## What it is

Qontext turns a company's fragmented data — HR systems, CRM, emails, tickets, GitHub, policies — into a structured **knowledge graph** with per-fact provenance, a **virtual file system** that an AI or human can browse like Markdown, and **edit / extend** endpoints so humans can correct or annotate facts without ever touching the underlying source data.

Three things distinguish it from "RAG over a folder":

1. **Per-fact provenance.** Every property on every node carries source/file/record-id. Edits and human notes get their own `Human/vfs_edit` or `Human/vfs_note` provenance, so you always know who said what.
2. **Conflict resolution that involves humans only when it matters.** A rules layer (`ingestion/resolver.py`) auto-resolves easy cases; an LLM layer (`ingestion/llm_resolver.py`) reasons about the ambiguous ones; anything still uncertain lands in a review queue with full evidence and proposed actions.
3. **VFS as a navigable surface.** Pages cross-link via Markdown (`[Aguilar Inc](/clients/{id})`), notes attach as first-class `Note` nodes via an `annotates` edge, and edits are auditable through `graph.conflicts`.

## Architecture

```
Raw sources ──▶ ingestion/ ──▶ NetworkX graph ──▶ api/ ──▶ frontend/
                  (per-fact            │              │
                   provenance)         │              ├─ /vfs/{path}        browse
                                       │              ├─ /retrieve          hybrid graph + TF-IDF
                                       │              ├─ /conflicts         review queue
                                       │              ├─ PATCH /vfs/...     human edit
                                       │              └─ POST /vfs/.../notes  extend
                                       │
                                       └─ resolver + LLM resolver + detectors
                                          ↓
                                          graph.conflicts (auto-resolved + pending_review)
```

## Repository layout

```
api/                 FastAPI server, VFS generator, hybrid retriever, Cognee export
ingestion/           Per-source ingesters, resolver, LLM resolver, detectors, risk policy
docs/                CONTEXT, DECISIONS, LEARNINGS, RESOLVER, RETRIEVAL, TODO
tests/               Pytest suite for resolver, detectors, risk, proposals
frontend/            Vite + React + Tailwind UI (graph view, file browser, conflict queue)
run_qontext_api.py   Convenience launcher for the FastAPI server
```

## Quick start

### Backend

```bash
pip install fastapi uvicorn networkx pydantic
hf auth login                              # AST-FRI/EnterpriseBench is a gated dataset
hf download AST-FRI/EnterpriseBench --repo-type dataset --local-dir ./Dataset

# Build the graph from all sources
cd ingestion
python run_all.py --data-dir ../Dataset --output ../full_with_policies_resolved.json --verbose

# Start the API
cd ../api
python server.py --graph ../full_with_policies_resolved.json
# Browse http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
bun install            # or: npm install
bun dev                # or: npm run dev
```

## Key endpoints

| Endpoint | Purpose |
|---|---|
| `GET /vfs/`                          | Root directory of the virtual file system |
| `GET /vfs/people/{emp_id}`           | Stitched employee profile (HR + emails + tickets + clients) |
| `GET /vfs/policies/{slug}`           | Policy with category, summary, full text, notes |
| `GET /retrieve?q=...&mode=hybrid`    | Graph-grounded retrieval for AI consumption |
| `GET /conflicts?status=pending_review` | Human-review queue |
| `PATCH /vfs/{section}/{id}`          | Apply a human edit to any property; carries `Human/vfs_edit` provenance |
| `POST /vfs/{section}/{id}/notes`     | Attach a `Note` node via `annotates`; surfaces on the entity page and is retrievable |

## Ingestion sources covered

HR (employees + résumés), CRM (customers, products, sales, reviews, support chats), B&M (clients, vendors), Mail, Collaboration, IT tickets, GitHub, Overflow, Social, Policy markdown.

## Status

Working: graph construction with provenance, cross-source resolver + LLM resolver, hybrid retrieval, VFS pages with Markdown links, edit + extend endpoints with audit trail, policy browsing, conflict review queue.

Not yet wired: `/projects/` trajectory pages, automated change-propagation when source files mutate (the `_ADDED` PDFs are the intended demo), schema-detection layer for generalising to new datasets.

## License

Internal hackathon code; ask before redistributing the EnterpriseBench-derived artefacts.
