# Qontext hackathon — project context

## Challenge summary

Build a system that turns raw, fragmented company data into a **structured company memory** that AI can operate on. Not a chatbot, not a RAG pipeline — a persistent, inspectable **context base**.

**Deliverables:**
1. A **virtual file system** documenting the business: static data (employees, customers, products), procedural knowledge (processes, SOPs, rules), and trajectory information (tasks, projects, progress)
2. A **knowledge graph** with explicit references: links between entities, and provenance links back to source records
3. **Interface(s)** for AI retrieval + human inspection, validation, editing, and extension

**Judging criteria (what wins):**
- Generalises beyond the provided dataset/format
- Auto-resolves easy conflicts, surfaces ambiguous ones for humans
- Preserves provenance at the fact level
- Updates automatically when source facts change
- Explainable, editable, robust under change, useful in practice

**Submission requirements:**
- 2-minute video demo (Loom or equivalent)
- Public GitHub repo with comprehensive README, API docs, setup instructions
- Deadline: Sunday 14:00
- Must use minimum 3 partner technologies

**Prize:** 1g gold bar per member + private dinner with Qontext team

---

## The company: Inazuma.co

The dataset simulates a full enterprise with 10 source systems, 307 files, ~27MB total.
Inazuma.co appears to be an Indian D2C tech company (prices in ₹, Indian names, Bangalore references).

### Data sources inventory

| Source | Files | Format | Size | Records | Primary keys | Contents |
|---|---|---|---|---|---|---|
| Human_Resource_Management | employees.json, resume_information.csv | JSON, CSV | 2.2MB + 3.6MB | 1,260 employees | `emp_id` | Employee records (name, email, dept, salary, leaves, performance) + CVs |
| Business_and_Management | clients.json, vendors.json | JSON | 311K + 179K | 400 clients, ? vendors | `client_id` (UUID), vendor_id | B2B relationships with POC status, engagement descriptions |
| Customer_Relation_Management | customers.json, products.json, sales.json | JSON | 31K + 1.5MB + 3.5MB | 90 customers, 1,351 products, 13,510 sales | `customer_id` (short code), `product_id`, `sales_record_id` | CRM core data |
| CRM / Customer Support | customer_support_chats.json | JSON | 3.8MB | 1,000 chats | composite (customer_id + product_id + emp_id) | Support conversations linking customer + product + agent |
| CRM / Product Sentiment | product_sentiment.json | JSON | 21MB | 13,510 reviews | `sentiment_id` | Customer reviews with `customer_id` + `product_id` (1:1 with sales) |
| CRM / Customer Orders | ~270 PDFs | PDF | ~3.5MB total | ~90 customers × 3 doc types | filename → `customer_id` | Invoices, purchase orders, shipping orders per customer |
| Enterprise_Mail_System | emails.json | JSON | 16MB | 11,928 emails | `email_id`, `thread_id` | Emails with sender/recipient `emp_id`, threading, categories |
| Collaboration_tools | conversations.json | JSON | 6MB | 2,897 conversations | `conversation_id` | Internal chat with sender/recipient `emp_id` |
| Enterprise_Social_Platform | posts.json | JSON | 1.6MB | 971 posts | TBD | Internal social feed with `emp_id` and `author` |
| IT_Service_Management | it_tickets.json | JSON | 185K | 163 tickets | `id` | IT tickets with `raised_by_emp_id` and assigned `emp_id` |
| Inazuma_overflow | overflow.json | JSON | 13MB | 10,823 posts | `Id` | Internal Q&A (Stack Overflow style) with `employee_id`, parent/child threading |
| Workspace / GitHub | GitHub.json | JSON | 9.6MB | 750 repos | `repo_name` | Repos with code, issues, PRs, linked to `emp_id` |
| Policy_Documents | 24 PDFs | PDF | ~5.5MB total | 24 policies | filename | Company policies (ethics, data protection, leave, SDLC, etc.) |

### Key observations
- `emp_id` is the universal join key — appears in HR, emails, conversations, IT tickets, GitHub, clients, support chats, overflow, social posts
- `customer_id` (short codes like "arout", "hungc") links customers → sales → reviews → support chats → order PDFs (filename suffix)
- `product_id` links products → sales → reviews → support chats
- `client_id` (UUIDs) is separate from `customer_id` — clients are B2B relationships, customers are B2C transactional
- `thread_id` on emails enables conversation threading
- product_sentiment and sales have identical record counts (13,510) — likely 1:1
- The `_ADDED` suffix on some order PDFs likely represents data added after initial ingestion (test for change propagation)
- Email signature mismatch detected (sender says Ravi Kumar, signature says Aji Joseph) — possible intentional conflict for testing
- clients.json references employees via `business_representative_employee` field

---

## Architecture

### Tech stack
- **Python** — ingestion pipeline, graph construction, API
- **NetworkX** — knowledge graph (in-memory, JSON-serialisable)
- **FastAPI** — serves virtual file system + graph queries + conflict queue API
- **React** (via Lovable) — browsing/inspection interface
- **Google Gemini** — entity extraction from unstructured sources (emails, PDFs, chat), summarisation, optional query interface
- **Entire** — human-in-the-loop conflict resolution workflow
- **Anthropic Claude API** — available as supplementary LLM

### Partner technologies (minimum 3 required)
1. **Google DeepMind (Gemini)** — entity extraction, PDF summarisation, query interface
2. **Lovable** — React frontend generation (file browser, graph viewer, conflict queue)
3. **Entire** — agent-human collaboration for conflict resolution workflow (also eligible for Entire side challenge: $1,000 Apple gift cards + consoles)

### Graph schema

#### Entity types (16 types)

| Entity type | Source(s) | Primary key | Record count |
|---|---|---|---|
| Employee | HR employees.json, resume_information.csv | `emp_id` | ~1,260 |
| Department | HR (derived from `category` field) | name | ~10-15 |
| Customer | CRM customers.json | `customer_id` | 90 |
| Client | B&M clients.json | `client_id` | 400 |
| Vendor | B&M vendors.json | vendor_id | TBD |
| Product | CRM products.json | `product_id` | 1,351 |
| Sale | CRM sales.json | `sales_record_id` | 13,510 |
| Review | product_sentiment.json | `sentiment_id` | 13,510 |
| Email | emails.json | `email_id` | 11,928 |
| EmailThread | emails.json (derived) | `thread_id` | TBD |
| Conversation | conversations.json | `conversation_id` | 2,897 |
| SupportChat | customer_support_chats.json | composite | 1,000 |
| ITTicket | it_tickets.json | `id` | 163 |
| GitHubRepo | GitHub.json | `repo_name` | 750 |
| GitHubIssue | GitHub.json (nested) | `issues.id` | TBD |
| OverflowPost | overflow.json | `Id` | 10,823 |
| SocialPost | posts.json | TBD | 971 |
| Policy | Policy PDFs | filename | 24 |

#### Relationship types

| Relationship | From → To | Join key | Source |
|---|---|---|---|
| `works_in` | Employee → Department | `category` | HR |
| `sent_email` | Employee → Email | `sender_emp_id` | Mail |
| `received_email` | Employee → Email | `recipient_emp_id` | Mail |
| `part_of_thread` | Email → EmailThread | `thread_id` | Mail |
| `chatted_in` | Employee → Conversation | `sender/recipient_emp_id` | Collaboration |
| `raised_ticket` | Employee → ITTicket | `raised_by_emp_id` | ITSM |
| `assigned_ticket` | Employee → ITTicket | `emp_id` | ITSM |
| `contributed_to` | Employee → GitHubRepo | `emp_id` | GitHub |
| `repo_has_issue` | GitHubRepo → GitHubIssue | nested | GitHub |
| `posted_overflow` | Employee → OverflowPost | `employee_id` | Overflow |
| `answer_to` | OverflowPost → OverflowPost | `ParentId` | Overflow |
| `posted_social` | Employee → SocialPost | `emp_id` | Social |
| `represents_client` | Employee → Client | `business_representative_employee` | B&M |
| `purchased` | Customer → Sale | `customer_id` | CRM |
| `product_in_sale` | Sale → Product | `product_id` | CRM |
| `reviewed` | Customer → Review | `customer_id` | Sentiment |
| `review_of` | Review → Product | `product_id` | Sentiment |
| `support_for_customer` | SupportChat → Customer | `customer_id` | Support |
| `support_for_product` | SupportChat → Product | `product_id` | Support |
| `support_by_agent` | SupportChat → Employee | `emp_id` | Support |
| `has_invoice` | Customer → OrderDoc | `customer_id` → filename | CRM/Orders |
| `governed_by` | (inferred) Entity → Policy | semantic matching | Policies |

#### Provenance model
Every fact (node property or edge) carries:
```json
{
  "sources": [
    {
      "source_system": "Enterprise_Mail_System",
      "file": "emails.json",
      "record_id": "email-4226322d",
      "field": "sender_emp_id",
      "timestamp": "2012-03-18T06:58:29",
      "confidence": 1.0
    }
  ]
}
```

Confidence scoring:
- **1.0** — direct field mapping from authoritative source
- **0.9** — direct field mapping from non-authoritative source
- **0.7-0.8** — LLM-extracted fact from unstructured text
- **0.5-0.6** — inferred relationship (e.g. semantic matching to policies)

### Virtual file system structure
```
/company/
  /people/{emp_id}-{name}.md              — employee profiles with roles, teams, activity
  /teams/{department-name}.md              — team overview, members, responsibilities
  /customers/{customer-id}.md              — customer profile, orders, support history, sentiment
  /clients/{client-name}.md                — B2B client info, POC status, representative
  /vendors/{vendor-name}.md                — vendor info, contracts
  /products/{product-id}.md                — product details, reviews, sales stats
  /projects/{project-name}/
    overview.md                            — project summary, status, team
    tasks.md                               — open/closed tasks and issues
  /policies/{policy-name}.md               — policy summaries with key rules extracted
  /processes/{process-name}.md             — inferred SOPs from actual behaviour patterns
  /it/tickets/{ticket-id}.md               — ticket details with resolution history
  /github/{repo-name}.md                   — repo overview, contributors, open issues
```

Each file is a **generated view** from the graph — not a static artefact. Inline provenance annotations link back to source records using the format:
```
**Status:** Active [source: CRM customers.json → arout | confidence: 1.0]
```

### Ingestion pipeline

#### Per-source pipeline
1. **Extract** — parse raw data, pull entities + relationships
2. **Normalise** — resolve entity identity across sources (emp_id matching, email matching, fuzzy name matching)
3. **Merge** — upsert into graph with conflict detection
4. **Conflict resolution** — auto-resolve high-confidence cases, queue ambiguous ones for human review via Entire

#### Source ingestion order (recommended)
1. **HR** (employees.json + resume_information.csv) — establishes the employee entity backbone
2. **CRM** (customers.json, products.json, sales.json) — establishes customer/product entities
3. **Business & Management** (clients.json, vendors.json) — B2B entities
4. **IT tickets** (it_tickets.json) — small, quick, good for testing pipeline
5. **Emails** (emails.json) — largest structured file, creates many relationship edges
6. **Conversations** (conversations.json) — more relationship edges
7. **GitHub** (GitHub.json) — repos + issues
8. **Overflow** (overflow.json) — Q&A posts
9. **Social** (posts.json) — social posts
10. **Support chats** (customer_support_chats.json) — cross-references customers + products + employees
11. **Product sentiment** (product_sentiment.json) — reviews
12. **Order PDFs** (~270 files) — extract with PDF parser, link via customer_id in filename
13. **Policy PDFs** (24 files) — extract with Gemini, semantic chunking

### Conflict resolution strategy
- **Auto-resolve:** same entity, same field, different values → pick most recent from most authoritative source
- **Flag for review:** contradictory facts from equally authoritative sources, or semantic conflicts (e.g. email says deal is off, CRM says active)
- **Confidence scoring:** based on source authority ranking, recency, and corroboration count

Source authority ranking:
1. HR system (canonical for employee data)
2. CRM (canonical for customer/sales data)
3. Business_and_Management (canonical for client/vendor data)
4. IT_Service_Management (canonical for tickets)
5. GitHub (canonical for code/issues)
6. Enterprise_Mail_System (high signal but informal)
7. Collaboration_tools (informal, high noise)
8. Enterprise_Social_Platform (informal)
9. Inazuma_overflow (Q&A, may be outdated)

---

## Demo plan

Prepare these scenarios for the 2-minute video:

1. **Cross-source stitching** — show a customer or employee page that combines data from 3+ sources (e.g. employee profile pulling HR + emails + GitHub + tickets)
2. **Auto-resolved conflict** — show a case where two sources disagreed and the system resolved it with provenance trail
3. **Human review queue** — show the Entire-powered conflict resolution interface where a human decides an ambiguous case
4. **Change propagation** — modify a source record, show the graph + virtual file system update
5. **File system browsing** — navigate the virtual file system, click into entities, see provenance links

---

## Task breakdown

| Phase | Task | Time estimate | Owner | Status |
|---|---|---|---|---|
| 1 | ~~Explore JSON record shapes, finalise graph schema~~ | ~~30-45 min~~ | | ✅ Done |
| 2 | Build ingestion pipeline for structured JSON sources | 2-3 hrs | | |
| 3 | Build PDF extraction (orders + policies) | 1-1.5 hrs | | |
| 4 | Entity resolution + conflict detection | 1-1.5 hrs | | |
| 5 | Virtual file system generator | 1-1.5 hrs | | |
| 6 | FastAPI backend (serve VFS + graph queries) | 1 hr | | |
| 7 | React frontend via Lovable (browser + conflict queue) | 2-3 hrs | | |
| 8 | Entire integration for conflict resolution | 1 hr | | |
| 9 | Demo prep + video recording | 1 hr | | |
| 10 | README + documentation for GitHub repo | 30 min | | |
