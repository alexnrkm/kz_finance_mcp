"""Atomic import of normalized statements with conservative duplicate review."""

import json
import re
import sqlite3

from finance_mcp.identity import fingerprint, normalize_merchant
from finance_mcp.models import StatementInput, TransactionInput
from finance_mcp.storage import Record, Store, insert, row, rows

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def import_parsed(
    store: Store,
    statement: StatementInput,
    sha256: str,
    parser_version: str,
) -> Record:
    """Import trusted parser output; never expose normalized input as an MCP tool."""
    if not SHA256_PATTERN.fullmatch(sha256) or not parser_version.strip():
        raise ValueError("Import requires a SHA-256 digest and parser version")
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = rows(
            connection, "SELECT * FROM statements WHERE sha256=?", (sha256,)
        )
        if existing:
            return {"status": "already_imported", "statement_id": existing[0]["id"]}
        account_id = _account(connection, statement)
        statement_id = _statement(
            connection, statement, sha256, parser_version, account_id
        )
        created = 0
        for ordinal, transaction in enumerate(statement.transactions):
            transaction_id, is_new = _transaction(connection, account_id, transaction)
            created += is_new
            _source(connection, statement_id, ordinal, transaction_id, transaction)
        return {
            "status": "imported",
            "statement_id": statement_id,
            "new_transactions": created,
            "reconciliation": statement.reconciliation(),
        }


def _account(connection: sqlite3.Connection, statement: StatementInput) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO accounts(bank,reference,currency) VALUES (?,?,?)",
        (statement.bank, statement.account, statement.currency),
    )
    return int(
        row(
            connection,
            "SELECT id FROM accounts WHERE bank=? AND reference=?",
            (statement.bank, statement.account),
        )["id"]
    )


def _statement(
    connection: sqlite3.Connection,
    statement: StatementInput,
    digest: str,
    parser_version: str,
    account_id: int,
) -> int:
    return insert(
        connection,
        """INSERT INTO statements
        (sha256,account_id,start,end,parser_version,reconciliation,
         opening_tiyn,closing_tiyn,debits_tiyn,credits_tiyn)
         VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            digest,
            account_id,
            statement.start.isoformat(),
            statement.end.isoformat(),
            parser_version,
            statement.reconciliation(),
            statement.opening_tiyn,
            statement.closing_tiyn,
            statement.debits_tiyn,
            statement.credits_tiyn,
        ),
    )


def _transaction(
    connection: sqlite3.Connection,
    account_id: int,
    item: TransactionInput,
) -> tuple[int, bool]:
    identity = fingerprint(item)
    if item.bank_id:
        existing = rows(
            connection,
            "SELECT * FROM transactions WHERE account_id=? AND bank_id=?",
            (account_id, item.bank_id),
        )
        if existing:
            if existing[0]["fingerprint"] != identity:
                raise ValueError("Bank transaction ID has conflicting data")
            return int(existing[0]["id"]), False
    transaction_id = _insert_transaction(connection, account_id, item, identity)
    _review_duplicates(connection, transaction_id, account_id, identity)
    return transaction_id, True


def _insert_transaction(
    connection: sqlite3.Connection,
    account_id: int,
    item: TransactionInput,
    identity: str,
) -> int:
    return insert(
        connection,
        """INSERT INTO transactions
        (account_id,posted_on,amount_tiyn,description,merchant,kind,bank_id,
         counterparty_account,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            account_id,
            item.posted_on.isoformat(),
            item.amount_tiyn,
            item.description,
            normalize_merchant(item.merchant),
            item.kind,
            item.bank_id,
            item.counterparty_account,
            identity,
        ),
    )


def _review_duplicates(
    connection: sqlite3.Connection,
    transaction_id: int,
    account_id: int,
    identity: str,
) -> None:
    # Only committed earlier statements are candidates, not identical rows in this PDF.
    candidates = rows(
        connection,
        """SELECT DISTINCT t.id FROM transactions t
        JOIN sources s ON s.transaction_id=t.id
        JOIN statements st ON st.id=s.statement_id
        WHERE t.account_id=? AND t.fingerprint=? AND t.id!=?
        AND (t.bank_id IS NULL OR
             (SELECT bank_id FROM transactions WHERE id=?) IS NULL)
        AND st.id < (SELECT MAX(id) FROM statements)""",
        (account_id, identity, transaction_id, transaction_id),
    )
    if candidates:
        connection.execute(
            """INSERT INTO review_items(kind,transaction_id,details)
            VALUES ('duplicate',?,?)""",
            (
                transaction_id,
                json.dumps({"candidate_ids": [item["id"] for item in candidates]}),
            ),
        )


def _source(
    connection: sqlite3.Connection,
    statement_id: int,
    ordinal: int,
    transaction_id: int,
    item: TransactionInput,
) -> None:
    try:
        connection.execute(
            """INSERT INTO sources
            (statement_id,ordinal,transaction_id,page,raw_text) VALUES (?,?,?,?,?)""",
            (statement_id, ordinal, transaction_id, item.page, item.description),
        )
    except sqlite3.IntegrityError as error:
        raise ValueError(
            "A bank transaction ID occurs more than once in this statement"
        ) from error
