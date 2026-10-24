PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY, bank TEXT NOT NULL, reference TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (currency = 'KZT'),
    UNIQUE(bank, reference)
);
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    start TEXT NOT NULL, end TEXT NOT NULL, parser_version TEXT NOT NULL,
    reconciliation TEXT NOT NULL CHECK (reconciliation IN ('passed','failed','unavailable')),
    opening_tiyn INTEGER, closing_tiyn INTEGER, debits_tiyn INTEGER, credits_tiyn INTEGER
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE
);
INSERT OR IGNORE INTO categories(id, name) VALUES (1, 'Uncategorized');
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
    posted_on TEXT NOT NULL, amount_tiyn INTEGER NOT NULL CHECK(amount_tiyn != 0),
    description TEXT NOT NULL, merchant TEXT NOT NULL, kind TEXT NOT NULL,
    bank_id TEXT, counterparty_account TEXT, fingerprint TEXT NOT NULL,
    category_id INTEGER NOT NULL DEFAULT 1 REFERENCES categories(id),
    assignment TEXT NOT NULL DEFAULT 'none' CHECK(assignment IN ('none','rule','manual')),
    rule_id INTEGER REFERENCES rules(id),
    UNIQUE(account_id, bank_id)
);
CREATE TABLE IF NOT EXISTS sources (
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    ordinal INTEGER NOT NULL, transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    page INTEGER NOT NULL CHECK(page > 0), raw_text TEXT NOT NULL,
    PRIMARY KEY(statement_id, ordinal), UNIQUE(statement_id, transaction_id)
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY, merchant TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    account_id INTEGER REFERENCES accounts(id), direction TEXT CHECK(direction IN ('debit','credit')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    details TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0 CHECK(resolved IN (0,1)),
    UNIQUE(kind, transaction_id)
);
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('transfer','refund','duplicate')),
    left_id INTEGER NOT NULL REFERENCES transactions(id),
    right_id INTEGER NOT NULL REFERENCES transactions(id),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), CHECK(left_id != right_id)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY, action TEXT NOT NULL, patches TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    undone INTEGER NOT NULL DEFAULT 0 CHECK(undone IN (0,1))
);
CREATE INDEX IF NOT EXISTS transaction_period ON transactions(posted_on, account_id);
CREATE INDEX IF NOT EXISTS transaction_fingerprint ON transactions(account_id, fingerprint);
CREATE INDEX IF NOT EXISTS source_transaction ON sources(transaction_id);
PRAGMA user_version = 1;
