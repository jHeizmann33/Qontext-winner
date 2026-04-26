# Cross-source entity resolver

Phase 5 of the ingestion pipeline. Identifies records that refer to the same
real-world entity across heterogeneous source systems (e.g. a `Client` UUID
matching a `Vendor` short-code), then either merges them, links them, or
escalates to a human review queue.

The resolver runs in **two stages**:

1. **Rules-based** (`ingestion/resolver.py`) — fast, deterministic. 8 match
   strategies (tax_id, exact name, fuzzy name, address, ZIP+address, industry,
   email, phone, representative employee) combined via noisy-OR scoring. Same-
   type pairs above 0.85 confidence are merged; cross-type pairs above 0.75
   become `same_as` edges. Anything below — or with an identifier conflict
   like mismatched tax_ids — lands in `graph.conflicts` for later resolution.

2. **LLM-driven** (`ingestion/llm_resolver.py`) — for every conflict the rules
   layer flagged, asks a local LLM (via Ollama) to make the
   `same_entity / different / uncertain` call. Each decision is then evaluated
   by a **risk-based policy** (`ingestion/risk.py`) that combines the LLM's
   stated confidence with the cost of being wrong about the *specific* action
   that decision would trigger. Acts autonomously only when
   `risk_score < risk_threshold`; otherwise routes to the human queue with
   the assessment attached.

## Files added in this phase

| File | Role |
|---|---|
| [`ingestion/normalize.py`](../ingestion/normalize.py) | String normalisation helpers (business name, address, phone, email) |
| [`ingestion/resolver.py`](../ingestion/resolver.py) | Rules-based resolver (Phase 5b) |
| [`ingestion/prompts.py`](../ingestion/prompts.py) | System prompt + 3 few-shot examples for the LLM |
| [`ingestion/llm_resolver.py`](../ingestion/llm_resolver.py) | LLM-based resolver (Phase 5c), Ollama-backed |
| [`ingestion/risk.py`](../ingestion/risk.py) | Risk-based decision policy (cost × probability) |
| [`ingestion/proposals.py`](../ingestion/proposals.py) | Builds confirmable action proposals per conflict |
| [`ingestion/apply_proposal.py`](../ingestion/apply_proposal.py) | CLI to confirm or override a proposal |
| [`ingestion/detectors.py`](../ingestion/detectors.py) | Post-ingestion conflict detectors (employee name inconsistency etc.) |
| [`bm_graph.llm_resolved.json`](../bm_graph.llm_resolved.json) | Sample output: full B&M dataset run through both stages |

`ingestion/run_all.py` is wired so both phases execute as part of the standard
pipeline (Phase 5b is on by default; Phase 5c is opt-in via `--llm-resolve`).

## Dependencies

```bash
pip install networkx requests
```

That's it for the rules layer. For the LLM layer you also need
[Ollama](https://ollama.com/download) running locally:

```bash
# Once Ollama is installed and its background service is running:
ollama pull llama3.2:3b      # ~2 GB, the default model

# Optional, better quality but slower:
# ollama pull qwen2.5:7b     # ~4.7 GB
```

The LLM resolver talks to Ollama at `http://localhost:11434` (override with
`--ollama-url`). No API key, no network calls beyond localhost.

## Running it

End-to-end via the orchestrator (recommended):

```bash
cd ingestion

# Rules layer only — no LLM needed:
python run_all.py --data-dir <path/to/Dataset> --output ../graph.json

# Rules layer + LLM layer:
python run_all.py --data-dir <path/to/Dataset> --output ../graph.json \
                  --llm-resolve --llm-model llama3.2:3b --verbose

# Skip the resolver entirely (e.g. just rebuild the raw graph):
python run_all.py --data-dir <path/to/Dataset> --output ../graph.json \
                  --skip-resolver
```

Standalone (handy when iterating on resolver logic without re-ingesting):

```bash
cd ingestion

# Step 1: build the raw graph from one source
python ingest_bm.py --data-dir <path/to/Dataset> --output ../bm_graph.json

# Step 2: rules-based resolution
python resolver.py --graph ../bm_graph.json \
                   --output ../bm_graph.resolved.json --verbose

# Step 3: LLM resolution of the review queue
python llm_resolver.py --graph ../bm_graph.resolved.json \
                       --output ../bm_graph.llm_resolved.json \
                       --model llama3.2:3b --verbose

# Quick smoke test (process only N clusters):
python llm_resolver.py --graph ../bm_graph.resolved.json \
                       --max-clusters 3 --verbose
```

The LLM resolver caches each cluster's decision in `.llm_resolver_cache.json`
so re-runs (e.g. when tuning the threshold) skip the LLM call for already-
seen clusters.

## Human-in-the-loop: confirmable proposals

Every conflict the resolver touches gets a `proposal` block at the top
level. The reviewer never has to figure out *what* to do — they only have
to **confirm or override** a concrete suggestion.

For autonomous resolutions (low risk), the proposal is a **post-hoc audit**:

```json
{
  "kind": "post_hoc_audit",
  "proposed_action": "remove_same_as_edges",
  "summary": "Resolved autonomously: Reject match for `Hickman Ltd` as false positive",
  "rationale": "Acted automatically because risk_score=1.5 < threshold=5.0...",
  "auto_applied": true,
  "requires_human_confirmation": false,
  "confidence_label": "high",
  "expected_changes": [
    "Delete 2 same_as edge(s) between the 2 members",
    "Records remain in graph as fully independent entities",
    "Conflict marked resolved as false-positive"
  ],
  "alternatives": [ ... ],
  "risk_score": 1.5,
  "risk_threshold": 5.0
}
```

For escalated conflicts (high risk or LLM uncertainty), the proposal is a
**pending recommendation** the human is asked to confirm:

```json
{
  "kind": "pending_confirmation",
  "proposed_action": "no_action",
  "summary": "Keep `Johnson Group` separate (LLM was uncertain — conservative default)",
  "rationale": "LLM could not decide between same_entity / different ...",
  "auto_applied": false,
  "requires_human_confirmation": true,
  "confidence_label": "low",
  "alternatives": [
    { "action": "upgrade_to_auto_linked", "description": "..." },
    { "action": "remove_same_as_edges",   "description": "..." },
    { "action": "investigate_further",    "description": "..." }
  ],
  ...
}
```

### Confirming or overriding from the CLI

```bash
cd ingestion

# 1) See what's pending:
python apply_proposal.py --graph ../graph.json --list-pending

# 2) Confirm the proposed action for conflict #2:
python apply_proposal.py --graph ../graph.json --conflict 2 --confirm \
                         --reason "verified by sales team" \
                         --decided-by "alice@inazuma.co"

# 3) Override with a different action:
python apply_proposal.py --graph ../graph.json --conflict 2 \
                         --action remove_same_as_edges \
                         --reason "they're definitely separate companies — different industries" \
                         --decided-by "alice@inazuma.co"
```

Available actions when confirming/overriding (see `proposals.py` for full
descriptions):

| Action | Effect |
|---|---|
| `merge_nodes` | Collapse same-type nodes into one canonical (DESTRUCTIVE) |
| `upgrade_to_auto_linked` | Confirm cross-type same_as link |
| `remove_same_as_edges` | Drop the same_as edges (false positive) |
| `no_action` | Leave as-is (status quo) |
| `investigate_further` | Mark for follow-up; no graph mutation |

Every confirmation/override appends an entry to `graph.resolver_actions`
with `decided_by`, `applied_action`, `applied_at`, `reason`, and the
proposal it was based on — so the chain from LLM verdict to risk
assessment to proposal to human decision is fully auditable.

## What ends up in the graph

After Phase 5c, three new artefact families live on the graph:

- **`graph.edges` of `rel_type="same_as"`** — bidirectional links between
  cross-source records the resolver thinks refer to the same real-world
  entity. `properties.status` is one of:
    - `"auto_linked"` — high-confidence LLM decision
    - `"needs_review"` — rules layer linked them, LLM hasn't run yet OR LLM
      was uncertain
- **`graph.conflicts[i].llm_review`** — the LLM's structured response for
  every cluster it touched (`decision`, `confidence`, `reasoning`,
  `key_signals`, `open_questions`, `model`, `reviewed_at`). Always present
  when the LLM was consulted, even when it acted autonomously.
- **`graph.conflicts[i].resolution.status`** — life-cycle state:
    - `"auto_resolved_by_llm"` — LLM made a high-confidence call, already acted on
    - `"pending_human_after_llm"` — LLM was uncertain or low-confidence, needs human
    - `"pending_review"` — LLM never got to it (e.g. Ollama timeout)

## Sample run results (full B&M dataset)

`bm_graph.llm_resolved.json` was produced from the 800-record
`Business_and_Management/` subset (400 clients + 400 vendors). Headline:

| Stage | Number |
|---|---|
| Records ingested | 800 |
| Pair comparisons (after blocking) | 737 |
| Clusters flagged by rules layer | 45 |
| Autonomously resolved by LLM (≥ 0.85 conf) | 39 (87%) |
| Escalated to human (low confidence / uncertain) | 4 |
| Failed (Ollama timeout, retryable) | 2 |
| `same_as` edges removed as false positives | 94 (168 → 74) |

Total LLM compute: 41 minutes on a CPU laptop with `llama3.2:3b`.

The escalated clusters are exactly the surname-style cases where multiple
records share a common name (Johnson, Williams, Reyes, Hudson) but spread
across distinct industries — i.e. cases where genuine human judgement is
needed and the LLM correctly recognised that.

## Risk-based decision policy

The LLM resolver does NOT use a flat confidence threshold. Each decision
goes through `risk.assess_risk(...)`, which computes:

```
error_probability = max(0, 1 - llm_confidence)         # how likely LLM is wrong
final_cost        = base_cost(action) × modifiers      # damage if wrong
risk_score        = error_probability × final_cost     # expected damage
recommended       = "auto_act"  if risk < risk_threshold
                    else "escalate"                    # route to human queue
```

**Action cost matrix** (in `risk.py`):

| Action | base_cost | reversibility | what it does |
|---|---|---|---|
| `remove_same_as_edges` | 15 | trivial | Drop a false-positive cross-source link |
| `upgrade_to_auto_linked` | 40 | medium | Promote a cross-type same_as edge |
| `merge_nodes` | 90 | hard | Collapse two same-type nodes (destructive) |

**Cost modifiers stack on top:**

| Modifier | Multiplier | When it fires |
|---|---|---|
| Cluster size > 3 | ×1.3 | More members = more chances for error |
| LLM overrides identifier conflict | ×1.6 | LLM says "same" despite a tax_id disagreement |
| Small LLM (3b/1b/phi3/etc.) | ×1.25 | Smaller models hallucinate corroborating signals |
| LLM itself reported `uncertain` | ×2.0 | Don't act on self-confessed uncertainty |

Default `risk_threshold` is **5.0**. Concrete examples at this threshold:

- `different` decision (cost=15, no modifiers, conf=0.92) → risk=1.2 → **auto_act**
- `same_entity` cross-type (cost=40 ×1.6 ×1.25 = 80, conf=0.98) → risk=1.6 → **auto_act**
- Same as above but conf=0.85 → risk=12 → **escalate**
- `merge_nodes` (cost=90 ×1.25=112, conf=0.92) → risk=8.96 → **escalate**

Every conflict's `llm_review[i].risk` block records the full breakdown
(action, base_cost, applied modifiers, final_cost, error_probability,
risk_score, recommended, rationale) so the policy is fully auditable.

## Tuning

| Knob | Effect |
|---|---|
| `--risk-threshold 1.5` | Stricter — only the most certain low-cost actions auto-execute. |
| `--risk-threshold 10` | Looser — accepts more auto-merges; useful with a stronger model. |
| `--llm-model qwen2.5:7b` | Better calibration on tricky cases (also drops the small-model cost penalty). |
| `--max-clusters 10` | Cap for smoke tests / debugging. |
| `--no-cache` | Disable the decision cache (force fresh LLM calls). |
| `--threshold 0.85` | DEPRECATED legacy flag; ignored — use `--risk-threshold`. |

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

61 tests cover:
- `tests/test_risk.py` — cost matrix, modifiers, decision boundary, regression
  guards for the real B&M observed cases (Parrish/Gomez, Johnson cluster, etc.)
- `tests/test_proposals.py` — all 5 action types, auto vs pending kinds,
  alternatives logic (cross-type excludes merge), confidence labels,
  expected_changes, JSON round-trip
- `tests/test_resolver_e2e.py` — synthetic 3-cluster mini-graph end-to-end
  with mocked LLM: verifies merge actually mutates the graph, "different"
  removes edges, "uncertain" stays in queue, every conflict gets a proposal,
  audit trail recorded, apply_proposal confirm + override flows work

The E2E tests mock the Ollama HTTP call (`unittest.mock.patch`) so they
run offline and deterministically — no model download needed in CI.

## Conflict types handled

The system handles two distinct conflict patterns; each has its own LLM prompt
and decision schema, but flows through the same risk policy + proposal layer.

### `entity_match_review` (from `resolver.py`)

Two records with different `node_id`s that look like they refer to the same
real-world entity (e.g. `Client:UUID` vs `Vendor:short-code` for the same
business). The LLM picks one of:

| Decision | Action |
|---|---|
| `same_entity` (same-type cluster) | `merge_nodes` |
| `same_entity` (cross-type cluster) | `upgrade_to_auto_linked` |
| `different` | `remove_same_as_edges` |
| `uncertain` | `no_action` (escalate) |

### `employee_name_inconsistency` (from `detectors.py`)

An Employee with HR-canonical name X has emails sent under their `emp_id`
that are signed by completely different name(s) Y, Z. The LLM picks one of:

| Decision | Action | What it does |
|---|---|---|
| `alias` | `mark_alias` | Adds the foreign signatures to `aliases` on the Employee node |
| `shared_mailbox` | `mark_shared_mailbox` | Sets `is_shared_mailbox=True` on the Employee node |
| `wrong_assignment` | `flag_email_reassignment` | Marks affected emails `_sender_assignment_disputed=True` (does NOT rewire — too risky autonomous) |
| `uncertain` | `no_action` (escalate) | Stays in human queue |

In the validation run on the full EnterpriseBench dataset, the detectors
surfaced **494 employee name inconsistencies** on top of the 45
entity-match clusters — a 12x increase in actionable conflicts.

After adding the Product within-source rule and the Policy ingester /
within-rule, the totals on the full dataset are:

| Source | Conflicts found |
|---|---|
| Client + Vendor (`business_orgs`) | 45 |
| Product within-source (`products`) | 9 (e.g. Fire-Boltt, Samsung Galaxy duplicates) |
| Policy within-source (`policies`) | 0 (24 distinct policy documents — no dupes) |
| Email signature mismatches (`employee_name_inconsistency`) | 494 |
| **Total** | **548** |

## Architectural notes

- The resolver is **type-agnostic.** `BUSINESS_ORG_RULE` in `resolver.py`
  is one configured pass; adding a `EMPLOYEE_RULE` covering Employee records
  across HR, email, GitHub etc. is the obvious next step (same code path,
  different config).
- The system **respects D001** (keep entity types distinct): cross-type
  matches always become `same_as` edges, never destructive merges.
- **Identifier conflicts veto auto-merges.** If matched records have
  different values for an identifier field (`tax_id` for orgs), the rules
  layer caps the score at 0.55 and mandates review — the LLM then has the
  full record context to decide whether the disagreement is a real
  separation or just dirty data.
- **All LLM decisions are logged with provenance.** Nothing happens
  silently — every autonomous merge or edge upgrade has a corresponding
  `conflict.llm_review` entry with the model, confidence, and reasoning
  the decision was based on, and an `ingested_at`-style timestamp.
