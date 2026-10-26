-- StockWise SQLite schema (loaded by database.init_db)
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY CHECK (id > 0),
    name        TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    category    TEXT    NOT NULL CHECK (length(trim(category)) > 0),
    price       REAL    NOT NULL CHECK (price >= 0),
    quantity    INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    min_stock   INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    demand      INTEGER CHECK (demand IS NULL OR demand >= 0),
    importance  INTEGER CHECK (importance IS NULL OR importance BETWEEN 1 AND 5),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    type           TEXT    NOT NULL CHECK (type IN ('IN', 'OUT')),
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    balance_after  INTEGER NOT NULL CHECK (balance_after >= 0),
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_tx_product ON inventory_transactions(product_id);
