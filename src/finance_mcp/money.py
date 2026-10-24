"""Exact conversion of statement amounts to integer tiyn."""

import re
from decimal import Decimal, InvalidOperation

TIYN_PER_TENGE = 100
AMOUNT_PATTERN = re.compile(r"[+-]?(?:\d+|\d{1,3}(?: \d{3})+)(?:[.,]\d{1,2})?")


def parse_kzt(value: str) -> int:
    """Parse a signed KZT amount without guessing ambiguous separators."""
    cleaned = value.replace("\u00a0", " ").replace("\u202f", " ").strip()
    if not AMOUNT_PATTERN.fullmatch(cleaned):
        raise ValueError("Expected a KZT amount with at most two decimal places")
    try:
        amount = Decimal(cleaned.replace(" ", "").replace(",", "."))
    except InvalidOperation as error:
        raise ValueError("Invalid KZT amount") from error
    return int(amount * TIYN_PER_TENGE)
