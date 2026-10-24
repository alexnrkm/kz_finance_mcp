"""Application interface shared by MCP tools and local tests."""

import json
from datetime import date

from finance_mcp import categories, history, links, reports
from finance_mcp.ingestion import Ingestion
from finance_mcp.queries import (
    DEFAULT_LIMIT,
    Filters,
    search,
    transaction_detail,
    validate_page,
)
from finance_mcp.review import review_items
from finance_mcp.signals import signals
from finance_mcp.storage import Record, Store, rows


class FinanceService:
    """Expose typed operations without depending on MCP transport internals."""

    def __init__(self, store: Store, ingestion: Ingestion) -> None:
        self.store = store
        self.ingestion = ingestion

    def get_status(self) -> Record:
        """Inspect readiness, configured import roots, and verified bank adapters."""
        return {
            "database": str(self.store.path),
            "currency": "KZT",
            "unit": "tiyn",
            "import_roots": [str(root) for root in self.ingestion.roots],
            "verified_parsers": [
                {"bank": parser.bank, "version": parser.version}
                for parser in self.ingestion.parsers
            ],
            "bank_support_note": "Bank adapters await verified statement samples.",
        }

    def import_statement(self, path: str) -> Record:
        """Import a PDF in an allowed root; reject unsupported formats."""
        try:
            return self.ingestion.import_statement(path)
        except OSError as error:
            raise ValueError("Cannot access the local PDF") from error

    def import_folder(self, path: str) -> Record:
        """Import direct PDF children; return success or failure separately per file."""
        try:
            return self.ingestion.import_folder(path)
        except OSError as error:
            raise ValueError("Cannot access the local import folder") from error

    def list_statements(self, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Record:
        """List periods, parser versions, hashes, and reconciliation results."""
        return self._page("statements", limit, offset)

    def list_accounts(self, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Record:
        """List owned accounts observed in imported statements."""
        return self._page("accounts", limit, offset)

    def search_transactions(
        self,
        filters: Filters | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> Record:
        """Search signed tiyn amounts, dates, bank, account, merchant, and category.

        Returned eligibility flags explain excluded rows. Dates are inclusive.
        """
        return search(self.store, filters or Filters(), limit, offset)

    def get_transaction(self, transaction_id: int) -> Record:
        """Read operation details and source PDF paths, page numbers, and raw text."""
        result = transaction_detail(self.store, transaction_id)
        for source in result["sources"]:
            source["pdf_path"] = str(self.ingestion.archive / f"{source['sha256']}.pdf")
        return result

    def manage_categories(
        self, action: str, name: str = "", category_id: int = 0
    ) -> Record:
        """Use list, create, or rename. Categories are never invented by the server."""
        return categories.manage_category(self.store, action, name, category_id)

    def assign_category(
        self,
        transaction_ids: list[int],
        category_id: int,
        preview_token: str | None = None,
    ) -> Record:
        """Preview explicit transaction IDs, then pass the returned token to assign."""
        return categories.assign(
            self.store, transaction_ids, category_id, preview_token
        )

    def manage_rules(
        self,
        action: str,
        merchant: str = "",
        category_id: int = 0,
        account_id: int | None = None,
        direction: str | None = None,
        rule_id: int = 0,
        preview_token: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> Record:
        """Use list/create/disable or apply. Apply requires its preview token.

        Rules use exact normalized merchants; direction is debit or credit.
        Creating a rule affects future imports; apply handles existing operations.
        """
        if action == "list":
            return self._page("rules", limit, offset)
        if action == "create":
            return categories.create_rule(
                self.store, merchant, category_id, account_id, direction
            )
        if action == "disable":
            return categories.disable_rule(self.store, rule_id)
        if action == "apply":
            return categories.apply_rules(self.store, preview_token)
        raise ValueError("Use list, create, disable, or apply")

    def list_review_items(self, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Record:
        """Inspect conflicts, unknown merchants, and transfer candidates."""
        return review_items(self.store, limit, offset)

    def resolve_review_item(
        self,
        action: str,
        left_id: int = 0,
        right_id: int = 0,
        review_id: int = 0,
    ) -> Record:
        """Use keep_separate with review_id, or transfer/refund/duplicate with two IDs.

        For transfers/refunds put the debit first. For duplicates put the canonical
        operation first. Resolve category conflicts through assign_category.
        """
        if action == "keep_separate":
            return links.keep_separate(self.store, review_id)
        return links.confirm_pair(self.store, action, left_id, right_id)

    def spending_report(self, filters: Filters | None = None) -> Record:
        """Calculate spending, income, cash, and coverage for the full selection."""
        return reports.spending(self.store, filters or Filters())

    def compare_periods(
        self,
        previous_start: date,
        previous_end: date,
        current_start: date,
        current_end: date,
        account_id: int | None = None,
    ) -> Record:
        """Calculate changes by category and merchant between inclusive periods."""
        return reports.compare(
            self.store,
            previous_start,
            previous_end,
            current_start,
            current_end,
            account_id,
        )

    def review_signals(self, filters: Filters) -> Record:
        """Return evidence for largest expenses, new merchants, and recurring payments.

        A start date is required. Candidates are not financial advice or fraud claims.
        """
        return signals(self.store, filters)

    def list_changes(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        include_details: bool = False,
    ) -> Record:
        """Read audit history; request details to inspect before/after snapshots."""
        result = self._page("changes", limit, offset)
        for change in result["items"]:
            patches = change.pop("patches")
            if include_details:
                change["patches"] = json.loads(patches)
        return result

    def undo_change(self, change_id: int) -> Record:
        """Undo a decision if no later changes depend on or have modified its state."""
        return history.undo(self.store, change_id)

    def _page(self, table: str, limit: int, offset: int) -> Record:
        validate_page(limit, offset)
        if table not in {"accounts", "statements", "rules", "changes"}:
            raise ValueError("Unsupported listing")
        with self.store.connect() as connection:
            connection.execute("BEGIN")
            total = rows(connection, f"SELECT COUNT(*) AS total FROM {table}")[0][
                "total"
            ]
            items = rows(
                connection,
                f"SELECT * FROM {table} ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
        }
