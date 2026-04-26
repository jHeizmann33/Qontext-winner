"""
run_qontext_api.py - Start the current Qontext FastAPI server with local deps.

This runner keeps the repo self-contained by preferring the project's local
`.local-py` folder for Python dependencies.
"""

from __future__ import annotations

import os
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL_DEPS = os.path.join(ROOT, ".local-py")
API_DIR = os.path.join(ROOT, "api")

if os.path.isdir(LOCAL_DEPS):
    sys.path.insert(0, LOCAL_DEPS)
sys.path.insert(0, API_DIR)

import server  # noqa: E402


if __name__ == "__main__":
    graph_path = os.path.join(ROOT, "bm_graph.resolved.json")
    server.start_server(graph_path=graph_path, host="127.0.0.1", port=8000)
