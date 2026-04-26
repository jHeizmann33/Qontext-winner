"""
ingest_communications.py — Ingest communication sources.

Sources:
    - emails.json (11,928 records) → Email + EmailThread nodes, employee edges
    - conversations.json (2,897 records) → Conversation nodes, employee edges
    - it_tickets.json (163 records) → ITTicket nodes, employee edges

These sources are edge-heavy — they mostly create relationships between
existing Employee nodes, with the communication records as intermediate nodes.

Usage:
    python ingest_communications.py --data-dir ./Dataset --graph ./graph.json --output ./graph.json
"""

import json
import os
import argparse
from graph_utils import (
    create_graph, load_graph, make_node_id, add_node, add_edge,
    make_provenance, save_graph, get_stats
)


# ---------------------------------------------------------------------------
# Email ingestion
# ---------------------------------------------------------------------------

def ingest_emails(graph, data_dir: str) -> None:
    """
    Parse emails.json → Email nodes + EmailThread nodes + employee edges.
    
    Each email record has:
        email_id (UUID), thread_id, date, sender_email, sender_name,
        sender_emp_id, recipient_email, recipient_name, recipient_emp_id,
        subject, body, importance, signature, category
    
    Creates:
        - Email node per record
        - EmailThread node per unique thread_id
        - sent_email edge: Employee → Email
        - received_email edge: Employee → Email
        - part_of_thread edge: Email → EmailThread
    
    NOTE: There's a known data quirk — some emails have mismatched sender_name
    vs signature (e.g. Ravi Kumar sends but signature says Aji Joseph). This
    is likely an intentional conflict for testing. We store both and let the
    conflict detection layer handle it.
    """
    filepath = os.path.join(data_dir, "Enterprise_Mail_System", "emails.json")
    
    with open(filepath, "r") as f:
        emails = json.load(f)
    
    threads_seen = set()
    sender_edges = 0
    recipient_edges = 0
    thread_edges = 0
    signature_mismatches = 0
    
    for record in emails:
        email_id = record.get("email_id", "").strip()
        if not email_id:
            continue
        
        # --- Create Email node ---
        node_id = make_node_id("Email", email_id)
        
        properties = {
            "subject": record.get("subject", "").strip(),
            "date": record.get("date", "").strip(),
            "sender_name": record.get("sender_name", "").strip(),
            "sender_email": record.get("sender_email", "").strip(),
            "sender_emp_id": record.get("sender_emp_id", "").strip(),
            "recipient_name": record.get("recipient_name", "").strip(),
            "recipient_email": record.get("recipient_email", "").strip(),
            "recipient_emp_id": record.get("recipient_emp_id", "").strip(),
            "body": record.get("body", "").strip(),
            "importance": record.get("importance", "").strip(),
            "category": record.get("category", "").strip(),
            "thread_id": record.get("thread_id", "").strip(),
        }
        
        # Check for signature mismatch — a known conflict pattern
        signature = record.get("signature", "")
        if signature:
            properties["signature"] = signature.strip()
            sender_name = record.get("sender_name", "").strip().lower()
            # Simple check: if sender name doesn't appear in signature
            if sender_name and sender_name not in signature.lower():
                properties["_signature_mismatch"] = True
                signature_mismatches += 1
        
        properties = {k: v for k, v in properties.items() if v != "" and v is not None}
        
        provenance = make_provenance(
            source_system="Enterprise_Mail_System",
            file="emails.json",
            record_id=email_id,
            confidence=1.0,
            timestamp=record.get("date", "")
        )
        
        add_node(graph, node_id, "Email", properties, provenance)
        
        # --- Create EmailThread node (if new) ---
        thread_id = record.get("thread_id", "").strip()
        if thread_id:
            thread_node_id = make_node_id("EmailThread", thread_id)
            
            if thread_id not in threads_seen:
                add_node(graph, thread_node_id, "EmailThread", {
                    "thread_id": thread_id,
                    "subject": record.get("subject", "").strip(),  # Use first email's subject
                }, make_provenance(
                    source_system="Enterprise_Mail_System",
                    file="emails.json",
                    record_id=f"thread:{thread_id}",
                    confidence=1.0
                ))
                threads_seen.add(thread_id)
            
            # Email → EmailThread
            add_edge(graph, node_id, thread_node_id, "part_of_thread",
                provenance=make_provenance(
                    source_system="Enterprise_Mail_System",
                    file="emails.json",
                    record_id=email_id,
                    field="thread_id",
                    confidence=1.0
                ))
            thread_edges += 1
        
        # --- Create employee edges ---
        sender_emp_id = record.get("sender_emp_id", "").strip()
        if sender_emp_id:
            sender_node_id = make_node_id("Employee", sender_emp_id)
            if graph.has_node(sender_node_id):
                add_edge(graph, sender_node_id, node_id, "sent_email",
                    provenance=make_provenance(
                        source_system="Enterprise_Mail_System",
                        file="emails.json",
                        record_id=email_id,
                        field="sender_emp_id",
                        confidence=1.0
                    ))
                sender_edges += 1
        
        recipient_emp_id = record.get("recipient_emp_id", "").strip()
        if recipient_emp_id:
            recipient_node_id = make_node_id("Employee", recipient_emp_id)
            if graph.has_node(recipient_node_id):
                add_edge(graph, recipient_node_id, node_id, "received_email",
                    provenance=make_provenance(
                        source_system="Enterprise_Mail_System",
                        file="emails.json",
                        record_id=email_id,
                        field="recipient_emp_id",
                        confidence=1.0
                    ))
                recipient_edges += 1
    
    print(f"  Ingested {len(emails)} emails, {len(threads_seen)} threads")
    print(f"    Edges: {sender_edges} sent_email, {recipient_edges} received_email, {thread_edges} part_of_thread")
    if signature_mismatches:
        print(f"    ⚠ {signature_mismatches} signature mismatches detected (potential conflicts)")


# ---------------------------------------------------------------------------
# Conversation ingestion
# ---------------------------------------------------------------------------

def ingest_conversations(graph, data_dir: str) -> None:
    """
    Parse conversations.json → Conversation nodes + employee edges.
    
    Each conversation record has:
        conversation_id (UUID), sender_emp_id, recipient_emp_id, date, text
    
    Creates:
        - Conversation node per record
        - chatted_in edges: Employee → Conversation (for both sender and recipient)
    """
    filepath = os.path.join(data_dir, "Collaboration_tools", "conversations.json")
    
    with open(filepath, "r") as f:
        conversations = json.load(f)
    
    edges_created = 0
    
    for record in conversations:
        conv_id = record.get("conversation_id", "").strip()
        if not conv_id:
            continue
        
        node_id = make_node_id("Conversation", conv_id)
        
        # Extract a summary from the text (first 200 chars)
        text = record.get("text", "").strip()
        summary = text[:200] + "..." if len(text) > 200 else text
        
        properties = {
            "date": record.get("date", "").strip(),
            "sender_emp_id": record.get("sender_emp_id", "").strip(),
            "recipient_emp_id": record.get("recipient_emp_id", "").strip(),
            "summary": summary,
            "full_text": text,
        }
        properties = {k: v for k, v in properties.items() if v}
        
        provenance = make_provenance(
            source_system="Collaboration_tools",
            file="conversations.json",
            record_id=conv_id,
            confidence=1.0,
            timestamp=record.get("date", "")
        )
        
        add_node(graph, node_id, "Conversation", properties, provenance)
        
        # Sender → Conversation
        sender_emp_id = record.get("sender_emp_id", "").strip()
        if sender_emp_id:
            sender_node_id = make_node_id("Employee", sender_emp_id)
            if graph.has_node(sender_node_id):
                add_edge(graph, sender_node_id, node_id, "chatted_in",
                    properties={"role": "sender"},
                    provenance=make_provenance(
                        source_system="Collaboration_tools",
                        file="conversations.json",
                        record_id=conv_id,
                        field="sender_emp_id",
                        confidence=1.0
                    ))
                edges_created += 1
        
        # Recipient → Conversation
        recipient_emp_id = record.get("recipient_emp_id", "").strip()
        if recipient_emp_id:
            recipient_node_id = make_node_id("Employee", recipient_emp_id)
            if graph.has_node(recipient_node_id):
                add_edge(graph, recipient_node_id, node_id, "chatted_in",
                    properties={"role": "recipient"},
                    provenance=make_provenance(
                        source_system="Collaboration_tools",
                        file="conversations.json",
                        record_id=conv_id,
                        field="recipient_emp_id",
                        confidence=1.0
                    ))
                edges_created += 1
    
    print(f"  Ingested {len(conversations)} conversations, created {edges_created} chatted_in edges")


# ---------------------------------------------------------------------------
# IT Ticket ingestion
# ---------------------------------------------------------------------------

def ingest_it_tickets(graph, data_dir: str) -> None:
    """
    Parse it_tickets.json → ITTicket nodes + employee edges.
    
    Each ticket record has:
        id, priority, raised_by_emp_id, assigned_date, emp_id (assigned to),
        Issue, Resolution
    
    Creates:
        - ITTicket node per record
        - raised_ticket edge: Employee → ITTicket
        - assigned_ticket edge: Employee → ITTicket
    """
    filepath = os.path.join(data_dir, "IT_Service_Management", "it_tickets.json")
    
    with open(filepath, "r") as f:
        tickets = json.load(f)
    
    raised_edges = 0
    assigned_edges = 0
    
    for record in tickets:
        ticket_id = str(record.get("id", "")).strip()
        if not ticket_id:
            continue
        
        node_id = make_node_id("ITTicket", ticket_id)
        
        properties = {
            "priority": record.get("priority", "").strip(),
            "assigned_date": record.get("assigned_date", "").strip(),
            "issue": record.get("Issue", "").strip(),
            "resolution": record.get("Resolution", "").strip(),
            "raised_by_emp_id": record.get("raised_by_emp_id", "").strip(),
            "assigned_to_emp_id": record.get("emp_id", "").strip(),
        }
        properties = {k: v for k, v in properties.items() if v}
        
        provenance = make_provenance(
            source_system="IT_Service_Management",
            file="it_tickets.json",
            record_id=ticket_id,
            confidence=1.0,
            timestamp=record.get("assigned_date", "")
        )
        
        add_node(graph, node_id, "ITTicket", properties, provenance)
        
        # Employee → ITTicket (raised_ticket)
        raised_by = record.get("raised_by_emp_id", "").strip()
        if raised_by:
            raiser_node_id = make_node_id("Employee", raised_by)
            if graph.has_node(raiser_node_id):
                add_edge(graph, raiser_node_id, node_id, "raised_ticket",
                    provenance=make_provenance(
                        source_system="IT_Service_Management",
                        file="it_tickets.json",
                        record_id=ticket_id,
                        field="raised_by_emp_id",
                        confidence=1.0
                    ))
                raised_edges += 1
        
        # Employee → ITTicket (assigned_ticket)
        assigned_to = record.get("emp_id", "").strip()
        if assigned_to:
            assignee_node_id = make_node_id("Employee", assigned_to)
            if graph.has_node(assignee_node_id):
                add_edge(graph, assignee_node_id, node_id, "assigned_ticket",
                    provenance=make_provenance(
                        source_system="IT_Service_Management",
                        file="it_tickets.json",
                        record_id=ticket_id,
                        field="emp_id",
                        confidence=1.0
                    ))
                assigned_edges += 1
    
    print(f"  Ingested {len(tickets)} IT tickets, edges: {raised_edges} raised, {assigned_edges} assigned")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest_communications(graph, data_dir: str) -> None:
    """Run the full communications ingestion pipeline."""
    print("=" * 60)
    print("Ingesting: Communications (Emails + Conversations + IT Tickets)")
    print("=" * 60)
    
    ingest_emails(graph, data_dir)
    ingest_conversations(graph, data_dir)
    ingest_it_tickets(graph, data_dir)
    
    stats = get_stats(graph)
    graph.graph["stats"]["communications"] = stats
    print(f"  Graph state: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest communications data")
    parser.add_argument("--data-dir", required=True, help="Path to Dataset folder")
    parser.add_argument("--graph", default=None, help="Existing graph file to load")
    parser.add_argument("--output", default="graph.json", help="Output graph file")
    args = parser.parse_args()
    
    if args.graph and os.path.exists(args.graph):
        graph = load_graph(args.graph)
        print(f"Loaded existing graph: {graph.number_of_nodes()} nodes")
    else:
        graph = create_graph()
    
    ingest_communications(graph, args.data_dir)
    save_graph(graph, args.output)
