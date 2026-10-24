"""Exact conversion of statement amounts to integer tiyn."""

import re

TIYN_PER_TENGE = 100
MIN_TIYN = -(2**63)
MAX_TIYN = 2**63 - 1
AMOUNT_PATTERN = re.compile(r"[+-]?(?:\d+|\d{1,3}(?: \d{3})+)(?:[.,]\d{1,2})?")


def parse_kzt(value: str) -> int:
    """Parse a signed KZT amount without guessing ambiguous separators."""
    cleaned = value.replace("\u00a0", " ").replace("\u202f", " ").strip()
    if not AMOUNT_PATTERN.fullmatch(cleaned):
        raise ValueError("Expected a KZT amount with at most two decimal places")
    normalized = cleaned.replace(" ", "").replace(",", ".")
    whole, _, fraction = normalized.lstrip("+-").partition(".")
    amount = int(whole) * TIYN_PER_TENGE + int(fraction.ljust(2, "0"))
    result = -amount if normalized.startswith("-") else amount
    validate_tiyn(result)
    return result


def validate_tiyn(value: int) -> None:
    """Require the exact signed integer range supported by SQLite."""
    if type(value) is not int or not MIN_TIYN <= value <= MAX_TIYN:
        raise ValueError("Amount is outside the signed 64-bit integer tiyn range")
