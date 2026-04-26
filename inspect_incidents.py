"""Inspect incidents_graph.json for changes vs the prior graph."""
import json
import sys
from collections import Counter

NEW = "incidents_graph.json"
OLD = "full_with_policies_resolved.json"

with open(NEW, "r", encoding="utf-8") as f:
    new = json.load(f)
with open(OLD, "r", encoding="utf-8") as f:
    old = json.load(f)


def conflicts(g):
    return g.get("graph", {}).get("conflicts", []) or g.get("conflicts", [])


new_conf = conflicts(new)
old_conf = conflicts(old)

print(f"OLD graph: {len(old_conf)} conflicts")
print(f"NEW graph: {len(new_conf)} conflicts")
print(f"Delta: {len(new_conf) - len(old_conf)}")
print()

print("=== NEW conflicts by type ===")
print(Counter(c.get("conflict_type") for c in new_conf))
print()

print("=== OLD conflicts by type ===")
print(Counter(c.get("conflict_type") for c in old_conf))
print()

# Find conflicts only present in NEW
old_keys = {(c.get("conflict_type"), tuple(sorted((c.get("entity_a") or c.get("nodes") or [str(c)])
            if isinstance((c.get("entity_a") or c.get("nodes")), list)
            else [str(c.get("entity_a")), str(c.get("entity_b"))]))) for c in old_conf}

added = []
for c in new_conf:
    key = (c.get("conflict_type"), tuple(sorted((c.get("entity_a") or c.get("nodes") or [str(c)])
           if isinstance((c.get("entity_a") or c.get("nodes")), list)
           else [str(c.get("entity_a")), str(c.get("entity_b"))])))
    if key not in old_keys:
        added.append(c)

print(f"=== {len(added)} conflicts present only in NEW ===")
print(Counter(c.get("conflict_type") for c in added))
print()

# Inspect change_log on Policy nodes
policy_changes = []
nodes = new.get("nodes", [])
for n in nodes:
    nid = n.get("id", "")
    if not str(nid).startswith("Policy:"):
        continue
    cl = n.get("change_log", [])
    if cl:
        policy_changes.append((nid, cl))

print(f"=== Policy nodes with change_log entries: {len(policy_changes)} ===")
for nid, cl in policy_changes[:20]:
    print(f"\n--- {nid} ({len(cl)} entries) ---")
    for entry in cl[-5:]:
        kind = entry.get("kind")
        prop = entry.get("property", "")
        if kind == "updated":
            old_v = entry.get("old_value", "")
            new_v = entry.get("new_value", "")
            old_s = (str(old_v)[:80] + "...") if len(str(old_v)) > 80 else str(old_v)
            new_s = (str(new_v)[:80] + "...") if len(str(new_v)) > 80 else str(new_v)
            print(f"  [updated] {prop}: {old_s!r} -> {new_s!r}")
        elif kind == "added":
            v = entry.get("value", "")
            v_s = (str(v)[:80] + "...") if len(str(v)) > 80 else str(v)
            print(f"  [added]   {prop}: {v_s!r}")
        else:
            print(f"  [{kind}]   {entry}")

# Sample of newly added conflicts
print(f"\n=== Sample of {min(5, len(added))} newly added conflicts ===")
for c in added[:5]:
    print(json.dumps(c, indent=2, default=str)[:1500])
    print("---")
