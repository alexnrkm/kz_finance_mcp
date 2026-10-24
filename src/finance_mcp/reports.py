"""Deterministic spending reports; no financial advice or model calls."""

import sqlite3
from collections import defaultdict
from dataclasses import asdict
from datetime import date

from finance_mcp.queries import ELIGIBLE, LEDGER, Filters
from finance_mcp.storage import Record, Store, rows


def spending(store: Store, filters: Filters) -> Record:
    """Aggregate the full selection rather than a page of search results."""
    where, values = filters.sql()
    with store.connect() as connection:
        connection.execute("BEGIN")
        items = rows(
            connection,
            LEDGER + f"SELECT * FROM ledger WHERE {where} AND {ELIGIBLE}",
            values,
        )
        excluded = rows(
            connection,
            LEDGER + f"SELECT COUNT(*) AS total FROM ledger "
            f"WHERE {where} AND NOT ({ELIGIBLE})",
            values,
        )[0]["total"]
        categories = {
            item["id"]: item["name"]
            for item in rows(connection, "SELECT * FROM categories")
        }
        context = _context(connection, filters, excluded)
    return _report(items, categories) | context


def _context(connection: sqlite3.Connection, filters: Filters, excluded: int) -> Record:
    coverage = rows(
        connection,
        "SELECT st.*,a.bank FROM statements st "
        "JOIN accounts a ON a.id=st.account_id ORDER BY st.account_id,st.start",
    )
    return {
        "filters": asdict(filters),
        "currency": "KZT",
        "unit": "tiyn",
        "excluded_transactions": excluded,
        "coverage": _coverage(coverage, filters),
        "coverage_note": (
            "Only imported accounts and periods are known; "
            "completeness is not guaranteed."
        ),
    }


def expense(item: Record) -> int:
    """Net consumption; cash and unconfirmed refunds remain separate."""
    if item["internal_transfer"] or item["kind"] == "cash":
        return 0
    if item["amount_tiyn"] < 0:
        return -int(item["amount_tiyn"])
    if item["linked_refund"]:
        return -int(item["amount_tiyn"])
    return 0


def _report(items: list[Record], categories: dict[int, str]) -> Record:
    grouped: dict[int, int] = defaultdict(int)
    merchants: dict[str, int] = defaultdict(int)
    for item in items:
        amount = expense(item)
        if amount:
            grouped[item["effective_category_id"]] += amount
            merchants[item["merchant"]] += amount
    return _cash_flow(items) | {
        "transaction_count": len(items),
        "net_spending_tiyn": sum(grouped.values()),
        "uncategorized_net_tiyn": grouped.get(1, 0),
        "categories": [
            {"category_id": key, "name": categories[key], "net_tiyn": value}
            for key, value in sorted(grouped.items(), key=lambda pair: -pair[1])
        ],
        "merchants": [
            {"merchant": key, "net_tiyn": value}
            for key, value in sorted(merchants.items(), key=lambda pair: -pair[1])
        ],
    }


def _cash_flow(items: list[Record]) -> Record:
    return {
        "income_tiyn": sum(
            item["amount_tiyn"]
            for item in items
            if item["amount_tiyn"] > 0
            and item["kind"] != "refund"
            and not item["internal_transfer"]
        ),
        "cash_withdrawals_tiyn": -sum(
            item["amount_tiyn"] for item in items if item["kind"] == "cash"
        ),
        "fees_tiyn": -sum(
            item["amount_tiyn"] for item in items if item["kind"] == "fee"
        ),
        "unlinked_refunds_tiyn": sum(
            item["amount_tiyn"]
            for item in items
            if item["kind"] == "refund" and not item["linked_refund"]
        ),
    }


def _coverage(statements: list[Record], filters: Filters) -> list[Record]:
    return [
        item
        for item in statements
        if (filters.account_id is None or item["account_id"] == filters.account_id)
        and (filters.bank is None or item["bank"] == filters.bank)
        and (filters.start is None or item["end"] >= filters.start.isoformat())
        and (filters.end is None or item["start"] <= filters.end.isoformat())
    ]


def compare(
    store: Store,
    previous_start: date,
    previous_end: date,
    current_start: date,
    current_end: date,
    account_id: int | None = None,
) -> Record:
    """Return exact contributions, including groups absent from the other period."""
    previous = spending(store, Filters(previous_start, previous_end, account_id))
    current = spending(store, Filters(current_start, current_end, account_id))
    return {
        "previous": previous,
        "current": current,
        "delta_tiyn": current["net_spending_tiyn"] - previous["net_spending_tiyn"],
        "category_changes": _deltas(
            previous["categories"], current["categories"], "category_id"
        ),
        "merchant_changes": _deltas(
            previous["merchants"], current["merchants"], "merchant"
        ),
    }


def _deltas(before: list[Record], after: list[Record], key: str) -> list[Record]:
    previous = {item[key]: item for item in before}
    current = {item[key]: item for item in after}
    result = []
    for group in previous.keys() | current.keys():
        old = previous.get(group, {}).get("net_tiyn", 0)
        new = current.get(group, {}).get("net_tiyn", 0)
        result.append(
            {
                key: group,
                "previous_tiyn": old,
                "current_tiyn": new,
                "delta_tiyn": new - old,
            }
        )
    return sorted(result, key=lambda item: (-abs(item["delta_tiyn"]), str(item[key])))
