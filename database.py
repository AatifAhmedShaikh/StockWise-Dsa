"""database.py - SQLite persistence for products and stock transactions.

SQLite is the single source of truth. The C engine is rebuilt from
list_products() whenever the app needs it, so its indexes are never stale.
"""
import os
import sqlite3

from c_bridge import validate_product

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("STOCKWISE_DB", os.path.join(HERE, "stockwise.db"))

with open(os.path.join(HERE, "schema.sql")) as _f:
    SCHEMA = _f.read()

PRODUCT_FIELDS = ("id", "name", "category", "price", "quantity", "min_stock", "demand",
                  "importance")

# (id, name, category, price, quantity, min_stock, demand/month, importance 1-5)
SAMPLE_PRODUCTS = [
    (1042, "USB-C Charging Cable", "Electronics", 9.99, 120, 40, 85, 4),
    (1007, "Wireless Mouse", "Electronics", 18.50, 14, 20, 30, 3),
    (1311, "Bluetooth Speaker", "Electronics", 45.00, 6, 10, 12, 3),
    (1120, "AA Batteries (4-pack)", "Electronics", 4.75, 0, 50, 90, 5),
    (1205, "HDMI Cable 2m", "Electronics", 7.25, 35, 15, 18, 2),
    (2031, "Basmati Rice 5kg", "Grocery", 12.40, 22, 25, 40, 5),
    (2004, "Olive Oil 1L", "Grocery", 8.90, 48, 20, 26, 4),
    (2150, "Whole Wheat Flour 10kg", "Grocery", 11.00, 9, 15, 22, 4),
    (2088, "Sugar 1kg", "Grocery", 1.60, 140, 60, 75, 4),
    (2203, "Green Tea (50 bags)", "Grocery", 3.80, 0, 12, None, 2),
    (3017, "A4 Copy Paper (500 sheets)", "Stationery", 5.50, 60, 30, 45, 4),
    (3002, "Blue Ballpoint Pens (10)", "Stationery", 2.20, 200, 50, 70, 3),
    (3145, "Stapler", "Stationery", 6.80, 4, 8, 5, 2),
    (3099, "Sticky Notes Pack", "Stationery", 3.10, 18, 18, 20, None),
    (3250, "Whiteboard Marker Set", "Stationery", 7.40, 11, 10, 9, 2),
    (4012, "Dish Soap 750ml", "Cleaning", 2.95, 30, 25, 35, 4),
    (4077, "Floor Cleaner 2L", "Cleaning", 5.60, 7, 20, 28, 4),
    (4101, "Paper Towels (6 rolls)", "Cleaning", 6.40, 55, 30, 40, 3),
    (4008, "Disinfectant Spray", "Cleaning", 4.20, 0, 15, 25, 5),
    (5003, "Mineral Water 1.5L", "Beverages", 0.80, 300, 100, 220, 5),
    (5060, "Orange Juice 1L", "Beverages", 2.75, 16, 30, 50, 3),
    (5114, "Instant Coffee 200g", "Beverages", 6.90, 25, 12, 15, 3),
    (5021, "Cola 330ml (12-pack)", "Beverages", 7.80, 40, 20, 35, 2),
    (6005, "Hand Sanitizer 500ml", "Personal Care", 3.40, 12, 25, 30, 4),
    (6040, "Toothpaste 150g", "Personal Care", 2.10, 70, 30, 32, 3),
]


def connect(path=DEFAULT_DB):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn, seed=True):
    """Create tables; seed sample data the first time if requested."""
    conn.executescript(SCHEMA)
    if seed and conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        for row in SAMPLE_PRODUCTS:
            add_product(conn, dict(zip(PRODUCT_FIELDS, row)), note="Opening stock")


def list_products(conn):
    # Ordered by name, so the array handed to C is NOT sorted by id; binary
    # search must use the engine's own id-sorted index.
    rows = conn.execute(f"SELECT {', '.join(PRODUCT_FIELDS)} FROM products "
                        "ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def get_product(conn, product_id):
    row = conn.execute(f"SELECT {', '.join(PRODUCT_FIELDS)} FROM products WHERE id = ?",
                       (product_id,)).fetchone()
    return dict(row) if row else None


def add_product(conn, product, note="Initial stock"):
    """Insert a product; its starting quantity is logged as an IN transaction."""
    p = validate_product(product)
    with conn:  # one transaction: product row + opening history row
        try:
            conn.execute(f"INSERT INTO products ({', '.join(PRODUCT_FIELDS)}) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         tuple(p[f] for f in PRODUCT_FIELDS))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"product id {p['id']} already exists") from exc
        if p["quantity"] > 0:
            conn.execute("INSERT INTO inventory_transactions "
                         "(product_id, type, quantity, balance_after, note) "
                         "VALUES (?, 'IN', ?, ?, ?)",
                         (p["id"], p["quantity"], p["quantity"], note))
    return p


def update_product(conn, product_id, changes):
    """Edit product details. Quantity is changed only via record_transaction()
    so every stock change has a history record."""
    current = get_product(conn, product_id)
    if current is None:
        raise ValueError(f"product {product_id} not found")
    changes = {k: v for k, v in changes.items() if k not in ("id", "quantity")}
    p = validate_product({**current, **changes})
    with conn:
        conn.execute("UPDATE products SET name = ?, category = ?, price = ?, min_stock = ?, "
                     "demand = ?, importance = ?, updated_at = datetime('now', 'localtime') "
                     "WHERE id = ?",
                     (p["name"], p["category"], p["price"], p["min_stock"], p["demand"],
                      p["importance"], product_id))
    return p


def delete_product(conn, product_id):
    with conn:
        deleted = conn.execute("DELETE FROM products WHERE id = ?", (product_id,)).rowcount
    if not deleted:
        raise ValueError(f"product {product_id} not found")


def record_transaction(conn, product_id, tx_type, quantity, note=""):
    """Add (IN) or remove (OUT) stock atomically. Raises ValueError if the
    product is missing, the quantity is invalid, or stock would go negative."""
    if tx_type not in ("IN", "OUT"):
        raise ValueError("transaction type must be IN or OUT")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive whole number")
    delta = quantity if tx_type == "IN" else -quantity
    with conn:
        # The WHERE clause makes the stock check and the update one atomic step.
        cur = conn.execute("UPDATE products SET quantity = quantity + ?, "
                           "updated_at = datetime('now', 'localtime') "
                           "WHERE id = ? AND quantity + ? >= 0", (delta, product_id, delta))
        if cur.rowcount == 0:
            product = get_product(conn, product_id)
            if product is None:
                raise ValueError(f"product {product_id} not found")
            raise ValueError(f"insufficient stock: {product['quantity']} available, "
                             f"{quantity} requested")
        balance = conn.execute("SELECT quantity FROM products WHERE id = ?",
                               (product_id,)).fetchone()[0]
        conn.execute("INSERT INTO inventory_transactions "
                     "(product_id, type, quantity, balance_after, note) VALUES (?, ?, ?, ?, ?)",
                     (product_id, tx_type, quantity, balance, note.strip() or None))
    return balance


def list_transactions(conn, product_id=None, limit=None):
    sql = ("SELECT t.id, t.created_at, t.product_id, p.name AS product_name, t.type, "
           "t.quantity, t.balance_after, t.note FROM inventory_transactions t "
           "JOIN products p ON p.id = t.product_id")
    params = []
    if product_id is not None:
        sql += " WHERE t.product_id = ?"
        params.append(product_id)
    sql += " ORDER BY t.id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
