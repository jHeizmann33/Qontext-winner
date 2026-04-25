import type { SourceRecord } from "../types";
import { similarity } from "./levenshtein";

export type MatchSignal = { score: number; reason: string };

const emailDomain = (email: string | undefined): string | null => {
  if (!email) return null;
  const at = email.indexOf("@");
  return at < 0 ? null : email.slice(at + 1).toLowerCase().trim();
};

const normPhone = (phone: string | undefined): string | null => {
  if (!phone) return null;
  const digits = phone.replace(/\D/g, "");
  return digits.length >= 7 ? digits.slice(-10) : null;
};

export function exactEmailMatch(a: SourceRecord, b: SourceRecord): MatchSignal | null {
  const ea = a.attributes.email?.toLowerCase().trim();
  const eb = b.attributes.email?.toLowerCase().trim();
  if (ea && eb && ea === eb) return { score: 1.0, reason: `Exact email match (${ea})` };
  return null;
}

export function emailDomainMatch(a: SourceRecord, b: SourceRecord): MatchSignal | null {
  const da = emailDomain(a.attributes.email);
  const db = emailDomain(b.attributes.email);
  if (da && db && da === db) return { score: 0.4, reason: `Same email domain (${da})` };
  return null;
}

export function phoneMatch(a: SourceRecord, b: SourceRecord): MatchSignal | null {
  const pa = normPhone(a.attributes.phone);
  const pb = normPhone(b.attributes.phone);
  if (pa && pb && pa === pb) return { score: 0.7, reason: `Phone match (${pa})` };
  return null;
}

export function fuzzyNameMatch(a: SourceRecord, b: SourceRecord): MatchSignal | null {
  const na = a.attributes.name;
  const nb = b.attributes.name;
  if (!na || !nb) return null;
  const sim = similarity(na, nb);
  if (sim >= 0.95) return { score: 0.9, reason: `Near-exact name match ("${na}" ≈ "${nb}", ${(sim * 100).toFixed(0)}%)` };
  if (sim >= 0.75) return { score: 0.55, reason: `Fuzzy name match ("${na}" ≈ "${nb}", ${(sim * 100).toFixed(0)}%)` };
  return null;
}

export function externalIdMatch(a: SourceRecord, b: SourceRecord): MatchSignal | null {
  const keys = ["external_id", "customer_id", "employee_id", "vendor_id"];
  for (const k of keys) {
    const va = a.attributes[k];
    const vb = b.attributes[k];
    if (va && vb && va === vb) return { score: 1.0, reason: `Matching ${k} (${va})` };
  }
  return null;
}

const STRATEGIES = [exactEmailMatch, externalIdMatch, fuzzyNameMatch, phoneMatch, emailDomainMatch];

export function scorePair(a: SourceRecord, b: SourceRecord): { score: number; reasons: string[] } {
  const signals: MatchSignal[] = [];
  for (const strat of STRATEGIES) {
    const s = strat(a, b);
    if (s) signals.push(s);
  }
  if (signals.length === 0) return { score: 0, reasons: [] };
  const combined = 1 - signals.reduce((acc, s) => acc * (1 - s.score), 1);
  return { score: combined, reasons: signals.map((s) => s.reason) };
}
