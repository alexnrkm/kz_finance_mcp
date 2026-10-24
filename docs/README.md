# Engineering documentation

Finance MCP KZ turns local bank-statement data into structured tools that an AI
agent can query. The server stores and calculates facts; the agent interprets
them and talks to the user.

This documentation describes version 0.1.0 as implemented in this repository.
The source of truth for storage is [schema.sql](../src/finance_mcp/schema.sql),
and the source of truth for tool arguments is
[FinanceService](../src/finance_mcp/service.py). Generated MCP schemas expose
those method signatures to clients.

## Start here

| Document | Questions it answers |
| --- | --- |
| [Project README](../README.md) | What works today? How do I install and launch it? |
| [Architecture](../ARCHITECTURE.md) | What are the components and how do requests move through them? |
| [Data model](data-model.md) | What does each table and field represent? How are records related? |
| [Algorithms and accounting](algorithms.md) | How do deduplication, categories, transfers, and calculations work? |
| [MCP tool reference](mcp-tools.md) | What can an agent call, with which arguments and results? |
| [Operations](operations.md) | Where is data stored? How do I back it up and troubleshoot failures? |
| [Development guide](development.md) | Where should I change code? How do I add a bank parser and verify it? |
| [Implementation plan](../PLAN.md) | What is completed and what remains? |

For a first reading, follow the table from Architecture through Algorithms,
then inspect the tool examples. When changing code, use the module map in
Architecture and the test map in the Development guide.

## The problem being solved

A user may have several accounts at different banks, each with a separate PDF
statement. Asking an agent to read every PDF repeatedly wastes context and can
produce inconsistent calculations. Overlapping statements can also count the
same operation twice, and moving money between owned accounts can look like
new spending.

The project provides a persistent local ledger and deterministic rules so the
agent can ask focused questions: category totals, the purchases behind a change,
or the unresolved operations that need attention. Every imported operation keeps
references to the statement and page it came from.

## Responsibility boundary

| Server | Connected agent |
| --- | --- |
| Extract and validate supported statement formats | Ask the user about ambiguous information |
| Store source records and prevent exact reimports | Decide which user-defined category fits a merchant |
| Apply saved matching rules consistently | Create categories and rules through tools |
| Calculate totals and period differences | Explain the meaning of those differences |
| Produce evidence for review candidates | Judge whether a candidate matters to the user |
| Preserve decision history | Formulate spending recommendations |

There is no model inside the server. It neither searches the web nor invents a
category vocabulary. An agent may use its own search tools, but that is outside
this application.

## Current release boundary

The core, SQLite schema, PDF text extraction, and 17-tool stdio interface exist.
They are tested with synthetic transactions and a test-only PDF adapter.
**Production currently registers no bank adapters.** Kaspi and Freedom are
target banks, not a claim that their real statements can already be imported.

The implemented domain supports KZT only and one data owner per data directory.
There is no web UI, background folder watcher, Telegram bot, OCR, remote URL
fetching, currency conversion, or multi-user authorization.

## Terminology

| Term | Meaning in this project |
| --- | --- |
| MCP client / host | The agent application that starts the server and invokes tools |
| stdio | A local child-process connection using standard input and output |
| Adapter / parser | A bank-format implementation that produces validated input models |
| Statement | One imported PDF and its account, period, and control totals |
| Transaction | A normalized ledger operation, distinct from its appearances in PDFs |
| Source | One occurrence of an operation in a statement, including page and text |
| Tiyn | One hundredth of a tenge; the integer storage unit |
| Fingerprint | A hash of normalized transaction fields used to find possible matches |
| Canonical transaction | The operation retained for reporting when a duplicate is confirmed |
| Reconciliation | Comparing parsed operations with available statement balances or totals |
| Eligibility | Whether an operation participates in ordinary report calculations |
| Preview token | A checksum binding a batch decision to the data that was previewed |
| Change | An audited decision with before/after snapshots that may be undone |
