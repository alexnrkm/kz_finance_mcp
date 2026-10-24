"""Explainable review candidates, not claims of fraud or unwanted spending."""

from collections import defaultdict
from datetime import date

from finance_mcp.queries import ELIGIBLE, LEDGER, Filters
from finance_mcp.reports import expense
from finance_mcp.storage import Record, Store, rows

SIGNAL_LIMIT = 20
MIN_RECURRING_OCCURRENCES = 3
MIN_MONTHLY_GAP = 25
MAX_MONTHLY_GAP = 35


def signals(store: Store, filters: Filters) -> Record:
    """Find largest expenses, newly observed merchants, and exact recurring payments."""
    if filters.start is None:
        raise ValueError("Signals require a start date for the historical comparison")
    where, values = filters.sql()
    with store.connect() as connection:
        items = rows(
            connection,
            LEDGER + f"SELECT * FROM ledger WHERE {where} AND {ELIGIBLE}",
            values,
        )
        history_filter = Filters(
            end=filters.start, account_id=filters.account_id, bank=filters.bank
        )
        history_where, history_values = history_filter.sql()
        history = rows(
            connection,
            LEDGER + f"SELECT * FROM ledger WHERE {history_where} "
            f"AND posted_on<? AND {ELIGIBLE}",
            (*history_values, filters.start.isoformat()),
        )
    expenses = [item for item in items if expense(item) > 0]
    known = {item["merchant"] for item in history if expense(item) > 0}
    return {
        "largest_expenses": sorted(expenses, key=expense, reverse=True)[:SIGNAL_LIMIT],
        "new_merchants": sorted({item["merchant"] for item in expenses} - known)[
            :SIGNAL_LIMIT
        ],
        "new_merchants_note": "New relative to imported history only.",
        "recurring_candidates": _recurring(history + items),
        "criteria": {
            "recurring_min_occurrences": MIN_RECURRING_OCCURRENCES,
            "monthly_gap_days": [MIN_MONTHLY_GAP, MAX_MONTHLY_GAP],
            "amount_matching": "exact signed tiyn, same account and merchant",
        },
    }


def _recurring(items: list[Record]) -> list[Record]:
    grouped: dict[tuple[int, str, int], list[Record]] = defaultdict(list)
    for item in items:
        if expense(item) > 0:
            grouped[(item["account_id"], item["merchant"], item["amount_tiyn"])].append(
                item
            )
    result: list[Record] = []
    for (account_id, merchant, amount), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: (item["posted_on"], item["id"]))
        dates = [date.fromisoformat(item["posted_on"]) for item in ordered]
        gaps = [
            (later - earlier).days
            for earlier, later in zip(dates, dates[1:], strict=False)
        ]
        if len(ordered) >= MIN_RECURRING_OCCURRENCES and all(
            MIN_MONTHLY_GAP <= gap <= MAX_MONTHLY_GAP for gap in gaps
        ):
            result.append(
                {
                    "merchant": merchant,
                    "account_id": account_id,
                    "amount_tiyn": amount,
                    "transaction_ids": [item["id"] for item in ordered],
                    "gap_days": gaps,
                }
            )
    return result[:SIGNAL_LIMIT]
