# Decision log

All architecture and product decisions for the Qontext hackathon project.

---

### D001 — Graph schema approach: domain-faithful (Option B)
**Date:** 2025-04-25
**Context:** Two options for modelling entities — (A) collapse similar types into generic nodes (e.g. Customer + Client → Organisation), or (B) keep each source's entity types distinct.
**Decision:** Option B — domain-faithful. Keep Customer and Client as separate entity types. Same for Email vs Conversation vs SupportChat.
**Rationale:** The judges want to see that the system understands the difference between a CRM customer (B2C transactional) and a B&M client (B2B relationship). Keeping types distinct makes provenance tracking trivial and conflict detection between sources more explicit. We can always create unified views in the virtual file system.

---

### D002 — Email threading: separate EmailThread entity
**Date:** 2025-04-25
**Context:** Emails have `thread_id`. Option was to either link emails to each other via shared property, or create a dedicated EmailThread node.
**Decision:** Create EmailThread as a separate entity type.
**Rationale:** Gives us a natural "conversation about X" node to hang summaries and topic labels on. Makes the virtual file system richer — users can browse by thread, not just individual emails.

---

### D003 — GitHub depth: issues as separate entities
**Date:** 2025-04-25
**Context:** GitHub records contain nested issue data. Could model as flat repo nodes or extract issues into their own entities.
**Decision:** Model GitHubIssue as a separate entity linked to GitHubRepo.
**Rationale:** Enables cross-source stitching — linking a GitHub issue to the employee who raised it, the IT ticket that prompted it, or the email thread discussing it. This is exactly the kind of cross-referencing that wins the challenge.

---

### D004 — Partner technologies: Gemini + Lovable + Entire
**Date:** 2025-04-25
**Context:** Must use minimum 3 partner technologies. Evaluated all options against project fit.
**Decision:** Google DeepMind (Gemini), Lovable, Entire.
**Rationale:**
- **Gemini** — natural fit for entity extraction from unstructured sources, PDF summarisation, query interface
- **Lovable** — builds React frontend fast (file browser, graph viewer, conflict queue), freeing engineers for backend work
- **Entire** — maps directly to core judging criterion ("involve humans where ambiguity matters") for conflict resolution workflow. Also eligible for Entire side challenge ($1,000 Apple gift cards + consoles)
- Rejected Tavily (web search doesn't map well to the core problem), Gradium (voice is flashy but shallow integration), Pioneer (fine-tuning not needed for this use case)

---

### D005 — Tech stack: Python + NetworkX + FastAPI + React
**Date:** 2025-04-25
**Context:** Needed to choose graph database, backend framework, and frontend approach.
**Decision:** NetworkX for graph (in-memory), FastAPI for API, React via Lovable for frontend.
**Rationale:** NetworkX is simple, no infrastructure to set up during a hackathon, and JSON-serialisable. FastAPI is fast to build and auto-generates API docs (useful for the submission README). Lovable handles React frontend generation so engineers can focus on the backend pipeline.

---

### D006 — Ingestion order: HR first, then CRM, then communications
**Date:** 2025-04-25
**Context:** 13 source types to ingest. Order matters because later sources reference entities from earlier ones.
**Decision:** HR → CRM → B&M → IT tickets → Emails → Conversations → GitHub → Overflow → Social → Support → Sentiment → Order PDFs → Policy PDFs
**Rationale:** HR establishes the employee entity backbone (emp_id is the universal join key). CRM establishes customers and products. Everything else creates relationship edges to these core entities. PDFs are last because they're slowest to process and lowest priority.
