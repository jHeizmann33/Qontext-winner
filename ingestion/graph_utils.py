"""
graph_utils.py — Core graph utilities for the Qontext context base.

Provides helper functions for building a NetworkX knowledge graph with
per-fact provenance tracking and conflict detection.

Usage:
    from graph_utils import create_graph, add_node, add_edge, save_graph, load_graph
"""

import json
import hashlib
from datetime import datetime
from typing import Any, Optional
import networkx as nx


# ---------------------------------------------------------------------------
# Graph creation
# ---------------------------------------------------------------------------

def create_graph() -> nx.MultiDiGraph:
    """
    Create an empty knowledge graph.
    
    Uses MultiDiGraph because:
    - Directed: relationships have direction (Employee --works_in--> Department)
    - Multi: two nodes can have multiple relationship types between them
      (e.g. Employee --sent_email--> Email AND Employee --received_email--> Email)
    """
    G = nx.MultiDiGraph()
    # Store metadata on the graph itself
    G.graph["created_at"] = datetime.utcnow().isoformat()
    G.graph["conflicts"] = []  # List of detected conflicts
    G.graph["stats"] = {}      # Ingestion statistics
    return G


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def make_provenance(
    source_system: str,
    file: str,
    record_id: str,
    field: Optional[str] = None,
    confidence: float = 1.0,
    timestamp: Optional[str] = None
) -> dict:
    """
    Create a provenance record for a fact.
    
    Args:
        source_system: e.g. "Human_Resource_Management"
        file: e.g. "employees.json"
        record_id: e.g. "emp_0431" or "index:0"
        field: specific field this fact came from, e.g. "Name"
        confidence: 1.0 = direct authoritative, 0.7 = LLM-extracted, 0.5 = inferred
        timestamp: when the source record was created/updated (if known)
    """
    prov = {
        "source_system": source_system,
        "file": file,
        "record_id": record_id,
        "confidence": confidence,
        "ingested_at": datetime.utcnow().isoformat()
    }
    if field:
        prov["field"] = field
    if timestamp:
        prov["timestamp"] = timestamp
    return prov


# ---------------------------------------------------------------------------
# Node operations
# ---------------------------------------------------------------------------

def make_node_id(node_type: str, key: str) -> str:
    """
    Create a canonical node ID. Format: "Type:key"
    Examples: "Employee:emp_0431", "Department:Engineering", "Customer:arout"
    """
    return f"{node_type}:{key}"


def add_node(
    graph: nx.MultiDiGraph,
    node_id: str,
    node_type: str,
    properties: dict[str, Any],
    provenance: dict
) -> str:
    """
    Add or update a node in the graph with provenance tracking.
    
    If the node already exists, properties are merged:
    - New properties are added
    - Existing properties with different values trigger conflict detection
    - Provenance is appended (a node can have facts from multiple sources)
    
    Args:
        graph: the knowledge graph
        node_id: canonical ID, e.g. "Employee:emp_0431"
        node_type: entity type, e.g. "Employee"
        properties: dict of property name → value
        provenance: provenance record from make_provenance()
    
    Returns:
        The node_id (for chaining)
    """
    now_iso = datetime.utcnow().isoformat()
    if graph.has_node(node_id):
        # Node exists — merge properties, detect conflicts
        existing = graph.nodes[node_id]
        change_log = existing.setdefault("change_log", [])

        for key, new_value in properties.items():
            existing_props = existing.setdefault("properties", {})
            if key in existing_props and existing_props[key] != new_value:
                # Conflict detected — different value for same property
                conflict = {
                    "entity_id": node_id,
                    "entity_type": node_type,
                    "field": key,
                    "existing_value": existing_props[key],
                    "new_value": new_value,
                    "existing_provenance": _find_provenance_for_field(existing, key),
                    "new_provenance": {**provenance, "field": key},
                    "detected_at": now_iso,
                    "resolution": None  # To be filled by auto-resolve or human review
                }

                # Auto-resolve based on source authority
                resolution = _try_auto_resolve(conflict)
                if resolution:
                    conflict["resolution"] = resolution
                    if resolution["winner"] == "new":
                        # Actual value change → record in change_log so the
                        # VFS can surface "Updated DD-MM: field X went from A to B"
                        change_log.append({
                            "field": key,
                            "old_value": existing_props[key],
                            "new_value": new_value,
                            "kind": "updated",
                            "at": now_iso,
                            "source_system": provenance.get("source_system"),
                            "source_record_id": provenance.get("record_id"),
                            "reason": resolution.get("reason"),
                        })
                        existing_props[key] = new_value
                    # else: keep existing value
                else:
                    # Queue for human review
                    conflict["resolution"] = {"status": "pending_review"}

                graph.graph["conflicts"].append(conflict)
            elif key not in existing_props:
                # New property added on an existing node — also a change.
                existing_props[key] = new_value
                change_log.append({
                    "field": key,
                    "old_value": None,
                    "new_value": new_value,
                    "kind": "added",
                    "at": now_iso,
                    "source_system": provenance.get("source_system"),
                    "source_record_id": provenance.get("record_id"),
                })
            # else: same value — no change, no log entry

        # Append provenance
        existing.setdefault("provenance", []).append(provenance)
    else:
        # New node
        graph.add_node(node_id,
            node_type=node_type,
            properties=properties,
            provenance=[provenance],
            change_log=[],
        )

    return node_id


def _find_provenance_for_field(node_data: dict, field: str) -> Optional[dict]:
    """Find the provenance record that set a specific field."""
    for prov in node_data.get("provenance", []):
        if prov.get("field") == field:
            return prov
    # If no field-specific provenance, return the first one (general source)
    provenance_list = node_data.get("provenance", [])
    return provenance_list[0] if provenance_list else None


# ---------------------------------------------------------------------------
# Source authority for conflict resolution
# ---------------------------------------------------------------------------

SOURCE_AUTHORITY = {
    "Human_Resource_Management": 100,
    "Customer_Relation_Management": 90,
    "Business_and_Management": 85,
    "IT_Service_Management": 80,
    "Workspace": 75,               # GitHub
    "Enterprise_Mail_System": 60,
    "Collaboration_tools": 50,
    "Enterprise_Social_Platform": 40,
    "Inazuma_overflow": 30,
}

# Which source is authoritative for which entity types
SOURCE_CANONICAL_FOR = {
    "Human_Resource_Management": ["Employee", "Department"],
    "Customer_Relation_Management": ["Customer", "Product", "Sale", "Review"],
    "Business_and_Management": ["Client", "Vendor"],
    "IT_Service_Management": ["ITTicket"],
    "Workspace": ["GitHubRepo", "GitHubIssue"],
}


def _try_auto_resolve(conflict: dict) -> Optional[dict]:
    """
    Attempt to auto-resolve a conflict based on source authority.
    
    Returns a resolution dict if auto-resolved, None if needs human review.
    """
    existing_prov = conflict.get("existing_provenance", {})
    new_prov = conflict.get("new_provenance", {})
    
    if not existing_prov or not new_prov:
        return None

    existing_source = existing_prov.get("source_system", "")
    new_source = new_prov.get("source_system", "")

    # Same source touching the same fact = re-ingest of an updated record. The
    # newer reading is the truth, otherwise property changes in source data
    # would never propagate into the graph.
    if existing_source and existing_source == new_source:
        return {
            "status": "auto_resolved",
            "winner": "new",
            "reason": f"Re-ingest from {existing_source} — newer reading wins"
        }

    existing_authority = SOURCE_AUTHORITY.get(existing_source, 0)
    new_authority = SOURCE_AUTHORITY.get(new_source, 0)

    # Check if one source is canonical for this entity type
    entity_type = conflict.get("entity_type", "")
    for source, types in SOURCE_CANONICAL_FOR.items():
        if entity_type in types:
            if existing_source == source:
                return {
                    "status": "auto_resolved",
                    "winner": "existing",
                    "reason": f"{source} is canonical for {entity_type} entities"
                }
            elif new_source == source:
                return {
                    "status": "auto_resolved",
                    "winner": "new",
                    "reason": f"{source} is canonical for {entity_type} entities"
                }
    
    # If authority difference is large enough, auto-resolve
    if abs(existing_authority - new_authority) >= 20:
        winner = "existing" if existing_authority > new_authority else "new"
        return {
            "status": "auto_resolved",
            "winner": winner,
            "reason": f"Source authority: {existing_prov.get('source_system')}={existing_authority} vs {new_prov.get('source_system')}={new_authority}"
        }
    
    # Too close to call — needs human review
    return None


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------

def add_edge(
    graph: nx.MultiDiGraph,
    source: str,
    target: str,
    rel_type: str,
    properties: Optional[dict] = None,
    provenance: Optional[dict] = None
) -> None:
    """
    Add a directed relationship edge between two nodes.
    
    Args:
        graph: the knowledge graph
        source: source node ID, e.g. "Employee:emp_0431"
        target: target node ID, e.g. "Department:Engineering"
        rel_type: relationship type, e.g. "works_in"
        properties: optional edge properties
        provenance: provenance record
    """
    edge_data = {
        "rel_type": rel_type,
        "properties": properties or {},
        "provenance": [provenance] if provenance else []
    }
    graph.add_edge(source, target, key=rel_type, **edge_data)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def save_graph(graph: nx.MultiDiGraph, filepath: str) -> None:
    """
    Save the graph to a JSON file.
    
    Output format:
    {
        "metadata": { "created_at": "...", "node_count": N, "edge_count": M },
        "nodes": [ { "id": "...", "type": "...", "properties": {...}, "provenance": [...] } ],
        "edges": [ { "source": "...", "target": "...", "rel_type": "...", "properties": {...}, "provenance": [...] } ],
        "conflicts": [ { ... } ]
    }
    """
    data = {
        "metadata": {
            "created_at": graph.graph.get("created_at"),
            "saved_at": datetime.utcnow().isoformat(),
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "conflict_count": len(graph.graph.get("conflicts", [])),
            "stats": graph.graph.get("stats", {})
        },
        "nodes": [],
        "edges": [],
        "conflicts": graph.graph.get("conflicts", [])
    }
    
    for node_id, node_data in graph.nodes(data=True):
        data["nodes"].append({
            "id": node_id,
            "type": node_data.get("node_type", "Unknown"),
            "properties": node_data.get("properties", {}),
            "provenance": node_data.get("provenance", []),
            "change_log": node_data.get("change_log", []),
        })
    
    for source, target, key, edge_data in graph.edges(data=True, keys=True):
        data["edges"].append({
            "source": source,
            "target": target,
            "rel_type": edge_data.get("rel_type", key),
            "properties": edge_data.get("properties", {}),
            "provenance": edge_data.get("provenance", [])
        })
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    
    print(f"Graph saved: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges, {len(graph.graph.get('conflicts', []))} conflicts → {filepath}")


def load_graph(filepath: str) -> nx.MultiDiGraph:
    """Load a graph from a JSON file."""
    with open(filepath) as f:
        data = json.load(f)
    
    G = nx.MultiDiGraph()
    G.graph["created_at"] = data.get("metadata", {}).get("created_at")
    G.graph["conflicts"] = data.get("conflicts", [])
    G.graph["stats"] = data.get("metadata", {}).get("stats", {})
    
    for node in data["nodes"]:
        G.add_node(node["id"],
            node_type=node["type"],
            properties=node["properties"],
            provenance=node["provenance"],
            change_log=node.get("change_log", []),
        )
    
    for edge in data["edges"]:
        G.add_edge(edge["source"], edge["target"],
            key=edge["rel_type"],
            rel_type=edge["rel_type"],
            properties=edge["properties"],
            provenance=edge["provenance"]
        )
    
    return G


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_node(graph: nx.MultiDiGraph, node_id: str) -> Optional[dict]:
    """Get a node's full data by ID."""
    if graph.has_node(node_id):
        data = graph.nodes[node_id]
        return {
            "id": node_id,
            "type": data.get("node_type"),
            "properties": data.get("properties", {}),
            "provenance": data.get("provenance", [])
        }
    return None


def get_neighbors(graph: nx.MultiDiGraph, node_id: str, rel_type: Optional[str] = None) -> list[dict]:
    """
    Get all nodes connected to a given node.
    Optionally filter by relationship type.
    """
    results = []
    
    # Outgoing edges
    for _, target, key, data in graph.out_edges(node_id, data=True, keys=True):
        if rel_type is None or data.get("rel_type") == rel_type:
            target_data = graph.nodes[target]
            results.append({
                "direction": "outgoing",
                "rel_type": data.get("rel_type", key),
                "node_id": target,
                "node_type": target_data.get("node_type"),
                "properties": target_data.get("properties", {})
            })
    
    # Incoming edges
    for source, _, key, data in graph.in_edges(node_id, data=True, keys=True):
        if rel_type is None or data.get("rel_type") == rel_type:
            source_data = graph.nodes[source]
            results.append({
                "direction": "incoming",
                "rel_type": data.get("rel_type", key),
                "node_id": source,
                "node_type": source_data.get("node_type"),
                "properties": source_data.get("properties", {})
            })
    
    return results


def get_entities_by_type(graph: nx.MultiDiGraph, node_type: str) -> list[str]:
    """Get all node IDs of a given type."""
    return [
        node_id for node_id, data in graph.nodes(data=True)
        if data.get("node_type") == node_type
    ]


def get_stats(graph: nx.MultiDiGraph) -> dict:
    """Get summary statistics for the graph."""
    type_counts = {}
    for _, data in graph.nodes(data=True):
        t = data.get("node_type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    
    rel_counts = {}
    for _, _, _, data in graph.edges(data=True, keys=True):
        r = data.get("rel_type", "unknown")
        rel_counts[r] = rel_counts.get(r, 0) + 1
    
    return {
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "total_conflicts": len(graph.graph.get("conflicts", [])),
        "nodes_by_type": type_counts,
        "edges_by_type": rel_counts
    }
