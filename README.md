# Finance MCP KZ

A local Python MCP server for personal bank statements in KZT.
The server owns deterministic parsing, deduplication, rules, and report math.
The connected agent resolves uncertain decisions and provides recommendations.

For a detailed explanation of the project, start with the
[engineering documentation](docs/README.md). It includes architecture, database
tables, accounting algorithms, every MCP tool, operations, and a development guide.

## Current status

This is a working core and stdio MCP interface, not a completed bank importer.

Implemented:

- SQLite storage with atomic normalized-statement imports and source provenance.
- File hashes, bank transaction IDs, and conservative duplicate review.
- Agent-created categories, exact-merchant rules, preview tokens, history, and undo.
- Transaction search, full-selection reports, period comparisons, and review signals.
- Internal-transfer matching, linked refunds, separate cash withdrawals and fees.
- Restricted local PDF ingestion, text extraction, and a bank-parser interface.

**Kaspi and Freedom PDF adapters are not implemented or registered yet.**
Actual statement samples are required to establish their formats and test them.
The installed server explicitly rejects unsupported PDFs rather than guessing.
Synthetic test data does not establish support for either bank.
Use `get_status` to inspect the currently registered, verified parsers.

No OCR, URL ingestion, network requests, internal model, currency conversion,
Telegram integration, or financial advice from the server.

## Installation

Requires Python 3.12+. Tested locally on Windows with Python 3.14.
Linux and macOS have not yet been validated.

From a checkout, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m finance_mcp --check
```

For development instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -e . --group dev
```

The `--group` option requires pip 25.1+. The installed command is
`finance-mcp-kz`; `python -m finance_mcp` runs the same server.

## Storage and file access

By default, data is stored outside the checkout:

- Windows: `%LOCALAPPDATA%/finance-mcp-kz`.
- macOS: `~/Library/Application Support/finance-mcp-kz`.
- Linux: `$XDG_DATA_HOME/finance-mcp-kz` or `~/.local/share/finance-mcp-kz`.

Override it with `--data-dir` or `FINANCE_MCP_DATA_DIR`.
The directory contains `finance.sqlite3`, an `inbox/`, and archived source PDFs
named by SHA-256 under `statements/`.

Only files inside configured import roots can be imported. The default root is
the data directory's inbox. Repeat `--import-root` to allow additional folders:

```powershell
.\.venv\Scripts\python.exe -m finance_mcp --import-root "C:/bank-statements"
```

Use absolute root paths. Relative file arguments resolve against the first root.
Folders are scanned nonrecursively, with a maximum of 200 PDFs per call.
PDFs are limited to 20 MiB and 200 pages. Symlinks are resolved before checking
the root boundary. Password-protected PDFs are not supported.

Without `--check`, the process waits for MCP messages over stdio.
It is not an interactive terminal application.
The database and archived PDFs are local and are not encrypted by the application.
The connected agent receives data returned by tools; its own privacy policy applies.

## Connect to Codex

Replace the example paths with absolute paths on your machine:

```powershell
codex mcp add kz-finance -- "C:/path/to/project/.venv/Scripts/python.exe" -m finance_mcp --import-root "C:/bank-statements"
codex mcp list
```

This is the stdio registration syntax from the
[official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
The project does not modify your Codex configuration automatically.

## Connect to Claude Code

Use the same absolute Python path and server arguments:

```powershell
claude mcp add kz-finance -- "C:/path/to/project/.venv/Scripts/python.exe" -m finance_mcp --import-root "C:/bank-statements"
```

The launch-command pattern is documented in the
[official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/docs/get-started/real-host.md).

## Tools

| Purpose | Tools |
| --- | --- |
| Readiness | `get_status` |
| Import | `import_statement`, `import_folder`, `list_statements` |
| Browse | `list_accounts`, `search_transactions`, `get_transaction` |
| Categorize | `manage_categories`, `assign_category`, `manage_rules` |
| Review | `list_review_items`, `resolve_review_item` |
| Analyze | `spending_report`, `compare_periods`, `review_signals` |
| Audit | `list_changes`, `undo_change` |

Amounts are signed integer tiyn: 100 tiyn = 1 KZT.
Search dates are inclusive. Amount filters use signed values, so expenses are negative.
Search limits are 1..200; aggregates always use the full matching selection.

Category assignments and applying rules return a preview first.
Pass its `preview_token` with the same operation to apply it.
A stale preview fails rather than overwriting newer decisions.
Manual categories take precedence; conflicting rules leave a review item.
Creating a rule applies to future imports; applying it to existing rows is separate.

Duplicate candidates are excluded from report totals until resolved and are counted
as excluded operations. Failed reconciliation also blocks statement-only rows
from reports; a valid linked source can establish an operation's eligibility.
These exclusions mean totals may be incomplete. Inspect coverage and review queues.

Confirmed internal transfers are excluded from spending and income.
Cash withdrawals and fees are reported separately; fees also count as spending.
Unconfirmed outbound transfers still count as spending.
Unlinked refunds are reported separately; linked refunds reduce the purchase
category's net spending in the refund period.

Recurring-payment candidates require at least three exact amounts at the same
merchant and account, spaced 25..35 days apart. New merchants are new only relative
to imported history. These are review candidates, not fraud claims.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the data flow and
[PLAN.md](PLAN.md) for milestones.

## Development checks

After installing development dependencies, add the environment to this
PowerShell terminal's path:

```powershell
$env:Path = "$PWD\.venv\Scripts;$env:Path"
pytest -q
ruff check .
ruff format .
mypy src/
```

If formatting changes code, rerun tests, linting, and type checking.
Tests use synthetic data, temporary databases, and local subprocesses, without
network access. They cover the core and MCP transport, not real bank formats.

The `.pytest_cache/`, `.ruff_cache/`, and `.mypy_cache/` directories are generated
by development tools to speed up repeated checks. They are ignored by Git and
are recreated when removed. The README inside `.pytest_cache/` is generated by pytest.

## Personal data

Never commit real statements, databases, `.env` files, or secrets.
Keep private samples under the ignored `data/` directory.
PDFs are ignored by default; bank test fixtures must be anonymized and reviewed
before being added explicitly. Learning notes are local and ignored.
