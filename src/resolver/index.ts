import type { Cluster, ResolvedAttribute, SourceRecord } from "../types";
import { scorePair } from "./strategies";

const AUTO_RESOLVE_THRESHOLD = 0.75;
const REVIEW_THRESHOLD = 0.45;

class UnionFind {
  private parent: Map<string, string> = new Map();
  add(x: string) { if (!this.parent.has(x)) this.parent.set(x, x); }
  find(x: string): string {
    let p = this.parent.get(x)!;
    while (p !== this.parent.get(p)) p = this.parent.get(p)!;
    let cur = x;
    while (this.parent.get(cur) !== p) { const next = this.parent.get(cur)!; this.parent.set(cur, p); cur = next; }
    return p;
  }
  union(a: string, b: string) {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra !== rb) this.parent.set(ra, rb);
  }
  groups(): Map<string, string[]> {
    const out = new Map<string, string[]>();
    for (const k of this.parent.keys()) {
      const r = this.find(k);
      if (!out.has(r)) out.set(r, []);
      out.get(r)!.push(k);
    }
    return out;
  }
}

function resolveAttributes(records: SourceRecord[]): Record<string, ResolvedAttribute> {
  const allKeys = new Set<string>();
  for (const r of records) for (const k of Object.keys(r.attributes)) allKeys.add(k);

  const out: Record<string, ResolvedAttribute> = {};
  for (const key of allKeys) {
    const values = records
      .filter((r) => r.attributes[key] != null && r.attributes[key] !== "")
      .map((r) => ({
        value: r.attributes[key],
        source: r.source,
        sourceLabel: r.sourceLabel,
        timestamp: r.timestamp,
      }));

    if (values.length === 0) continue;

    const distinct = new Map<string, typeof values>();
    for (const v of values) {
      const norm = v.value.toLowerCase().trim();
      if (!distinct.has(norm)) distinct.set(norm, []);
      distinct.get(norm)!.push(v);
    }

    if (distinct.size === 1) {
      const sorted = [...values].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      out[key] = { values, picked: sorted[0], conflict: false };
    } else {
      const sorted = [...values].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      out[key] = { values, picked: sorted[0], conflict: true };
    }
  }
  return out;
}

export type ResolverResult = {
  clusters: Cluster[];
  autoResolved: Cluster[];
  needsReview: Cluster[];
  singletons: Cluster[];
};

export function resolve(records: SourceRecord[]): ResolverResult {
  const uf = new UnionFind();
  records.forEach((r) => uf.add(r.id));

  const pairScores = new Map<string, { score: number; reasons: string[] }>();
  for (let i = 0; i < records.length; i++) {
    for (let j = i + 1; j < records.length; j++) {
      const result = scorePair(records[i], records[j]);
      if (result.score >= REVIEW_THRESHOLD) {
        uf.union(records[i].id, records[j].id);
        pairScores.set(`${records[i].id}|${records[j].id}`, result);
      }
    }
  }

  const groups = uf.groups();
  const byId = new Map(records.map((r) => [r.id, r]));

  const clusters: Cluster[] = [];
  for (const [groupId, ids] of groups) {
    const groupRecords = ids.map((id) => byId.get(id)!).filter(Boolean);
    const attributes = resolveAttributes(groupRecords);

    let maxScore = 0;
    const reasons: string[] = [];
    if (groupRecords.length > 1) {
      for (let i = 0; i < groupRecords.length; i++) {
        for (let j = i + 1; j < groupRecords.length; j++) {
          const k = `${groupRecords[i].id}|${groupRecords[j].id}`;
          const k2 = `${groupRecords[j].id}|${groupRecords[i].id}`;
          const ps = pairScores.get(k) || pairScores.get(k2);
          if (ps) {
            if (ps.score > maxScore) maxScore = ps.score;
            for (const r of ps.reasons) if (!reasons.includes(r)) reasons.push(r);
          }
        }
      }
    }

    const hasConflict = Object.values(attributes).some((a) => a.conflict);
    let status: Cluster["status"];
    if (groupRecords.length === 1) status = "singleton";
    else if (hasConflict || maxScore < AUTO_RESOLVE_THRESHOLD) status = "needs-review";
    else status = "auto-resolved";

    clusters.push({
      id: groupId,
      records: groupRecords,
      attributes,
      matchScore: maxScore,
      matchReasons: reasons,
      status,
    });
  }

  return {
    clusters,
    autoResolved: clusters.filter((c) => c.status === "auto-resolved"),
    needsReview: clusters.filter((c) => c.status === "needs-review"),
    singletons: clusters.filter((c) => c.status === "singleton"),
  };
}
