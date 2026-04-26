# Retrieval architecture

## Decision

Qontext keeps a single canonical knowledge graph in `NetworkX` and exposes one
retrieval layer on top of it.

We intentionally optimise for:

- deterministic IDs
- field-level provenance
- conflict resolution
- graph-grounded explainability
- low operational overhead

## What stays

### Canonical graph

The graph remains the source of truth.

That means:

- ingestion creates explicit nodes and edges
- facts keep provenance
- conflicts are reviewed on the graph itself

### Local retriever

`api/retrieval.py` adds a lightweight retrieval layer without introducing a new
database or service.

It combines:

- graph retrieval for explicit relationships
- local sparse TF-IDF retrieval for fuzzy matching
- hybrid ranking for natural-language questions over structured business data

This is the best current tradeoff for the project because it improves search
without creating a second truth system.

## What was cut from the runtime path

The server no longer depends on `cognee` for the main retrieval flow.

Reasons:

- the local retriever already covers the current product need
- the `cognee` integration added setup and failure modes
- it did not materially improve the main UI or explanation flow

`cognee` remains a possible future experiment, but it is not part of the active
runtime architecture.

## Current implementation

Files:

- `api/retrieval.py` - local graph + vector + hybrid retriever
- `api/server.py` - retrieval API and graph API

Main endpoint:

```text
GET /retrieve?q=which engineering employees handle client POCs&mode=auto
GET /retrieve?q=late delivery complaints&mode=vector
GET /retrieve?q=emp_0431&mode=graph
```

Status endpoint:

```text
GET /retrieval/status
```

## Design principle

The retrieval layer should stay downstream from the graph.

If we later add richer semantic recall, it should only be accepted when it:

- improves results measurably
- preserves provenance and explainability
- does not become a second source of truth
