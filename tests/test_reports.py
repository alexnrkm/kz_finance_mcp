from dataclasses import replace
from datetime import date

import pytest

from finance_mcp.categories import assign, manage_category
from finance_mcp.history import undo
from finance_mcp.importer import import_parsed
from finance_mcp.links import confirm_pair, keep_separate
from finance_mcp.models import Bank, Kind, StatementInput, TransactionInput
from finance_mcp.queries import Filters, search, transaction_detail
from finance_mcp.reports import compare, spending
from finance_mcp.signals import signals
from finance_mcp.storage import Store, rows


def test_report_uses_all_rows_and_search_is_paginated(
    store: Store, statement: StatementInput
) -> None:
    items = tuple(
        replace(statement.transactions[0], bank_id=f"synthetic-{key}")
        for key in range(5)
    )
    import_parsed(
        store,
        replace(statement, transactions=items, closing_tiyn=-425000),
        "a" * 64,
        "test",
    )
    assert search(store, Filters(), limit=2)["total"] == 5
    assert search(store, Filters(), limit=2)["next_offset"] == 2
    assert len(search(store, Filters(), limit=2, offset=4)["items"]) == 1
    assert spending(store, Filters())["net_spending_tiyn"] == 625000
    assert search(store, Filters(merchant="%' OR 1=1 --"))["total"] == 0
    with pytest.raises(ValueError, match="Limit"):
        search(store, Filters(), limit=0)


def test_failed_reconciliation_is_searchable_but_excluded(
    store: Store, statement: StatementInput
) -> None:
    import_parsed(store, replace(statement, closing_tiyn=0), "a" * 64, "test")
    report = spending(store, Filters())
    assert report["net_spending_tiyn"] == 0
    assert report["excluded_transactions"] == 1
    assert report["coverage"][0]["reconciliation"] == "failed"
    assert search(store, Filters())["items"][0]["report_eligible"] == 0


def test_duplicate_resolution_preserves_multiplicity_and_sources(
    store: Store, statement: StatementInput
) -> None:
    item = replace(statement.transactions[0], bank_id=None)
    repeated = replace(statement, transactions=(item, item), closing_tiyn=-50000)
    import_parsed(store, repeated, "a" * 64, "test")
    import_parsed(store, repeated, "b" * 64, "test")
    assert spending(store, Filters())["excluded_transactions"] == 2
    change = confirm_pair(store, "duplicate", 1, 3)
    with pytest.raises(ValueError, match="same statement"):
        confirm_pair(store, "duplicate", 1, 4)
    confirm_pair(store, "duplicate", 2, 4)
    assert spending(store, Filters())["net_spending_tiyn"] == 250000
    assert len(transaction_detail(store, 1)["sources"]) == 2
    undo(store, change["change_id"])
    assert spending(store, Filters())["excluded_transactions"] == 2


def test_keep_separate_and_undo(store: Store, statement: StatementInput) -> None:
    changed = replace(
        statement, transactions=(replace(statement.transactions[0], bank_id=None),)
    )
    import_parsed(store, changed, "a" * 64, "test")
    import_parsed(store, changed, "b" * 64, "test")
    change = keep_separate(store, 1)
    assert spending(store, Filters())["net_spending_tiyn"] == 250000
    undo(store, change["change_id"])
    assert spending(store, Filters())["net_spending_tiyn"] == 125000


def test_reciprocal_owned_transfer_is_automatically_excluded(
    store: Store, statement: StatementInput
) -> None:
    debit = replace(
        statement.transactions[0],
        kind=Kind.TRANSFER,
        counterparty_account="OWN-FREEDOM",
    )
    credit = replace(
        debit,
        amount_tiyn=125000,
        bank_id="synthetic-credit",
        counterparty_account=statement.account,
    )
    import_parsed(store, replace(statement, transactions=(debit,)), "a" * 64, "test")
    incoming = replace(
        statement,
        bank=Bank.FREEDOM,
        account="OWN-FREEDOM",
        transactions=(credit,),
        opening_tiyn=0,
        closing_tiyn=125000,
    )
    import_parsed(store, incoming, "b" * 64, "test")
    report = spending(store, Filters())
    assert report["net_spending_tiyn"] == report["income_tiyn"] == 0
    with store.connect() as connection:
        assert rows(connection, "SELECT * FROM links")[0]["kind"] == "transfer"


def test_amount_match_alone_does_not_confirm_transfer(
    store: Store, statement: StatementInput
) -> None:
    debit = replace(statement.transactions[0], kind=Kind.TRANSFER)
    credit = replace(debit, amount_tiyn=125000)
    import_parsed(store, replace(statement, transactions=(debit,)), "a" * 64, "test")
    import_parsed(
        store,
        replace(
            statement,
            bank=Bank.FREEDOM,
            transactions=(credit,),
            opening_tiyn=0,
            closing_tiyn=125000,
        ),
        "b" * 64,
        "test",
    )
    assert spending(store, Filters())["net_spending_tiyn"] == 125000
    confirm_pair(store, "transfer", 1, 2)
    assert spending(store, Filters())["net_spending_tiyn"] == 0


def test_refund_affects_category_in_refund_period(
    store: Store, statement: StatementInput
) -> None:
    import_parsed(store, statement, "a" * 64, "test")
    category_id = manage_category(store, "create", "Food")["category_id"]
    preview = assign(store, [1], category_id)
    assign(store, [1], category_id, preview["preview_token"])
    refund = replace(
        statement.transactions[0],
        posted_on=date(2026, 11, 1),
        amount_tiyn=25000,
        kind=Kind.REFUND,
        bank_id="synthetic-refund",
    )
    next_month = replace(
        statement,
        start=date(2026, 11, 1),
        end=date(2026, 11, 30),
        transactions=(refund,),
        opening_tiyn=75000,
        closing_tiyn=100000,
    )
    import_parsed(store, next_month, "b" * 64, "test")
    assert spending(store, Filters())["unlinked_refunds_tiyn"] == 25000
    confirm_pair(store, "refund", 1, 2)
    report = spending(store, Filters(start=date(2026, 11, 1)))
    assert report["categories"][0] == {
        "category_id": category_id,
        "name": "Food",
        "net_tiyn": -25000,
    }
    assert spending(store, Filters())["net_spending_tiyn"] == 100000
    with pytest.raises(ValueError):
        confirm_pair(store, "refund", 1, 2)


def test_cash_fees_and_period_comparison(
    store: Store, statement: StatementInput
) -> None:
    original = statement.transactions[0]
    items = (
        replace(original, kind=Kind.CASH),
        replace(original, kind=Kind.FEE, bank_id="synthetic-fee", amount_tiyn=-100),
    )
    import_parsed(
        store,
        replace(statement, transactions=items, closing_tiyn=74900),
        "a" * 64,
        "test",
    )
    report = spending(store, Filters())
    assert report["net_spending_tiyn"] == report["fees_tiyn"] == 100
    assert report["cash_withdrawals_tiyn"] == 125000
    result = compare(
        store,
        date(2026, 9, 1),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 31),
    )
    assert result["delta_tiyn"] == result["category_changes"][0]["delta_tiyn"] == 100


def test_recurring_candidates_show_evidence(store: Store) -> None:
    dates = [date(2026, month, 5) for month in (8, 9, 10)]
    items = tuple(
        TransactionInput(
            day,
            -1000,
            "Synthetic subscription",
            "Test Service",
            Kind.PURCHASE,
            bank_id=f"synthetic-{day}",
        )
        for day in dates
    )
    statement = StatementInput(
        Bank.KASPI, "SYNTHETIC", date(2026, 8, 1), date(2026, 10, 31), items
    )
    import_parsed(store, statement, "a" * 64, "test")
    result = signals(store, Filters(start=date(2026, 10, 1), end=date(2026, 10, 31)))
    assert result["new_merchants"] == []
    assert result["recurring_candidates"][0]["transaction_ids"] == [1, 2, 3]
    assert result["recurring_candidates"][0]["gap_days"] == [31, 30]


def test_good_duplicate_source_can_validate_canonical_operation(
    store: Store,
    statement: StatementInput,
) -> None:
    changed = replace(
        statement, transactions=(replace(statement.transactions[0], bank_id=None),)
    )
    import_parsed(store, replace(changed, closing_tiyn=0), "a" * 64, "test")
    import_parsed(store, changed, "b" * 64, "test")
    confirm_pair(store, "duplicate", 1, 2)
    assert spending(store, Filters())["net_spending_tiyn"] == 125000


def test_failed_statement_cannot_auto_confirm_transfer(
    store: Store,
    statement: StatementInput,
) -> None:
    debit = replace(
        statement.transactions[0],
        kind=Kind.TRANSFER,
        counterparty_account="OWN-FREEDOM",
    )
    credit = replace(
        debit,
        amount_tiyn=125000,
        bank_id="synthetic-credit",
        counterparty_account=statement.account,
    )
    import_parsed(store, replace(statement, transactions=(debit,)), "a" * 64, "test")
    incoming = replace(
        statement,
        bank=Bank.FREEDOM,
        account="OWN-FREEDOM",
        transactions=(credit,),
        opening_tiyn=0,
        closing_tiyn=0,
    )
    import_parsed(store, incoming, "b" * 64, "test")
    with store.connect() as connection:
        assert not rows(connection, "SELECT * FROM links")
