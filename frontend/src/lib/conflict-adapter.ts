/**
 * Maps the qontext backend's conflict shape (entity-level field divergence)
 * to the richer UI shape the review screen expects.
 *
 * The two shapes were designed independently and do not have a 1:1 overlap:
 *   - Backend: a single contested field on a node, plus existing/new values.
 *   - UI: a "two-document side-by-side" comparison with structured Source A/B,
 *         AI suggestion (approve/reject/escalate), audit trail, and a doc viewer.
 *
 * Where backend data is missing, we synthesise sensible defaults so the UI
 * still renders. Anything that *does* exist on the backend (entity_id,
 * confidence, reason) is preserved so live data stays distinguishable from
 * mocks during development.
 */
import type {
  Conflict,
  Decision,
  Risk,
  SourceField,
  SourceRecord,
} from "./qontext-data";
import type { BackendConflict } from "./api";

const FIELD_TO_UI: Record<string, SourceField> = {
  party: "party",
  parties: "party",
  counterparty: "party",
  date: "date",
  effective_date: "date",
  amount: "amount",
  value: "amount",
  total: "amount",
  clause: "clause",
  terms: "clause",
  jurisdiction: "jurisdiction",
};

function toUiField(field?: string): SourceField {
  if (!field) return "clause";
  const key = field.toLowerCase();
  return FIELD_TO_UI[key] ?? "clause";
}

function riskFromConfidence(confidence: number | undefined): Risk {
  // High confidence in a conflict signal = high risk it really is wrong.
  if (typeof confidence !== "number") return "med";
  if (confidence >= 0.8) return "high";
  if (confidence >= 0.5) return "med";
  return "low";
}

function aiActionFromBackend(b: BackendConflict): Decision {
  // If backend already chose a winner with high confidence, we map it.
  // - winner "existing"  -> reject (the new value should not replace existing)
  // - winner "new"       -> approve (use the new value)
  // - otherwise          -> escalate (let a human decide)
  const winner = b.resolution?.winner;
  if (winner === "existing") return "reject";
  if (winner === "new") return "approve";
  return "escalate";
}

function asString(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

function shortIdFromEntity(entityId?: string, backendIndex = 0): string {
  if (!entityId) return `Q-${String(backendIndex).padStart(4, "0")}`;
  // "Employee:emp_0431" -> "emp_0431"
  const tail = entityId.includes(":") ? entityId.split(":").slice(1).join(":") : entityId;
  return `Q-${tail}`;
}

function partiesFromEntity(entityId?: string): [string, string] {
  if (!entityId || !entityId.includes(":")) {
    return ["Source A", "Source B"];
  }
  const [type, key] = entityId.split(":");
  return [`${type} ${key}`, `${type} ${key}`];
}

export function adaptBackendConflict(
  raw: BackendConflict,
  backendIndex: number,
): Conflict {
  const field = toUiField(raw.field);
  const confidence = typeof raw.confidence === "number" ? raw.confidence : 0.6;
  const existingValue = asString(raw.existing_value);
  const newValue = asString(raw.new_value);

  const sourceA: SourceRecord = {
    party: field === "party" ? existingValue : "—",
    date: field === "date" ? existingValue : "—",
    amount: field === "amount" ? existingValue : "—",
    clause: field === "clause" ? existingValue : "—",
    jurisdiction: field === "jurisdiction" ? existingValue : "—",
  };
  const sourceB: SourceRecord = {
    party: field === "party" ? newValue : "—",
    date: field === "date" ? newValue : "—",
    amount: field === "amount" ? newValue : "—",
    clause: field === "clause" ? newValue : "—",
    jurisdiction: field === "jurisdiction" ? newValue : "—",
  };

  // Cross-fill remaining (non-contested) fields with the same value so the
  // diff view does not light them up as conflicts.
  (Object.keys(sourceA) as Array<keyof SourceRecord>).forEach((k) => {
    if (sourceA[k] === "—" && sourceB[k] === "—") {
      sourceA[k] = "—";
      sourceB[k] = "—";
    }
  });

  return {
    id: shortIdFromEntity(raw.entity_id, backendIndex),
    risk: riskFromConfidence(confidence),
    title:
      raw.entity_id && raw.field
        ? `${raw.entity_id} · field "${raw.field}"`
        : "Field divergence detected",
    parties: partiesFromEntity(raw.entity_id),
    age: "—",
    sourceA,
    sourceB,
    conflictFields: [field],
    aiSuggestion: {
      action: aiActionFromBackend(raw),
      confidence,
      reasoning:
        raw.reason ||
        raw.resolution?.reason ||
        "Backend flagged this field as divergent; reasoning not provided.",
    },
    entityId: raw.entity_id,
    backendIndex,
  };
}

/** Map a UI decision to the backend's winner enum. `escalate`/`skip` are not pushed. */
export function decisionToBackendWinner(d: Decision): "existing" | "new" | null {
  if (d === "approve") return "new";
  if (d === "reject") return "existing";
  return null; // escalate -> needs a human/ticket flow, no backend call yet
}
