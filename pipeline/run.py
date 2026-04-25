import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .load import load_business_and_management
from .resolver import resolve
from .types import Cluster


def cluster_to_jsonable(c: Cluster) -> dict:
    return {
        "cluster_id": c.cluster_id,
        "status": c.status,
        "confidence": round(c.confidence, 3),
        "member_record_ids": c.member_record_ids,
        "match_reasons": c.match_reasons,
        "review_reason": c.review_reason,
        "merged_attributes": {
            k: {
                "picked_value": v.picked.value if v.picked else None,
                "picked_source_record_id": v.picked.source_record_id if v.picked else None,
                "picked_source": v.picked.source if v.picked else None,
                "conflict": v.conflict,
                "all_values": [
                    {
                        "value": av.value,
                        "source_record_id": av.source_record_id,
                        "source": av.source,
                        "timestamp": av.timestamp,
                    }
                    for av in v.values
                ],
            }
            for k, v in c.attributes.items()
        },
    }


def write_report(result, out_dir: Path) -> None:
    auto = result.auto_resolved
    review = result.needs_review
    singletons = result.singletons
    total_records = sum(len(c.records) for c in result.clusters)

    lines = []
    lines.append("# Qontext Resolver — Run Report")
    lines.append("")
    lines.append(f"- **Total input records:** {total_records}")
    lines.append(f"- **Total clusters formed:** {len(result.clusters)}")
    lines.append(f"  - Auto-resolved (multi-member): {len(auto)}")
    lines.append(f"  - Needs review: {len(review)}")
    lines.append(f"  - Singletons: {len(singletons)}")
    lines.append(f"- **Records merged:** {sum(len(c.records) for c in auto)} (records collapsed into auto-resolved clusters)")
    lines.append(f"- **Dedup rate:** {(1 - len(result.clusters) / total_records) * 100:.1f}% (clusters / records)")
    lines.append("")

    lines.append("## Auto-resolved (sample, up to 10)")
    lines.append("")
    for c in auto[:10]:
        name = c.attributes.get("business_name")
        name_val = name.picked.value if name and name.picked else "(no name)"
        lines.append(f"### {name_val}  —  confidence {c.confidence:.0%}")
        lines.append(f"- Members: `{', '.join(c.member_record_ids)}`")
        lines.append(f"- Match reasons:")
        for r in c.match_reasons:
            lines.append(f"  - {r}")
        conflicts = [k for k, v in c.attributes.items() if v.conflict]
        if conflicts:
            lines.append(f"- Conflicting attributes: {', '.join(conflicts)}")
        lines.append("")

    lines.append("## Needs review (sample, up to 15)")
    lines.append("")
    for c in review[:15]:
        name_attr = c.attributes.get("business_name")
        name_val = name_attr.picked.value if name_attr and name_attr.picked else "(no name)"
        lines.append(f"### {name_val}  —  confidence {c.confidence:.0%}")
        lines.append(f"- Members: `{', '.join(c.member_record_ids)}`")
        lines.append(f"- Reason: **{c.review_reason}**")
        lines.append(f"- Match signals:")
        for r in c.match_reasons:
            lines.append(f"  - {r}")
        names_seen = name_attr.values if name_attr else []
        if len(names_seen) > 1:
            lines.append(f"- Names seen: {', '.join(repr(v.value) for v in names_seen)}")
        lines.append("")

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="c:/Users/heizm/Documents/Playground/EnterpriseBench-data/Business_and_Management")
    parser.add_argument("--out-dir", default="c:/Users/heizm/Documents/Playground/Qontext-winner/output")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on records (per source)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading from {data_dir}...")
    records = load_business_and_management(data_dir)
    if args.limit:
        clients = [r for r in records if r.source == "clients"][: args.limit]
        vendors = [r for r in records if r.source == "vendors"][: args.limit]
        records = clients + vendors
    print(f"  Loaded {len(records)} records ({sum(1 for r in records if r.source=='clients')} clients, {sum(1 for r in records if r.source=='vendors')} vendors)")

    print("Resolving...")
    result = resolve(records, verbose=args.verbose)
    print(f"  -> {len(result.clusters)} clusters: {len(result.auto_resolved)} auto-resolved, {len(result.needs_review)} review, {len(result.singletons)} singletons")

    print(f"Writing output to {out_dir}...")
    (out_dir / "clusters.json").write_text(
        json.dumps([cluster_to_jsonable(c) for c in result.auto_resolved], indent=2, default=str),
        encoding="utf-8",
    )
    (out_dir / "review_queue.json").write_text(
        json.dumps([cluster_to_jsonable(c) for c in result.needs_review], indent=2, default=str),
        encoding="utf-8",
    )
    (out_dir / "singletons.json").write_text(
        json.dumps([cluster_to_jsonable(c) for c in result.singletons], indent=2, default=str),
        encoding="utf-8",
    )

    stats = {
        "total_records": len(records),
        "total_clusters": len(result.clusters),
        "auto_resolved": len(result.auto_resolved),
        "needs_review": len(result.needs_review),
        "singletons": len(result.singletons),
        "records_merged_into_auto": sum(len(c.records) for c in result.auto_resolved),
        "records_in_review": sum(len(c.records) for c in result.needs_review),
        "dedup_rate_pct": round((1 - len(result.clusters) / len(records)) * 100, 2) if records else 0,
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    write_report(result, out_dir)
    print("\n=== STATS ===")
    print(json.dumps(stats, indent=2))
    print(f"\nReport written to {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
