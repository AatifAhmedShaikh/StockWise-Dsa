"""Python-to-C integration tests. Run from the project root:
    python -m unittest discover -s tests -v
"""
import random
import unittest

from c_bridge import (Engine, StockWiseError, fifo_lots, knapsack, knapsack_greedy,
                      shortest_path, validate_product)


def product(pid, name="Item", price=1.0, quantity=10, min_stock=5, demand=10, importance=3,
            category="Test"):
    return dict(id=pid, name=name, category=category, price=price, quantity=quantity,
                min_stock=min_stock, demand=demand, importance=importance)


SAMPLE = [
    product(50, "Widget", 2.5, 100, 20, 30, 3),
    product(10, "apple juice", 1.0, 0, 10, 60, 5),
    product(40, "Bolt", 0.1, 5, 50, 20, 2),
    product(20, "Cable", 5.0, 8, 8, None, None),
    product(30, "Apple Pie", 3.0, 12, 10, 10, 1),
]


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(SAMPLE)

    def tearDown(self):
        self.engine.close()

    def test_all_searches_find_every_product(self):
        for p in SAMPLE:
            for search in (self.engine.linear_search, self.engine.binary_search,
                           self.engine.hash_search):
                result = search(p["id"])
                self.assertTrue(result["found"])
                self.assertEqual(result["product"]["name"], p["name"])

    def test_missing_product(self):
        for search in (self.engine.linear_search, self.engine.binary_search,
                       self.engine.hash_search):
            result = search(999)
            self.assertFalse(result["found"])
            self.assertIsNone(result["product"])
        self.assertEqual(self.engine.linear_search(999)["comparisons"], len(SAMPLE))

    def test_comparison_counts(self):
        self.assertEqual(self.engine.linear_search(30)["comparisons"], 5)  # last element
        self.assertLessEqual(self.engine.binary_search(30)["comparisons"], 3)
        self.assertEqual(self.engine.hash_search(30)["comparisons"], 1)  # no collisions

    def test_binary_search_large_unsorted_input(self):
        ids = random.Random(1).sample(range(1, 100_000), 2000)
        with Engine([product(i) for i in ids]) as big:
            for i in ids[:200]:
                result = big.binary_search(i)
                self.assertTrue(result["found"])
                self.assertLessEqual(result["comparisons"], 11)  # ceil(log2(2001))
            self.assertFalse(big.binary_search(100_001)["found"])

    def test_name_search(self):
        result = self.engine.search_name("APPLE")
        self.assertEqual({p["id"] for p in result["products"]}, {10, 30})
        self.assertEqual(result["comparisons"], len(SAMPLE))
        self.assertEqual(self.engine.search_name("nothing")["products"], [])
        with self.assertRaises(ValueError):
            self.engine.search_name("   ")


class EmptyAndInvalidTests(unittest.TestCase):
    def test_empty_engine(self):
        with Engine([]) as engine:
            self.assertFalse(engine.hash_search(1)["found"])
            self.assertFalse(engine.binary_search(1)["found"])
            self.assertEqual(engine.sort("price")["products"], [])
            self.assertEqual(engine.restock_ranking()["ranking"], [])

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            Engine([product(1), product(1)])

    def test_invalid_values_rejected(self):
        bad = [dict(price=-1), dict(quantity=-1), dict(price=float("nan")), dict(importance=9),
               dict(name=""), dict(name="x" * 64), dict(id=0), dict(quantity=1.5),
               dict(min_stock=-3), dict(demand=-2)]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_product({**product(1), **change})

    def test_closed_engine(self):
        engine = Engine(SAMPLE)
        engine.close()
        engine.close()  # double close is safe
        with self.assertRaises(StockWiseError):
            engine.hash_search(10)


class SortTests(unittest.TestCase):
    def test_sorts_match_python_sorted(self):
        rng = random.Random(7)
        items = [product(i, f"Item {rng.randint(0, 999)}", round(rng.uniform(0, 50), 2),
                         rng.randint(0, 100)) for i in range(1, 301)]
        keys = {"name": lambda p: p["name"].lower(), "price": lambda p: p["price"],
                "quantity": lambda p: p["quantity"],
                "value": lambda p: p["price"] * p["quantity"]}
        with Engine(items) as engine:
            for key, fn in keys.items():
                for algorithm in ("merge", "insertion"):
                    for desc in (False, True):
                        result = engine.sort(key, algorithm, desc)
                        # Python's sort is stable (also with reverse=True), as are ours.
                        expected = sorted(items, key=fn, reverse=desc)
                        self.assertEqual([p["id"] for p in result["products"]],
                                         [p["id"] for p in expected],
                                         f"{algorithm} {key} desc={desc}")

    def test_merge_beats_insertion_on_large_input(self):
        rng = random.Random(3)
        items = [product(i, price=rng.random()) for i in range(1, 1001)]
        with Engine(items) as engine:
            merge = engine.sort("price", "merge")["comparisons"]
            insertion = engine.sort("price", "insertion")["comparisons"]
        self.assertLess(merge, 1000 * 10)  # n log2 n ~ 9966
        self.assertGreater(insertion, merge * 10)

    def test_invalid_sort_arguments(self):
        with Engine(SAMPLE) as engine, self.assertRaises(ValueError):
            engine.sort("colour")


class HashAndHeapTests(unittest.TestCase):
    def test_collisions_with_tiny_table(self):
        with Engine([product(i) for i in (3, 6, 9, 12, 4)], bucket_count=3) as engine:
            stats = engine.hash_stats()
            self.assertEqual(stats["chain_lengths"], [4, 1, 0])
            self.assertEqual(stats["collisions"], 3)
            self.assertEqual(engine.hash_search(3)["comparisons"], 4)
            self.assertTrue(all(engine.hash_search(i)["found"] for i in (3, 6, 9, 12, 4)))

    def test_restock_ranking_order(self):
        with Engine(SAMPLE) as engine:
            result = engine.restock_ranking()
        ranking = result["ranking"]
        self.assertEqual([p["id"] for p in ranking][0], 10)  # out of stock, top demand
        self.assertEqual({p["id"] for p in ranking}, {10, 40, 20})  # qty <= min only
        scores = [p["score"] for p in ranking]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(ranking[0]["score"], 100.0)
        self.assertIn("Out of stock", ranking[0]["reasons"])
        cable = next(p for p in ranking if p["id"] == 20)
        self.assertIn("Missing demand/importance data (neutral 0.5 used)", cable["reasons"])
        heap = result["heap_array"]
        for i in range(1, len(heap)):
            self.assertGreaterEqual(heap[(i - 1) // 2]["score"], heap[i]["score"])


class NewStructureTests(unittest.TestCase):
    def test_quick_and_heap_sort_order_keys_correctly(self):
        rng = random.Random(11)
        items = [product(i, f"Item {rng.randint(0, 50)}", round(rng.uniform(0, 20), 1),
                         rng.randint(0, 9)) for i in range(1, 401)]
        keys = {"name": lambda p: p["name"].lower(), "price": lambda p: p["price"],
                "quantity": lambda p: p["quantity"]}
        with Engine(items) as engine:
            for key, fn in keys.items():
                for algorithm in ("quick", "heap"):
                    for desc in (False, True):
                        got = [fn(p) for p in engine.sort(key, algorithm, desc)["products"]]
                        # Not stable, so compare the key sequence, not product order.
                        self.assertEqual(got, sorted(got, reverse=desc), (key, algorithm))

    def test_price_range_matches_brute_force(self):
        rng = random.Random(5)
        items = [product(i, price=round(rng.uniform(0, 100), 2)) for i in range(1, 501)]
        with Engine(items) as engine:
            for lo, hi in [(0, 100), (10, 20), (55.5, 55.6), (99, 100), (0, 0)]:
                got = engine.price_range(lo, hi)
                expected = sorted((p for p in items if lo <= p["price"] <= hi),
                                  key=lambda p: (p["price"], p["id"]))
                self.assertEqual([p["id"] for p in got["products"]], [p["id"] for p in expected])
            self.assertLess(engine.price_range(10, 11)["nodes_visited"], 60)
            stats = engine.index_stats()
            self.assertLessEqual(stats["avl_height"], 13)  # 1.44 * log2(502)
            self.assertEqual(len(engine.avl_nodes()), 500)
            with self.assertRaises(ValueError):
                engine.price_range(5, 1)

    def test_prefix_search(self):
        items = [product(1, "USB-C Charging Cable"), product(2, "HDMI Cable 2m"),
                 product(3, "Cable Ties"), product(4, "Charger")]
        with Engine(items) as engine:
            self.assertEqual([p["id"] for p in engine.prefix_search("cab")["products"]],
                             [1, 2, 3])  # keys "cable" < "cable 2m" < "cable ties"
            self.assertEqual({p["id"] for p in engine.prefix_search("CHARG")["products"]}, {1, 4})
            self.assertEqual(engine.prefix_search("usb-c")["products"][0]["id"], 1)
            self.assertEqual(engine.prefix_search("ties")["products"][0]["id"], 3)
            self.assertEqual(engine.prefix_search("zzz")["products"], [])
            with self.assertRaises(ValueError):
                engine.prefix_search("   ")

    def test_knapsack_dp_beats_greedy(self):
        dp = knapsack([1, 3, 4, 5], [1, 4, 5, 7], 7, with_table=True)
        greedy = knapsack_greedy([1, 3, 4, 5], [1, 4, 5, 7], 7)
        self.assertEqual((dp["chosen"], dp["value"]), ([1, 2], 9))
        self.assertEqual((greedy["chosen"], greedy["value"]), ([0, 3], 8))
        self.assertEqual(len(dp["table"]), 5)
        self.assertEqual(dp["table"][-1][-1], 9)

    def test_knapsack_against_brute_force(self):
        rng = random.Random(9)
        for _ in range(20):
            n = rng.randint(1, 8)
            costs = [rng.randint(0, 12) for _ in range(n)]
            values = [round(rng.uniform(0, 50), 1) for _ in range(n)]
            budget = rng.randint(0, 30)
            best = max(sum(values[i] for i in range(n) if mask >> i & 1)
                       for mask in range(1 << n)
                       if sum(costs[i] for i in range(n) if mask >> i & 1) <= budget)
            result = knapsack(costs, values, budget)
            self.assertAlmostEqual(result["value"], best, places=6)
            self.assertLessEqual(sum(costs[i] for i in result["chosen"]), budget)
            self.assertLessEqual(knapsack_greedy(costs, values, budget)["value"], best + 1e-9)

    def test_knapsack_rejects_bad_input(self):
        for args in (([1], [1], -1), ([-1], [1], 5), ([1], [-2], 5), ([1, 2], [1], 5)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                knapsack(*args)
        with self.assertRaises(ValueError):
            knapsack([1] * 100, [1] * 100, 1_000_000)  # DP table too large

    def test_shortest_path(self):
        edges = [(0, 1, 4), (0, 2, 1), (2, 1, 2), (1, 3, 1), (2, 3, 5)]
        r = shortest_path(5, edges, 0, 3)
        self.assertEqual(r["path"], [0, 2, 1, 3])
        self.assertEqual(r["distances"], [0, 3, 1, 4, None])
        self.assertEqual(shortest_path(5, edges, 0, 4)["path"], [])
        with self.assertRaises(ValueError):
            shortest_path(5, [(0, 1, 0)], 0, 1)
        with self.assertRaises(ValueError):
            shortest_path(5, edges, 0, 7)

    def test_sample_network_routes(self):
        import database as db
        n = len(db.LOCATIONS)
        r = shortest_path(n, db.ROUTES, 0, 6)  # airport: via Harbor Depot beats the direct road
        self.assertEqual(r["path"], [0, 5, 6])
        self.assertEqual(r["distances"][6], 24)
        self.assertTrue(all(d is not None for d in r["distances"]))

    def test_fifo_lots(self):
        r = fifo_lots([(10, 1), (5, 2), (-12, 3), (7, 4)])
        self.assertEqual(r["lots"], [{"quantity": 3, "received": 2},
                                     {"quantity": 7, "received": 4}])
        self.assertEqual(fifo_lots([])["lots"], [])
        self.assertEqual(fifo_lots([(5, 1), (-5, 2)])["lots"], [])
        with self.assertRaises(StockWiseError):
            fifo_lots([(2, 1), (-3, 2)])
        with self.assertRaises(ValueError):
            fifo_lots([(0, 1)])


if __name__ == "__main__":
    unittest.main()
