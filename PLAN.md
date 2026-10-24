# Implementation plan

## First release boundaries

Local Python MCP over stdio, one data owner, Kaspi and Freedom,
PDFs with a text layer, KZT only. Import using a file or folder path.
No Telegram, URLs, OCR, currency conversion, budgets, or internal model.

Layers: MCP -> application logic -> SQLite and separate bank parsers.
Approve the MCP SDK and PDF library before adding them.
Project documentation, code comments, and commit messages are written in English.

## Invariants

- Store money as integer tiyn; link every transaction to its source.
- SHA-256 prevents repeated file imports; transaction identifiers and
  fingerprints help reconcile overlapping statements.
- Preserve two identical real purchases. Send ambiguous matches for review.
- Import each file atomically; one failed file does not block the others.
- Reject unknown formats and currencies explicitly. Failed reconciliation
  excludes the statement from ordinary reports until reviewed.
- Create categories through tools; unknown transactions are "Uncategorized".
- Manual assignments take precedence over rules; conflicts require review.
- Bulk assignments have a preview, history, and undo.
- Exclude confirmed internal transfers from spending and income.
- Report fees and cash withdrawals separately; linked refunds reduce net
  category spending in the refund period.
- Reports show data coverage, reconciliation results, and uncategorized amounts.
- Signals are explainable; financial recommendations and merchant web searches
  remain the agent's responsibility.

## Stages and commits

Current progress: core models, storage, conservative deduplication, categories,
history, relationship validation, analytics, and the stdio MCP interface are
implemented and tested on synthetic data. Installation is documented.
Verified bank fixtures and Kaspi/Freedom adapters are still pending actual samples.
Windows/Python 3.14 is tested; macOS/Linux validation remains outstanding.

1. Skeleton, environment, checks - `chore: initialize project and quality checks`.
2. Anonymized bank samples - `test: add bank statement fixtures`.
3. Data model and SQLite - `feat: add transaction storage`.
4. Parsers - `feat: parse Kaspi statements`, `feat: parse Freedom statements`.
5. Import and deduplication - `feat: add idempotent statement import`.
6. Categories and history - `feat: add category rules`,
   `feat: add change history and undo`.
7. Transfers and refunds - `feat: reconcile transfers and refunds`.
8. Reports and signals - `feat: add spending reports`, `feat: add review signals`.
9. MCP - `feat: expose finance MCP tools`.
10. Installation - `docs: add installation and usage guide`.

## MCP interface

- Import: `import_statement`, `import_folder`, `list_statements`.
- Browsing: `list_accounts`, `search_transactions`, `get_transaction`.
- Categories: `manage_categories`, `assign_category`, `manage_rules`.
- Review: `list_review_items`, `resolve_review_item`.
- Analytics: `spending_report`, `compare_periods`, `review_signals`.
- History: `list_changes`, `undo_change`.

Responses are structured. Search supports filters and pagination; aggregates
use the entire matching dataset. Group unknown transactions by merchant
to reduce agent context usage.

## Learning workflow and Git

Continue implementation without mandatory exercises or pauses between stages.
Explain meaningful decisions briefly as work progresses. Exercises are optional
and only assigned on request. Ask when required input or approval is missing.

Usually make one or two commits per stage. Before committing, inspect the diff,
the file list, and all four checks from the README. Do not commit unfinished
logic on a timer. Work on a separate branch. Push reviewed, passing milestones
to the working branch as authorized by the user; never push directly to main.

New dependencies, changes to the agreed public API or database schema,
and file deletions require approval. Do not change AGENTS.md without confirmation.

## Acceptance criteria

Test repeated files, overlapping statements, identical purchases, separate accounts,
reconciliation errors, rule conflicts, undo, transfers, fees, cash withdrawals,
refunds, report accuracy, pagination, and persistence across restarts.
Tests use local fixtures and temporary SQLite databases without network access.

Bank support requires verification against actual formats and anonymized samples.
Final scenario: import both banks, resolve categories, obtain a spending report
and an explanation of spending changes with links to the source transactions.
