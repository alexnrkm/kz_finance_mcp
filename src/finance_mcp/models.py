"""Bank-independent input models. Amounts are signed integer tiyn."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

CURRENCY = "KZT"
UNCATEGORIZED_ID = 1


class Bank(StrEnum):
    KASPI = "kaspi"
    FREEDOM = "freedom"


class Kind(StrEnum):
    PURCHASE = "purchase"
    INCOME = "income"
    TRANSFER = "transfer"
    REFUND = "refund"
    FEE = "fee"
    CASH = "cash"


@dataclass(frozen=True)
class TransactionInput:
    posted_on: date
    amount_tiyn: int
    description: str
    merchant: str
    kind: Kind
    page: int = 1
    bank_id: str | None = None
    counterparty_account: str | None = None

    def __post_init__(self) -> None:
        if type(self.amount_tiyn) is not int or self.amount_tiyn == 0:
            raise ValueError("Transaction amount must be a nonzero integer in tiyn")
        if self.page < 1 or not self.description.strip() or not self.merchant.strip():
            raise ValueError("Transaction requires a page, description, and merchant")
        if self.kind in {Kind.PURCHASE, Kind.FEE, Kind.CASH} and self.amount_tiyn > 0:
            raise ValueError("Expense amount must be negative")
        if self.kind in {Kind.INCOME, Kind.REFUND} and self.amount_tiyn < 0:
            raise ValueError("Income or refund amount must be positive")


@dataclass(frozen=True)
class StatementInput:
    bank: Bank
    account: str
    start: date
    end: date
    transactions: tuple[TransactionInput, ...]
    currency: str = CURRENCY
    opening_tiyn: int | None = None
    closing_tiyn: int | None = None
    debits_tiyn: int | None = None
    credits_tiyn: int | None = None

    def __post_init__(self) -> None:
        if self.currency != CURRENCY:
            raise ValueError("Only KZT statements are supported")
        if not self.account.strip() or self.start > self.end:
            raise ValueError("Statement requires an account and a valid date range")
        if any(
            not self.start <= item.posted_on <= self.end for item in self.transactions
        ):
            raise ValueError("Transaction date is outside the statement period")

    def reconciliation(self) -> str:
        """Return passed, failed, or unavailable; missing checks never imply success."""
        amounts = [item.amount_tiyn for item in self.transactions]
        checks: list[bool] = []
        if self.opening_tiyn is not None and self.closing_tiyn is not None:
            checks.append(self.opening_tiyn + sum(amounts) == self.closing_tiyn)
        if self.debits_tiyn is not None:
            checks.append(
                -sum(value for value in amounts if value < 0) == self.debits_tiyn
            )
        if self.credits_tiyn is not None:
            checks.append(
                sum(value for value in amounts if value > 0) == self.credits_tiyn
            )
        if not checks:
            return "unavailable"
        return "passed" if all(checks) else "failed"
