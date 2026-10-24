# Running, storage, and troubleshooting

Use the [project README](../README.md#installation) for installation and agent
registration commands. This guide explains what happens after installation and
how to operate the current implementation.

## Process model

The agent host launches one Python process and exchanges MCP messages over
stdin/stdout. The server opens no listening HTTP port and needs no API key.
Dependencies may be downloaded during installation; normal application calls
do not make network requests.

Running the following in a terminal normally appears to wait:

```powershell
.\.venv\Scripts\python.exe -m finance_mcp
```

That is expected: it is waiting for protocol messages, not a terminal command.
Use `Ctrl+C` to stop a manually launched process. When connected through an
agent host, let that host start and stop the process. Do not print debugging
messages to stdout; they would corrupt the protocol.

## Configuration

| Option | Default | Effect |
| --- | --- | --- |
| `--data-dir PATH` | Environment override or OS user-data location | Selects database, inbox, and archive directory |
| `--import-root PATH` | `<data-dir>/inbox` | Allows import from this root; may be repeated |
| `--check` | Off | Initialize local storage, print readiness JSON, and exit |
| `--version` | Off | Print installed package version and exit |
| `FINANCE_MCP_DATA_DIR` | Unset | Supplies the default data directory if the CLI option is absent |

An explicit `--data-dir` takes precedence over `FINANCE_MCP_DATA_DIR`. If neither
is set, the OS default is used:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%/finance-mcp-kz`; fallback: `~/AppData/Local/finance-mcp-kz` |
| macOS | `~/Library/Application Support/finance-mcp-kz` |
| Linux/other | `$XDG_DATA_HOME/finance-mcp-kz`; fallback: `~/.local/share/finance-mcp-kz` |

Supplying import roots replaces the default inbox root; it does not append to it
implicitly. The inbox directory is still created. Include it explicitly if both
inbox and another folder should be importable. Use absolute configuration paths
so startup behavior does not depend on the agent host's working directory.

The application does not read a `.env` file. A separate data directory creates
a separate owner context; there is no user switch within one database.

## Readiness diagnostic

```powershell
.\.venv\Scripts\python.exe -m finance_mcp --check --data-dir "C:/finance-data"
```

This creates the data directory, inbox, and database if necessary. It reports
resolved paths and registered parsers. It does not import PDFs or establish that
bank adapters are available; currently `verified_parsers` is empty. A successful
diagnostic proves startup works, not that the bank-import milestone is complete.

## Runtime files

```text
<data-dir>/
  finance.sqlite3              normalized facts and decisions
  inbox/                      default import root
  statements/
    <sha256>.pdf              archived original bytes, when import reaches archival
```

Original files in the import folder are not moved or deleted. Successfully
archived sources allow provenance after the user moves an original input file.
Moving or removing the archive separately can break returned source paths.
The archive may also contain unreferenced files from failed database imports.
There is no automated cleanup, retention policy, or import-delete tool.

`data/` in the repository is an ignored workspace location for private samples
and development artifacts. It is not the installed application's default data
directory unless selected with `--data-dir`.

## Backups and restoration

For a straightforward consistent backup:

1. Stop every server process using the data directory, including agent-hosted ones.
2. Copy the entire directory to a protected backup location, including the
   SQLite file, archived PDFs, and any SQLite sidecar files present.
3. Keep the original copy unchanged until the backup has been checked.
4. Restore to a separate directory while the server is stopped, then start with
   `--data-dir` pointing to that directory.
5. Check readiness, list statements, and inspect representative source paths.

Copying just the database preserves ledger records but not archived PDF bytes.
Copying just PDFs loses categories, rules, reviews, and history. No backup or
restore MCP tool currently exists. For online backups, a separately designed
SQLite backup procedure would be needed; ordinary concurrent file copying is
not the documented workflow.

## Privacy and trust boundaries

- The server stores raw source descriptions, account references, categories,
  and decision snapshots locally. They can contain personal financial data.
- Application storage has no encryption or account authentication. Protect the
  operating-system user account and the data/backup directories accordingly.
- The import-root guard resolves paths and symlinks before checking boundaries.
  It applies to this server's import tools, not to all capabilities of the host
  agent or operating system. It is not a general process sandbox.
- Tool outputs, including raw descriptions and local paths, are visible to the
  connected agent. The host's data handling determines what leaves the machine.
- Treat bank-document text as untrusted data. The server instructions state that
  the agent must not follow instructions embedded in source text.
- Do not assume all third-party exception output is redacted. Review terminal
  diagnostics before sharing them; avoid including real source content in issues.

`.gitignore` prevents normal accidental additions of PDFs, databases, private
`data/`, secrets, and local learning notes. It is not encryption, and forced
Git additions can bypass it. Previously tracked files are not untracked merely
by adding an ignore pattern.

## Troubleshooting

| Symptom | Meaning and next step |
| --- | --- |
| Terminal waits without output | Normal stdio behavior; use `--check` for diagnostics or launch through the MCP host |
| `Path is outside the configured import roots` | Move/copy the intended input into an allowed root, or configure that root explicitly |
| Cannot access PDF/folder | Check the path exists, permissions, and whether a relative path resolved against the first root |
| Unsupported or ambiguous format | No unique verified parser matched; bank samples/adapters are required |
| PDF has no text layer | Scanned/image-only input; OCR is outside current scope |
| Unable to read PDF | Damaged, encrypted, or otherwise unsupported PDF; page-limit failures also currently surface through this generic message |
| Bank transaction ID has conflicting data | A reused bank ID disagreed with stored identity fields; inspect source data/parser behavior, do not force overwrite |
| Preview is stale or invalid | Relevant data changed or arguments differ; request another preview |
| Relationship rejected | Verify debit/credit order, kinds, amounts, dates, existing links, and duplicate multiplicity |
| Undo blocked by later changes | Inspect detailed history and reverse dependent decisions first |
| Unsupported database version | This application version cannot interpret the stored schema; preserve data and use a compatible release |
| SQLite locked/busy | Another writer holds a lock beyond the timeout; reduce simultaneous writers and inspect the other process |

### A report looks too small

1. Confirm date, account, bank, and **signed** amount filters.
2. Inspect `coverage`; statements may be missing or have failed reconciliation.
3. Inspect `excluded_transactions` and search eligibility flags.
4. Resolve pending duplicate reviews; candidate exclusion can temporarily hide
   a real purchase from totals.
5. Check confirmed transfers, separate cash withdrawals, and linked refunds.

### A category looks wrong

1. Inspect `get_transaction`: stored category, assignment source, and `rule_id`.
2. Check the effective category if this is a linked refund.
3. List active rules and exact normalized merchant names.
4. Remember that manual assignments win and disabling a rule does not immediately
   change old operations.
5. Preview a manual assignment or global rule reapplication before applying it.

## Current operational limits

Inputs are bounded to 20 MiB per PDF, 200 pages, and 200 selected PDFs per folder
call. These bounds are not a hard memory or execution-time sandbox: page discovery
and text extraction still use the PDF library in the server process.

Ordinary paginated listings cap page size at 200. Reports, rule-application
previews, category lists, and some evidence arrays are not globally paginated.
Reports materialize matching operations in memory. There are no performance
benchmarks, background jobs, cancellation protocol beyond the MCP SDK's behavior,
telemetry service, HTTP authentication, or multi-user isolation inside one data
directory. Windows/Python 3.14 is validated locally; other platforms remain pending.
