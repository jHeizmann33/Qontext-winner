# Qontext-winner

Entity-resolution work for the Qontext hackathon, exploring how to dedupe and link
business records across heterogeneous enterprise sources (clients ↔ vendors).
The dataset is the public **AST-FRI/EnterpriseBench** dataset on HuggingFace.

The repo evolved through three layers, all kept here so the trajectory is visible:

```
.
├── ingestion/              ← primary deliverable: graph-based entity resolver
│   ├── resolver.py         ← cross-source entity resolution (clusters, merges, same_as edges)
│   ├── normalize.py        ← string normalisation helpers
│   ├── graph_utils.py      ← NetworkX graph + provenance helpers (from Jannik098/qontext)
│   └── ingest_bm.py        ← Business_and_Management ingester (from Jannik098/qontext)
│
├── pipeline/               ← earlier exploration: standalone Python pipeline
│   │                          (no graph, just rules + JSON in/out)
│   ├── load.py
│   ├── normalize.py
│   ├── strategies.py
│   ├── resolver.py
│   └── run.py
│
├── prompts/                ← LLM resolver prompt for ambiguous cases (not yet wired)
│   └── resolver.business_and_management.md
│
├── output/                 ← result artefacts from the standalone pipeline run
│   ├── report.md
│   ├── stats.json
│   ├── review_queue.json
│   └── singletons.json
│
└── src/, index.html, ...   ← Vite + React + TS demo (initial UI sketch with sample data)
```

## What the resolver does

`ingestion/resolver.py` runs after source ingesters have populated a NetworkX
knowledge graph. The standard `add_node()` only catches conflicts when the
*same* `node_id` is added twice; the resolver catches the harder case:
**two records with different `node_id`s that refer to the same real-world
entity**.

Example from the EnterpriseBench data:
- `Client:3a578a8e-a948-...` from `clients.json` (UUID-based)
- `Vendor:vendor_285` from `vendors.json` (positional id)
- Both are "Hickman Ltd" — same business, different relationship roles.

Decision per cluster:

| Cluster shape                | Confidence      | Action                                                    |
|------------------------------|-----------------|-----------------------------------------------------------|
| Same type (Client + Client)  | ≥ 0.85          | **Merge** — properties combined, edges rewired, alias dropped |
| Cross type (Client + Vendor) | ≥ 0.75          | **`same_as` edge** — keep distinct (per architecture decision D001) |
| Any cluster                  | < threshold     | Flag in `graph.conflicts` for human review + linked with `status: needs_review` |
| Identifier disagreement      | (e.g. tax_id)   | Score capped at 0.55 → review queue, never auto-merged    |

Eight match strategies feed into a noisy-OR score: `tax_id`, exact normalised
name, fuzzy name (SequenceMatcher), address, ZIP+address, industry, contact
email, phone, representative employee.

## How to run

You'll need the EnterpriseBench data locally first (it's a gated HF dataset):

```bash
pip install huggingface_hub networkx
hf auth login                                  # use a Read token

hf download AST-FRI/EnterpriseBench \
  Business_and_Management/clients.json \
  Business_and_Management/vendors.json \
  --repo-type dataset \
  --local-dir ./EnterpriseBench-data
```

Then build a graph and run the resolver:

```bash
cd ingestion

# 1) Ingest B&M into a NetworkX graph
python ingest_bm.py \
  --data-dir ../EnterpriseBench-data \
  --output ../bm_graph.json

# 2) Run cross-source entity resolution
python resolver.py \
  --graph ../bm_graph.json \
  --output ../bm_graph.resolved.json \
  --verbose
```

Expected output on the full B&M dataset (400 clients + 400 vendors):

```
Compared 737 pairs in-block, 76 above link threshold (50%)
Found 45 multi-member clusters (out of 738 total groups)
-> 0 merges, 172 same_as edges added, 45 clusters flagged for review
```

The 45 review clusters include matches like:
- `Hickman Ltd` (Client, Education) ↔ `Hickman Inc` (Vendor, Hospitality)
- `Hogan PLC` ↔ `Hogan Corp` (both Education)
- a 6-member `Johnson` cluster (5 Clients + 1 Vendor across 6 different industries
  — likely distinct businesses sharing a common surname)

The resolver intentionally refuses to auto-merge any of them because every
candidate pair has a `tax_id` mismatch — this is the conservative behaviour the
hackathon judging criteria reward ("auto-resolve easy conflicts, surface
ambiguous ones for humans").

## Folder origins & attribution

- `ingestion/graph_utils.py` and `ingestion/ingest_bm.py` come from
  **[Jannik098/qontext](https://github.com/Jannik098/qontext)** — the upstream
  hackathon repository — and are needed as runtime dependencies of the resolver.
  They are unmodified.
- `ingestion/resolver.py` and `ingestion/normalize.py` were built here and
  contributed back upstream as Phase 5 of the qontext pipeline.
- `pipeline/`, `prompts/`, `output/`, `src/` are this repo's earlier
  experimentation — kept for reference.

## Limitations / not done

- No LLM layer for the 45 review-flagged clusters (intended next step: send
  ambiguous cases to Gemini or Claude with `prompts/resolver.business_and_management.md`).
- Resolver only configured for `Client + Vendor`. An `Employee` resolver across
  HR + email + GitHub records would be the obvious next pass.
- No API endpoint exposing the review queue.
- The Vite/React frontend (`src/`) renders **sample** records, not the real
  resolved data — wiring is left as a follow-up.
