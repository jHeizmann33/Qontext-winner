"""
cognee_export.py - Export canonical Qontext graph views into Cognee-friendly documents.

This module deliberately exports derived text documents instead of raw graph
mutations so Qontext remains the source of truth.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Any, Optional

try:
    from vfs_generator import (
        generate_customer_page,
        generate_employee_page,
        generate_team_page,
    )
except Exception:
    generate_customer_page = None
    generate_employee_page = None
    generate_team_page = None


def _display_title(node_id: str, node_data: dict) -> str:
    props = node_data.get("properties", {}) or {}
    for key in ("name", "business_name", "subject", "issue", "title", "summary"):
        if props.get(key):
            return str(props[key])
    return node_id


def _node_text(graph, node_id: str, node_data: dict) -> str:
    node_type = node_data.get("node_type", "Unknown")
    node_key = node_id.split(":", 1)[1] if ":" in node_id else node_id

    try:
        if node_type == "Employee" and generate_employee_page:
            rendered = generate_employee_page(graph, node_key)
            if rendered:
                return rendered
        if node_type == "Customer" and generate_customer_page:
            rendered = generate_customer_page(graph, node_key)
            if rendered:
                return rendered
        if node_type == "Department" and generate_team_page:
            rendered = generate_team_page(graph, node_key)
            if rendered:
                return rendered
    except Exception:
        pass

    props = node_data.get("properties", {}) or {}
    lines = [f"# {node_type}: {_display_title(node_id, node_data)}", f"Node ID: {node_id}", ""]
    for key, value in props.items():
        if value in ("", None, [], {}):
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def build_cognee_documents(
    graph,
    node_types: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    documents = []
    allowed_types = {node_type.lower() for node_type in node_types} if node_types else None

    for node_id, node_data in graph.nodes(data=True):
        node_type = node_data.get("node_type", "Unknown")
        if allowed_types and node_type.lower() not in allowed_types:
            continue
        documents.append({
            "node_id": node_id,
            "node_type": node_type,
            "title": _display_title(node_id, node_data),
            "text": _node_text(graph, node_id, node_data),
            "provenance": node_data.get("provenance", [])[:3],
        })
        if limit is not None and len(documents) >= limit:
            break

    return documents


class CogneeExporter:
    def __init__(self) -> None:
        self.enabled = (os.getenv("QONTEXT_ENABLE_COGNEE") or "").strip().lower() in {"1", "true", "yes", "on"}
        self.service_url = os.getenv("COGNEE_SERVICE_URL") or os.getenv("QONTEXT_COGNEE_URL")
        self.api_key = os.getenv("COGNEE_API_KEY") or os.getenv("QONTEXT_COGNEE_API_KEY")
        self.package_available = importlib.util.find_spec("cognee") is not None
        self._connected = False

    def export(
        self,
        graph,
        dataset_name: str,
        node_types: Optional[list[str]] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "disabled"}
        if not self.package_available:
            return {"ok": False, "reason": "package_not_installed"}

        documents = build_cognee_documents(graph, node_types=node_types, limit=limit)
        try:
            return asyncio.run(self._export_async(documents, dataset_name))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._export_async(documents, dataset_name))
            finally:
                loop.close()
        except Exception as exc:
            return {"ok": False, "reason": "runtime_error", "error": str(exc)}

    async def _export_async(self, documents: list[dict[str, Any]], dataset_name: str) -> dict[str, Any]:
        import cognee

        await self._connect_if_needed(cognee)
        exported = 0
        for document in documents:
            await cognee.remember(
                document["text"],
                dataset_name=dataset_name,
            )
            exported += 1
        return {"ok": True, "dataset_name": dataset_name, "exported": exported}

    async def _connect_if_needed(self, cognee_module) -> None:
        if self._connected:
            return
        if self.service_url or self.api_key:
            await cognee_module.serve(url=self.service_url, api_key=self.api_key)
        self._connected = True
