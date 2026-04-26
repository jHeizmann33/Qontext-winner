"""
server.py — FastAPI backend for the Qontext context base.

Serves:
    - Virtual file system (browsable markdown pages generated from the graph)
    - Graph query endpoints (raw node/edge data)
    - Conflict queue (for human review)
    - Stats and metadata

Usage:
    pip install fastapi uvicorn networkx
    python server.py --graph ./graph.json

Then visit http://localhost:8000/docs for the auto-generated API docs.
"""

import os
import sys
import argparse
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Add parent directory to path so we can import graph_utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ingestion"))
from graph_utils import (
    load_graph, save_graph, get_node, get_neighbors,
    get_entities_by_type, get_stats,
    make_node_id, make_provenance, add_node, add_edge,
)

from vfs_generator import (
    generate_employee_page,
    generate_customer_page,
    generate_team_page,
    generate_policy_page,
    list_directory,
)
from retrieval import LocalHybridRetriever

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Qontext — Company Context Base",
    description="A structured company memory built from 10 source systems. "
                "Browse the virtual file system, query the knowledge graph, "
                "and review detected conflicts.",
    version="0.1.0"
)

# Allow frontend to call the API (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, lock this down
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global graph reference — loaded on startup
GRAPH = None
GRAPH_PATH: Optional[str] = None
RETRIEVER = None
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIST_DIR = os.path.join(APP_ROOT, "frontend", "dist")
FRONTEND_INDEX_PATH = os.path.join(FRONTEND_DIST_DIR, "index.html")


# Maps URL section names to graph entity types so edits/notes can target any
# entity uniformly without re-listing the routing table per endpoint.
SECTION_TO_TYPE: dict[str, str] = {
    "people": "Employee",
    "customers": "Customer",
    "teams": "Department",
    "clients": "Client",
    "vendors": "Vendor",
    "products": "Product",
    "it-tickets": "ITTicket",
    "policies": "Policy",
}


def _persist_and_reindex() -> None:
    """Save the graph to disk (if loaded from a file) and rebuild the retriever
    index so every read-side surface reflects the latest mutation."""
    global RETRIEVER
    if GRAPH_PATH:
        save_graph(GRAPH, GRAPH_PATH)
    RETRIEVER = LocalHybridRetriever(GRAPH)


def _resolve_target_node(section: str, entity_id: str) -> str:
    """Translate (section, id) into the canonical node_id, raising 404 if missing."""
    node_type = SECTION_TO_TYPE.get(section)
    if not node_type:
        raise HTTPException(status_code=404, detail=f"Unknown section '{section}'")
    node_id = make_node_id(node_type, entity_id)
    if not GRAPH.has_node(node_id):
        raise HTTPException(status_code=404, detail=f"{node_type} '{entity_id}' not found")
    return node_id


# ---------------------------------------------------------------------------
# Virtual file system endpoints
# ---------------------------------------------------------------------------

@app.get("/vfs/{path:path}", response_class=JSONResponse,
         tags=["Virtual File System"],
         summary="Browse the virtual file system")
def vfs_browse(path: str = ""):
    """
    Browse the virtual file system.
    
    - Directory paths return a listing of children
    - File paths return generated markdown content
    
    Examples:
        GET /vfs/              → root directory listing
        GET /vfs/people        → list all employees
        GET /vfs/people/emp_0431  → Raj Patel's profile page
        GET /vfs/customers/arout  → customer profile
        GET /vfs/teams/Engineering → Engineering team page
    """
    path = path.strip("/")
    
    # --- Route to the right generator ---
    
    # File paths (contain a specific entity ID)
    parts = path.split("/")
    
    if len(parts) == 2:
        section, entity_id = parts
        
        if section == "people":
            content = generate_employee_page(GRAPH, entity_id)
            if content is None:
                raise HTTPException(status_code=404, detail=f"Employee {entity_id} not found")
            return {"path": f"/{path}", "type": "file", "format": "markdown", "content": content}
        
        elif section == "customers":
            content = generate_customer_page(GRAPH, entity_id)
            if content is None:
                raise HTTPException(status_code=404, detail=f"Customer {entity_id} not found")
            return {"path": f"/{path}", "type": "file", "format": "markdown", "content": content}
        
        elif section == "teams":
            content = generate_team_page(GRAPH, entity_id)
            if content is None:
                raise HTTPException(status_code=404, detail=f"Team {entity_id} not found")
            return {"path": f"/{path}", "type": "file", "format": "markdown", "content": content}
        
        elif section == "clients":
            # For clients, we need to generate a page (TODO: add generate_client_page)
            node = get_node(GRAPH, f"Client:{entity_id}")
            if node is None:
                raise HTTPException(status_code=404, detail=f"Client {entity_id} not found")
            # Return raw data for now
            return {"path": f"/{path}", "type": "file", "format": "json", "content": node}
        
        elif section == "products":
            node = get_node(GRAPH, f"Product:{entity_id}")
            if node is None:
                raise HTTPException(status_code=404, detail=f"Product {entity_id} not found")
            return {"path": f"/{path}", "type": "file", "format": "json", "content": node}
        
        elif section == "it-tickets":
            node = get_node(GRAPH, f"ITTicket:{entity_id}")
            if node is None:
                raise HTTPException(status_code=404, detail=f"Ticket {entity_id} not found")
            return {"path": f"/{path}", "type": "file", "format": "json", "content": node}

        elif section == "policies":
            content = generate_policy_page(GRAPH, entity_id)
            if content is None:
                raise HTTPException(status_code=404, detail=f"Policy {entity_id} not found")
            return {"path": f"/{path}", "type": "file", "format": "markdown", "content": content}

    # Directory paths
    listing = list_directory(GRAPH, path)
    if not listing["children"] and path:
        raise HTTPException(status_code=404, detail=f"Path /{path} not found")
    return listing


# ---------------------------------------------------------------------------
# Graph query endpoints
# ---------------------------------------------------------------------------

@app.get("/graph/stats", tags=["Graph"],
         summary="Get graph statistics")
def graph_stats():
    """Returns node counts by type, edge counts by type, and conflict summary."""
    stats = get_stats(GRAPH)
    
    conflicts = GRAPH.graph.get("conflicts", [])
    stats["conflicts_summary"] = {
        "total": len(conflicts),
        "auto_resolved": sum(1 for c in conflicts if c.get("resolution", {}).get("status") == "auto_resolved"),
        "pending_review": sum(1 for c in conflicts if c.get("resolution", {}).get("status") == "pending_review"),
    }
    
    return stats


@app.get("/graph/node/{node_type}/{node_key}", tags=["Graph"],
         summary="Get raw node data")
def graph_node(node_type: str, node_key: str):
    """
    Get full data for a specific node.
    
    Example: GET /graph/node/Employee/emp_0431
    """
    node_id = f"{node_type}:{node_key}"
    node = get_node(GRAPH, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return node


@app.get("/graph/neighbors/{node_type}/{node_key}", tags=["Graph"],
         summary="Get connected nodes")
def graph_neighbors(node_type: str, node_key: str, rel_type: str = None):
    """
    Get all nodes connected to a given node.
    Optionally filter by relationship type.
    
    Example: GET /graph/neighbors/Employee/emp_0431?rel_type=sent_email
    """
    node_id = f"{node_type}:{node_key}"
    if not GRAPH.has_node(node_id):
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    
    neighbors = get_neighbors(GRAPH, node_id, rel_type=rel_type)
    return {"node_id": node_id, "neighbors": neighbors, "count": len(neighbors)}


@app.get("/graph/entities/{node_type}", tags=["Graph"],
         summary="List all entities of a type")
def graph_entities(node_type: str, limit: int = 100, offset: int = 0):
    """
    List all entity IDs of a given type.
    
    Example: GET /graph/entities/Employee?limit=10
    """
    entities = get_entities_by_type(GRAPH, node_type)
    total = len(entities)
    page = entities[offset:offset + limit]
    
    results = []
    for eid in page:
        node_data = GRAPH.nodes.get(eid, {})
        results.append({
            "id": eid,
            "properties": node_data.get("properties", {})
        })
    
    return {"type": node_type, "total": total, "offset": offset, "limit": limit, "entities": results}


# ---------------------------------------------------------------------------
# Conflict queue endpoints
# ---------------------------------------------------------------------------

@app.get("/conflicts", tags=["Conflicts"],
         summary="Get all detected conflicts")
def list_conflicts(status: str = None):
    """
    List all conflicts. Optionally filter by status:
    - pending_review: needs human decision
    - auto_resolved: system decided automatically
    
    Example: GET /conflicts?status=pending_review
    """
    conflicts = GRAPH.graph.get("conflicts", [])
    
    if status:
        conflicts = [c for c in conflicts if c.get("resolution", {}).get("status") == status]
    
    return {
        "total": len(conflicts),
        "conflicts": conflicts
    }


@app.post("/conflicts/{index}/resolve", tags=["Conflicts"],
          summary="Resolve a conflict manually")
def resolve_conflict(index: int, winner: str, reason: str = "Manual resolution"):
    """
    Resolve a pending conflict by choosing a winner.
    
    Args:
        index: conflict index in the list
        winner: "existing" or "new"
        reason: human-provided reason for the decision
    """
    conflicts = GRAPH.graph.get("conflicts", [])
    
    if index < 0 or index >= len(conflicts):
        raise HTTPException(status_code=404, detail=f"Conflict {index} not found")
    
    conflict = conflicts[index]
    if conflict.get("resolution", {}).get("status") != "pending_review":
        raise HTTPException(status_code=400, detail="Conflict already resolved")
    
    conflict["resolution"] = {
        "status": "manually_resolved",
        "winner": winner,
        "reason": reason
    }
    
    # Apply the resolution to the graph
    entity_id = conflict.get("entity_id")
    field = conflict.get("field")
    if entity_id and field and GRAPH.has_node(entity_id):
        if winner == "new":
            GRAPH.nodes[entity_id]["properties"][field] = conflict["new_value"]
        # If winner is "existing", no change needed

    _persist_and_reindex()

    return {"status": "resolved", "conflict": conflict}


# ---------------------------------------------------------------------------
# Edit & extend endpoints (human-in-the-loop)
# ---------------------------------------------------------------------------

class EditRequest(BaseModel):
    field: str = Field(..., description="Property name to update")
    value: object = Field(..., description="New value for the property")
    actor: str = Field("anonymous", description="Identifier of the human making the edit")
    reason: Optional[str] = Field(None, description="Optional human-readable rationale")


class NoteRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Free-text note to attach to the entity")
    author: str = Field("anonymous", description="Author identifier (email or username)")
    tags: Optional[list[str]] = Field(None, description="Optional tags for categorisation")


@app.patch("/vfs/{section}/{entity_id}", tags=["Edit"],
           summary="Edit a property on an entity (human override)")
def edit_entity_property(section: str, entity_id: str, edit: EditRequest):
    """
    Apply a human edit to a single property on an entity.

    The previous value (with its provenance) is preserved in the conflict log
    so the change is fully auditable. The new value carries a `human` source
    so retrieval and the VFS can show "edited by <actor>" alongside the fact.

    Example:
        PATCH /vfs/people/emp_0431
        { "field": "department", "value": "Platform", "actor": "marclange", "reason": "Re-org Q1" }
    """
    node_id = _resolve_target_node(section, entity_id)
    node = GRAPH.nodes[node_id]
    props = node.setdefault("properties", {})

    previous_value = props.get(edit.field)

    # Audit trail: record the override as a resolved conflict (auto-resolved
    # by human authority) so the existing review queue UI surfaces it.
    if previous_value != edit.value:
        prev_prov = None
        for p in node.get("provenance", []):
            if p.get("field") == edit.field:
                prev_prov = p
                break
        if prev_prov is None and node.get("provenance"):
            prev_prov = node["provenance"][0]

        GRAPH.graph.setdefault("conflicts", []).append({
            "conflict_type": "human_edit",
            "entity_id": node_id,
            "entity_type": SECTION_TO_TYPE.get(section, ""),
            "field": edit.field,
            "existing_value": previous_value,
            "new_value": edit.value,
            "existing_provenance": prev_prov,
            "new_provenance": {
                "source_system": "Human",
                "file": "vfs_edit",
                "record_id": edit.actor,
                "field": edit.field,
                "confidence": 1.0,
            },
            "detected_at": datetime.utcnow().isoformat(),
            "resolution": {
                "status": "manually_resolved",
                "winner": "new",
                "reason": edit.reason or f"Human override by {edit.actor}",
            },
        })

    # Apply the new value + append fact-level provenance so future page loads
    # render "[Human/vfs_edit | actor]" next to the property.
    props[edit.field] = edit.value
    node.setdefault("provenance", []).append(make_provenance(
        source_system="Human",
        file="vfs_edit",
        record_id=edit.actor,
        field=edit.field,
        confidence=1.0,
    ))

    _persist_and_reindex()

    return {
        "status": "ok",
        "node_id": node_id,
        "field": edit.field,
        "previous_value": previous_value,
        "new_value": edit.value,
        "actor": edit.actor,
    }


@app.post("/vfs/{section}/{entity_id}/notes", tags=["Edit"],
          summary="Attach a human note to an entity (extend the company memory)")
def add_note(section: str, entity_id: str, note: NoteRequest):
    """
    Extend the company memory with a human-authored note.

    Notes are first-class graph entities (`Note`) connected to the target
    entity via an `annotates` edge. They appear in the entity's VFS page,
    are indexed by the retriever, and carry their own provenance so they
    survive re-ingestion of source data.
    """
    target_node_id = _resolve_target_node(section, entity_id)

    note_key = uuid.uuid4().hex[:12]
    note_node_id = make_node_id("Note", note_key)
    created_at = datetime.utcnow().isoformat()

    properties = {
        "content": note.content,
        "author": note.author,
        "created_at": created_at,
        "target": target_node_id,
    }
    if note.tags:
        properties["tags"] = note.tags

    provenance = make_provenance(
        source_system="Human",
        file="vfs_note",
        record_id=f"{note.author}:{note_key}",
        confidence=1.0,
        timestamp=created_at,
    )
    add_node(GRAPH, note_node_id, "Note", properties, provenance)
    add_edge(GRAPH, note_node_id, target_node_id, "annotates", provenance=provenance)

    _persist_and_reindex()

    return {
        "status": "ok",
        "note_id": note_node_id,
        "target": target_node_id,
        "author": note.author,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Search endpoint (basic)
# ---------------------------------------------------------------------------

@app.get("/search", tags=["Search"],
         summary="Search entities by name")
def search_entities(q: str, limit: int = 20):
    """
    Simple text search across entity names/titles.
    
    Example: GET /search?q=raj+patel
    """
    q_lower = q.lower()
    results = []
    
    for node_id, data in GRAPH.nodes(data=True):
        props = data.get("properties", {})
        
        # Search across common name fields
        searchable = " ".join(str(v) for v in [
            props.get("name", ""),
            props.get("business_name", ""),
            props.get("subject", ""),
            props.get("issue", ""),
        ]).lower()
        
        if q_lower in searchable:
            results.append({
                "id": node_id,
                "type": data.get("node_type", ""),
                "name": props.get("name") or props.get("business_name") or props.get("subject", ""),
                "properties": {k: v for k, v in props.items() if k in ("name", "business_name", "department", "email", "customer_id", "priority")}
            })
            
            if len(results) >= limit:
                break
    
    return {"query": q, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Hybrid retrieval endpoint
# ---------------------------------------------------------------------------

@app.get("/retrieve", tags=["Retrieval"],
         summary="Hybrid retrieval over graph structure and vectors")
def retrieve(
    q: str,
    mode: str = "auto",
    top_k: int = 5,
    node_type: str = None,
    expand_hops: int = 1,
    related_limit: int = 6,
):
    """
    Retrieve graph-grounded context for a natural-language query.

    Modes:
    - graph: direct + neighborhood-aware graph retrieval
    - vector: sparse TF-IDF similarity over node documents
    - hybrid: weighted combination of both

    This endpoint is the recommended retrieval layer for the current Qontext
    stack because it keeps the NetworkX graph as the source of truth while
    still supporting richer search behavior than exact substring matching.
    """
    if RETRIEVER is None:
        raise HTTPException(status_code=503, detail="Retriever not initialised")

    try:
        return RETRIEVER.search(
            query=q,
            mode=mode,
            top_k=top_k,
            node_type=node_type,
            expand_hops=expand_hops,
            related_limit=related_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/retrieval/status", tags=["Retrieval"],
         summary="Show retrieval backend status")
def retrieval_status():
    """Show which retrieval backends are available in this server instance."""
    return {
        "local": {
            "available": RETRIEVER is not None,
            "documents": len(RETRIEVER.documents) if RETRIEVER is not None else 0,
            "unique_terms": len(RETRIEVER.idf) if RETRIEVER is not None else 0,
        },
    }


# ---------------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------------

if os.path.isdir(os.path.join(FRONTEND_DIST_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST_DIR, "assets")), name="frontend-assets")


@app.get("/", include_in_schema=False)
def frontend_index():
    """Serve the built demo UI when available."""
    if os.path.exists(FRONTEND_INDEX_PATH):
        return FileResponse(FRONTEND_INDEX_PATH)
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Frontend build not found. Build the demo UI under frontend/dist first."
        },
    )


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa_fallback(full_path: str):
    """
    Serve the SPA shell for non-API routes so in-app browser refreshes work.
    API and asset routes are handled by the explicit routes mounted above.
    """
    if not os.path.exists(FRONTEND_INDEX_PATH):
        raise HTTPException(
            status_code=404,
            detail="Frontend build not found. Build the demo UI under frontend/dist first.",
        )

    api_prefixes = (
        "docs",
        "openapi.json",
        "redoc",
        "graph",
        "vfs",
        "conflicts",
        "search",
        "retrieve",
        "retrieval",
        "assets",
    )
    if full_path.startswith(api_prefixes):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(FRONTEND_INDEX_PATH)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def start_server(graph_path: str, host: str = "0.0.0.0", port: int = 8000):
    """Load the graph and start the API server."""
    global GRAPH, GRAPH_PATH, RETRIEVER

    print(f"Loading graph from {graph_path}...")
    GRAPH = load_graph(graph_path)
    GRAPH_PATH = os.path.abspath(graph_path)
    RETRIEVER = LocalHybridRetriever(GRAPH)
    stats = get_stats(GRAPH)
    print(f"Graph loaded: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print(f"Retriever index: {len(RETRIEVER.documents)} documents, {len(RETRIEVER.idf)} unique terms")
    print(f"Starting server at http://{host}:{port}")
    print(f"API docs at http://{host}:{port}/docs")
    
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the Qontext API server")
    parser.add_argument("--graph", required=True, help="Path to graph.json")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()
    
    start_server(args.graph, args.host, args.port)
