"""
ingest_hr.py — Ingest Human Resource Management data.

Sources:
    - employees.json (1,260 records) → Employee nodes + Department nodes
    - resume_information.csv (1,260 records) → enriches Employee nodes with CV data

This runs FIRST because emp_id is the universal join key across almost every
other source in the dataset. Every subsequent ingester depends on Employee
nodes already existing in the graph.

Usage:
    python ingest_hr.py --data-dir ./Dataset --output ./graph.json
"""

import json
import csv
import os
import argparse
from graph_utils import (
    create_graph, make_node_id, add_node, add_edge,
    make_provenance, save_graph, get_stats
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_SYSTEM = "Human_Resource_Management"
EMPLOYEES_FILE = "employees.json"
RESUME_FILE = "resume_information.csv"


# ---------------------------------------------------------------------------
# Employee ingestion
# ---------------------------------------------------------------------------

def ingest_employees(graph, data_dir: str) -> None:
    """
    Parse employees.json → Employee nodes + Department nodes + works_in edges.
    
    Each employee record has:
        index, category (=department), description, Experience, Name, skills,
        emp_id, Level, email, DOJ, DOL, Salary, leave fields, Age,
        Performance Rating, Marital Status, ...
    """
    filepath = os.path.join(data_dir, "Human_Resource_Management", "Employees", EMPLOYEES_FILE)
    
    with open(filepath, "r") as f:
        employees = json.load(f)
    
    departments_seen = set()
    
    for record in employees:
        emp_id = record.get("emp_id")
        if not emp_id:
            continue
        
        # --- Create Employee node ---
        node_id = make_node_id("Employee", emp_id)
        
        properties = {
            "name": record.get("Name", "").strip(),
            "email": record.get("email", "").strip(),
            "department": record.get("category", "").strip(),
            "level": record.get("Level", "").strip(),
            "description": record.get("description", "").strip(),
            "experience_summary": record.get("Experience", "").strip(),
            "skills": record.get("skills", "").strip(),
            "date_of_joining": record.get("DOJ", "").strip(),
            "date_of_leaving": record.get("DOL", "").strip(),
            "salary": record.get("Salary", "").strip(),
            "age": record.get("Age", "").strip(),
            "performance_rating": record.get("Performance Rating", "").strip(),
            "marital_status": record.get("Marital Status", "").strip() if "Marital Status" in record else "",
            "total_casual_leaves": record.get("Total Casual Leaves", ""),
            "remaining_casual_leaves": record.get("Remaining Casual Leaves", ""),
            "total_sick_leaves": record.get("Total Sick Leaves", ""),
            "remaining_sick_leaves": record.get("Remaining Sick Leaves", ""),
            "total_vacation_leaves": record.get("Total Vacation Leaves", ""),
            "remaining_vacation_leaves": record.get("Remaining Vacation Leaves", ""),
            "total_leaves_taken": record.get("Total Leaves Taken", ""),
        }
        
        # Remove empty string values to keep the graph clean
        properties = {k: v for k, v in properties.items() if v != ""}
        
        provenance = make_provenance(
            source_system=SOURCE_SYSTEM,
            file=EMPLOYEES_FILE,
            record_id=emp_id,
            confidence=1.0  # HR is authoritative for employee data
        )
        
        add_node(graph, node_id, "Employee", properties, provenance)
        
        # --- Create Department node (if new) + works_in edge ---
        department = record.get("category", "").strip()
        if department:
            dept_node_id = make_node_id("Department", department)
            
            if department not in departments_seen:
                add_node(graph, dept_node_id, "Department", {
                    "name": department
                }, make_provenance(
                    source_system=SOURCE_SYSTEM,
                    file=EMPLOYEES_FILE,
                    record_id=f"derived:department:{department}",
                    confidence=1.0
                ))
                departments_seen.add(department)
            
            add_edge(graph, node_id, dept_node_id, "works_in",
                provenance=make_provenance(
                    source_system=SOURCE_SYSTEM,
                    file=EMPLOYEES_FILE,
                    record_id=emp_id,
                    field="category",
                    confidence=1.0
                ))
    
    print(f"  Ingested {len(employees)} employees across {len(departments_seen)} departments")


# ---------------------------------------------------------------------------
# Resume/CV ingestion
# ---------------------------------------------------------------------------

def ingest_resumes(graph, data_dir: str) -> None:
    """
    Parse resume_information.csv → enrich existing Employee nodes with CV data.
    
    This adds resume text to employees that already exist in the graph.
    If an employee from the CSV doesn't exist in the graph, it's logged
    as a potential data quality issue.
    """
    filepath = os.path.join(data_dir, "Human_Resource_Management", "Resume", RESUME_FILE)
    
    matched = 0
    unmatched = 0
    
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # Try to match by emp_id first, then by name
            emp_id = row.get("emp_id", "").strip()
            
            if not emp_id:
                # If no emp_id in CSV, we might need to match by name
                # For now, skip — this is a known limitation
                unmatched += 1
                continue
            
            node_id = make_node_id("Employee", emp_id)
            
            if graph.has_node(node_id):
                # Enrich existing node with resume data
                existing = graph.nodes[node_id]
                props = existing.get("properties", {})
                
                # Add resume content as a property
                resume_text = row.get("Resume", row.get("resume", "")).strip()
                if resume_text:
                    props["resume_text"] = resume_text
                
                # Add any other CV fields that aren't already in the node
                for key, value in row.items():
                    if key not in ("emp_id", "Resume", "resume") and value and value.strip():
                        cv_key = f"cv_{key.lower().replace(' ', '_')}"
                        if cv_key not in props:
                            props[cv_key] = value.strip()
                
                existing["properties"] = props
                existing.setdefault("provenance", []).append(
                    make_provenance(
                        source_system=SOURCE_SYSTEM,
                        file=RESUME_FILE,
                        record_id=emp_id,
                        confidence=1.0
                    )
                )
                matched += 1
            else:
                unmatched += 1
    
    print(f"  Resumes: {matched} matched to employees, {unmatched} unmatched")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest_hr(graph, data_dir: str) -> None:
    """Run the full HR ingestion pipeline."""
    print("=" * 60)
    print("Ingesting: Human Resource Management")
    print("=" * 60)
    
    ingest_employees(graph, data_dir)
    ingest_resumes(graph, data_dir)
    
    stats = get_stats(graph)
    graph.graph["stats"]["hr"] = stats
    print(f"  Graph state: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest HR data into knowledge graph")
    parser.add_argument("--data-dir", required=True, help="Path to Dataset folder")
    parser.add_argument("--output", default="graph.json", help="Output graph file")
    args = parser.parse_args()
    
    graph = create_graph()
    ingest_hr(graph, args.data_dir)
    save_graph(graph, args.output)
