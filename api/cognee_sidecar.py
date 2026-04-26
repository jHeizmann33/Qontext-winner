"""
cognee_sidecar.py - Optional Cognee recall sidecar for Qontext.

The sidecar never replaces the canonical Qontext graph. It is only used as an
additional retrieval source when Cognee is installed and configured.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Any, Optional


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CogneeSidecar:
    def __init__(self) -> None:
        self.enabled = _env_flag("QONTEXT_ENABLE_COGNEE", default=False)
        self.service_url = os.getenv("COGNEE_SERVICE_URL") or os.getenv("QONTEXT_COGNEE_URL")
        self.api_key = os.getenv("COGNEE_API_KEY") or os.getenv("QONTEXT_COGNEE_API_KEY")
        self.default_dataset = os.getenv("QONTEXT_COGNEE_DATASET")
        self._package_available = importlib.util.find_spec("cognee") is not None
        self._connected = False

    @property
    def available(self) -> bool:
        return self.enabled and self._package_available

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "package_available": self._package_available,
            "configured": bool(self.service_url or self.default_dataset),
            "connected": self._connected,
            "service_url": self.service_url,
            "default_dataset": self.default_dataset,
        }

    def recall(
        self,
        query: str,
        top_k: int = 5,
        dataset: Optional[str] = None,
        only_context: bool = True,
    ) -> dict[str, Any]:
        """
        Run Cognee recall if possible.

        Returns a structured object even when unavailable so callers can expose
        sidecar status without throwing errors.
        """
        if not self.enabled:
            return {"available": False, "reason": "disabled"}
        if not self._package_available:
            return {"available": False, "reason": "package_not_installed"}

        try:
            return asyncio.run(
                self._recall_async(
                    query=query,
                    top_k=top_k,
                    dataset=dataset,
                    only_context=only_context,
                )
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._recall_async(
                        query=query,
                        top_k=top_k,
                        dataset=dataset,
                        only_context=only_context,
                    )
                )
            finally:
                loop.close()
        except Exception as exc:
            return {
                "available": True,
                "ok": False,
                "reason": "runtime_error",
                "error": str(exc),
            }

    async def _recall_async(
        self,
        query: str,
        top_k: int,
        dataset: Optional[str],
        only_context: bool,
    ) -> dict[str, Any]:
        import cognee

        await self._connect_if_needed(cognee)

        datasets = [dataset or self.default_dataset] if (dataset or self.default_dataset) else None
        result = await cognee.recall(
            query_text=query,
            top_k=top_k,
            datasets=datasets,
            only_context=only_context,
        )
        return {
            "available": True,
            "ok": True,
            "dataset": datasets[0] if datasets else None,
            "raw": result,
            "context": self._coerce_context(result),
        }

    async def _connect_if_needed(self, cognee_module) -> None:
        if self._connected:
            return
        if self.service_url or self.api_key:
            await cognee_module.serve(url=self.service_url, api_key=self.api_key)
        self._connected = True

    def _coerce_context(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value[:10]:
                parts.append(self._coerce_context(item))
            return "\n".join(part for part in parts if part)
        if isinstance(value, dict):
            preferred_keys = ("answer", "context", "text", "content", "value")
            parts = []
            for key in preferred_keys:
                if key in value and value[key]:
                    parts.append(f"{key}: {self._coerce_context(value[key])}")
            if not parts:
                parts = [f"{key}: {self._coerce_context(val)}" for key, val in list(value.items())[:8]]
            return "\n".join(parts)
        return str(value)
