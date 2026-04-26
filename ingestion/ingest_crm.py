"""
ingest_crm.py — Ingest Customer Relation Management data.

Sources:
    - customers.json (90 records) → Customer nodes
    - products.json (1,351 records) → Product nodes
    - sales.json (13,510 records) → Sale nodes + edges to Customer + Product

This runs SECOND, after HR. It establishes the customer and product entity
backbone that support chats, reviews, and order PDFs will later link to.

Usage:
    python ingest_crm.py --data-dir ./Dataset --graph ./graph.json --output ./graph.json
"""

import json
import os
import re
import argparse
from graph_utils import (
    create_graph, load_graph, make_node_id, add_node, add_edge,
    make_provenance, save_graph, get_stats
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_SYSTEM = "Customer_Relation_Management"
CUSTOMERS_FILE = "customers.json"
PRODUCTS_FILE = "products.json"
SALES_FILE = "sales.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_price(price_str: str) -> str:
    """
    Clean price strings like '₹399' or '₹1,099' → '399' or '1099'.
    Keeps the original string if parsing fails.
    """
    if not price_str:
        return ""
    # Remove currency symbol and commas
    cleaned = re.sub(r"[₹,\s]", "", price_str)
    return cleaned


# ---------------------------------------------------------------------------
# Customer ingestion
# ---------------------------------------------------------------------------

def ingest_customers(graph, data_dir: str) -> None:
    """
    Parse customers.json → Customer nodes.
    
    Each customer record has:
        customer_id (short code like "arout"),
        customer_name,
        invoice_paths, purchase_order_paths, shipping_order_paths
    
    The paths reference PDF files in Customer_orders/ — we store them
    as properties so the PDF ingester can link them later.
    """
    filepath = os.path.join(data_dir, "Customer_Relation_Management", CUSTOMERS_FILE)
    
    with open(filepath, "r") as f:
        customers = json.load(f)
    
    for record in customers:
        customer_id = record.get("customer_id", "").strip()
        if not customer_id:
            continue
        
        node_id = make_node_id("Customer", customer_id)
        
        properties = {
            "name": record.get("customer_name", "").strip(),
            "invoice_path": record.get("invoice_paths", "").strip(),
            "purchase_order_path": record.get("purchase_order_paths", "").strip(),
            "shipping_order_path": record.get("shipping_order_paths", "").strip(),
        }
        properties = {k: v for k, v in properties.items() if v}
        
        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file=CUSTOMERS_FILE,
            record_id=customer_id,
            confidence=1.0  # CRM is authoritative for customer data
        )
        
        add_node(graph, node_id, "Customer", properties, provenance)
    
    print(f"  Ingested {len(customers)} customers")


# ---------------------------------------------------------------------------
# Product ingestion
# ---------------------------------------------------------------------------

def ingest_products(graph, data_dir: str) -> None:
    """
    Parse products.json → Product nodes.
    
    Each product record has:
        product_id, product_name, category, discounted_price, actual_price,
        rating, about_product
    """
    filepath = os.path.join(data_dir, "Customer_Relation_Management", PRODUCTS_FILE)
    
    with open(filepath, "r") as f:
        products = json.load(f)
    
    for record in products:
        product_id = record.get("product_id", "").strip()
        if not product_id:
            continue
        
        node_id = make_node_id("Product", product_id)
        
        # Parse the category hierarchy (e.g. "Electronics|WearableTechnology|SmartWatches")
        category_raw = record.get("category", "")
        categories = [c.strip() for c in category_raw.split("|")] if category_raw else []
        
        properties = {
            "name": record.get("product_name", "").strip(),
            "category": category_raw,
            "category_hierarchy": categories,
            "discounted_price": clean_price(record.get("discounted_price", "")),
            "actual_price": clean_price(record.get("actual_price", "")),
            "rating": record.get("rating", "").strip() if isinstance(record.get("rating"), str) else str(record.get("rating", "")),
            "description": record.get("about_product", "").strip(),
        }
        properties = {k: v for k, v in properties.items() if v and v != "[]"}
        
        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file=PRODUCTS_FILE,
            record_id=product_id,
            confidence=1.0
        )
        
        add_node(graph, node_id, "Product", properties, provenance)
    
    print(f"  Ingested {len(products)} products")


# ---------------------------------------------------------------------------
# Sales ingestion
# ---------------------------------------------------------------------------

def ingest_sales(graph, data_dir: str) -> None:
    """
    Parse sales.json → Sale nodes + edges to Customer and Product.
    
    Each sale record has:
        product_id, discounted_price, actual_price, discount_percentage,
        customer_id, Date_of_Purchase, sales_record_id
    
    Creates:
        - Sale node for each record
        - purchased edge: Customer → Sale
        - product_in_sale edge: Sale → Product
    """
    filepath = os.path.join(data_dir, "Customer_Relation_Management", SALES_FILE)
    
    with open(filepath, "r") as f:
        sales = json.load(f)
    
    edges_created = 0
    
    for record in sales:
        sale_id = str(record.get("sales_record_id", ""))
        customer_id = record.get("customer_id", "").strip()
        product_id = record.get("product_id", "").strip()
        
        if not sale_id:
            continue
        
        # --- Create Sale node ---
        sale_node_id = make_node_id("Sale", sale_id)
        
        properties = {
            "customer_id": customer_id,
            "product_id": product_id,
            "discounted_price": clean_price(record.get("discounted_price", "")),
            "actual_price": clean_price(record.get("actual_price", "")),
            "discount_percentage": record.get("discount_percentage", "").strip() if isinstance(record.get("discount_percentage"), str) else str(record.get("discount_percentage", "")),
            "date_of_purchase": record.get("Date_of_Purchase", "").strip(),
        }
        properties = {k: v for k, v in properties.items() if v}
        
        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file=SALES_FILE,
            record_id=f"sale:{sale_id}",
            confidence=1.0,
            timestamp=record.get("Date_of_Purchase", "")
        )
        
        add_node(graph, sale_node_id, "Sale", properties, provenance)
        
        # --- Create edges ---
        
        # Customer → Sale (purchased)
        if customer_id:
            customer_node_id = make_node_id("Customer", customer_id)
            if graph.has_node(customer_node_id):
                add_edge(graph, customer_node_id, sale_node_id, "purchased",
                    provenance=make_provenance(
                        source_system=SOURCE_SYSTEM,
                        file=SALES_FILE,
                        record_id=f"sale:{sale_id}",
                        field="customer_id",
                        confidence=1.0
                    ))
                edges_created += 1
        
        # Sale → Product (product_in_sale)
        if product_id:
            product_node_id = make_node_id("Product", product_id)
            if graph.has_node(product_node_id):
                add_edge(graph, sale_node_id, product_node_id, "product_in_sale",
                    provenance=make_provenance(
                        source_system=SOURCE_SYSTEM,
                        file=SALES_FILE,
                        record_id=f"sale:{sale_id}",
                        field="product_id",
                        confidence=1.0
                    ))
                edges_created += 1
    
    print(f"  Ingested {len(sales)} sales, created {edges_created} edges")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest_crm(graph, data_dir: str) -> None:
    """Run the full CRM ingestion pipeline."""
    print("=" * 60)
    print("Ingesting: Customer Relation Management")
    print("=" * 60)
    
    ingest_customers(graph, data_dir)
    ingest_products(graph, data_dir)
    ingest_sales(graph, data_dir)
    
    stats = get_stats(graph)
    graph.graph["stats"]["crm"] = stats
    print(f"  Graph state: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest CRM data into knowledge graph")
    parser.add_argument("--data-dir", required=True, help="Path to Dataset folder")
    parser.add_argument("--graph", default=None, help="Existing graph file to load (optional)")
    parser.add_argument("--output", default="graph.json", help="Output graph file")
    args = parser.parse_args()
    
    if args.graph and os.path.exists(args.graph):
        graph = load_graph(args.graph)
        print(f"Loaded existing graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    else:
        graph = create_graph()
    
    ingest_crm(graph, args.data_dir)
    save_graph(graph, args.output)
