"""Confirmed transaction relationships and conservative automatic transfer matching."""

import sqlite3
from datetime import date

from finance_mcp.history import Journal
from finance_mcp.storage import Record, Store, row, rows

TRANSFER_WINDOW_DAYS = 3


def confirm_pair(store: Store, kind: str, left_id: int, right_id: int) -> Record:
    """Confirm a validated transfer, purchase/refund, or canonical/duplicate pair."""
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        journal = Journal(connection)
        link_id = _pair(connection, journal, kind, left_id, right_id)
        return {"link_id": link_id, "change_id": journal.finish(f"link:{kind}")}


def _pair(
    connection: sqlite3.Connection,
    journal: Journal,
    kind: str,
    left_id: int,
    right_id: int,
) -> int:
    if kind not in {"transfer", "refund", "duplicate"} or left_id == right_id:
        raise ValueError("Choose a supported relationship and two different operations")
    left = row(connection, "SELECT * FROM transactions WHERE id=?", (left_id,))
    right = row(connection, "SELECT * FROM transactions WHERE id=?", (right_id,))
    _validate_pair(connection, kind, left, right)
    link_id = journal.create(
        "links", {"kind": kind, "left_id": left_id, "right_id": right_id}
    )
    if kind == "duplicate":
        reviews = rows(
            connection,
            """SELECT * FROM review_items
            WHERE kind='duplicate' AND transaction_id=? AND resolved=0""",
            (right_id,),
        )
        for review in reviews:
            journal.update("review_items", review["id"], {"resolved": 1})
    return link_id


def _validate_pair(
    connection: sqlite3.Connection, kind: str, left: Record, right: Record
) -> None:
    _available(connection, kind, left, right)
    if kind == "duplicate":
        _validate_duplicate(connection, left, right)
        return
    if left["amount_tiyn"] >= 0 or right["amount_tiyn"] <= 0:
        raise ValueError("Select the debit first and credit second")
    if kind == "transfer":
        days = abs(
            (
                date.fromisoformat(left["posted_on"])
                - date.fromisoformat(right["posted_on"])
            ).days
        )
        if left["kind"] != "transfer" or right["kind"] != "transfer":
            raise ValueError("Both operations must be transfers")
        if left["account_id"] == right["account_id"] or days > TRANSFER_WINDOW_DAYS:
            raise ValueError(
                "Transfers require different owned accounts and close dates"
            )
        if -left["amount_tiyn"] != right["amount_tiyn"]:
            raise ValueError("Transfer amounts must balance; fees must be separate")
    else:
        _validate_refund(connection, left, right)


def _available(
    connection: sqlite3.Connection, kind: str, left: Record, right: Record
) -> None:
    ids = (left["id"], right["id"])
    blocked = rows(
        connection,
        """SELECT * FROM links WHERE active=1 AND
        (right_id IN (?,?) OR (kind!='duplicate' AND left_id IN (?,?)))""",
        (*ids, *ids),
    )
    if kind == "refund":
        blocked = [
            link
            for link in blocked
            if not (
                link["kind"] == "refund"
                and link["left_id"] == left["id"]
                and link["right_id"] != right["id"]
            )
        ]
    if blocked:
        raise ValueError(
            "Operation already participates in an incompatible relationship"
        )


def _validate_duplicate(
    connection: sqlite3.Connection, left: Record, right: Record
) -> None:
    if (
        left["account_id"] != right["account_id"]
        or left["fingerprint"] != right["fingerprint"]
    ):
        raise ValueError("Duplicate records must have the same account and fingerprint")
    if left["bank_id"] and right["bank_id"] and left["bank_id"] != right["bank_id"]:
        raise ValueError("Different bank transaction IDs are distinct operations")
    left_sources = rows(
        connection,
        """SELECT statement_id FROM sources WHERE transaction_id=?
        OR transaction_id IN (SELECT right_id FROM links
        WHERE kind='duplicate' AND active=1 AND left_id=?)""",
        (left["id"], left["id"]),
    )
    right_sources = rows(
        connection,
        "SELECT statement_id FROM sources WHERE transaction_id=?",
        (right["id"],),
    )
    if {item["statement_id"] for item in left_sources} & {
        item["statement_id"] for item in right_sources
    }:
        raise ValueError("Two purchases in the same statement cannot be merged")
    if rows(
        connection, "SELECT id FROM links WHERE active=1 AND left_id=?", (right["id"],)
    ):
        raise ValueError(
            "Duplicate chains are not supported; choose the canonical operation"
        )


def _validate_refund(
    connection: sqlite3.Connection, left: Record, right: Record
) -> None:
    if left["kind"] != "purchase" or right["kind"] != "refund":
        raise ValueError("Link a purchase debit to a refund credit")
    if (
        right["posted_on"] < left["posted_on"]
        or left["account_id"] != right["account_id"]
    ):
        raise ValueError("Refund must follow the purchase on the same account")
    refunded = rows(
        connection,
        """SELECT COALESCE(SUM(t.amount_tiyn),0) AS total FROM links l
        JOIN transactions t ON t.id=l.right_id
        WHERE l.kind='refund' AND l.active=1 AND l.left_id=?""",
        (left["id"],),
    )[0]["total"]
    if refunded + right["amount_tiyn"] > -left["amount_tiyn"]:
        raise ValueError("Linked refunds exceed the purchase amount")


def keep_separate(store: Store, review_id: int) -> Record:
    """Resolve a duplicate candidate as a distinct real transaction."""
    with store.connect() as connection:
        review = row(connection, "SELECT * FROM review_items WHERE id=?", (review_id,))
        if review["kind"] != "duplicate" or review["resolved"]:
            raise ValueError("Choose an unresolved duplicate review")
        journal = Journal(connection)
        journal.update("review_items", review_id, {"resolved": 1})
        return {
            "review_id": review_id,
            "change_id": journal.finish("duplicate:keep_separate"),
        }


def reconcile_transfers(connection: sqlite3.Connection) -> None:
    """Auto-confirm only unique, same-day pairs with reciprocal account references."""
    candidates = rows(
        connection,
        """SELECT debit.id AS left_id, credit.id AS right_id
        FROM transactions debit JOIN transactions credit
          ON debit.amount_tiyn=-credit.amount_tiyn AND debit.posted_on=credit.posted_on
        JOIN accounts a ON a.id=debit.account_id
        JOIN accounts b ON b.id=credit.account_id
        WHERE debit.kind='transfer' AND credit.kind='transfer' AND debit.amount_tiyn<0
          AND a.id!=b.id AND debit.counterparty_account=b.reference
          AND credit.counterparty_account=a.reference""",
    )
    journal = Journal(connection)
    for pair in candidates:
        if _unique_pair(candidates, pair):
            _auto_pair(connection, journal, pair)
    journal.finish("transfer:auto")


def _unique_pair(candidates: list[Record], pair: Record) -> bool:
    return bool(
        sum(item["left_id"] == pair["left_id"] for item in candidates) == 1
        and sum(item["right_id"] == pair["right_id"] for item in candidates) == 1
    )


def _auto_pair(connection: sqlite3.Connection, journal: Journal, pair: Record) -> None:
    occupied = rows(
        connection,
        """SELECT id FROM links WHERE active=1 AND
        (left_id IN (?,?) OR right_id IN (?,?))""",
        (pair["left_id"], pair["right_id"], pair["left_id"], pair["right_id"]),
    )
    pending = rows(
        connection,
        """SELECT id FROM review_items WHERE resolved=0
        AND kind='duplicate' AND transaction_id IN (?,?)""",
        (pair["left_id"], pair["right_id"]),
    )
    valid = rows(
        connection,
        """SELECT DISTINCT s.transaction_id FROM sources s
        JOIN statements st ON st.id=s.statement_id
        WHERE s.transaction_id IN (?,?) AND st.reconciliation!='failed'""",
        (pair["left_id"], pair["right_id"]),
    )
    if not occupied and not pending and len(valid) == 2:
        _pair(connection, journal, "transfer", pair["left_id"], pair["right_id"])
