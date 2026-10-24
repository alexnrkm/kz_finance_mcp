from datetime import date
from pathlib import Path

import pytest

from finance_mcp.models import Bank, Kind, StatementInput, TransactionInput
from finance_mcp.storage import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.sqlite3")


@pytest.fixture
def statement() -> StatementInput:
    return StatementInput(
        Bank.KASPI,
        "SYNTHETIC-KASPI-ACCOUNT",
        date(2026, 10, 1),
        date(2026, 10, 31),
        (
            TransactionInput(
                date(2026, 10, 5),
                -125000,
                "Synthetic coffee",
                "Test Cafe",
                Kind.PURCHASE,
                bank_id="synthetic-001",
            ),
        ),
        opening_tiyn=200000,
        closing_tiyn=75000,
    )
