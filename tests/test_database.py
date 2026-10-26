"""SQLite persistence tests. Run from the project root:
    python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

import database as db
from datetime import datetime

from c_bridge import Engine, fifo_lots


def item(pid=1, **kw):
    return {"id": pid, "name": "Test Item", "category": "Test", "price": 2.0, "quantity": 10,
            "min_stock": 5, "demand": 8, "importance": 3, **kw}


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.db")
        self.conn = db.connect(self.path)
        db.init_db(self.conn, seed=False)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_seed_data_is_valid_and_loads_into_c(self):
        db.init_db(self.conn, seed=True)
        products = db.list_products(self.conn)
        self.assertEqual(len(products), len(db.SAMPLE_PRODUCTS))
        with Engine(products) as engine:
            self.assertTrue(engine.hash_search(1042)["found"])
            self.assertGreater(len(engine.restock_ranking()["ranking"]), 0)
        db.init_db(self.conn, seed=True)  # seeding twice must not duplicate
        self.assertEqual(len(db.list_products(self.conn)), len(db.SAMPLE_PRODUCTS))

    def test_add_logs_opening_transaction(self):
        db.add_product(self.conn, item())
        tx = db.list_transactions(self.conn, product_id=1)
        self.assertEqual([(t["type"], t["quantity"], t["balance_after"]) for t in tx],
                         [("IN", 10, 10)])

    def test_duplicate_id_rejected(self):
        db.add_product(self.conn, item())
        with self.assertRaises(ValueError):
            db.add_product(self.conn, item(name="Other"))

    def test_invalid_price_and_quantity_rejected(self):
        for bad in (dict(price=-1.0), dict(quantity=-4), dict(importance=0)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                db.add_product(self.conn, item(**bad))
        self.assertEqual(db.list_products(self.conn), [])

    def test_stock_in_and_out(self):
        db.add_product(self.conn, item())
        self.assertEqual(db.record_transaction(self.conn, 1, "IN", 5, "delivery"), 15)
        self.assertEqual(db.record_transaction(self.conn, 1, "OUT", 15), 0)
        self.assertEqual(db.get_product(self.conn, 1)["quantity"], 0)
        self.assertEqual(len(db.list_transactions(self.conn, product_id=1)), 3)

    def test_insufficient_stock_changes_nothing(self):
        db.add_product(self.conn, item())
        with self.assertRaisesRegex(ValueError, "insufficient stock"):
            db.record_transaction(self.conn, 1, "OUT", 11)
        self.assertEqual(db.get_product(self.conn, 1)["quantity"], 10)
        self.assertEqual(len(db.list_transactions(self.conn, product_id=1)), 1)

    def test_invalid_transactions(self):
        db.add_product(self.conn, item())
        for args in ((1, "OUT", 0), (1, "IN", -3), (1, "IN", 2.5), (1, "MOVE", 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                db.record_transaction(self.conn, *args)
        with self.assertRaisesRegex(ValueError, "not found"):
            db.record_transaction(self.conn, 404, "IN", 1)

    def test_update_does_not_touch_quantity(self):
        db.add_product(self.conn, item())
        db.update_product(self.conn, 1, {"name": "Renamed", "price": 3.5, "quantity": 999})
        p = db.get_product(self.conn, 1)
        self.assertEqual((p["name"], p["price"], p["quantity"]), ("Renamed", 3.5, 10))
        with self.assertRaises(ValueError):
            db.update_product(self.conn, 1, {"price": -2})

    def test_delete_cascades_history(self):
        db.add_product(self.conn, item())
        db.delete_product(self.conn, 1)
        self.assertIsNone(db.get_product(self.conn, 1))
        self.assertEqual(db.list_transactions(self.conn), [])
        with self.assertRaises(ValueError):
            db.delete_product(self.conn, 1)

    def test_persists_across_connections(self):
        db.add_product(self.conn, item(demand=None, importance=None))
        db.record_transaction(self.conn, 1, "OUT", 4)
        self.conn.close()
        self.conn = db.connect(self.path)
        p = db.get_product(self.conn, 1)
        self.assertEqual((p["quantity"], p["demand"], p["importance"]), (6, None, None))

    def test_engine_rebuilt_after_change_is_not_stale(self):
        db.add_product(self.conn, item(quantity=10, min_stock=5))
        with Engine(db.list_products(self.conn)) as engine:
            self.assertEqual(engine.restock_ranking()["ranking"], [])
        db.record_transaction(self.conn, 1, "OUT", 8)
        with Engine(db.list_products(self.conn)) as engine:
            self.assertEqual([p["id"] for p in engine.restock_ranking()["ranking"]], [1])
            self.assertEqual(engine.hash_search(1)["product"]["quantity"], 2)


    def test_seeded_history_ends_at_listed_quantities(self):
        db.init_db(self.conn, seed=True)
        listed = {row[0]: row[4] for row in db.SAMPLE_PRODUCTS}
        for p in db.list_products(self.conn):
            self.assertEqual(p["quantity"], listed[p["id"]])
            history = db.list_transactions(self.conn, product_id=p["id"])
            self.assertGreater(len(history), 1)
            history.sort(key=lambda t: (t["created_at"], t["id"]))
            balance = 0
            for t in history:  # every balance_after must match a replay of the moves
                balance += t["quantity"] if t["type"] == "IN" else -t["quantity"]
                self.assertEqual(t["balance_after"], balance)
                self.assertGreaterEqual(balance, 0)
            # The C FIFO queue must account for exactly the units on hand.
            moves = [(t["quantity"] if t["type"] == "IN" else -t["quantity"],
                      int(datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M:%S").timestamp()))
                     for t in history]
            self.assertEqual(sum(lot["quantity"] for lot in fifo_lots(moves)["lots"]),
                             p["quantity"])

    def test_backdated_transaction(self):
        db.add_product(self.conn, item(), created_at="2026-01-01 09:00:00")
        db.record_transaction(self.conn, 1, "OUT", 2, created_at="2026-01-05 10:00:00")
        db.record_transaction(self.conn, 1, "IN", 1)  # now
        times = [t["created_at"] for t in db.list_transactions(self.conn, product_id=1)]
        self.assertEqual(times[1:], ["2026-01-05 10:00:00", "2026-01-01 09:00:00"])
        self.assertEqual(times, sorted(times, reverse=True))


if __name__ == "__main__":
    unittest.main()
