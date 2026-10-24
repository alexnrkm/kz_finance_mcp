from dataclasses import replace
from pathlib import Path

import pytest

from finance_mcp.importer import import_parsed
from finance_mcp.models import Bank, StatementInput
from finance_mcp.storage import Store, rows

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
PARSER = "synthetic-test-v1"


def test_repeat_import_and_persistence(store: Store, statement: StatementInput) -> None:
    assert import_parsed(store, statement, DIGEST_A, PARSER)["new_transactions"] == 1
    reopened = Store(store.path)
    assert (
        import_parsed(reopened, statement, DIGEST_A, PARSER)["status"]
        == "already_imported"
    )
    assert import_parsed(reopened, statement, DIGEST_B, PARSER)["new_transactions"] == 0
    with reopened.connect() as connection:
        assert len(rows(connection, "SELECT * FROM transactions")) == 1
        assert len(rows(connection, "SELECT * FROM sources")) == 2


def test_same_purchase_twice_is_preserved(
    store: Store, statement: StatementInput
) -> None:
    item = replace(statement.transactions[0], bank_id=None)
    repeated = replace(statement, transactions=(item, item), closing_tiyn=-50000)
    import_parsed(store, repeated, DIGEST_A, PARSER)
    with store.connect() as connection:
        assert len(rows(connection, "SELECT * FROM transactions")) == 2
        assert not rows(connection, "SELECT * FROM review_items")
    import_parsed(store, repeated, DIGEST_B, PARSER)
    with store.connect() as connection:
        assert len(rows(connection, "SELECT * FROM transactions")) == 4
        assert len(rows(connection, "SELECT * FROM review_items")) == 2


def test_same_bank_id_on_different_account_is_not_duplicate(
    store: Store,
    statement: StatementInput,
) -> None:
    import_parsed(store, statement, DIGEST_A, PARSER)
    import_parsed(store, replace(statement, bank=Bank.FREEDOM), DIGEST_B, PARSER)
    with store.connect() as connection:
        assert len(rows(connection, "SELECT * FROM transactions")) == 2


def test_distinct_bank_ids_are_not_duplicate_candidates(
    store: Store,
    statement: StatementInput,
) -> None:
    import_parsed(store, statement, DIGEST_A, PARSER)
    item = replace(statement.transactions[0], bank_id="synthetic-002")
    import_parsed(store, replace(statement, transactions=(item,)), DIGEST_B, PARSER)
    with store.connect() as connection:
        assert not rows(connection, "SELECT * FROM review_items")


def test_conflicting_bank_id_rolls_back_entire_statement(
    store: Store,
    statement: StatementInput,
) -> None:
    import_parsed(store, statement, DIGEST_A, PARSER)
    changed = replace(statement.transactions[0], amount_tiyn=-10)
    with pytest.raises(ValueError, match="conflicting"):
        import_parsed(
            store, replace(statement, transactions=(changed,)), DIGEST_B, PARSER
        )
    with store.connect() as connection:
        assert len(rows(connection, "SELECT * FROM statements")) == 1


def test_repeated_bank_id_rolls_back(store: Store, statement: StatementInput) -> None:
    repeated = replace(statement, transactions=statement.transactions * 2)
    with pytest.raises(ValueError, match="more than once"):
        import_parsed(store, repeated, DIGEST_A, PARSER)
    with store.connect() as connection:
        assert not rows(connection, "SELECT * FROM statements")
        assert not rows(connection, "SELECT * FROM accounts")


def test_future_schema_is_not_silently_downgraded(store: Store, tmp_path: Path) -> None:
    with store.connect() as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(ValueError, match="version"):
        Store(store.path)
