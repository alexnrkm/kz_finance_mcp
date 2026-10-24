"""Reversible, conflict-checked changes to user decisions."""

import json
import sqlite3

from finance_mcp.storage import Record, Store, insert, row, rows

EDITABLE_TABLES = frozenset(
    {"categories", "rules", "transactions", "links", "review_items"}
)


def _table(name: str) -> str:
    if name not in EDITABLE_TABLES:
        raise ValueError("Unsupported history entity")
    return name


class Journal:
    """Record before/after snapshots in the same transaction as each change."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.patches: list[Record] = []

    def create(self, table: str, values: Record) -> int:
        """Create an entity and capture its complete persisted representation."""
        table = _table(table)
        columns = ",".join(values)
        markers = ",".join("?" for _ in values)
        entity_id = insert(
            self.connection,
            f"INSERT INTO {table} ({columns}) VALUES ({markers})",
            tuple(values.values()),
        )
        after = row(self.connection, f"SELECT * FROM {table} WHERE id=?", (entity_id,))
        self.patches.append(
            {"table": table, "id": entity_id, "before": None, "after": after}
        )
        return entity_id

    def update(self, table: str, entity_id: int, values: Record) -> None:
        """Update an existing entity and remember its original state."""
        table = _table(table)
        before = row(self.connection, f"SELECT * FROM {table} WHERE id=?", (entity_id,))
        if not values.keys() <= before.keys() or "id" in values:
            raise ValueError("Unsupported update fields")
        assignments = ",".join(f"{column}=?" for column in values)
        self.connection.execute(
            f"UPDATE {table} SET {assignments} WHERE id=?",
            (*values.values(), entity_id),
        )
        after = row(self.connection, f"SELECT * FROM {table} WHERE id=?", (entity_id,))
        if before != after:
            self.patches.append(
                {"table": table, "id": entity_id, "before": before, "after": after}
            )

    def finish(self, action: str) -> int | None:
        """Persist the journal only when the operation changed something."""
        if not self.patches:
            return None
        return insert(
            self.connection,
            "INSERT INTO changes(action,patches) VALUES (?,?)",
            (action, json.dumps(self.patches)),
        )


def undo(store: Store, change_id: int) -> Record:
    """Undo only if affected rows have not changed since the recorded action."""
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        change = row(connection, "SELECT * FROM changes WHERE id=?", (change_id,))
        if change["undone"] or change["action"].startswith("undo:"):
            raise ValueError("This change cannot be undone")
        patches: list[Record] = json.loads(change["patches"])
        try:
            for patch in reversed(patches):
                _restore(connection, patch)
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "Later changes depend on this entity; undo them first"
            ) from error
        connection.execute("UPDATE changes SET undone=1 WHERE id=?", (change_id,))
        insert(
            connection,
            "INSERT INTO changes(action,patches) VALUES (?,?)",
            (f"undo:{change_id}", "[]"),
        )
        return {"undone_change_id": change_id}


def _restore(connection: sqlite3.Connection, patch: Record) -> None:
    table = _table(patch["table"])
    current = rows(connection, f"SELECT * FROM {table} WHERE id=?", (patch["id"],))
    if current != [patch["after"]]:
        raise ValueError("Affected data changed; undo the later change first")
    before = patch["before"]
    if before is None:
        connection.execute(f"DELETE FROM {table} WHERE id=?", (patch["id"],))
        return
    assignments = ",".join(f"{key}=?" for key in before if key != "id")
    values = [value for key, value in before.items() if key != "id"]
    connection.execute(
        f"UPDATE {table} SET {assignments} WHERE id=?", (*values, patch["id"])
    )
