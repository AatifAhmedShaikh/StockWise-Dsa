"""Tests for the zero-dependency web UI: data layer and HTTP server.
Run from the project root:  python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import database as db
from webui import api
from webui.server import make_server


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(os.path.join(self.tmp.name, "t.db"))
        db.init_db(self.conn)  # 25 sample products with history

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_dashboard_totals_match_the_database(self):
        d = api.dashboard(self.conn)
        products = db.list_products(self.conn)
        self.assertEqual(d["kpis"]["products"], len(products))
        self.assertEqual(d["kpis"]["units"], sum(p["quantity"] for p in products))
        self.assertEqual(d["level"][-1]["units"], d["kpis"]["units"])  # history ends at stock on hand
        self.assertEqual(len(d["movement"]), 30)
        self.assertEqual(d["by_category"], sorted(d["by_category"], key=lambda r: -r["value"]))
        self.assertEqual(d["attention"][0]["status"], "Out of stock")

    def test_catalog_search_uses_each_c_structure(self):
        by_id = api.products_view(self.conn, "1042")
        self.assertEqual([p["id"] for p in by_id["products"]], [1042])
        self.assertIn("Hash table", by_id["notes"][0])
        prefix = api.products_view(self.conn, "cab")
        self.assertTrue(all("cable" in p["name"].lower() for p in prefix["products"]))
        self.assertIn("Trie", prefix["notes"][0])
        inner = api.products_view(self.conn, "harging")  # inside "Charging": trie finds nothing
        self.assertIn("linear substring", inner["notes"][0])
        self.assertTrue(inner["products"])
        ranged = api.products_view(self.conn, "", None, 5, 10)
        self.assertTrue(all(5 <= p["price"] <= 10 for p in ranged["products"]))
        self.assertIn("AVL", ranged["notes"][0])
        self.assertEqual(api.products_view(self.conn, "99999999999")["products"], [])  # > int32 id

    def test_add_edit_delete_and_validation(self):
        body = {"id": 7001, "name": "Test Item", "category": "Test", "price": "2.5",
                "quantity": 3, "min_stock": 5, "demand": "", "importance": "4"}
        added = api.add_product(self.conn, body)["product"]
        self.assertEqual((added["price"], added["demand"], added["importance"]), (2.5, None, 4))
        with self.assertRaisesRegex(ValueError, "already exists"):
            api.add_product(self.conn, body)
        for bad in ({"price": -1}, {"quantity": -2}, {"name": ""}, {"importance": 9}, {"id": "x"},
                    {"quantity": 1.5}, {"price": float("nan")}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                api.add_product(self.conn, {**body, "id": 7002, **bad})
        api.update_product(self.conn, 7001, dict(body, name="Renamed", quantity=999))
        row = db.get_product(self.conn, 7001)
        self.assertEqual((row["name"], row["quantity"]), ("Renamed", 3))  # quantity is not editable
        api.delete_product(self.conn, 7001)
        self.assertIsNone(db.get_product(self.conn, 7001))

    def test_transactions_never_go_negative(self):
        with self.assertRaisesRegex(ValueError, "insufficient stock"):
            api.record_transaction(self.conn, {"product_id": 1042, "type": "OUT", "quantity": 10**6})
        before = db.get_product(self.conn, 1042)["quantity"]
        r = api.record_transaction(self.conn, {"product_id": 1042, "type": "IN", "quantity": 5, "note": "x"})
        self.assertEqual(r["balance"], before + 5)
        view = api.transactions_view(self.conn, 1042)
        self.assertEqual(sum(l["quantity"] for l in view["lots"]["lots"]), before + 5)  # C FIFO queue
        self.assertTrue(api.transactions_view(self.conn)["aging"])

    def test_restock_plan_dp_is_never_worse_than_greedy(self):
        view = api.restock_view(self.conn)
        for budget in (0, 100, 700, 1500, view["total_cost"]):
            plan = api.restock_plan(self.conn, budget)
            self.assertGreaterEqual(plan["dp"]["value"] + 1e-9, plan["greedy"]["value"])
            self.assertLessEqual(plan["dp"]["cost"], budget)
        with self.assertRaises(ValueError):
            api.restock_plan(self.conn, -5)
        before = len(db.list_transactions(self.conn))
        out = api.restock_order(self.conn, 1500)
        self.assertEqual(len(db.list_transactions(self.conn)), before + out["ordered"])

    def test_routes_search_sort_and_lab(self):
        self.assertEqual(api.routes_view(0, 6)["path"], [0, 5, 6])  # via Harbor Depot, 24 km
        self.assertEqual(api.search_view(self.conn, {"method": "binary", "id": "1042"})["products"][0]["id"], 1042)
        self.assertEqual(api.search_view(self.conn, {"method": "hash", "id": "5"})["products"], [])
        with self.assertRaises(ValueError):
            api.search_view(self.conn, {"method": "nope"})
        for algo in ("merge", "insertion", "quick", "heap"):
            names = [p["name"].lower() for p in api.sort_view(self.conn, "name", algo, False)["products"]]
            self.assertEqual(names, sorted(names))
        lab = api.lab_sort(self.conn, {"source": "generated", "n": "300", "key": "price"})
        self.assertTrue(lab["same_order"])
        hashed = api.lab_hash(self.conn, {"source": "generated", "n": "100", "buckets": "5"})
        self.assertGreater(hashed["longest_chain"], 10)  # 100 items in 5 buckets must collide
        avl = api.lab_avl(self.conn, {"source": "generated", "n": "500"})
        self.assertLessEqual(avl["stats"]["avl_height"], 13)
        self.assertLessEqual(len(avl["tree"]), 31)  # trimmed to 5 levels
        self.assertTrue(api.lab_trie(self.conn, {"prefix": "s"})["suggestions"])
        ks = api.lab_knapsack({"items": [{"cost": 1, "value": 1}, {"cost": 3, "value": 4},
                                         {"cost": 4, "value": 5}, {"cost": 5, "value": 7}], "budget": 7})
        self.assertEqual((ks["dp"]["value"], ks["greedy"]["value"]), (9.0, 8.0))
        self.assertTrue(all(c["Result"] == "Passed" for c in api.lab_edge()["cases"]))
        with self.assertRaises(ValueError):
            api.lab_search(self.conn, {"n": "999999", "source": "generated"})

    def test_empty_inventory_pages_work(self):
        for p in db.list_products(self.conn):
            db.delete_product(self.conn, p["id"])
        self.assertEqual(api.dashboard(self.conn)["kpis"]["products"], 0)
        self.assertEqual(api.products_view(self.conn)["price_ceiling"], 1.0)  # slider stays valid
        self.assertEqual(api.restock_view(self.conn)["items"], [])
        self.assertEqual(api.restock_plan(self.conn, 10)["items"], [])
        self.assertEqual(api.lab_avl(self.conn, {})["tree"], [])
        self.assertEqual(api.lab_heap(self.conn, {})["count"], 0)

    def test_zero_prices_keep_the_price_slider_valid(self):
        for p in db.list_products(self.conn):
            db.delete_product(self.conn, p["id"])
        db.add_product(self.conn, {"id": 1, "name": "Free", "category": "x", "price": 0,
                                   "quantity": 1, "min_stock": 1, "demand": None, "importance": None})
        self.assertEqual(api.products_view(self.conn)["price_ceiling"], 1.0)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = make_server(os.path.join(cls.tmp.name, "s.db"), 0)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.conn.close()
        cls.tmp.cleanup()

    def call(self, path, method="GET", body=None, headers=None):
        hdrs = {"Content-Type": "application/json"} if method != "GET" else {}
        hdrs.update(headers or {})
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type"), e.read()

    def test_pages_and_static_files_have_correct_types(self):
        status, ctype, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"StockWise", body)
        for path, expected in (("/static/app.js", "javascript"), ("/static/style.css", "css"),
                               ("/assets/logo.svg", "svg+xml"), ("/assets/categories/grocery.svg", "svg+xml")):
            status, ctype, _ = self.call(path)
            self.assertEqual(status, 200, path)
            self.assertIn(expected, ctype, path)

    def test_every_script_the_page_loads_exists(self):
        import re
        html = self.call("/")[2].decode()
        for src in re.findall(r'<script src="([^"]+)"', html):
            self.assertEqual(self.call(src)[0], 200, src)

    def test_api_roundtrip(self):
        status, _, body = self.call("/api/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["kpis"]["products"], 25)
        status, _, body = self.call("/api/products", "POST", {"id": 8801, "name": "HTTP Item", "category": "T",
                                                              "price": 1, "quantity": 2, "min_stock": 1})
        self.assertEqual(status, 200)
        status, _, body = self.call("/api/transactions", "POST", {"product_id": 8801, "type": "OUT", "quantity": 99})
        self.assertEqual(status, 400)
        self.assertIn("insufficient stock", json.loads(body)["error"])
        self.assertEqual(self.call("/api/products/8801", "DELETE", {})[0], 200)
        self.assertEqual(self.call("/api/products/8801", "DELETE", {})[0], 400)  # already gone

    def test_bad_requests_get_clean_errors(self):
        self.assertEqual(self.call("/api/nope")[0], 404)
        self.assertEqual(self.call("/api/dashboard", "POST", {})[0], 405)
        self.assertEqual(self.call("/api/sort?key=zzz")[0], 400)
        self.assertEqual(self.call("/api/lab/avl?n=abc&source=generated")[0], 400)
        status, ctype, body = self.call("/api/products", "POST", {"id": 1})
        self.assertEqual(status, 400)
        self.assertIn("application/json", ctype)

    def test_security_checks(self):
        self.assertEqual(self.call("/api/dashboard", headers={"Host": "evil.example"})[0], 403)  # DNS rebinding
        self.assertEqual(self.call("/api/products", "POST", None, {"Content-Type": "text/plain"})[0], 415)
        for path in ("/static/..%2f..%2fdatabase.py", "/static/%2e%2e/database.py", "/assets/../database.py"):
            self.assertEqual(self.call(path)[0], 404, path)
        self.assertEqual(self.call("/api/products", "POST", {"x": 1}, {"Content-Length": "9999999"})[0] in (413, 400), True)


if __name__ == "__main__":
    unittest.main()
