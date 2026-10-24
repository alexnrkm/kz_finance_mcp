from dataclasses import replace
from datetime import date

import pytest

from finance_mcp.models import Bank, Kind, StatementInput, TransactionInput
from finance_mcp.money import parse_kzt


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1 234,56", 123456), ("-0.01", -1), ("1\u202f000", 100000), ("+12", 1200)],
)
def test_exact_money_conversion(value: str, expected: int) -> None:
    assert parse_kzt(value) == expected


@pytest.mark.parametrize("value", ["1,234.56", "NaN", "1.001", "1 23", "", "1e3"])
def test_money_rejects_ambiguous_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_kzt(value)


def test_reconciliation_and_validation() -> None:
    transaction = TransactionInput(
        date(2026, 10, 1), -100, "Coffee", "Cafe", Kind.PURCHASE
    )
    statement = StatementInput(
        Bank.KASPI,
        "TEST-ACCOUNT",
        date(2026, 10, 1),
        date(2026, 10, 31),
        (transaction,),
        opening_tiyn=1000,
        closing_tiyn=900,
    )
    assert statement.reconciliation() == "passed"
    assert replace(statement, closing_tiyn=800).reconciliation() == "failed"
    assert replace(statement, opening_tiyn=None).reconciliation() == "unavailable"
    with pytest.raises(ValueError, match="KZT"):
        replace(statement, currency="USD")
    with pytest.raises(ValueError, match="outside"):
        replace(statement, end=date(2026, 9, 30), start=date(2026, 9, 1))
