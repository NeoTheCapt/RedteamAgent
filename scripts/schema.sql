-- schema.sql — Case collection pipeline database schema
-- Usage: sqlite3 cases.db < scripts/schema.sql

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Request identity
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    url_path TEXT NOT NULL,

    -- Structured parameters (pre-extracted by producers)
    query_params TEXT,
    body_params TEXT,
    path_params TEXT,
    cookie_params TEXT,

    -- Request content
    headers TEXT,
    body TEXT,
    content_type TEXT,
    content_length INTEGER,

    -- Response summary
    response_status INTEGER,
    response_headers TEXT,
    response_size INTEGER,
    response_snippet TEXT,

    -- Classification and routing
    type TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL,

    -- State management
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_agent TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    consumed_at TEXT,

    -- Dedup signature: hash of sorted query/body param KEYS (not values)
    params_key_sig TEXT,

    UNIQUE(method, url_path, params_key_sig)
);

CREATE INDEX IF NOT EXISTS idx_consume ON cases(status, type);
CREATE INDEX IF NOT EXISTS idx_source ON cases(source);
CREATE INDEX IF NOT EXISTS idx_created ON cases(created_at);
