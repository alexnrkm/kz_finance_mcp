"""Parameterized transaction search with explicit report eligibility."""

from dataclasses import dataclass
from datetime import date

from finance_mcp.identity import normalize_merchant
from finance_mcp.models import Bank
from finance_mcp.storage import Record, Store, rows

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
LEDGER = """WITH ledger AS (
    SELECT t.*, a.bank, a.currency,
      COALESCE((SELECT purchase.category_id FROM links l
        JOIN transactions purchase ON purchase.id=l.left_id
        WHERE l.kind='refund' AND l.active=1 AND l.right_id=t.id),t.category_id)
        AS effective_category_id,
      EXISTS(SELECT 1 FROM links l WHERE l.kind='transfer' AND l.active=1
        AND (l.left_id=t.id OR l.right_id=t.id)) AS internal_transfer,
      EXISTS(SELECT 1 FROM links l WHERE l.kind='refund' AND l.active=1
        AND l.right_id=t.id) AS linked_refund,
      EXISTS(SELECT 1 FROM sources s JOIN statements st ON st.id=s.statement_id
        WHERE (s.transaction_id=t.id OR s.transaction_id IN (
          SELECT right_id FROM links
          WHERE kind='duplicate' AND active=1 AND left_id=t.id))
        AND st.reconciliation!='failed') AS valid_source,
      EXISTS(SELECT 1 FROM links l WHERE l.kind='duplicate' AND l.active=1
        AND l.right_id=t.id) AS confirmed_duplicate,
      EXISTS(SELECT 1 FROM review_items r WHERE r.kind='duplicate'
        AND r.resolved=0 AND r.transaction_id=t.id) AS pending_duplicate
    FROM transactions t JOIN accounts a ON a.id=t.account_id
) """
ELIGIBLE = "valid_source=1 AND confirmed_duplicate=0 AND pending_duplicate=0"


@dataclass(frozen=True)
class Filters:
    start: date | None = None
    end: date | None = None
    account_id: int | None = None
    bank: Bank | None = None
    category_id: int | None = None
    merchant: str | None = None
    min_tiyn: int | None = None
    max_tiyn: int | None = None

    def __post_init__(self) -> None:
        if self.start and self.end and self.start > self.end:
            raise ValueError("Start date must not follow end date")
        if self.min_tiyn is not None and self.max_tiyn is not None:
            if self.min_tiyn > self.max_tiyn:
                raise ValueError("Minimum amount must not exceed maximum")

    def sql(self) -> tuple[str, list[object]]:
        """Build conditions only from fixed column names; amounts are signed."""
        conditions: list[str] = []
        values: list[object] = []
        for column, operator, value in (
            ("posted_on", ">=", self.start.isoformat() if self.start else None),
            ("posted_on", "<=", self.end.isoformat() if self.end else None),
            ("account_id", "=", self.account_id),
            ("bank", "=", self.bank),
            ("effective_category_id", "=", self.category_id),
            ("amount_tiyn", ">=", self.min_tiyn),
            ("amount_tiyn", "<=", self.max_tiyn),
        ):
            if value is not None:
                conditions.append(f"{column}{operator}?")
                values.append(value)
        if self.merchant is not None:
            conditions.append("instr(merchant,?)>0")
            values.append(normalize_merchant(self.merchant))
        return " AND ".join(conditions) or "1=1", values


def validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise ValueError(f"Limit must be 1..{MAX_LIMIT}; offset must be nonnegative")


def search(
    store: Store,
    filters: Filters,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> Record:
    """Search all operations, including excluded rows with eligibility flags."""
    validate_page(limit, offset)
    where, values = filters.sql()
    with store.connect() as connection:
        connection.execute("BEGIN")
        count = rows(
            connection,
            LEDGER + f"SELECT COUNT(*) AS total FROM ledger WHERE {where}",
            values,
        )[0]["total"]
        items = rows(
            connection,
            LEDGER
            + f"""SELECT *, ({ELIGIBLE}) AS report_eligible
            FROM ledger WHERE {where} ORDER BY posted_on,id LIMIT ? OFFSET ?""",
            (*values, limit, offset),
        )
        return {
            "items": items,
            "total": count,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < count else None,
        }


def transaction_detail(store: Store, transaction_id: int) -> Record:
    """Return original lines, pages, and all confirmed duplicate source references."""
    with store.connect() as connection:
        items = rows(
            connection,
            LEDGER + f"SELECT *, ({ELIGIBLE}) AS report_eligible "
            "FROM ledger WHERE id=?",
            (transaction_id,),
        )
        if not items:
            raise ValueError("Transaction not found")
        sources = rows(
            connection,
            """SELECT s.*, st.sha256, st.parser_version,
            st.reconciliation FROM sources s JOIN statements st ON st.id=s.statement_id
            WHERE s.transaction_id=? OR s.transaction_id IN (
              SELECT right_id FROM links
              WHERE left_id=? AND kind='duplicate' AND active=1)
            ORDER BY s.statement_id,s.ordinal""",
            (transaction_id, transaction_id),
        )
        return {"transaction": items[0], "sources": sources}
