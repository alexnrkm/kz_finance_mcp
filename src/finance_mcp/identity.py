"""Conservative normalization and transaction identity."""

import hashlib
import json

from finance_mcp.models import TransactionInput


def normalize_merchant(value: str) -> str:
    """Normalize whitespace and case, preserving digits and punctuation."""
    return " ".join(value.split()).casefold()


def fingerprint(transaction: TransactionInput) -> str:
    """Fingerprint within an account; never use this alone to discard duplicates."""
    parts = [
        transaction.posted_on.isoformat(),
        transaction.amount_tiyn,
        normalize_merchant(transaction.description),
        normalize_merchant(transaction.merchant),
        transaction.kind,
        transaction.counterparty_account,
    ]
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
