"""Database placeholder for Phase 3.

Phase 1/2 runs without a database. This module exists so the project shape is
ready for SQLite first, then MySQL later.
"""

from pathlib import Path


def default_sqlite_path() -> Path:
    """Return the planned local SQLite path."""

    return Path(__file__).resolve().parents[1] / "data" / "tricore_scanner.sqlite3"

