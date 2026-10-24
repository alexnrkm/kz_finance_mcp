# Development guide

The goal is to keep financial interpretation separate from reproducible data
processing. Read [Architecture](../ARCHITECTURE.md) first, then use this guide
to locate changes and verify them.

## Repository layout

```text
src/finance_mcp/   application package
tests/            synthetic unit and integration tests
docs/             engineering reference
data/             ignored private samples and local artifacts
pyproject.toml    package metadata, dependency groups, and check configuration
README.md         entry point and installation
ARCHITECTURE.md   component map and design decisions
PLAN.md           milestones and development workflow
```

The `src` layout separates importable application code from repository files.
`py.typed` marks the package as typed. `schema.sql` is a packaged resource, loaded
through `importlib.resources`, so a built wheel does not depend on a checkout.
Setuptools creates the `finance-mcp-kz` console entry point, which calls
`finance_mcp.server:main`. `python -m finance_mcp` calls the same function.

## Development environment

From the checkout in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . --group dev
$env:Path = "$PWD\.venv\Scripts;$env:Path"
```

Editable installation makes source changes visible without reinstalling the
package after every edit. Changes to package metadata, dependencies, or entry
points can still require reinstalling. The PATH assignment affects only the
current terminal; it does not configure automatic environment activation.

## Follow a request through the code

For `spending_report`, the path is:

1. `server.py` registers the bound `FinanceService.spending_report` method.
2. The MCP SDK validates the tool arguments and constructs the filter model.
3. `service.py` supplies default filters and delegates to `reports.spending`.
4. `queries.py` supplies the ledger CTE, eligibility expression, and parameterized
   filter conditions.
5. `storage.py` opens a SQLite connection and starts the requested transaction.
6. `reports.py` reads the entire eligible selection and source context, computes
   integer totals, and returns a dictionary.
7. The SDK serializes structured results for the agent.

Business calculations belong in domain modules, not in MCP decorators or tool
descriptions. Domain tests should run without starting a protocol client.
Transport tests separately verify that schemas, serialization, and subprocess
lifecycle preserve those behaviors.

## Adding a verified bank adapter

Do not implement a parser from the bank name alone. A bank can change its export
layout, column ordering, language, or transaction descriptions between versions.
The extension contract is `BankParser` in `ingestion.py`:

```python
class BankParser(Protocol):
    bank: Bank
    version: str

    def matches(self, pages: tuple[str, ...]) -> bool: ...

    def parse(self, pages: tuple[str, ...]) -> StatementInput: ...
```

`pages` contains extracted text in page order, using `layout=True`. It does not
currently include words' bounding boxes, image data, or a live PDF handle. If a
real layout requires a richer extraction contract, propose that interface change
before modifying it rather than adding undocumented access to the source file.
One adapter invocation currently returns one statement for one account. A PDF
containing multiple accounts would require an agreed contract change rather
than silently combining them under one account reference.

Implementation sequence:

1. Obtain actual statement samples and inspect account identification, period,
   columns, signs, page breaks, row continuations, and control totals.
2. Keep originals under ignored `data/private/`. Prepare separately reviewed,
   anonymized fixtures; do not force-add a private PDF to Git.
3. Define expected operations and reconciliation results independently of the
   parser code. Cover multiple operations and boundary cases, not just one row.
4. Implement strict format recognition. Return false for unsupported variants;
   a short bank-name substring alone is insufficient evidence of a layout.
5. Parse into `StatementInput` and `TransactionInput`, using explicit bank rules
   for amounts and signs. Preserve descriptions, page numbers, and bank IDs.
6. Extract a stable account reference. If only a masked reference is available,
   establish how collisions between accounts will be prevented before claiming
   reliable account identity or reciprocal-transfer matching.
7. Run model validation and reconciliation; add negative tests for changed
   headers, missing rows, invalid totals, other currencies, and malformed inputs.
8. Register the verified adapter explicitly in `server.create_service`.
   Production currently supplies an empty parser sequence.
9. Verify PDF import through the service and then the MCP transport. Update
   readiness and support documentation to describe only tested variants.

`tests/test_ingestion.py` has a `SyntheticParser` demonstrating dependency
injection. It is intentionally test-only and must never be registered as real
Kaspi support. Do not expose `import_parsed` directly as an MCP tool: the ledger
should receive source-backed parser results, not agent-invented financial facts.

## Where changes belong

| Requested change | First place to inspect |
| --- | --- |
| Amount notation or numeric validation | `money.py`, `models.py`, model tests |
| Reimport or duplicate identity | `identity.py`, `importer.py`, import tests |
| Category precedence or previews | `categories.py`, category tests |
| Pair compatibility or refund limits | `links.py`, relationship/report tests |
| Eligibility or search semantics | `queries.py`, report tests |
| Report formulas or comparisons | `reports.py`, report tests |
| Signal evidence or thresholds | `signals.py`, signal tests in report tests |
| New tool or changed arguments | `service.py`, `server.py`, protocol tests and tool reference |
| New persistent data | `schema.sql`, `storage.py`, schema-version strategy, data-model reference |

## Verification

The required commands are:

```powershell
pytest -q
ruff check .
ruff format .
mypy src/
```

If formatting changes source, repeat tests, linting, and typing checks. Ruff
checks error, import, bugbear, and modernization rules selected in `pyproject.toml`.
Mypy runs in strict mode on `src/`; this command does not type-check `tests/`.
Financial expectations must be tested as behavior: a well-typed wrong formula
can still pass mypy.

| Tests | Coverage |
| --- | --- |
| `test_package.py` | Source-layout import identity |
| `test_models.py` | Exact money conversion, range/sign/date/currency controls and reconciliation cases |
| `test_importer.py` | File reimports, source persistence, duplicate multiplicity, ID conflicts, atomic rollback, schema version rejection |
| `test_categories.py` | Rule scope, conflicts, manual precedence, stale previews, history dependencies |
| `test_reports.py` | Full-selection totals, pagination, excluded sources, duplicate decisions, transfers, refunds, cash, fees, comparisons, recurrence evidence |
| `test_ingestion.py` | Minimal synthetic PDF extraction, malformed/no-text input, folder error isolation, root boundaries, absent production fallback |
| `test_server.py` | Tool schemas/annotations and a real stdio subprocess session, assignment/undo, date serialization, persistence |

Tests use temporary databases and synthetic inputs without network access.
An actual stdio test is still local: it starts a Python child process rather
than contacting an external model or bank. This suite does not establish real
bank-format coverage, performance guarantees, or validation on every platform.

For a bug, first add a failing behavior test, then make the minimal fix. Do not
weaken assertions, exclude a test, or suppress a check to obtain a passing run.

## Build verification

Before distributing a package, build a wheel and verify it outside editable
source imports. Confirm that it contains the SQL resource, typed marker, and
entry point; initialize a temporary data directory and exercise MCP startup.
The current implementation has been checked this way locally on Windows.

Dependency ranges in `pyproject.toml` are not a lock file. A new installation may
resolve different transitive versions. New dependencies require approval, and
their API use should be verified against the version actually being supported.

## Database changes and compatibility

Schema version one is initialized only for version-zero databases. Editing
`schema.sql` alone will not update existing version-one installations. A schema
change must include an agreed compatibility/migration design and tests on an
existing database. Do not silently reset user data or bump the version without
an upgrade path.

Public tool argument and result changes also require review: connected agents
discover these schemas and may depend on their meaning. Preserve source
provenance, report eligibility, and manual categorization when extending the core.

## Git workflow

Work on a non-main branch. Make small commits for complete, checked behaviors;
use `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, or `chore:` as appropriate.
Review the staged diff and file list before committing, and send milestones to
the authorized working branch. Do not push directly to main.

Keep application code and documentation in English. Do not commit private
statements, databases, `.env`, secrets, caches, or local learning notes.
Development continues without mandatory exercise pauses; explanations should
accompany significant decisions, and questions are reserved for missing input
or required approvals.

## Keeping documentation accurate

When changing behavior, update its algorithm description, tool contract, and
test coverage together. Keep planned capabilities in `PLAN.md` and identify
untested support explicitly. Examples must use synthetic names and amounts.
Do not turn private debugging discoveries or real source lines into documentation.

Review relative links and heading anchors after moving or renaming documents.
MCP method names and defaults come from `FinanceService`; persistent fields
come from `schema.sql`; business decisions come from the relevant domain module.
Prefer those sources over assumptions based on a tool name or the roadmap.
