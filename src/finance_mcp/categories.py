"""Agent-managed categories and deterministic exact-merchant rules."""

import hashlib
import json
import sqlite3

from finance_mcp.history import Journal
from finance_mcp.identity import normalize_merchant
from finance_mcp.models import UNCATEGORIZED_ID
from finance_mcp.storage import Record, Store, row, rows

MAX_ASSIGNMENT_BATCH = 1000


def manage_category(
    store: Store, action: str, name: str = "", category_id: int = 0
) -> Record:
    """List, create, or rename categories. The system category is immutable."""
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if action == "list":
            return {
                "categories": rows(connection, "SELECT * FROM categories ORDER BY id")
            }
        if action not in {"create", "rename"} or not name.strip():
            raise ValueError("Use list, create, or rename with a nonempty name")
        journal = Journal(connection)
        try:
            if action == "create":
                category_id = journal.create("categories", {"name": name.strip()})
            elif category_id == UNCATEGORIZED_ID:
                raise ValueError("The system category cannot be renamed")
            else:
                journal.update("categories", category_id, {"name": name.strip()})
        except sqlite3.IntegrityError as error:
            raise ValueError("Category name already exists") from error
        return {
            "category_id": category_id,
            "change_id": journal.finish(f"category:{action}"),
        }


def preview_token(snapshot: object) -> str:
    """Bind an explicit confirmation to the current affected rows and operation."""
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def assign(
    store: Store,
    transaction_ids: list[int],
    category_id: int,
    token: str | None = None,
) -> Record:
    """Preview a batch; applying requires the exact current preview token."""
    ids = sorted(set(transaction_ids))
    if not ids or len(ids) > MAX_ASSIGNMENT_BATCH:
        raise ValueError(f"Select between 1 and {MAX_ASSIGNMENT_BATCH} transactions")
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        category = row(
            connection, "SELECT * FROM categories WHERE id=?", (category_id,)
        )
        selected = [
            row(connection, "SELECT * FROM transactions WHERE id=?", (key,))
            for key in ids
        ]
        expected = preview_token({"category": category, "transactions": selected})
        result: Record = {
            "transaction_ids": ids,
            "count": len(ids),
            "preview_token": expected,
            "signed_amount_tiyn": sum(item["amount_tiyn"] for item in selected),
        }
        if token is None:
            return result
        if token != expected:
            raise ValueError("Preview is stale or invalid; request a new preview")
        journal = Journal(connection)
        for key in ids:
            journal.update(
                "transactions",
                key,
                {"category_id": category_id, "assignment": "manual", "rule_id": None},
            )
        result["change_id"] = journal.finish("category:assign")
        return result


def create_rule(
    store: Store,
    merchant: str,
    category_id: int,
    account_id: int | None = None,
    direction: str | None = None,
) -> Record:
    """Save an exact-merchant rule; application to existing rows is separate."""
    normalized = normalize_merchant(merchant)
    if not normalized or direction not in {None, "debit", "credit"}:
        raise ValueError("Rule requires a merchant and optional debit/credit direction")
    with store.connect() as connection:
        row(connection, "SELECT id FROM categories WHERE id=?", (category_id,))
        if account_id is not None:
            row(connection, "SELECT id FROM accounts WHERE id=?", (account_id,))
        journal = Journal(connection)
        rule_id = journal.create(
            "rules",
            {
                "merchant": normalized,
                "category_id": category_id,
                "account_id": account_id,
                "direction": direction,
            },
        )
        return {"rule_id": rule_id, "change_id": journal.finish("rule:create")}


def matching_rules(connection: sqlite3.Connection, item: Record) -> list[Record]:
    """Resolve all exact matches; priority is not inferred from rule ordering."""
    direction = "debit" if item["amount_tiyn"] < 0 else "credit"
    return rows(
        connection,
        """SELECT * FROM rules WHERE active=1 AND merchant=?
        AND (account_id IS NULL OR account_id=?) AND (direction IS NULL OR direction=?)
        ORDER BY id""",
        (item["merchant"], item["account_id"], direction),
    )


def apply_to_import(connection: sqlite3.Connection, transaction_id: int) -> None:
    """Apply current rules to a newly imported transaction with an audit entry."""
    journal = Journal(connection)
    item = row(connection, "SELECT * FROM transactions WHERE id=?", (transaction_id,))
    _classify(connection, journal, item)
    journal.finish("rule:import")


def _classify(connection: sqlite3.Connection, journal: Journal, item: Record) -> None:
    if item["assignment"] == "manual":
        return
    matches = matching_rules(connection, item)
    categories = {rule["category_id"] for rule in matches}
    category_id = next(iter(categories)) if len(categories) == 1 else UNCATEGORIZED_ID
    rule_id = matches[0]["id"] if len(categories) == 1 else None
    journal.update(
        "transactions",
        item["id"],
        {
            "category_id": category_id,
            "rule_id": rule_id,
            "assignment": "rule" if rule_id else "none",
        },
    )
    _conflict(connection, journal, item["id"], matches, len(categories) > 1)


def _conflict(
    connection: sqlite3.Connection,
    journal: Journal,
    transaction_id: int,
    matches: list[Record],
    has_conflict: bool,
) -> None:
    existing = rows(
        connection,
        """SELECT * FROM review_items
        WHERE kind='rule_conflict' AND transaction_id=?""",
        (transaction_id,),
    )
    values = {
        "details": json.dumps({"rule_ids": [rule["id"] for rule in matches]}),
        "resolved": int(not has_conflict),
    }
    if existing:
        journal.update("review_items", existing[0]["id"], values)
    elif has_conflict:
        journal.create(
            "review_items",
            {"kind": "rule_conflict", "transaction_id": transaction_id, **values},
        )


def apply_rules(store: Store, token: str | None = None) -> Record:
    """Preview or apply all active rules, preserving manual assignments."""
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        items = rows(
            connection,
            "SELECT * FROM transactions WHERE assignment!='manual' ORDER BY id",
        )
        rules = rows(connection, "SELECT * FROM rules ORDER BY id")
        expected = preview_token({"rules": rules, "items": items})
        result: Record = {
            "count": len(items),
            "preview_token": expected,
            "signed_amount_tiyn": sum(item["amount_tiyn"] for item in items),
            "transaction_ids": [item["id"] for item in items],
        }
        if token is None:
            return result
        if token != expected:
            raise ValueError("Preview is stale or invalid; request a new preview")
        journal = Journal(connection)
        for item in items:
            _classify(connection, journal, item)
        result["change_id"] = journal.finish("rule:apply")
        return result


def disable_rule(store: Store, rule_id: int) -> Record:
    """Disable future matching. Reapplying to existing rows requires a preview."""
    with store.connect() as connection:
        journal = Journal(connection)
        journal.update("rules", rule_id, {"active": 0})
        return {"rule_id": rule_id, "change_id": journal.finish("rule:disable")}
