# Architecture

## Data flow

```text
MCP client -> typed service methods -> domain functions -> SQLite
                                      |
PDF path -> allowed-root check -> SHA-256 -> text extraction
                                      |
                             verified bank adapter
                                      |
                         validated StatementInput
                                      |
                     atomic import and source records
```

The bank-adapter slot is intentionally empty until Kaspi and Freedom statement
formats have been inspected. There is no generic parser pretending to support them.
Tests inject a synthetic adapter; production never registers it.

## Money and identity

Money is a signed integer count of tiyn. A purchase of KZT 1,250.00 is stored as
`-125000`. Decimal separator handling is explicit; ambiguous formats are rejected.
Integer arithmetic avoids binary floating-point rounding in report calculations.

File SHA-256 identifies exact byte-for-byte reimports. Transaction identity is
separate: bank IDs are scoped to an account. Without a bank ID, a fingerprint
finds review candidates; it does not prove two purchases are identical.
Occurrences within one statement remain distinct. Confirming duplicates across
statements cannot merge two occurrences from the same statement into one.

## Storage and audit

SQLite stores accounts, statements, transactions, source rows, categories, rules,
review items, relationship links, and decision history. Source rows keep original
descriptions and page numbers; statement hashes locate archived PDFs.
The database schema version is checked on startup. Unknown versions fail rather
than being silently modified.

Each operation opens and closes its own connection. Write workflows that inspect
and modify shared state use a transaction. Imports roll back completely on failure.
Batch folder imports report file errors independently. Archived bytes may remain
unreferenced if a database import fails after archival; they are not transactions.

Category assignments, rule changes, and links record before/after snapshots in
the same transaction. Undo checks current state before restoring snapshots.
Later edits or foreign-key dependencies prevent an unsafe undo.
Importing source facts is not itself reversible through the decision-history tool.

## Categorization

Categories are agent-created records, with one reserved system category:
`Uncategorized`. Merchant normalization changes only case and whitespace.
It preserves digits and punctuation to avoid merging unrelated companies.

Rules match exact normalized merchants, optionally constrained by account and
debit/credit direction. Manual assignments win. Different matching categories
create a conflict; rule order never decides the category.

Batch previews include a hash of the current selection and requested decision.
The apply call recomputes it within a write transaction. A changed selection or
decision invalidates the token. Tokens establish a reviewed batch, not user identity.

## Reports

Search includes all stored operations and eligibility flags. Ordinary reports
exclude confirmed duplicate copies, unresolved duplicate candidates, and operations
without a source that passes available reconciliation checks. Missing checks are
reported as unavailable, not passed.

Confirmed internal transfers do not count as income or spending. Automatic linking
requires unique same-day opposite amounts on two owned accounts and reciprocal
account references. Amount/date coincidence alone is only a review candidate.
Fees remain expenses; cash withdrawals are separate because subsequent cash use
is unknown. Confirmed refunds reduce the original category in the refund period.

Reports calculate over all matching eligible rows, not the visible search page.
They return source coverage and excluded counts. Coverage describes imported data;
it cannot establish that the user provided every account and statement.

## Boundaries

The server runs locally over stdio, does not use the network, and does not call a
model. The MCP SDK's transport dependencies do not imply network use by this app.
The agent chooses interpretations and recommendations. Returned source text is
untrusted data, never instructions.

The application restricts its import tools to configured folders. This restriction
does not sandbox the host agent or prevent it from using other filesystem tools.
The application does not encrypt storage or control data retained by the agent host.
