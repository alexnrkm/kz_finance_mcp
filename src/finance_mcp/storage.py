"""Short-lived SQLite connections shared by service and MCP calls."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

Record = dict[str, Any]
SCHEMA_VERSION = 1


def rows(
    connection: sqlite3.Connection, sql: str, values: Sequence[object] = ()
) -> list[Record]:
    """Read dictionaries using parameterized SQL."""
    return [dict(row) for row in connection.execute(sql, values).fetchall()]


def row(
    connection: sqlite3.Connection, sql: str, values: Sequence[object] = ()
) -> Record:
    """Read one required record."""
    result = rows(connection, sql, values)
    if not result:
        raise ValueError("Record not found")
    return result[0]


def insert(connection: sqlite3.Connection, sql: str, values: Sequence[object]) -> int:
    """Insert a row and return its generated identifier."""
    cursor = connection.execute(sql, values)
    if cursor.lastrowid is None:
        raise RuntimeError("Insert did not produce an identifier")
    return cursor.lastrowid


class Store:
    """Own a database path; connections never cross worker threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION}:
                raise ValueError(
                    "Unsupported database version; use a compatible release"
                )
            if version == 0:
                schema = files("finance_mcp").joinpath("schema.sql").read_text("utf-8")
                connection.executescript(schema)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Commit a successful operation, roll it back on failure, and close."""
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
