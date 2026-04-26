"""
conftest.py — shared pytest fixtures.

Adds the `ingestion/` directory to sys.path so test modules can import
resolver components directly (`from risk import ...`, `from resolver import ...`).
"""

import os
import sys

# Make `ingestion/` importable for all tests.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ingestion"))
