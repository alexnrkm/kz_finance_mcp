"""Review queues and compact, merchant-grouped categorization work."""

import json
import sqlite3

from finance_mcp.links import TRANSFER_WINDOW_DAYS
from finance_mcp.queries import DEFAULT_LIMIT, ELIGIBLE, LEDGER, validate_page
from finance_mcp.storage import Record, Store, rows

MAX_EXAMPLES = 3


def review_items(store: Store, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Record:
    """Return conflicts, grouped unknown merchants, and transfer candidates."""
    validate_page(limit, offset)
    with store.connect() as connection:
        connection.execute("BEGIN")
        total = rows(
            connection, "SELECT COUNT(*) AS total FROM review_items WHERE resolved=0"
        )[0]["total"]
        items = rows(
            connection,
            """SELECT * FROM review_items WHERE resolved=0
            ORDER BY id LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        groups = _unknown_groups(connection, limit, offset)
        candidates = _transfer_candidates(connection, limit, offset)
    for item in items:
        item["details"] = json.loads(item["details"])
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "uncategorized_groups": groups,
        "transfer_candidates": candidates,
        "candidate_note": "Confirm candidate pairs explicitly.",
    }


def _transfer_candidates(
    connection: sqlite3.Connection,
    limit: int,
    offset: int,
) -> list[Record]:
    return rows(
        connection,
        """SELECT debit.id AS left_id, credit.id AS right_id,
            debit.amount_tiyn, debit.posted_on AS debit_date,
            credit.posted_on AS credit_date
            FROM transactions debit JOIN transactions credit
              ON debit.amount_tiyn=-credit.amount_tiyn
            WHERE debit.kind='transfer' AND credit.kind='transfer'
              AND debit.amount_tiyn<0
              AND debit.account_id!=credit.account_id
              AND ABS(julianday(debit.posted_on)-julianday(credit.posted_on))<=?
              AND NOT EXISTS(SELECT 1 FROM links l WHERE active=1 AND
                (l.left_id IN (debit.id,credit.id)
                 OR l.right_id IN (debit.id,credit.id)))
            ORDER BY debit.id,credit.id LIMIT ? OFFSET ?""",
        (TRANSFER_WINDOW_DAYS, limit, offset),
    )


def _unknown_groups(
    connection: sqlite3.Connection, limit: int, offset: int
) -> list[Record]:
    groups = rows(
        connection,
        LEDGER
        + f"""SELECT merchant,COUNT(*) AS count,
        SUM(amount_tiyn) AS signed_amount_tiyn FROM ledger
        WHERE category_id=1 AND {ELIGIBLE}
        GROUP BY merchant ORDER BY count DESC,merchant LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    for group in groups:
        group["examples"] = rows(
            connection,
            LEDGER
            + f"""SELECT id,posted_on,amount_tiyn,description
            FROM ledger WHERE category_id=1 AND merchant=? AND {ELIGIBLE}
            ORDER BY id LIMIT ?""",
            (group["merchant"], MAX_EXAMPLES),
        )
    return groups
