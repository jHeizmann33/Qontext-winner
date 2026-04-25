"""
ingest_bm.py — Ingest Business and Management data.

Sources:
    - clients.json (400 records) → Client nodes + represents_client edges to Employee
    - vendors.json (? records) → Vendor nodes

Usage:
    python ingest_bm.py --data-dir ./Dataset --graph ./graph.json --output ./graph.json
"""

import json
import os
import argparse
from graph_utils import (
    create_graph, load_graph, make_node_id, add_node, add_edge,
    make_provenance, save_graph, get_stats
)

SOURCE_SYSTEM = "Business_and_Management"


# ---------------------------------------------------------------------------
# Client ingestion
# ---------------------------------------------------------------------------

def ingest_clients(graph, data_dir: str) -> None:
    """
    Parse clients.json → Client nodes + represents_client edges.
    
    Each client record has:
        client_id (UUID), business_name, industry, business_type,
        contact_person_id, contact_person_name, contact_email, phone_number,
        registered_address, tax_id, monthly_revenue, onboarding_date,
        current_POC_product, POC_status, engagement_description,
        business_representative_employee (emp_id!)
    
    The business_representative_employee field links to Employee nodes — this
    is a key cross-source relationship.
    """
    filepath = os.path.join(data_dir, "Business_and_Management", "clients.json")
    
    with open(filepath, "r") as f:
        clients = json.load(f)
    
    edges_created = 0
    
    for record in clients:
        client_id = record.get("client_id", "").strip()
        if not client_id:
            continue
        
        node_id = make_node_id("Client", client_id)
        
        # Cast all values to str before .strip() — some fields (e.g. phone_number)
        # are stored as integers in the source JSON
        def s(val):
            return str(val).strip() if val is not None else ""
        
        properties = {
            "business_name": s(record.get("business_name")),
            "industry": s(record.get("industry")),
            "business_type": s(record.get("business_type")),
            "contact_person_name": s(record.get("contact_person_name")),
            "contact_email": s(record.get("contact_email")),
            "phone_number": s(record.get("phone_number")),
            "registered_address": s(record.get("registered_address")),
            "tax_id": s(record.get("tax_id")),
            "monthly_revenue": s(record.get("monthly_revenue")),
            "onboarding_date": s(record.get("onboarding_date")),
            "current_poc_product": s(record.get("current_POC_product")),
            "poc_status": s(record.get("POC_status")),
            "engagement_description": s(record.get("engagement_description")),
            "representative_emp_id": s(record.get("business_representative_employee")),
        }
        properties = {k: v for k, v in properties.items() if v}
        
        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file="clients.json",
            record_id=client_id,
            confidence=1.0
        )
        
        add_node(graph, node_id, "Client", properties, provenance)
        
        # Create represents_client edge: Employee → Client
        rep_emp_id = record.get("business_representative_employee", "").strip()
        if rep_emp_id:
            emp_node_id = make_node_id("Employee", rep_emp_id)
            if graph.has_node(emp_node_id):
                add_edge(graph, emp_node_id, node_id, "represents_client",
                    provenance=make_provenance(
                        source_system=SOURCE_SYSTEM,
                        file="clients.json",
                        record_id=client_id,
                        field="business_representative_employee",
                        confidence=1.0
                    ))
                edges_created += 1
    
    print(f"  Ingested {len(clients)} clients, created {edges_created} represents_client edges")


# ---------------------------------------------------------------------------
# Vendor ingestion
# ---------------------------------------------------------------------------

def ingest_vendors(graph, data_dir: str) -> None:
    """
    Parse vendors.json → Vendor nodes.
    
    We haven't seen the record shape yet, so this is defensive — it reads
    whatever fields exist and maps them generically.
    """
    filepath = os.path.join(data_dir, "Business_and_Management", "vendors.json")
    
    with open(filepath, "r") as f:
        vendors = json.load(f)
    
    for i, record in enumerate(vendors):
        # Try common ID field names
        vendor_id = (
            record.get("vendor_id") or
            record.get("id") or
            record.get("vendor_name", f"vendor_{i}")
        )
        if isinstance(vendor_id, str):
            vendor_id = vendor_id.strip()
        else:
            vendor_id = str(vendor_id)
        
        node_id = make_node_id("Vendor", vendor_id)
        
        # Map all fields as properties (defensive — we don't know the exact shape)
        properties = {}
        for key, value in record.items():
            if value is not None and str(value).strip():
                clean_key = key.lower().replace(" ", "_")
                properties[clean_key] = str(value).strip() if isinstance(value, str) else value
        
        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file="vendors.json",
            record_id=str(vendor_id),
            confidence=1.0
        )
        
        add_node(graph, node_id, "Vendor", properties, provenance)
    
    print(f"  Ingested {len(vendors)} vendors")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest_bm(graph, data_dir: str) -> None:
    """Run the full Business & Management ingestion pipeline."""
    print("=" * 60)
    print("Ingesting: Business and Management")
    print("=" * 60)
    
    ingest_clients(graph, data_dir)
    ingest_vendors(graph, data_dir)
    
    stats = get_stats(graph)
    graph.graph["stats"]["bm"] = stats
    print(f"  Graph state: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest B&M data into knowledge graph")
    parser.add_argument("--data-dir", required=True, help="Path to Dataset folder")
    parser.add_argument("--graph", default=None, help="Existing graph file to load")
    parser.add_argument("--output", default="graph.json", help="Output graph file")
    args = parser.parse_args()
    
    if args.graph and os.path.exists(args.graph):
        graph = load_graph(args.graph)
        print(f"Loaded existing graph: {graph.number_of_nodes()} nodes")
    else:
        graph = create_graph()
    
    ingest_bm(graph, args.data_dir)
    save_graph(graph, args.output)
