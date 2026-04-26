"""
vfs_generator.py — Virtual file system generator.

Takes a NetworkX graph and generates markdown pages for entities,
stitching together data from all connected nodes with provenance annotations.

This module is used by:
    - server.py (dynamic generation via API)
    - Can also be used standalone to dump static .md files

Usage:
    from vfs_generator import generate_employee_page, generate_customer_page, ...
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Provenance formatting
# ---------------------------------------------------------------------------

def _prov_tag(provenance: list[dict], field: Optional[str] = None) -> str:
    """
    Format a provenance annotation for inline display.
    Example: [source: HR employees.json → emp_0431 | confidence: 1.0]
    """
    if not provenance:
        return ""
    
    # Find the most relevant provenance entry
    prov = None
    if field:
        for p in provenance:
            if p.get("field") == field:
                prov = p
                break
    if not prov:
        prov = provenance[0]
    
    source = prov.get("source_system", "unknown")
    file = prov.get("file", "")
    record_id = prov.get("record_id", "")
    confidence = prov.get("confidence", "")
    
    parts = []
    if source and file:
        parts.append(f"{source}/{file}")
    elif source:
        parts.append(source)
    if record_id:
        parts.append(f"→ {record_id}")
    if confidence:
        parts.append(f"confidence: {confidence}")
    
    return f" `[{' | '.join(parts)}]`" if parts else ""


def _prop(node_data: dict, key: str, label: Optional[str] = None, show_provenance: bool = True) -> Optional[str]:
    """
    Format a single property line with optional provenance.
    Returns None if the property doesn't exist.
    """
    props = node_data.get("properties", {})
    value = props.get(key)
    if not value:
        return None
    
    display_label = label or key.replace("_", " ").title()
    prov = _prov_tag(node_data.get("provenance", []), field=key) if show_provenance else ""
    return f"- **{display_label}:** {value}{prov}"


# ---------------------------------------------------------------------------
# Helper: get connected nodes by relationship type
# ---------------------------------------------------------------------------

def _get_related(graph, node_id: str, rel_type: str, direction: str = "outgoing") -> list[dict]:
    """
    Get nodes connected by a specific relationship type.
    
    Args:
        direction: "outgoing" (this node → related), "incoming" (related → this node), or "both"
    """
    results = []
    
    if direction in ("outgoing", "both"):
        for _, target, key, data in graph.out_edges(node_id, data=True, keys=True):
            if data.get("rel_type") == rel_type:
                target_data = graph.nodes.get(target, {})
                results.append({
                    "node_id": target,
                    "node_type": target_data.get("node_type", ""),
                    "properties": target_data.get("properties", {}),
                    "provenance": target_data.get("provenance", []),
                    "edge_data": data
                })
    
    if direction in ("incoming", "both"):
        for source, _, key, data in graph.in_edges(node_id, data=True, keys=True):
            if data.get("rel_type") == rel_type:
                source_data = graph.nodes.get(source, {})
                results.append({
                    "node_id": source,
                    "node_type": source_data.get("node_type", ""),
                    "properties": source_data.get("properties", {}),
                    "provenance": source_data.get("provenance", []),
                    "edge_data": data
                })
    
    return results


# ---------------------------------------------------------------------------
# Employee page
# ---------------------------------------------------------------------------

def generate_employee_page(graph, emp_id: str) -> Optional[str]:
    """
    Generate a rich markdown page for an employee, stitching data from:
    - HR (name, department, salary, level, performance, leaves)
    - Resume/CV (skills, experience)
    - Emails (sent/received counts, recent subjects)
    - Conversations (chat partner counts)
    - IT Tickets (raised/assigned)
    - Client relationships
    """
    from graph_utils import make_node_id
    
    node_id = make_node_id("Employee", emp_id)
    if not graph.has_node(node_id):
        return None
    
    node = graph.nodes[node_id]
    props = node.get("properties", {})
    prov = node.get("provenance", [])
    
    lines = []
    
    # --- Header ---
    name = props.get("name", emp_id)
    lines.append(f"# {name} ({emp_id})")
    lines.append("")
    
    # --- Basic information ---
    lines.append("## Basic information")
    
    basic_fields = [
        ("department", "Department"),
        ("level", "Level"),
        ("email", "Email"),
        ("date_of_joining", "Date of joining"),
        ("date_of_leaving", "Date of leaving"),
        ("salary", "Salary"),
        ("age", "Age"),
        ("marital_status", "Marital status"),
        ("performance_rating", "Performance rating"),
    ]
    
    for key, label in basic_fields:
        line = _prop(node, key, label)
        if line:
            lines.append(line)
    
    lines.append("")
    
    # --- Skills & experience ---
    if props.get("skills") or props.get("experience_summary"):
        lines.append("## Skills & experience")
        if props.get("skills"):
            lines.append(f"**Skills:** {props['skills']}")
            lines.append("")
        if props.get("experience_summary"):
            lines.append(f"**Experience:** {props['experience_summary']}")
            lines.append("")
        if props.get("resume_text"):
            # Show first 500 chars of resume
            resume = props["resume_text"]
            if len(resume) > 500:
                resume = resume[:500] + "..."
            lines.append(f"**Resume excerpt:** {resume}")
            lines.append("")
    
    # --- Leave balance ---
    if props.get("total_casual_leaves"):
        lines.append("## Leave balance")
        lines.append(f"| Type | Total | Remaining |")
        lines.append(f"|---|---|---|")
        lines.append(f"| Casual | {props.get('total_casual_leaves', '-')} | {props.get('remaining_casual_leaves', '-')} |")
        lines.append(f"| Sick | {props.get('total_sick_leaves', '-')} | {props.get('remaining_sick_leaves', '-')} |")
        lines.append(f"| Vacation | {props.get('total_vacation_leaves', '-')} | {props.get('remaining_vacation_leaves', '-')} |")
        lines.append(f"| **Total taken** | {props.get('total_leaves_taken', '-')} | |")
        lines.append("")
    
    # --- Activity summary ---
    emails_sent = _get_related(graph, node_id, "sent_email")
    emails_received = _get_related(graph, node_id, "received_email")
    conversations = _get_related(graph, node_id, "chatted_in")
    tickets_raised = _get_related(graph, node_id, "raised_ticket")
    tickets_assigned = _get_related(graph, node_id, "assigned_ticket")
    clients = _get_related(graph, node_id, "represents_client")
    
    lines.append("## Activity summary")
    lines.append(f"| Activity | Count |")
    lines.append(f"|---|---|")
    lines.append(f"| Emails sent | {len(emails_sent)} |")
    lines.append(f"| Emails received | {len(emails_received)} |")
    lines.append(f"| Conversations | {len(conversations)} |")
    lines.append(f"| IT tickets raised | {len(tickets_raised)} |")
    lines.append(f"| IT tickets assigned | {len(tickets_assigned)} |")
    lines.append(f"| Clients represented | {len(clients)} |")
    lines.append("")
    
    # --- Client relationships ---
    if clients:
        lines.append("## Client relationships")
        for client in clients:
            cp = client["properties"]
            client_key = client["node_id"].split(":", 1)[-1]
            name = cp.get("business_name", client["node_id"])
            link = _link(name, "clients", client_key)
            industry = cp.get("industry", "")
            poc = cp.get("poc_status", "")
            product = cp.get("current_poc_product", "")
            detail = f" ({industry}" if industry else ""
            if poc:
                detail += f", POC: {poc}"
            if product:
                detail += f", product: {product}"
            detail += ")" if detail else ""
            lines.append(f"- {link}{detail}")
        lines.append("")
    
    # --- Recent emails (last 10) ---
    if emails_sent:
        lines.append("## Recent emails sent")
        # Sort by date if available
        sorted_emails = sorted(emails_sent, 
            key=lambda e: e["properties"].get("date", ""), reverse=True)[:10]
        for email in sorted_emails:
            ep = email["properties"]
            date = ep.get("date", "")[:10]  # Just the date part
            subject = ep.get("subject", "(no subject)")
            recipient = ep.get("recipient_name", ep.get("recipient_email", ""))
            lines.append(f"- [{date}] **{subject}** → {recipient}")
        if len(emails_sent) > 10:
            lines.append(f"- *... and {len(emails_sent) - 10} more*")
        lines.append("")
    
    # --- IT tickets ---
    if tickets_raised or tickets_assigned:
        lines.append("## IT tickets")
        if tickets_raised:
            lines.append("### Raised")
            for ticket in tickets_raised:
                tp = ticket["properties"]
                tid = tp.get("id", ticket["node_id"].split(":")[-1])
                priority = tp.get("priority", "")
                issue = tp.get("issue", "")[:100]
                lines.append(f"- **#{tid}** ({priority}) — {issue}")
            lines.append("")
        if tickets_assigned:
            lines.append("### Assigned to resolve")
            for ticket in tickets_assigned:
                tp = ticket["properties"]
                tid = tp.get("id", ticket["node_id"].split(":")[-1])
                priority = tp.get("priority", "")
                issue = tp.get("issue", "")[:100]
                lines.append(f"- **#{tid}** ({priority}) — {issue}")
            lines.append("")
    
    # --- Notes (human extensions) ---
    lines.extend(render_recent_changes(graph.nodes[node_id]))
    lines.extend(render_notes_section(graph, node_id))

    # --- Provenance ---
    lines.append("## Data sources")
    source_systems = set()
    for p in prov:
        src = p.get("source_system", "unknown")
        file = p.get("file", "")
        source_systems.add(f"{src}/{file}" if file else src)
    for src in sorted(source_systems):
        lines.append(f"- {src}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inter-file link helpers
# ---------------------------------------------------------------------------

def _link(label: str, section: str, key: str) -> str:
    """Render a markdown link into the VFS for an entity reference."""
    safe = (key or "").strip()
    if not safe or not label:
        return label or safe or ""
    return f"[{label}](/{section}/{safe})"


# ---------------------------------------------------------------------------
# Customer page
# ---------------------------------------------------------------------------

def generate_customer_page(graph, customer_id: str) -> Optional[str]:
    """
    Generate a markdown page for a customer, stitching:
    - CRM (name, paths to order docs)
    - Sales (purchase history)
    - Support chats (if ingested)
    - Reviews/sentiment (if ingested)
    """
    from graph_utils import make_node_id
    
    node_id = make_node_id("Customer", customer_id)
    if not graph.has_node(node_id):
        return None
    
    node = graph.nodes[node_id]
    props = node.get("properties", {})
    
    lines = []
    
    # --- Header ---
    name = props.get("name", customer_id)
    lines.append(f"# {name.title()} ({customer_id})")
    lines.append("")
    
    # --- Basic information ---
    lines.append("## Basic information")
    lines.append(f"- **Customer ID:** {customer_id}")
    if props.get("name"):
        lines.append(f"- **Name:** {props['name'].title()}")
    lines.append("")
    
    # --- Order documents ---
    if props.get("invoice_path") or props.get("purchase_order_path") or props.get("shipping_order_path"):
        lines.append("## Order documents")
        if props.get("invoice_path"):
            lines.append(f"- Invoice: `{props['invoice_path']}`")
        if props.get("purchase_order_path"):
            lines.append(f"- Purchase order: `{props['purchase_order_path']}`")
        if props.get("shipping_order_path"):
            lines.append(f"- Shipping order: `{props['shipping_order_path']}`")
        lines.append("")
    
    # --- Purchase history ---
    sales = _get_related(graph, node_id, "purchased")
    if sales:
        lines.append(f"## Purchase history ({len(sales)} orders)")
        lines.append("| Date | Product | Price | Discount |")
        lines.append("|---|---|---|---|")
        
        sorted_sales = sorted(sales,
            key=lambda s: s["properties"].get("date_of_purchase", ""), reverse=True)[:20]
        
        for sale in sorted_sales:
            sp = sale["properties"]
            date = sp.get("date_of_purchase", "")
            price = sp.get("discounted_price", "")
            discount = sp.get("discount_percentage", "")

            # Try to get product name + link
            product_id = sp.get("product_id", "")
            product_edges = _get_related(graph, sale["node_id"], "product_in_sale")
            product_name = product_id
            if product_edges:
                product_id = product_edges[0]["node_id"].split(":", 1)[-1]
                product_name = product_edges[0]["properties"].get("name", product_id)
                if len(product_name) > 60:
                    product_name = product_name[:60] + "..."

            product_cell = _link(product_name, "products", product_id) if product_id else product_name
            lines.append(f"| {date} | {product_cell} | ₹{price} | {discount} |")
        
        if len(sales) > 20:
            lines.append(f"\n*... and {len(sales) - 20} more orders*")
        lines.append("")
    
    # --- Support interactions ---
    support_chats = _get_related(graph, node_id, "support_for_customer", direction="incoming")
    if support_chats:
        lines.append(f"## Support interactions ({len(support_chats)} chats)")
        for chat in support_chats[:10]:
            cp = chat["properties"]
            product = cp.get("product_name", "")
            lines.append(f"- {product}")
        lines.append("")
    
    # --- Reviews ---
    reviews = _get_related(graph, node_id, "reviewed")
    if reviews:
        lines.append(f"## Reviews ({len(reviews)} total)")
        for review in reviews[:5]:
            rp = review["properties"]
            content = rp.get("review_content", "")[:150]
            date = rp.get("review_date", "")
            lines.append(f"- [{date}] {content}")
        lines.append("")
    
    # --- Notes (human extensions) ---
    lines.extend(render_recent_changes(graph.nodes[node_id]))
    lines.extend(render_notes_section(graph, node_id))

    # --- Provenance ---
    prov = node.get("provenance", [])
    lines.append("## Data sources")
    source_systems = set()
    for p in prov:
        src = p.get("source_system", "unknown")
        file = p.get("file", "")
        source_systems.add(f"{src}/{file}" if file else src)
    for src in sorted(source_systems):
        lines.append(f"- {src}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Team/Department page
# ---------------------------------------------------------------------------

def generate_team_page(graph, department_name: str) -> Optional[str]:
    """
    Generate a markdown page for a department/team, showing:
    - Member list with roles and levels
    - Aggregate stats (email volume, ticket counts)
    - Client portfolio
    """
    from graph_utils import make_node_id
    
    node_id = make_node_id("Department", department_name)
    if not graph.has_node(node_id):
        return None
    
    # Get all employees in this department
    members = _get_related(graph, node_id, "works_in", direction="incoming")
    
    lines = []
    
    # --- Header ---
    lines.append(f"# {department_name} department")
    lines.append("")
    lines.append(f"**Team size:** {len(members)} members")
    lines.append("")
    
    # --- Members ---
    if members:
        lines.append("## Members")
        lines.append("| Name | ID | Level | Performance | Salary |")
        lines.append("|---|---|---|---|---|")
        
        sorted_members = sorted(members,
            key=lambda m: m["properties"].get("name", ""))
        
        for member in sorted_members:
            mp = member["properties"]
            name = mp.get("name", "")
            eid = member["node_id"].split(":")[-1]
            name_link = _link(name or eid, "people", eid)
            level = mp.get("level", "")
            perf = mp.get("performance_rating", "")
            salary = mp.get("salary", "")
            lines.append(f"| {name_link} | {eid} | {level} | {perf} | {salary} |")
        lines.append("")
    
    # --- Aggregate activity ---
    total_emails_sent = 0
    total_tickets_raised = 0
    total_clients = 0
    
    for member in members:
        mid = member["node_id"]
        total_emails_sent += len(_get_related(graph, mid, "sent_email"))
        total_tickets_raised += len(_get_related(graph, mid, "raised_ticket"))
        total_clients += len(_get_related(graph, mid, "represents_client"))
    
    lines.append("## Team activity")
    lines.append(f"| Metric | Count |")
    lines.append(f"|---|---|")
    lines.append(f"| Total emails sent | {total_emails_sent} |")
    lines.append(f"| IT tickets raised | {total_tickets_raised} |")
    lines.append(f"| Clients represented | {total_clients} |")
    lines.append("")

    # --- Notes (human extensions) ---
    lines.extend(render_recent_changes(graph.nodes[node_id]))
    lines.extend(render_notes_section(graph, node_id))


    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Policy page
# ---------------------------------------------------------------------------

def generate_policy_page(graph, slug: str) -> Optional[str]:
    """
    Generate a markdown page for a Policy node.

    Surfaces title, category, summary, full content, plus any human-added
    notes (Note nodes attached via `annotates`) and the source filename.
    """
    from graph_utils import make_node_id

    node_id = make_node_id("Policy", slug)
    if not graph.has_node(node_id):
        return None

    node = graph.nodes[node_id]
    props = node.get("properties", {})

    lines = []

    title = props.get("title", slug)
    lines.append(f"# {title}")
    lines.append("")

    category = props.get("category")
    if category:
        lines.append(f"**Category:** {category}")
    if props.get("filename"):
        lines.append(f"**Source file:** `{props['filename']}`")
    lines.append("")

    if props.get("summary"):
        lines.append("## Summary")
        lines.append(props["summary"])
        lines.append("")

    if props.get("content"):
        lines.append("## Full text")
        lines.append(props["content"].strip())
        lines.append("")

    # Human-added notes (extension surface)
    notes = _get_related(graph, node_id, "annotates", direction="incoming")
    if notes:
        lines.append("## Notes")
        for note in sorted(notes,
                           key=lambda n: n["properties"].get("created_at", ""),
                           reverse=True):
            np = note["properties"]
            author = np.get("author", "anonymous")
            ts = np.get("created_at", "")[:19]
            content = np.get("content", "")
            lines.append(f"- **{author}** ({ts}): {content}")
        lines.append("")

    # Provenance
    prov = node.get("provenance", [])
    lines.append("## Data sources")
    seen = set()
    for p in prov:
        src = p.get("source_system", "unknown")
        file = p.get("file", "")
        key = f"{src}/{file}" if file else src
        if key not in seen:
            seen.add(key)
            lines.append(f"- {key}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generic note-aware section renderer (reused by all pages)
# ---------------------------------------------------------------------------

def render_notes_section(graph, node_id: str) -> list[str]:
    """Render any `annotates` Notes attached to a node as markdown lines."""
    notes = _get_related(graph, node_id, "annotates", direction="incoming")
    if not notes:
        return []
    out = ["## Notes"]
    for note in sorted(notes,
                       key=lambda n: n["properties"].get("created_at", ""),
                       reverse=True):
        np = note["properties"]
        author = np.get("author", "anonymous")
        ts = np.get("created_at", "")[:19]
        content = np.get("content", "")
        out.append(f"- **{author}** ({ts}): {content}")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Recent-changes section (change propagation)
# ---------------------------------------------------------------------------

def render_recent_changes(node_data: dict, limit: int = 10) -> list[str]:
    """
    Render the most recent change_log entries on a node so the VFS shows when
    each fact was last updated and by which source. Returns markdown lines or
    [] if the node has no recorded changes.
    """
    log = node_data.get("change_log", [])
    if not log:
        return []
    out = ["## Recent updates"]
    for entry in sorted(log, key=lambda e: e.get("at", ""), reverse=True)[:limit]:
        kind = entry.get("kind", "updated")
        field = entry.get("field", "?")
        at = (entry.get("at") or "")[:19]
        source = entry.get("source_system") or "unknown"
        if kind == "added":
            out.append(f"- **{at}** — `{field}` added from {source}: `{entry.get('new_value')}`")
        else:
            old = entry.get("old_value")
            new = entry.get("new_value")
            out.append(
                f"- **{at}** — `{field}` updated from `{old}` to `{new}` "
                f"(source: {source})"
            )
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Provenance block helper (deduped across pages)
# ---------------------------------------------------------------------------

def _provenance_block(node_data: dict) -> list[str]:
    """Return the standard `## Data sources` markdown block for a node."""
    out = ["## Data sources"]
    seen = set()
    for p in node_data.get("provenance", []):
        src = p.get("source_system", "unknown")
        file = p.get("file", "")
        key = f"{src}/{file}" if file else src
        if key not in seen:
            seen.add(key)
            out.append(f"- {key}")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Email thread page (trajectory: ongoing conversations)
# ---------------------------------------------------------------------------

def generate_thread_page(graph, thread_id: str) -> Optional[str]:
    """
    Render an EmailThread as a trajectory page: subject, participants (linked
    employees), chronological email timeline, status (active/dormant), notes.
    """
    from graph_utils import make_node_id

    node_id = make_node_id("EmailThread", thread_id)
    if not graph.has_node(node_id):
        return None

    node = graph.nodes[node_id]
    props = node.get("properties", {})

    # Pull all emails in this thread via the part_of_thread incoming edges
    emails = _get_related(graph, node_id, "part_of_thread", direction="incoming")
    emails_sorted = sorted(emails, key=lambda e: e["properties"].get("date", ""))

    # Collect unique participants (sender + recipient emp_ids if present)
    participants: dict[str, str] = {}
    for e in emails:
        ep = e["properties"]
        for emp_id_field, name_field in (
            ("sender_emp_id", "sender_name"),
            ("recipient_emp_id", "recipient_name"),
        ):
            eid = ep.get(emp_id_field)
            if eid and eid not in participants:
                participants[eid] = ep.get(name_field, eid)

    lines = []
    subject = props.get("subject", thread_id)
    lines.append(f"# {subject}")
    lines.append("")
    lines.append(f"**Thread ID:** `{thread_id}`")
    lines.append(f"**Emails:** {len(emails)}")
    lines.append(f"**Participants:** {len(participants)}")

    # Status: active if anything within ~6 months of the latest email date,
    # dormant otherwise. We use string comparison since dates are ISO-prefixed.
    if emails_sorted:
        first_date = emails_sorted[0]["properties"].get("date", "")[:10]
        last_date = emails_sorted[-1]["properties"].get("date", "")[:10]
        lines.append(f"**Span:** {first_date} → {last_date}")
    lines.append("")

    if participants:
        lines.append("## Participants")
        for eid, name in participants.items():
            lines.append(f"- {_link(name, 'people', eid)}")
        lines.append("")

    if emails_sorted:
        lines.append("## Timeline")
        for e in emails_sorted:
            ep = e["properties"]
            date = ep.get("date", "")[:16]
            sender_eid = ep.get("sender_emp_id", "")
            sender = ep.get("sender_name", sender_eid or "(unknown)")
            sender_link = _link(sender, "people", sender_eid) if sender_eid else sender
            snippet = (ep.get("body", "") or "")[:180].replace("\n", " ").strip()
            if snippet and len(ep.get("body", "")) > 180:
                snippet += "…"
            lines.append(f"- **{date}** — {sender_link}: {snippet}")
        lines.append("")

    lines.extend(render_recent_changes(graph.nodes[node_id]))
    lines.extend(render_notes_section(graph, node_id))
    lines.extend(_provenance_block(node))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IT ticket page (trajectory: discrete tasks with status)
# ---------------------------------------------------------------------------

def generate_ticket_page(graph, ticket_id: str) -> Optional[str]:
    """
    Render an ITTicket as a markdown page (replaces the previous raw JSON
    response): priority, dates, raised-by + assigned-to (linked), full issue
    + resolution text, notes.
    """
    from graph_utils import make_node_id

    node_id = make_node_id("ITTicket", ticket_id)
    if not graph.has_node(node_id):
        return None

    node = graph.nodes[node_id]
    props = node.get("properties", {})

    lines = []
    lines.append(f"# IT ticket #{ticket_id}")
    lines.append("")

    priority = props.get("priority", "")
    status = "resolved" if (props.get("resolution") or "").strip() else "open"
    lines.append(f"**Status:** {status}")
    if priority:
        lines.append(f"**Priority:** {priority}")
    if props.get("assigned_date"):
        lines.append(f"**Assigned date:** {props['assigned_date']}")
    if props.get("resolved_date"):
        lines.append(f"**Resolved date:** {props['resolved_date']}")
    lines.append("")

    raised_by = props.get("raised_by_emp_id")
    assigned_to = props.get("assigned_to_emp_id")
    if raised_by or assigned_to:
        lines.append("## People")
        if raised_by:
            raiser_node = graph.nodes.get(f"Employee:{raised_by}", {})
            raiser_name = raiser_node.get("properties", {}).get("name", raised_by)
            lines.append(f"- **Raised by:** {_link(raiser_name, 'people', raised_by)}")
        if assigned_to:
            asg_node = graph.nodes.get(f"Employee:{assigned_to}", {})
            asg_name = asg_node.get("properties", {}).get("name", assigned_to)
            lines.append(f"- **Assigned to:** {_link(asg_name, 'people', assigned_to)}")
        lines.append("")

    if props.get("issue"):
        lines.append("## Issue")
        lines.append(props["issue"])
        lines.append("")
    if props.get("resolution"):
        lines.append("## Resolution")
        lines.append(props["resolution"])
        lines.append("")

    lines.extend(render_recent_changes(graph.nodes[node_id]))
    lines.extend(render_notes_section(graph, node_id))
    lines.extend(_provenance_block(node))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Project page (synthetic trajectory: curated cross-cutting initiatives)
# ---------------------------------------------------------------------------

def _project_threads(graph, min_emails: int = 3, min_participants: int = 2) -> list[dict]:
    """
    A "project" is synthesized from email threads that look substantial:
    >= min_emails emails AND >= min_participants distinct emp_ids. This
    surfaces real ongoing initiatives instead of one-off conversations.
    Returns a list sorted by descending email count.
    """
    out = []
    for nid, data in graph.nodes(data=True):
        if data.get("node_type") != "EmailThread":
            continue
        emails = [s for s, _, _, ed in graph.in_edges(nid, data=True, keys=True)
                  if ed.get("rel_type") == "part_of_thread"]
        if len(emails) < min_emails:
            continue
        participants = set()
        latest_date = ""
        for em_id in emails:
            ep = graph.nodes[em_id].get("properties", {})
            for f in ("sender_emp_id", "recipient_emp_id"):
                eid = ep.get(f)
                if eid:
                    participants.add(eid)
            d = ep.get("date", "")
            if d > latest_date:
                latest_date = d
        if len(participants) < min_participants:
            continue
        out.append({
            "node_id": nid,
            "thread_id": nid.split(":", 1)[-1],
            "subject": data.get("properties", {}).get("subject", nid),
            "email_count": len(emails),
            "participant_count": len(participants),
            "latest_date": latest_date,
            "participants": participants,
        })
    out.sort(key=lambda x: (-x["email_count"], x["latest_date"]))
    return out


def generate_project_page(graph, thread_id: str) -> Optional[str]:
    """
    Render a Project page (built on top of an EmailThread that meets the
    project threshold). Adds project-specific framing on top of the thread:
    contributing departments, related IT tickets raised by participants.
    """
    from graph_utils import make_node_id

    node_id = make_node_id("EmailThread", thread_id)
    if not graph.has_node(node_id):
        return None

    node = graph.nodes[node_id]
    props = node.get("properties", {})
    subject = props.get("subject", thread_id)

    emails = _get_related(graph, node_id, "part_of_thread", direction="incoming")
    if not emails:
        return None

    participants: dict[str, str] = {}
    departments: dict[str, int] = {}
    for e in emails:
        ep = e["properties"]
        for emp_id_field, name_field in (
            ("sender_emp_id", "sender_name"),
            ("recipient_emp_id", "recipient_name"),
        ):
            eid = ep.get(emp_id_field)
            if not eid:
                continue
            participants.setdefault(eid, ep.get(name_field, eid))
            emp_node = graph.nodes.get(f"Employee:{eid}", {})
            dept = emp_node.get("properties", {}).get("department")
            if dept:
                departments[dept] = departments.get(dept, 0) + 1

    # Related tickets: tickets raised by any participant
    related_tickets = []
    for eid in participants:
        for src, _, _, ed in graph.in_edges(f"Employee:{eid}", data=True, keys=True):
            pass  # Employee has outgoing raised_ticket edges
        for _, tgt, _, ed in graph.out_edges(f"Employee:{eid}", data=True, keys=True):
            if ed.get("rel_type") == "raised_ticket":
                tnode = graph.nodes.get(tgt, {})
                related_tickets.append({
                    "ticket_id": tgt.split(":", 1)[-1],
                    "priority": tnode.get("properties", {}).get("priority", ""),
                    "issue": (tnode.get("properties", {}).get("issue", "") or "")[:120],
                    "raised_by": eid,
                })
    # Dedupe
    seen_t = set()
    related_tickets_unique = []
    for t in related_tickets:
        if t["ticket_id"] in seen_t:
            continue
        seen_t.add(t["ticket_id"])
        related_tickets_unique.append(t)

    emails_sorted = sorted(emails, key=lambda e: e["properties"].get("date", ""))
    first_date = emails_sorted[0]["properties"].get("date", "")[:10]
    last_date = emails_sorted[-1]["properties"].get("date", "")[:10]

    lines = []
    lines.append(f"# {subject}")
    lines.append("")
    lines.append(f"_Synthesized project view derived from email thread `{thread_id}`._")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- **Emails exchanged:** {len(emails)}")
    lines.append(f"- **Participants:** {len(participants)}")
    lines.append(f"- **Departments involved:** {len(departments)}")
    lines.append(f"- **Active span:** {first_date} → {last_date}")
    lines.append(f"- **Related IT tickets (raised by participants):** {len(related_tickets_unique)}")
    lines.append("")
    lines.append(f"Full conversation: [thread {thread_id}](/threads/{thread_id})")
    lines.append("")

    if departments:
        lines.append("## Departments contributing")
        for dept, count in sorted(departments.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {_link(dept, 'teams', dept)} ({count} email touches)")
        lines.append("")

    if participants:
        lines.append("## Participants")
        for eid, name in participants.items():
            lines.append(f"- {_link(name, 'people', eid)}")
        lines.append("")

    if related_tickets_unique:
        lines.append(f"## Related IT tickets ({len(related_tickets_unique)})")
        for t in related_tickets_unique[:25]:
            link = _link(f"#{t['ticket_id']}", "it-tickets", t["ticket_id"])
            lines.append(f"- {link} ({t['priority']}) — {t['issue']}")
        if len(related_tickets_unique) > 25:
            lines.append(f"- *... and {len(related_tickets_unique) - 25} more*")
        lines.append("")

    lines.extend(render_recent_changes(graph.nodes[node_id]))
    lines.extend(render_notes_section(graph, node_id))
    lines.extend(_provenance_block(node))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Directory listings
# ---------------------------------------------------------------------------

def list_directory(graph, path: str) -> dict:
    """
    Return the contents of a virtual directory.
    
    Returns:
        {
            "path": "/people",
            "type": "directory",
            "children": [
                {"name": "emp_0431-raj-patel.md", "type": "file", "path": "/people/emp_0431"},
                ...
            ]
        }
    """
    from graph_utils import get_entities_by_type
    
    path = path.strip("/")
    
    if path == "":
        # Root directory
        return {
            "path": "/",
            "type": "directory",
            "children": [
                {"name": "people", "type": "directory", "path": "/people",
                 "description": "Employee profiles"},
                {"name": "customers", "type": "directory", "path": "/customers",
                 "description": "Customer profiles with order history"},
                {"name": "teams", "type": "directory", "path": "/teams",
                 "description": "Department overviews"},
                {"name": "clients", "type": "directory", "path": "/clients",
                 "description": "B2B client relationships"},
                {"name": "products", "type": "directory", "path": "/products",
                 "description": "Product catalogue"},
                {"name": "it-tickets", "type": "directory", "path": "/it-tickets",
                 "description": "IT service tickets — open and resolved tasks"},
                {"name": "threads", "type": "directory", "path": "/threads",
                 "description": "Email threads — ongoing conversations (trajectory)"},
                {"name": "projects", "type": "directory", "path": "/projects",
                 "description": "Curated cross-cutting initiatives (synthesized)"},
                {"name": "policies", "type": "directory", "path": "/policies",
                 "description": "Company policies and SOPs"},
            ]
        }
    
    elif path == "people":
        employees = get_entities_by_type(graph, "Employee")
        children = []
        for eid in sorted(employees):
            props = graph.nodes[eid].get("properties", {})
            name = props.get("name", "").lower().replace(" ", "-")
            emp_id = eid.split(":")[1]
            children.append({
                "name": f"{emp_id}-{name}.md",
                "type": "file",
                "path": f"/people/{emp_id}",
                "summary": f"{props.get('name', '')} — {props.get('department', '')} — {props.get('level', '')}"
            })
        return {"path": "/people", "type": "directory", "children": children}
    
    elif path == "customers":
        customers = get_entities_by_type(graph, "Customer")
        children = []
        for cid in sorted(customers):
            props = graph.nodes[cid].get("properties", {})
            customer_id = cid.split(":")[1]
            children.append({
                "name": f"{customer_id}.md",
                "type": "file",
                "path": f"/customers/{customer_id}",
                "summary": props.get("name", "").title()
            })
        return {"path": "/customers", "type": "directory", "children": children}
    
    elif path == "teams":
        departments = get_entities_by_type(graph, "Department")
        children = []
        for did in sorted(departments):
            props = graph.nodes[did].get("properties", {})
            dept_name = did.split(":")[1]
            # Count members
            member_count = len(_get_related(graph, did, "works_in", direction="incoming"))
            children.append({
                "name": f"{dept_name.lower().replace(' ', '-')}.md",
                "type": "file",
                "path": f"/teams/{dept_name}",
                "summary": f"{dept_name} — {member_count} members"
            })
        return {"path": "/teams", "type": "directory", "children": children}
    
    elif path == "clients":
        clients = get_entities_by_type(graph, "Client")
        children = []
        for cid in sorted(clients):
            props = graph.nodes[cid].get("properties", {})
            client_id = cid.split(":")[1]
            children.append({
                "name": f"{props.get('business_name', client_id).lower().replace(' ', '-').replace(',', '')}.md",
                "type": "file",
                "path": f"/clients/{client_id}",
                "summary": f"{props.get('business_name', '')} — {props.get('industry', '')} — POC: {props.get('poc_status', '')}"
            })
        return {"path": "/clients", "type": "directory", "children": children}
    
    elif path == "products":
        products = get_entities_by_type(graph, "Product")
        children = []
        for pid in sorted(products):
            props = graph.nodes[pid].get("properties", {})
            product_id = pid.split(":")[1]
            name = props.get("name", product_id)
            if len(name) > 80:
                name = name[:80] + "..."
            children.append({
                "name": f"{product_id}.md",
                "type": "file",
                "path": f"/products/{product_id}",
                "summary": name
            })
        return {"path": "/products", "type": "directory", "children": children}
    
    elif path == "policies":
        policies = get_entities_by_type(graph, "Policy")
        children = []
        for pid in sorted(policies):
            props = graph.nodes[pid].get("properties", {})
            slug = pid.split(":", 1)[-1]
            title = props.get("title", slug)
            category = props.get("category", "")
            summary_bits = [title]
            if category:
                summary_bits.append(category)
            children.append({
                "name": f"{slug}.md",
                "type": "file",
                "path": f"/policies/{slug}",
                "summary": " — ".join(summary_bits),
            })
        return {"path": "/policies", "type": "directory", "children": children}

    elif path == "it-tickets":
        tickets = get_entities_by_type(graph, "ITTicket")
        children = []
        for tid in sorted(tickets):
            props = graph.nodes[tid].get("properties", {})
            ticket_id = tid.split(":")[1]
            issue = props.get("issue", "")[:80]
            status = "resolved" if (props.get("resolution") or "").strip() else "open"
            children.append({
                "name": f"ticket-{ticket_id}.md",
                "type": "file",
                "path": f"/it-tickets/{ticket_id}",
                "summary": f"#{ticket_id} [{status}, {props.get('priority', '')}] — {issue}",
            })
        return {"path": "/it-tickets", "type": "directory", "children": children}

    elif path == "threads":
        # Threads are too numerous to enumerate fully (~4k+); return the top
        # N by email count so the listing remains useful instead of overwhelming.
        thread_summaries = []
        for nid, data in graph.nodes(data=True):
            if data.get("node_type") != "EmailThread":
                continue
            count = sum(1 for _, _, _, ed in graph.in_edges(nid, data=True, keys=True)
                        if ed.get("rel_type") == "part_of_thread")
            thread_summaries.append((count, nid, data))
        thread_summaries.sort(reverse=True)
        children = []
        for count, nid, data in thread_summaries[:200]:
            tid = nid.split(":", 1)[-1]
            subject = data.get("properties", {}).get("subject", tid)
            children.append({
                "name": f"{tid}.md",
                "type": "file",
                "path": f"/threads/{tid}",
                "summary": f"[{count} emails] {subject[:120]}",
            })
        return {
            "path": "/threads",
            "type": "directory",
            "children": children,
            "note": f"Showing top 200 of all threads by email count.",
        }

    elif path == "projects":
        projects = _project_threads(graph)
        children = []
        for p in projects:
            children.append({
                "name": f"{p['thread_id']}.md",
                "type": "file",
                "path": f"/projects/{p['thread_id']}",
                "summary": (
                    f"[{p['email_count']} emails, {p['participant_count']} people, "
                    f"last {p['latest_date'][:10]}] {p['subject'][:100]}"
                ),
            })
        return {
            "path": "/projects",
            "type": "directory",
            "children": children,
            "note": "Projects are synthesized from email threads with >= 3 emails AND >= 2 participants.",
        }

    return {"path": f"/{path}", "type": "directory", "children": []}
