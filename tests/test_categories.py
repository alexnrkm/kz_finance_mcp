from dataclasses import replace

import pytest

from finance_mcp.categories import apply_rules, assign, create_rule, manage_category
from finance_mcp.history import undo
from finance_mcp.importer import import_parsed
from finance_mcp.models import StatementInput
from finance_mcp.storage import Store, row, rows


def test_rule_applies_on_import_and_manual_override_survives(
    store: Store,
    statement: StatementInput,
) -> None:
    food = manage_category(store, "create", "Food")["category_id"]
    other = manage_category(store, "create", "Other")["category_id"]
    create_rule(store, " TEST   Cafe ", food, direction="debit")
    import_parsed(store, statement, "a" * 64, "synthetic-test-v1")
    with store.connect() as connection:
        assert row(connection, "SELECT * FROM transactions")["category_id"] == food
    preview = assign(store, [1], other)
    change = assign(store, [1], other, preview["preview_token"])
    rules_preview = apply_rules(store)
    apply_rules(store, rules_preview["preview_token"])
    import_parsed(store, statement, "b" * 64, "synthetic-test-v1")
    with store.connect() as connection:
        assert row(connection, "SELECT * FROM transactions")["category_id"] == other
    undo(store, change["change_id"])
    with store.connect() as connection:
        assert row(connection, "SELECT * FROM transactions")["category_id"] == food


def test_conflicting_rules_require_review(
    store: Store, statement: StatementInput
) -> None:
    first = manage_category(store, "create", "Food")["category_id"]
    second = manage_category(store, "create", "Leisure")["category_id"]
    create_rule(store, "Test Cafe", first)
    create_rule(store, "Test Cafe", second)
    import_parsed(store, statement, "a" * 64, "synthetic-test-v1")
    with store.connect() as connection:
        assert row(connection, "SELECT * FROM transactions")["category_id"] == 1
        assert row(connection, "SELECT * FROM review_items")["kind"] == "rule_conflict"


def test_stale_preview_cannot_overwrite_new_decision(
    store: Store,
    statement: StatementInput,
) -> None:
    category = manage_category(store, "create", "Food")["category_id"]
    import_parsed(store, statement, "a" * 64, "synthetic-test-v1")
    old = assign(store, [1], category)
    preview = assign(store, [1], 1)
    assign(store, [1], 1, preview["preview_token"])
    with pytest.raises(ValueError, match="stale"):
        assign(store, [1], category, old["preview_token"])


def test_undo_rejects_later_changes(store: Store) -> None:
    created = manage_category(store, "create", "Food")
    renamed = manage_category(store, "rename", "Groceries", created["category_id"])
    with pytest.raises(ValueError, match="later"):
        undo(store, created["change_id"])
    undo(store, renamed["change_id"])
    undo(store, created["change_id"])
    with store.connect() as connection:
        assert len(rows(connection, "SELECT * FROM categories")) == 1


def test_rule_account_scope(store: Store, statement: StatementInput) -> None:
    import_parsed(store, statement, "a" * 64, "synthetic-test-v1")
    category = manage_category(store, "create", "Food")["category_id"]
    create_rule(store, "Test Cafe", category, account_id=1)
    different = replace(statement, account="OTHER-SYNTHETIC-ACCOUNT")
    import_parsed(store, different, "b" * 64, "synthetic-test-v1")
    preview = apply_rules(store)
    apply_rules(store, preview["preview_token"])
    with store.connect() as connection:
        assert [
            item["category_id"]
            for item in rows(connection, "SELECT * FROM transactions ORDER BY id")
        ] == [category, 1]
