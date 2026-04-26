# Task tracker

## Current priorities

### 🔴 Up next
- [ ] **Phase 2: Build ingestion pipeline** — start with HR + CRM structured JSON sources
  - Parse employees.json → Employee + Department nodes
  - Parse resume_information.csv → enrich Employee nodes
  - Parse customers.json → Customer nodes
  - Parse products.json → Product nodes
  - Parse sales.json → Sale nodes + edges
  - Parse clients.json → Client nodes + edges to Employee
  - Parse vendors.json → Vendor nodes
  - Time estimate: 2-3 hrs

### 🟡 Queued
- [ ] **Phase 3: Communication sources** — emails, conversations, tickets, GitHub, overflow, social, support
  - Emails (11,928 records) — Employee edges + EmailThread entities
  - Conversations (2,897) — Employee edges
  - IT tickets (163) — Employee edges
  - GitHub (750) — Repo + Issue entities, Employee edges
  - Overflow (10,823) — Post entities with parent/child threading
  - Social (971) — Post entities
  - Support chats (1,000) — cross-reference Customer + Product + Employee
  - Product sentiment (13,510) — Review entities
  - Time estimate: 2-3 hrs

- [ ] **Phase 4: PDF extraction** — orders + policies
  - Order PDFs (~270 files) — structured extraction, link via customer_id in filename
  - Policy PDFs (24 files) — Gemini for semantic chunking + summarisation
  - Time estimate: 1-1.5 hrs

- [x] **Phase 5: Entity resolution + conflict detection** ✅ Done
  - [x] Cross-source identity matching (`ingestion/resolver.py` + `normalize.py`)
  - [x] Same-type clusters above 0.85 confidence → merged with provenance
  - [x] Cross-type clusters above 0.75 → `same_as` edges (respects D001)
  - [x] Identifier conflicts (e.g. tax_id mismatch) suppress auto-merge
  - [x] All ambiguous clusters land in `graph.conflicts` for human review
  - [x] Wired into `run_all.py` as Phase 5b (toggle: `--skip-resolver`)
  - First B&M validation run: 800 nodes (400 Client + 400 Vendor) → 45 review-flagged clusters, 172 same_as edges (e.g. Hickman Ltd ↔ Hickman Inc, 6-member Johnson cluster)

- [ ] **Phase 6: Virtual file system generator**
  - Template-based markdown generation from graph
  - Inline provenance annotations
  - Time estimate: 1-1.5 hrs

- [ ] **Phase 7: FastAPI backend**
  - VFS browsing endpoints
  - Graph query endpoints
  - Conflict queue API
  - Time estimate: 1 hr

- [ ] **Phase 8: React frontend via Lovable**
  - File tree browser
  - Entity detail view with provenance
  - Graph visualisation (mini)
  - Conflict review queue
  - Time estimate: 2-3 hrs

- [ ] **Phase 9: Entire integration**
  - Conflict resolution workflow
  - Time estimate: 1 hr

### 🟢 Done
- [x] **Phase 1: Explore data + finalise schema** — JSON shapes inspected, graph schema designed, 16 entity types + 22 relationship types defined

### 🔵 Final stretch
- [ ] **Phase 10: Demo prep + video** — 1 hr
- [ ] **Phase 11: README + docs for GitHub** — 30 min
