# Learnings from data ingestion

Patterns, quirks, and reusable insights from working with the Inazuma.co dataset. This document serves three purposes:
1. Help engineers avoid known pitfalls
2. Feed into the generalisation story for the demo
3. Document data quality signals that inform conflict resolution

---

## Universal patterns (generalisable to any company)

### L001 — There's always a universal join key
In Inazuma.co it's `emp_id`. Every communication system (email, chat, tickets, GitHub, social, overflow) references employees by this key. In other companies it might be an email address, a Slack user ID, or an LDAP username. **The first step for any new company is: find the universal join key for people.**

### L002 — B2B and B2C entities are always separate
Clients (B2B relationships, 400 records, UUID keys) and Customers (B2C transactional, 90 records, short code keys) are fundamentally different entities even though both represent "companies/people we do business with." They have different schemas, different ID formats, and different relationship semantics. **Never collapse these into a single entity type.**

### L003 — Communication sources are edge factories
Emails, chats, tickets, and support conversations rarely introduce new entities — they mostly create **relationship edges** between existing entities (employees, customers, products). Ingesting them after core entities means most references resolve cleanly.

### L004 — Source authority is domain-specific
HR is authoritative for employee data. CRM is authoritative for customer/sales data. B&M is authoritative for client data. No single source is authoritative for everything. **Conflict resolution must be entity-type-aware, not global.**

### L005 — Ingestion order matters
Later sources reference entities from earlier ones. The pattern is:
1. People first (HR/directory)
2. Business entities second (customers, products, clients, vendors)
3. Communication/activity sources third (emails, chat, tickets)
4. Cross-referencing sources last (support chats that link people + products + customers)

### L006 — Documents split into structured and unstructured
Order PDFs (invoices, purchase orders, shipping orders) are structured/tabular — you can extract with a parser. Policy PDFs are prose — you need an LLM for semantic chunking. **Always classify documents before choosing an extraction strategy.**

---

## Data quality patterns

### L007 — Signature mismatches in emails (81% of records)
9,714 out of 11,928 emails have a sender name that doesn't match the signature block. This is almost certainly intentional in the dataset. In a real company, this would be less extreme but still common (shared mailboxes, templates, delegated sending). **Treat signature mismatches as data quality alerts, not hard conflicts.**

### L008 — Some cross-references don't resolve
34 out of 2,897 conversations reference an `emp_id` that doesn't exist in the employee table. This represents ~1.2% data loss. In a real company this could mean: the employee left, the ID was entered incorrectly, or the systems are out of sync. **Always count and report unresolved references — they're a data quality signal.**

### L009 — Resume coverage is partial
1,013 out of 1,260 employees have matching resume records (80.3%). The CSV uses `emp_id` as the join key (confirmed by 100% match rate on available records, 0 unmatched). **Not every enrichment source will cover every entity.**

### L010 — Field types are inconsistent across records
`phone_number` in clients.json is sometimes an integer, sometimes a string. This is common in real-world JSON exports. **Always cast to string before processing — never assume consistent types within a single file.**

### L011 — Customer IDs are human-readable short codes
Customer IDs like "arout", "hungc", "alfki" appear to be abbreviated versions of customer names. They're used as filename suffixes in order PDFs (`invoice_arout.pdf`). **When source systems use human-readable IDs, they're often derived from names — useful for fuzzy matching if the ID isn't available.**

---

## Dataset-specific observations

### L012 — Product sentiment maps 1:1 with sales
Both have exactly 13,510 records. Every sale likely has exactly one review. This is unrealistic for a real company but useful for the hackathon — it means we can create a clean Customer → Sale → Review → Product chain for every transaction.

### L013 — The `_ADDED` suffix on PDFs
Three order PDFs have `_ADDED` suffix instead of a customer code: `invoice_ADDED.pdf`, `purchase_order_ADDED.pdf`, `shipping_order_ADDED.pdf`. These are likely a deliberate test: "new data arrived after initial ingestion — does your system handle it?" **Use these to demonstrate change propagation in the demo.**

### L014 — Inazuma.co is an Indian D2C tech company
Prices in ₹, Indian names (Raj Patel, Surya Reddy), Bangalore references in email signatures. Product categories are consumer electronics. The company has 1,260 employees, 90 B2C customers, 400 B2B clients, and 1,351 products.

### L015 — Overflow uses Stack Overflow schema
`PostTypeId` (1=question, 2=answer), `ParentId` (answer → question), `AcceptedAnswerId`, `Score`, `Tags`. This is a well-known schema — a generalised system could auto-detect it.

### L016 — Email threading is explicit
`thread_id` is a first-class field on every email. We extracted 4,417 unique threads from 11,928 emails, meaning an average of ~2.7 emails per thread. Some threads will be longer — worth investigating for the demo.

---

## Generalisation strategy

For the demo narrative, these patterns suggest a **three-phase approach** for onboarding any new company:

1. **Schema detection** — scan source files, identify entity types and join keys automatically (using LLM to classify fields as IDs, names, dates, descriptions, etc.)
2. **Authority mapping** — for each entity type, determine which source is authoritative (using heuristics: the source with the most complete records for that entity type wins)
3. **Incremental ingestion** — start with the most authoritative source for each entity type, then layer on communication/activity sources that create edges

This isn't something we need to fully build — but we should be able to articulate it clearly in the demo and README.
