export type Risk = "high" | "med" | "low";
export type Decision = "approve" | "reject" | "escalate";

export interface SourceDocument {
  filename: string;
  pages: number;
  uploadedAt: string;
  uploadedBy: string;
  excerpt: string;
  /** the substring inside `excerpt` to highlight as the conflicting value */
  highlight: string;
  /** mock body paragraphs shown in the doc viewer sheet */
  body: string[];
}

export type SourceField = "party" | "date" | "amount" | "clause" | "jurisdiction";

export interface SourceRecord {
  party: string;
  date: string;
  amount: string;
  clause: string;
  jurisdiction: string;
  document?: SourceDocument;
}

export interface AuditEntry {
  timestamp: string;
  actor: string;
  action: string;
}

export interface Conflict {
  id: string;
  risk: Risk;
  title: string;
  parties: [string, string];
  age: string;
  sourceA: SourceRecord;
  sourceB: SourceRecord;
  conflictFields: SourceField[];
  aiSuggestion: {
    action: Decision;
    confidence: number;
    reasoning: string;
  };
  auditTrail?: AuditEntry[];
  /** Backend graph node id (e.g. "Employee:emp_0431") for drill-down to the 3D graph view. */
  entityId?: string;
  /** Backend list index needed to call POST /conflicts/{index}/resolve. */
  backendIndex?: number;
}

export interface PastDecision {
  id: string;
  decision: Decision;
  reviewer: string;
  date: string;
}

export const PAST_DECISIONS: PastDecision[] = [
  { id: "Q-2801", decision: "reject", reviewer: "JM", date: "Apr 22" },
  { id: "Q-2776", decision: "approve", reviewer: "AS", date: "Apr 21" },
  { id: "Q-2754", decision: "escalate", reviewer: "RK", date: "Apr 19" },
  { id: "Q-2731", decision: "reject", reviewer: "JM", date: "Apr 18" },
];

export const CONFLICTS: Conflict[] = [
  {
    id: "Q-2847",
    risk: "high",
    title: "Contract value mismatch on MSA renewal — Acme vs. Beta",
    parties: ["Acme Corp", "Beta Holdings AG"],
    age: "2h ago",
    sourceA: {
      party: "Acme Corp",
      date: "2025-03-14",
      amount: "EUR 1,240,000.00",
      clause: "Auto-renewal 12mo, 30d notice",
      jurisdiction: "Frankfurt, DE",
      document: {
        filename: "MSA_Acme_2025_signed.pdf",
        pages: 12,
        uploadedAt: "14 Mar 2025",
        uploadedBy: "JM",
        excerpt:
          "...the total contract value shall be EUR 1,240,000.00 payable in four equal quarterly instalments...",
        highlight: "EUR 1,240,000.00",
        body: [
          "MASTER SERVICES AGREEMENT — RENEWAL 2025",
          "This Master Services Agreement (\"Agreement\") is entered into as of 14 March 2025 between Acme Corp (\"Customer\") and Beta Holdings AG (\"Supplier\").",
          "1. SCOPE. Supplier shall provide the services described in Schedule A for the renewed term of twelve (12) months.",
          "2. CONSIDERATION. In consideration of the services rendered, the total contract value shall be EUR 1,240,000.00 payable in four equal quarterly instalments, commencing 1 April 2025.",
          "3. RENEWAL. This Agreement shall auto-renew for successive twelve (12) month periods unless either party gives thirty (30) days written notice prior to the end of the then-current term.",
          "4. GOVERNING LAW. This Agreement shall be governed by the laws of Germany, with exclusive jurisdiction in Frankfurt am Main.",
        ],
      },
    },
    sourceB: {
      party: "Acme Corporation",
      date: "2025-03-14",
      amount: "EUR 1,420,000.00",
      clause: "Auto-renewal 12mo, 30d notice",
      jurisdiction: "Frankfurt, DE",
      document: {
        filename: "MSA_Acme_2025_amendment_v3.docx",
        pages: 4,
        uploadedAt: "02 Apr 2025",
        uploadedBy: "MK",
        excerpt:
          "...amended total contract value of EUR 1,420,000.00 effective Q2 2025...",
        highlight: "EUR 1,420,000.00",
        body: [
          "AMENDMENT NO. 3 TO MASTER SERVICES AGREEMENT",
          "Reference is made to the Master Services Agreement dated 14 March 2025 between Acme Corporation and Beta Holdings AG.",
          "1. AMENDED CONSIDERATION. The parties hereby agree to an amended total contract value of EUR 1,420,000.00 effective Q2 2025, reflecting expanded scope set out in revised Schedule A-1.",
          "2. NO OTHER CHANGES. Except as expressly amended hereby, all other terms of the Agreement remain in full force and effect.",
          "3. EFFECTIVE DATE. This Amendment is effective as of 1 April 2025.",
        ],
      },
    },
    conflictFields: ["amount", "party"],
    aiSuggestion: {
      action: "reject",
      confidence: 0.87,
      reasoning:
        "Amount delta of EUR 180k exceeds 10% tolerance. Source B figure unsupported by signed amendment log.",
    },
    auditTrail: [
      { timestamp: "14 Mar 2025 09:42", actor: "system", action: "ingested from sys.primary" },
      { timestamp: "02 Apr 2025 11:18", actor: "MK", action: "amendment uploaded to sys.ledger" },
      { timestamp: "26 Apr 2026 08:33", actor: "qontext-ai", action: "flagged conflict, confidence 87%" },
    ],
  },
  {
    id: "Q-2846",
    risk: "med",
    title: "Effective date divergence on supply agreement",
    parties: ["Müller GmbH", "Northwind Ltd"],
    age: "3h ago",
    sourceA: {
      party: "Müller GmbH",
      date: "2025-01-01",
      amount: "EUR 86,500.00",
      clause: "Net 30, 2% early-pay",
      jurisdiction: "München, DE",
      document: {
        filename: "Supply_Agreement_Mueller_2025.pdf",
        pages: 8,
        uploadedAt: "20 Dec 2024",
        uploadedBy: "RK",
        excerpt: "...this Agreement shall take effect on 01 January 2025 and continue for...",
        highlight: "01 January 2025",
        body: [
          "SUPPLY AGREEMENT",
          "1. EFFECTIVE DATE. This Agreement shall take effect on 01 January 2025 and continue for an initial term of twenty-four (24) months.",
          "2. PRICING. Net 30 payment terms, 2% discount for payment within 10 days.",
        ],
      },
    },
    sourceB: {
      party: "Müller GmbH",
      date: "2025-02-01",
      amount: "EUR 86,500.00",
      clause: "Net 30, 2% early-pay",
      jurisdiction: "München, DE",
      document: {
        filename: "Northwind_PO_2025_Q1.xlsx",
        pages: 2,
        uploadedAt: "05 Feb 2025",
        uploadedBy: "AS",
        excerpt: "...PO effective date: 01 February 2025, vendor: Müller GmbH...",
        highlight: "01 February 2025",
        body: [
          "PURCHASE ORDER — Q1 2025",
          "Vendor: Müller GmbH",
          "PO effective date: 01 February 2025",
          "Total: EUR 86,500.00 — Net 30",
        ],
      },
    },
    conflictFields: ["date"],
    aiSuggestion: {
      action: "escalate",
      confidence: 0.62,
      reasoning:
        "One-month effective-date gap could shift Q1 revenue recognition. Recommend finance review.",
    },
    auditTrail: [
      { timestamp: "20 Dec 2024 14:02", actor: "system", action: "ingested supply agreement from sys.primary" },
      { timestamp: "05 Feb 2025 09:11", actor: "AS", action: "PO uploaded to sys.ledger" },
      { timestamp: "26 Apr 2026 07:18", actor: "qontext-ai", action: "flagged conflict, confidence 62%" },
    ],
  },
  {
    id: "Q-2845",
    risk: "high",
    title: "Counterparty entity divergence — possible name swap",
    parties: ["Beta Holdings AG", "Beta Holdings SE"],
    age: "4h ago",
    sourceA: {
      party: "Beta Holdings AG",
      date: "2025-02-20",
      amount: "USD 2,300,000.00",
      clause: "Limitation of liability capped at fees",
      jurisdiction: "Zürich, CH",
      document: {
        filename: "Beta_AG_License_Agreement.pdf",
        pages: 18,
        uploadedAt: "20 Feb 2025",
        uploadedBy: "JM",
        excerpt: "...by and between the Licensee and Beta Holdings AG, a German stock corporation...",
        highlight: "Beta Holdings AG",
        body: [
          "LICENSE AGREEMENT",
          "Entered into by and between the Licensee and Beta Holdings AG, a German stock corporation registered under HRB 4421 in Frankfurt am Main.",
          "Total license fee: USD 2,300,000.00.",
        ],
      },
    },
    sourceB: {
      party: "Beta Holdings SE",
      date: "2025-02-20",
      amount: "USD 2,300,000.00",
      clause: "Limitation of liability capped at fees",
      jurisdiction: "Zürich, CH",
      document: {
        filename: "Beta_SE_Counterpart_Signed.pdf",
        pages: 18,
        uploadedAt: "21 Feb 2025",
        uploadedBy: "RK",
        excerpt: "...countersigned counterpart executed by Beta Holdings SE, a Societas Europaea...",
        highlight: "Beta Holdings SE",
        body: [
          "EXECUTION COUNTERPART",
          "This countersigned counterpart is executed by Beta Holdings SE, a Societas Europaea registered under HRB 8812.",
          "Same financial terms as primary counterpart.",
        ],
      },
    },
    conflictFields: ["party"],
    aiSuggestion: {
      action: "reject",
      confidence: 0.91,
      reasoning:
        "Entity legal form differs (AG vs SE). Distinct registrations under HR. Treat as separate counterparties.",
    },
    auditTrail: [
      { timestamp: "20 Feb 2025 16:40", actor: "JM", action: "primary counterpart uploaded to sys.primary" },
      { timestamp: "21 Feb 2025 10:05", actor: "RK", action: "execution counterpart uploaded to sys.ledger" },
      { timestamp: "26 Apr 2026 06:55", actor: "qontext-ai", action: "flagged conflict, confidence 91%" },
    ],
  },
  {
    id: "Q-2844",
    risk: "low",
    title: "Indemnity clause wording variance",
    parties: ["Helix Biotech", "Vertex Labs Inc"],
    age: "5h ago",
    sourceA: {
      party: "Helix Biotech",
      date: "2024-11-30",
      amount: "USD 420,000.00",
      clause: "Mutual indemnity, gross negligence carve-out",
      jurisdiction: "Delaware, US",
    },
    sourceB: {
      party: "Helix Biotech",
      date: "2024-11-30",
      amount: "USD 420,000.00",
      clause: "Mutual indemnity, willful misconduct carve-out",
      jurisdiction: "Delaware, US",
    },
    conflictFields: ["clause"],
    aiSuggestion: {
      action: "approve",
      confidence: 0.74,
      reasoning:
        "Carve-out language differs but legal effect is substantially equivalent under DE Chancery precedent.",
    },
  },
  {
    id: "Q-2843",
    risk: "high",
    title: "Governing law conflict on cross-border SaaS deal",
    parties: ["Orion Systems", "Sakura KK"],
    age: "6h ago",
    sourceA: {
      party: "Orion Systems",
      date: "2025-03-01",
      amount: "JPY 48,000,000",
      clause: "Arbitration, ICC rules",
      jurisdiction: "Tokyo, JP",
      document: {
        filename: "Orion_Sakura_SaaS_JP.pdf",
        pages: 22,
        uploadedAt: "01 Mar 2025",
        uploadedBy: "AS",
        excerpt: "...governing law of Japan, with seat of arbitration in Tokyo, JP under ICC rules...",
        highlight: "Tokyo, JP",
        body: [
          "CROSS-BORDER SAAS AGREEMENT",
          "GOVERNING LAW. This Agreement shall be governed by the laws of Japan, with seat of arbitration in Tokyo, JP under ICC rules.",
        ],
      },
    },
    sourceB: {
      party: "Orion Systems",
      date: "2025-03-01",
      amount: "JPY 48,000,000",
      clause: "Arbitration, ICC rules",
      jurisdiction: "London, UK",
      document: {
        filename: "Orion_Sakura_SaaS_UK_counterpart.docx",
        pages: 22,
        uploadedAt: "03 Mar 2025",
        uploadedBy: "RK",
        excerpt: "...seat of arbitration shall be London, UK pursuant to ICC rules...",
        highlight: "London, UK",
        body: [
          "EXECUTION COUNTERPART (UK)",
          "Notwithstanding the foregoing, the seat of arbitration shall be London, UK pursuant to ICC rules.",
        ],
      },
    },
    conflictFields: ["jurisdiction"],
    aiSuggestion: {
      action: "escalate",
      confidence: 0.83,
      reasoning:
        "Jurisdiction split (JP vs UK) materially changes enforceability. Requires GC sign-off.",
    },
    auditTrail: [
      { timestamp: "01 Mar 2025 12:00", actor: "AS", action: "primary uploaded to sys.primary" },
      { timestamp: "03 Mar 2025 09:30", actor: "RK", action: "UK counterpart uploaded to sys.ledger" },
      { timestamp: "26 Apr 2026 05:48", actor: "qontext-ai", action: "flagged conflict, confidence 83%" },
    ],
  },
  {
    id: "Q-2842",
    risk: "med",
    title: "Payment terms differ — Net 30 vs Net 60",
    parties: ["Schmidt & Partner", "Quantum Freight"],
    age: "7h ago",
    sourceA: {
      party: "Schmidt & Partner",
      date: "2025-04-10",
      amount: "EUR 312,400.00",
      clause: "Net 30, late fee 1.5%/mo",
      jurisdiction: "Hamburg, DE",
      document: {
        filename: "MSA_Schmidt_Quantum_2024.pdf",
        pages: 14,
        uploadedAt: "10 Apr 2025",
        uploadedBy: "JM",
        excerpt: "...payment terms shall be Net 30 with a late fee of 1.5%/mo applied...",
        highlight: "Net 30",
        body: [
          "MASTER AGREEMENT — SCHMIDT & PARTNER / QUANTUM FREIGHT",
          "PAYMENT. All invoices payment terms shall be Net 30 with a late fee of 1.5%/mo applied to overdue balances.",
        ],
      },
    },
    sourceB: {
      party: "Schmidt & Partner",
      date: "2025-04-10",
      amount: "EUR 312,400.00",
      clause: "Net 60, no late fee",
      jurisdiction: "Hamburg, DE",
      document: {
        filename: "Invoice_Q2_2025_Schmidt.pdf",
        pages: 1,
        uploadedAt: "10 Apr 2025",
        uploadedBy: "system",
        excerpt: "...invoice issued under terms Net 60, no late fee, payable by 09 Jun 2025...",
        highlight: "Net 60",
        body: [
          "INVOICE Q2-2025-0431",
          "Bill-to: Schmidt & Partner",
          "Terms: Net 60, no late fee. Payable by 09 Jun 2025.",
        ],
      },
    },
    conflictFields: ["clause"],
    aiSuggestion: {
      action: "reject",
      confidence: 0.78,
      reasoning:
        "Net 60 in Source B contradicts master agreement standard terms (Net 30). Likely data-entry error.",
    },
    auditTrail: [
      { timestamp: "10 Apr 2025 09:15", actor: "JM", action: "MSA uploaded to sys.primary" },
      { timestamp: "10 Apr 2025 16:42", actor: "system", action: "invoice ingested into sys.ledger" },
      { timestamp: "26 Apr 2026 04:21", actor: "qontext-ai", action: "flagged conflict, confidence 78%" },
    ],
  },
  {
    id: "Q-2841",
    risk: "low",
    title: "Renewal amount rounding discrepancy",
    parties: ["Acme Corp", "Linde Gas Solutions"],
    age: "9h ago",
    sourceA: {
      party: "Acme Corp",
      date: "2025-02-15",
      amount: "EUR 99,999.00",
      clause: "Annual renewal, fixed price",
      jurisdiction: "Frankfurt, DE",
    },
    sourceB: {
      party: "Acme Corp",
      date: "2025-02-15",
      amount: "EUR 100,000.00",
      clause: "Annual renewal, fixed price",
      jurisdiction: "Frankfurt, DE",
    },
    conflictFields: ["amount"],
    aiSuggestion: {
      action: "approve",
      confidence: 0.94,
      reasoning:
        "EUR 1.00 delta within rounding tolerance. No material impact on accounting period.",
    },
  },
  {
    id: "Q-2839",
    risk: "med",
    title: "Ambiguous counterparty alias on legacy NDA",
    parties: ["Nordic Steel A/S", "Nordic Steel Holding"],
    age: "10h ago",
    sourceA: {
      party: "Nordic Steel A/S",
      date: "2023-08-12",
      amount: "DKK 1,800,000.00",
      clause: "NDA, 5y term",
      jurisdiction: "Copenhagen, DK",
      document: {
        filename: "NDA_NordicSteel_AS_2023.pdf",
        pages: 6,
        uploadedAt: "12 Aug 2023",
        uploadedBy: "system",
        excerpt: "...by and between Discloser and Nordic Steel A/S (CVR 28194422)...",
        highlight: "Nordic Steel A/S",
        body: [
          "MUTUAL NON-DISCLOSURE AGREEMENT",
          "Entered into by and between Discloser and Nordic Steel A/S (CVR 28194422), the operating entity.",
        ],
      },
    },
    sourceB: {
      party: "Nordic Steel Holding",
      date: "2023-08-12",
      amount: "DKK 1,800,000.00",
      clause: "NDA, 5y term",
      jurisdiction: "Copenhagen, DK",
      document: {
        filename: "CRM_export_legacy.csv",
        pages: 1,
        uploadedAt: "15 Jan 2024",
        uploadedBy: "RK",
        excerpt: "...counterparty: Nordic Steel Holding, agreement_type: NDA, term: 5y...",
        highlight: "Nordic Steel Holding",
        body: [
          "CRM EXPORT (legacy system)",
          "counterparty: Nordic Steel Holding | agreement_type: NDA | term: 5y | value: DKK 1,800,000.00",
        ],
      },
    },
    conflictFields: ["party"],
    aiSuggestion: {
      action: "escalate",
      confidence: 0.58,
      reasoning:
        "Cannot disambiguate parent vs operating entity from available metadata. Manual lookup advised.",
    },
    auditTrail: [
      { timestamp: "12 Aug 2023 10:14", actor: "system", action: "NDA ingested into sys.primary" },
      { timestamp: "15 Jan 2024 13:22", actor: "RK", action: "legacy CRM export merged into sys.ledger" },
      { timestamp: "26 Apr 2026 03:02", actor: "qontext-ai", action: "flagged conflict, confidence 58%" },
    ],
  },
  {
    id: "Q-2838",
    risk: "low",
    title: "Currency code possibly transposed on invoice line",
    parties: ["Riviera Trading SA", "Atlas Logistics"],
    age: "12h ago",
    sourceA: {
      party: "Riviera Trading SA",
      date: "2025-01-22",
      amount: "CHF 74,300.00",
      clause: "FOB origin, 14d payment",
      jurisdiction: "Geneva, CH",
    },
    sourceB: {
      party: "Riviera Trading SA",
      date: "2025-01-22",
      amount: "EUR 74,300.00",
      clause: "FOB origin, 14d payment",
      jurisdiction: "Geneva, CH",
    },
    conflictFields: ["amount"],
    aiSuggestion: {
      action: "approve",
      confidence: 0.41,
      reasoning:
        "Currency mismatch (CHF/EUR) with identical numeric value. Could be FX conversion or data error — insufficient signal.",
    },
  },
  {
    id: "Q-2840",
    risk: "high",
    title: "Termination clause contradiction on framework agreement",
    parties: ["Voltex Energie GmbH", "Pioneer Capital"],
    age: "11h ago",
    sourceA: {
      party: "Voltex Energie GmbH",
      date: "2024-12-01",
      amount: "EUR 5,600,000.00",
      clause: "Termination for convenience, 90d notice",
      jurisdiction: "Berlin, DE",
      document: {
        filename: "Voltex_Pioneer_Framework_v1.pdf",
        pages: 32,
        uploadedAt: "01 Dec 2024",
        uploadedBy: "JM",
        excerpt: "...either party may terminate this Agreement for convenience upon 90 days written notice...",
        highlight: "for convenience",
        body: [
          "FRAMEWORK AGREEMENT — VOLTEX / PIONEER",
          "TERMINATION. Either party may terminate this Agreement for convenience upon 90 days written notice.",
        ],
      },
    },
    sourceB: {
      party: "Voltex Energie GmbH",
      date: "2024-12-01",
      amount: "EUR 5,600,000.00",
      clause: "Termination only for cause",
      jurisdiction: "Berlin, DE",
      document: {
        filename: "Voltex_Pioneer_Framework_v2_executed.pdf",
        pages: 32,
        uploadedAt: "05 Dec 2024",
        uploadedBy: "MK",
        excerpt: "...this Agreement may be terminated only for cause as defined in Section 14.2...",
        highlight: "only for cause",
        body: [
          "FRAMEWORK AGREEMENT — EXECUTED VERSION",
          "TERMINATION. This Agreement may be terminated only for cause as defined in Section 14.2.",
        ],
      },
    },
    conflictFields: ["clause"],
    aiSuggestion: {
      action: "escalate",
      confidence: 0.88,
      reasoning:
        "Convenience-vs-cause mismatch creates exit-risk asymmetry. Counsel review required before any decision.",
    },
    auditTrail: [
      { timestamp: "01 Dec 2024 11:00", actor: "JM", action: "draft uploaded to sys.primary" },
      { timestamp: "05 Dec 2024 17:30", actor: "MK", action: "executed version uploaded to sys.ledger" },
      { timestamp: "26 Apr 2026 02:11", actor: "qontext-ai", action: "flagged conflict, confidence 88%" },
    ],
  },
];
