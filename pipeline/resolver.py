from collections import defaultdict
from dataclasses import dataclass

from .normalize import normalize_business_name
from .strategies import score_pair
from .types import AttributeValue, Cluster, Record, ResolvedAttribute


AUTO_RESOLVE_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.50


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for k in self.parent:
            out[self.find(k)].append(k)
        return dict(out)


def block_records(records: list[Record]) -> dict[str, list[Record]]:
    """Block records by first 4 chars of normalized name to avoid O(n^2) on full set."""
    blocks: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        name = normalize_business_name(r.attributes.get("business_name") or "")
        key = name[:4] if len(name) >= 4 else name
        blocks[key].append(r)
    return dict(blocks)


def resolve_attributes(records: list[Record]) -> dict[str, ResolvedAttribute]:
    keys: set[str] = set()
    for r in records:
        keys.update(r.attributes.keys())

    out: dict[str, ResolvedAttribute] = {}
    for key in keys:
        values: list[AttributeValue] = []
        for r in records:
            v = r.attributes.get(key)
            if v is None or v == "":
                continue
            values.append(
                AttributeValue(
                    value=v,
                    source_record_id=r.id,
                    source=r.source,
                    timestamp=r.timestamp,
                )
            )
        if not values:
            continue
        distinct = {str(v.value).strip().lower() for v in values}
        sorted_vals = sorted(values, key=lambda v: v.timestamp, reverse=True)
        out[key] = ResolvedAttribute(
            values=values,
            picked=sorted_vals[0],
            conflict=len(distinct) > 1,
        )
    return out


@dataclass
class ResolverResult:
    clusters: list[Cluster]

    @property
    def auto_resolved(self) -> list[Cluster]:
        return [c for c in self.clusters if c.status == "auto-resolved"]

    @property
    def needs_review(self) -> list[Cluster]:
        return [c for c in self.clusters if c.status == "needs-review"]

    @property
    def singletons(self) -> list[Cluster]:
        return [c for c in self.clusters if c.status == "singleton"]


def resolve(records: list[Record], verbose: bool = False) -> ResolverResult:
    uf = UnionFind()
    for r in records:
        uf.add(r.id)

    by_id = {r.id: r for r in records}
    pair_scores: dict[tuple[str, str], tuple[float, list[str]]] = {}

    blocks = block_records(records)
    if verbose:
        print(f"  Blocking: {len(blocks)} blocks, max block size = {max(len(v) for v in blocks.values())}")

    pair_count = 0
    for block_records_list in blocks.values():
        n = len(block_records_list)
        if n < 2:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                a, b = block_records_list[i], block_records_list[j]
                pair_count += 1
                score, reasons = score_pair(a, b)
                if score >= REVIEW_THRESHOLD:
                    key = (a.id, b.id) if a.id < b.id else (b.id, a.id)
                    pair_scores[key] = (score, reasons)
                    uf.union(a.id, b.id)

    if verbose:
        print(f"  Compared {pair_count} pairs, {len(pair_scores)} above review threshold")

    clusters: list[Cluster] = []
    for group_id, ids in uf.groups().items():
        cluster_records = [by_id[i] for i in ids]
        attributes = resolve_attributes(cluster_records)

        max_score = 1.0 if len(cluster_records) == 1 else 0.0
        all_reasons: list[str] = []
        for i in range(len(cluster_records)):
            for j in range(i + 1, len(cluster_records)):
                a, b = cluster_records[i], cluster_records[j]
                key = (a.id, b.id) if a.id < b.id else (b.id, a.id)
                if key in pair_scores:
                    s, rs = pair_scores[key]
                    if s > max_score:
                        max_score = s
                    for r in rs:
                        if r not in all_reasons:
                            all_reasons.append(r)

        has_conflict_on_identifier = False
        for ident_key in ("tax_id",):
            attr = attributes.get(ident_key)
            if attr and attr.conflict:
                has_conflict_on_identifier = True

        if len(cluster_records) == 1:
            status = "singleton"
            review_reason = None
        elif has_conflict_on_identifier:
            status = "needs-review"
            review_reason = "Conflicting tax_id values across matched records"
        elif max_score >= AUTO_RESOLVE_THRESHOLD:
            status = "auto-resolved"
            review_reason = None
        else:
            status = "needs-review"
            review_reason = f"Match confidence {max_score:.0%} below auto-resolve threshold ({AUTO_RESOLVE_THRESHOLD:.0%})"

        sorted_ids = sorted(ids)
        cluster_id = "+".join(sorted_ids)[:80] if len(sorted_ids) <= 5 else f"cluster-{hash(tuple(sorted_ids)) & 0xffffffff:x}"

        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                member_record_ids=sorted_ids,
                records=cluster_records,
                attributes=attributes,
                confidence=max_score,
                match_reasons=all_reasons,
                status=status,
                review_reason=review_reason,
            )
        )

    return ResolverResult(clusters=clusters)
