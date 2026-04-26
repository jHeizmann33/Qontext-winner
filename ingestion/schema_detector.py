"""
schema_detector.py — Heuristic schema inference for new data sources.

The Qontext ingesters are hand-written for the EnterpriseBench schema. To
generalise to a new company, a human still has to write an ingester — but
they shouldn't have to read every column manually first. This module scans
JSON or CSV files and produces a Markdown report that proposes:

    - the likely entity type (from filename + record shape)
    - the primary key field and its pattern (UUID / short-code / counter / …)
    - foreign-key candidates that point at IDs in other files
    - field types (string, int, date, email, boolean, …) with sample values
    - records per file and obvious data quality flags

The report is intended as a starting point for a human to validate before
adding a new ingester to the pipeline.

Usage:
    python schema_detector.py <data_dir> [--output schema_report.md]
    python schema_detector.py <single_file.json>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
EMP_ID_RE = re.compile(r"^[a-z]+_\d{3,}$", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
SHORT_CODE_RE = re.compile(r"^[a-z]{3,8}$")


def _classify_value(value: Any) -> str:
    """Best-effort classification of a single value."""
    if value is None or value == "":
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    s = str(value).strip()
    if UUID_RE.match(s):
        return "uuid"
    if EMP_ID_RE.match(s):
        return "prefixed_id"
    if EMAIL_RE.match(s):
        return "email"
    if DATE_RE.match(s):
        return "date"
    if SHORT_CODE_RE.match(s):
        return "short_code"
    if s.isdigit():
        return "numeric_string"
    return "string"


def _entity_type_from_filename(filename: str) -> str:
    """Heuristic: 'employees.json' -> 'Employee'. Strips trailing 's'."""
    base = Path(filename).stem
    base = re.sub(r"[_\-]+", " ", base)
    parts = base.split()
    main = parts[0] if parts else "Entity"
    if main.endswith("ies"):
        main = main[:-3] + "y"
    elif main.endswith("s") and len(main) > 3:
        main = main[:-1]
    return main.capitalize()


# ---------------------------------------------------------------------------
# Field profiling
# ---------------------------------------------------------------------------

def _profile_field(values: list[Any], total_records: int) -> dict:
    """
    Profile a single field across all records: dominant type, uniqueness,
    null rate, sample values.
    """
    non_null = [v for v in values if v not in (None, "", [], {})]
    type_counts = Counter(_classify_value(v) for v in non_null)
    dominant_type = type_counts.most_common(1)[0][0] if type_counts else "null"
    distinct = {str(v) for v in non_null}

    # Trim very long sample values so the report stays readable
    sample = list(distinct)[:3]
    sample = [s if len(s) <= 80 else s[:80] + "…" for s in sample]

    return {
        "dominant_type": dominant_type,
        "type_distribution": dict(type_counts.most_common(4)),
        "distinct_count": len(distinct),
        "non_null_count": len(non_null),
        "null_rate": round(1.0 - len(non_null) / max(total_records, 1), 3),
        "uniqueness_ratio": round(len(distinct) / max(len(non_null), 1), 3),
        "samples": sample,
    }


def _looks_like_id(field_name: str, profile: dict) -> bool:
    """A field is a plausible primary key if its name + uniqueness agree."""
    name_signal = bool(re.search(r"(^|_)(id|key|uuid)$|^id$", field_name, re.I))
    type_signal = profile["dominant_type"] in {"uuid", "prefixed_id", "short_code", "integer"}
    unique_signal = profile["uniqueness_ratio"] >= 0.99 and profile["non_null_count"] > 1
    return (name_signal or type_signal) and unique_signal


def _looks_like_foreign_key(field_name: str, profile: dict) -> bool:
    """Plausible FK: ID-like values that repeat across records."""
    name_signal = bool(re.search(r"_id$|_uuid$|_key$", field_name, re.I))
    type_signal = profile["dominant_type"] in {"uuid", "prefixed_id", "short_code"}
    repeats_signal = profile["uniqueness_ratio"] < 0.95 and profile["non_null_count"] > 1
    return name_signal and (type_signal or repeats_signal)


# ---------------------------------------------------------------------------
# File-level analysis
# ---------------------------------------------------------------------------

def _load_records(path: str, sample_limit: int = 1000) -> list[dict]:
    """Load JSON (list of dicts or single dict) or CSV into a list of dicts."""
    ext = Path(path).suffix.lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Dict of dicts pattern (e.g. { "id1": {...}, "id2": {...} })
            if all(isinstance(v, dict) for v in data.values()):
                records = [{**v, "_key": k} for k, v in list(data.items())[:sample_limit]]
            else:
                records = [data]
        elif isinstance(data, list):
            records = data[:sample_limit]
        else:
            records = []
    elif ext == ".csv":
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            records = []
            for row in reader:
                records.append(row)
                if len(records) >= sample_limit:
                    break
    else:
        records = []
    return [r for r in records if isinstance(r, dict)]


def detect_schema(path: str, sample_limit: int = 1000) -> dict:
    """Profile a single data file and return the inferred schema info."""
    records = _load_records(path, sample_limit=sample_limit)
    if not records:
        return {
            "file": path,
            "error": "no records or unsupported format",
        }

    # Collect values per field across records
    field_values: dict[str, list] = {}
    for rec in records:
        for k, v in rec.items():
            field_values.setdefault(k, []).append(v)

    field_profiles = {
        k: _profile_field(v, total_records=len(records))
        for k, v in field_values.items()
    }

    primary_key_candidates = sorted(
        [(k, p["uniqueness_ratio"]) for k, p in field_profiles.items()
         if _looks_like_id(k, p)],
        key=lambda kv: -kv[1],
    )
    foreign_key_candidates = [
        k for k, p in field_profiles.items() if _looks_like_foreign_key(k, p)
    ]

    return {
        "file": path,
        "entity_type_guess": _entity_type_from_filename(path),
        "record_count_sample": len(records),
        "field_count": len(field_profiles),
        "primary_key_candidates": [k for k, _ in primary_key_candidates],
        "foreign_key_candidates": foreign_key_candidates,
        "fields": field_profiles,
    }


# ---------------------------------------------------------------------------
# Cross-file analysis (FK linkage)
# ---------------------------------------------------------------------------

def detect_cross_file_links(file_schemas: list[dict]) -> list[dict]:
    """
    Identify FK candidates in one file whose values overlap with the primary
    key of another file. Surface those as proposed graph edges.
    """
    # Index PKs by file: { file: { pk_field: set(values) } }
    pk_values: dict[str, dict[str, set]] = {}
    for sch in file_schemas:
        if "error" in sch:
            continue
        pks = sch.get("primary_key_candidates", [])
        if not pks:
            continue
        # We need the actual values, so re-load (cheap — sample_limit caps it)
        records = _load_records(sch["file"])
        for pk in pks:
            values = {str(r.get(pk)) for r in records if r.get(pk) not in (None, "")}
            pk_values.setdefault(sch["file"], {})[pk] = values

    links = []
    for sch in file_schemas:
        if "error" in sch:
            continue
        fks = sch.get("foreign_key_candidates", [])
        if not fks:
            continue
        records = _load_records(sch["file"])
        for fk in fks:
            fk_values = {str(r.get(fk)) for r in records if r.get(fk) not in (None, "")}
            if not fk_values:
                continue
            for other_file, other_pks in pk_values.items():
                if other_file == sch["file"]:
                    continue
                for other_pk, pk_set in other_pks.items():
                    overlap = fk_values & pk_set
                    if not overlap:
                        continue
                    coverage = len(overlap) / max(len(fk_values), 1)
                    if coverage >= 0.5:
                        links.append({
                            "from_file": sch["file"],
                            "from_field": fk,
                            "to_file": other_file,
                            "to_field": other_pk,
                            "coverage": round(coverage, 3),
                            "overlap_count": len(overlap),
                        })
    return links


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_report(file_schemas: list[dict], cross_links: list[dict]) -> str:
    lines = []
    lines.append("# Schema-detection report")
    lines.append("")
    lines.append(
        "_Heuristic inference — review before adding ingesters. "
        "PK / FK suggestions are based on naming + uniqueness patterns and "
        "may miss compound keys or semantic links._"
    )
    lines.append("")

    # Per-file sections
    for sch in file_schemas:
        lines.append(f"## `{sch['file']}`")
        if "error" in sch:
            lines.append(f"_{sch['error']}_")
            lines.append("")
            continue
        lines.append(f"- Likely entity type: **{sch['entity_type_guess']}**")
        lines.append(f"- Records sampled: {sch['record_count_sample']}")
        lines.append(f"- Fields: {sch['field_count']}")
        if sch["primary_key_candidates"]:
            lines.append(f"- Primary key candidates: " +
                         ", ".join(f"`{k}`" for k in sch["primary_key_candidates"]))
        else:
            lines.append("- _No clear primary key candidate_")
        if sch["foreign_key_candidates"]:
            lines.append(f"- Foreign key candidates: " +
                         ", ".join(f"`{k}`" for k in sch["foreign_key_candidates"]))
        lines.append("")

        lines.append("| Field | Type | Distinct | Null rate | Sample |")
        lines.append("|---|---|---|---|---|")
        for fname, prof in sch["fields"].items():
            samples = " · ".join(prof["samples"])
            lines.append(
                f"| `{fname}` | {prof['dominant_type']} | "
                f"{prof['distinct_count']} | {prof['null_rate']} | {samples} |"
            )
        lines.append("")

    # Cross-file links
    lines.append("## Detected cross-file links")
    if not cross_links:
        lines.append("_No high-confidence foreign-key overlaps detected._")
    else:
        lines.append("| From file | From field | To file | To field | FK coverage | Overlap |")
        lines.append("|---|---|---|---|---|---|")
        for link in sorted(cross_links, key=lambda l: -l["coverage"]):
            lines.append(
                f"| `{link['from_file']}` | `{link['from_field']}` | "
                f"`{link['to_file']}` | `{link['to_field']}` | "
                f"{link['coverage']} | {link['overlap_count']} |"
            )
    lines.append("")

    lines.append("## Suggested next steps")
    lines.append(
        "1. Validate primary key candidates — pick the right one if multiple "
        "fields are flagged.\n"
        "2. Confirm cross-file links — these become graph edges in your new "
        "ingester.\n"
        "3. Map each entity-type guess to a node type from "
        "`graph_utils.SOURCE_CANONICAL_FOR` (or extend that table for the "
        "new domain).\n"
        "4. Use one of the existing `ingest_*.py` files as a template — "
        "all of them follow the same `add_node` + `make_provenance` + "
        "`add_edge` pattern."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Heuristic schema detection")
    parser.add_argument("path", help="Data file or directory to scan")
    parser.add_argument("--output", default=None,
                        help="Write Markdown report to this file (default: stdout)")
    parser.add_argument("--limit", type=int, default=1000,
                        help="Records sampled per file (default: 1000)")
    args = parser.parse_args()

    if os.path.isfile(args.path):
        files = [args.path]
    elif os.path.isdir(args.path):
        files = []
        for ext in ("*.json", "*.csv"):
            files.extend(str(p) for p in Path(args.path).rglob(ext))
    else:
        print(f"Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    file_schemas = [detect_schema(f, sample_limit=args.limit) for f in sorted(files)]
    cross_links = detect_cross_file_links(file_schemas)
    report = render_report(file_schemas, cross_links)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {args.output} "
              f"({len(file_schemas)} files, {len(cross_links)} cross-file links)")
    else:
        print(report)


if __name__ == "__main__":
    main()
