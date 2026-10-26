"""c_bridge.py - ctypes wrapper around the StockWise C engine.

Every search, sort, hash lookup and heap operation here runs in C. Python only
validates input, packs it into C structs, and turns C results back into dicts.

Memory: the C engine copies the product array and owns its memory. `Engine`
frees it in close() (also called by `with` and by __del__). All output buffers
are Python-owned ctypes arrays, so nothing allocated by C leaks into Python.
"""
import ctypes
import math
import os
import struct

import build_c

EXPECTED_API_VERSION = 2  # must equal SW_API_VERSION in backend/inventory_types.h

NAME_LEN, CATEGORY_LEN, MISSING = 64, 32, -1
INT32_MAX = 2**31 - 1

SORT_KEYS = {"id": 0, "name": 1, "price": 2, "quantity": 3, "value": 4}
ALGORITHMS = {"merge": 0, "insertion": 1, "quick": 2, "heap": 3}
STABLE_ALGORITHMS = {"merge", "insertion"}
MAX_KNAPSACK_CELLS = 20_000_000

ERR_NOT_FOUND = -5
REASONS = {
    1: "Out of stock",
    2: "Below minimum stock",
    4: "At minimum stock",
    8: "High demand",
    16: "High importance",
    32: "Missing demand/importance data (neutral 0.5 used)",
}


class StockWiseError(Exception):
    """Raised when the C library is missing or a C call reports an error."""


class CProduct(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_int32),
        ("name", ctypes.c_char * NAME_LEN),
        ("category", ctypes.c_char * CATEGORY_LEN),
        ("price", ctypes.c_double),
        ("quantity", ctypes.c_int32),
        ("min_stock", ctypes.c_int32),
        ("demand", ctypes.c_int32),
        ("importance", ctypes.c_int32),
    ]


class CSearchResult(ctypes.Structure):
    _fields_ = [("index", ctypes.c_int32), ("found", ctypes.c_int32),
                ("comparisons", ctypes.c_int64)]


class COpStats(ctypes.Structure):
    _fields_ = [("comparisons", ctypes.c_int64), ("moves", ctypes.c_int64)]


class CRestockItem(ctypes.Structure):
    _fields_ = [
        ("product_index", ctypes.c_int32),
        ("product_id", ctypes.c_int32),
        ("score", ctypes.c_double),
        ("shortage_score", ctypes.c_double),
        ("demand_score", ctypes.c_double),
        ("importance_score", ctypes.c_double),
        ("suggested_qty", ctypes.c_int32),
        ("reasons", ctypes.c_uint32),
    ]


class CHashStats(ctypes.Structure):
    _fields_ = [
        ("bucket_count", ctypes.c_int32),
        ("item_count", ctypes.c_int32),
        ("used_buckets", ctypes.c_int32),
        ("collisions", ctypes.c_int32),
        ("longest_chain", ctypes.c_int32),
        ("load_factor", ctypes.c_double),
    ]


class CIndexStats(ctypes.Structure):
    _fields_ = [("avl_nodes", ctypes.c_int32), ("avl_height", ctypes.c_int32),
                ("avl_rotations", ctypes.c_int32), ("trie_nodes", ctypes.c_int32),
                ("trie_keys", ctypes.c_int32)]


class CAvlNodeInfo(ctypes.Structure):
    _fields_ = [("product_index", ctypes.c_int32), ("left", ctypes.c_int32),
                ("right", ctypes.c_int32), ("height", ctypes.c_int32)]


class CEdge(ctypes.Structure):
    _fields_ = [("from_", ctypes.c_int32), ("to", ctypes.c_int32), ("weight", ctypes.c_int32)]


class CStockMove(ctypes.Structure):
    _fields_ = [("quantity", ctypes.c_int32), ("timestamp", ctypes.c_int64)]


class CStockLot(ctypes.Structure):
    _fields_ = [("quantity", ctypes.c_int32), ("received", ctypes.c_int64)]


_lib = None


def load_library():
    """Build the C library if needed, load it once, and declare every signature."""
    global _lib
    if _lib is not None:
        return _lib
    try:
        path = build_c.ensure_library()
    except build_c.BuildError as exc:
        raise StockWiseError(f"The C library is missing and could not be built.\n{exc}") from exc
    if not os.path.exists(path):
        raise StockWiseError(f"C library not found at {path} (set by STOCKWISE_LIB).")
    try:
        lib = ctypes.CDLL(path)
    except OSError as exc:
        bits = struct.calcsize("P") * 8
        raise StockWiseError(
            f"Could not load the C library {path}: {exc}\n"
            f"This Python is {bits}-bit, so the library must be built by a {bits}-bit GCC. "
            f"Delete the file and run again, or rebuild with: python build_c.py") from exc

    i32, i64, p = ctypes.c_int32, ctypes.c_int64, ctypes.POINTER
    signatures = {
        "sw_api_version": ([], i32),
        "sw_error_message": ([i32], ctypes.c_char_p),
        "sw_engine_create": ([p(CProduct), i32, i32, p(i32)], ctypes.c_void_p),
        "sw_engine_destroy": ([ctypes.c_void_p], None),
        "sw_engine_count": ([ctypes.c_void_p], i32),
        "sw_linear_search_id": ([ctypes.c_void_p, i32, p(CSearchResult)], i32),
        "sw_binary_search_id": ([ctypes.c_void_p, i32, p(CSearchResult)], i32),
        "sw_hash_search_id": ([ctypes.c_void_p, i32, p(CSearchResult)], i32),
        "sw_linear_search_name": ([ctypes.c_void_p, ctypes.c_char_p, p(i32), i32, p(i32),
                                   p(i64)], i32),
        "sw_sort_products": ([ctypes.c_void_p, i32, i32, i32, p(i32), i32, p(COpStats)], i32),
        "sw_restock_ranking": ([ctypes.c_void_p, p(CRestockItem), i32, p(i32),
                                p(CRestockItem), p(COpStats)], i32),
        "sw_hash_stats": ([ctypes.c_void_p, p(CHashStats)], i32),
        "sw_hash_chain_lengths": ([ctypes.c_void_p, p(i32), i32], i32),
        "sw_price_range": ([ctypes.c_void_p, ctypes.c_double, ctypes.c_double, p(i32), i32,
                            p(i32), p(i64)], i32),
        "sw_prefix_search": ([ctypes.c_void_p, ctypes.c_char_p, p(i32), i32, p(i32), p(i64)],
                             i32),
        "sw_index_stats": ([ctypes.c_void_p, p(CIndexStats)], i32),
        "sw_avl_snapshot": ([ctypes.c_void_p, p(CAvlNodeInfo), i32, p(i32)], i32),
        "sw_knapsack": ([p(i32), p(ctypes.c_double), i32, i32, p(ctypes.c_uint8),
                         p(ctypes.c_double), p(ctypes.c_double), p(COpStats)], i32),
        "sw_knapsack_greedy": ([p(i32), p(ctypes.c_double), i32, i32, p(ctypes.c_uint8),
                                p(ctypes.c_double), p(COpStats)], i32),
        "sw_shortest_path": ([i32, p(CEdge), i32, i32, i32, p(i32), p(i32), p(i32),
                              p(COpStats)], i32),
        "sw_fifo_lots": ([p(CStockMove), i32, p(CStockLot), i32, p(i32), p(COpStats)], i32),
    }
    for name, (argtypes, restype) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = argtypes, restype
    if lib.sw_api_version() != EXPECTED_API_VERSION:
        raise StockWiseError(
            f"The C library at {path} is out of date (API {lib.sw_api_version()}, need "
            f"{EXPECTED_API_VERSION}). Delete that file and start again to rebuild it.")
    _lib = lib
    return lib


def error_message(code):
    return load_library().sw_error_message(code).decode()


def _check(code, allow_not_found=False):
    if code == 0 or (allow_not_found and code == ERR_NOT_FOUND):
        return code
    raise StockWiseError(f"C engine error {code}: {error_message(code)}")


def _int(value, field, low, high=INT32_MAX):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be a whole number")
    if not low <= value <= high:
        raise ValueError(f"{field} must be between {low} and {high}")
    return value


def _text(value, field, size):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    encoded = value.strip().encode("utf-8")
    if len(encoded) >= size:
        raise ValueError(f"{field} is too long (max {size - 1} bytes)")
    return value.strip()


def validate_product(p):
    """Validate a product dict and return a cleaned copy. Raises ValueError.

    Used by both the database layer and the C bridge, so the C engine never
    receives values it would reject."""
    price = p.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price < 0:
        raise ValueError("price must be a non-negative number")
    demand, importance = p.get("demand"), p.get("importance")
    return {
        "id": _int(p.get("id"), "id", 1),
        "name": _text(p.get("name"), "name", NAME_LEN),
        "category": _text(p.get("category"), "category", CATEGORY_LEN),
        "price": float(price),
        "quantity": _int(p.get("quantity"), "quantity", 0),
        "min_stock": _int(p.get("min_stock"), "min_stock", 0),
        "demand": None if demand is None else _int(demand, "demand", 0),
        "importance": None if importance is None else _int(importance, "importance", 1, 5),
    }


def _to_c(p):
    return CProduct(p["id"], p["name"].encode(), p["category"].encode(), p["price"],
                    p["quantity"], p["min_stock"],
                    MISSING if p["demand"] is None else p["demand"],
                    MISSING if p["importance"] is None else p["importance"])


def reason_text(mask):
    return [text for bit, text in REASONS.items() if mask & bit]


class Engine:
    """A C engine snapshot of a product list. Rebuild it after data changes."""

    def __init__(self, products, bucket_count=0):
        self._lib = load_library()
        self.products = [validate_product(p) for p in products]
        ids = [p["id"] for p in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate product ids")
        _int(bucket_count, "bucket_count", 0, 10_000_000)

        n = len(self.products)
        array = (CProduct * max(n, 1))(*[_to_c(p) for p in self.products])
        err = ctypes.c_int32(0)
        self._handle = self._lib.sw_engine_create(array, n, bucket_count, ctypes.byref(err))
        if not self._handle:
            raise StockWiseError(f"Could not build C engine: {error_message(err.value)}")
        self.count = n

    def close(self):
        if getattr(self, "_handle", None):
            self._lib.sw_engine_destroy(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    def _require_open(self):
        if not self._handle:
            raise StockWiseError("engine is closed")

    def _search(self, fn, product_id):
        self._require_open()
        _int(product_id, "product id", -2**31)
        result = CSearchResult()
        _check(fn(self._handle, product_id, ctypes.byref(result)), allow_not_found=True)
        found = bool(result.found)
        return {"found": found, "index": result.index if found else None,
                "product": self.products[result.index] if found else None,
                "comparisons": result.comparisons}

    def linear_search(self, product_id):
        return self._search(self._lib.sw_linear_search_id, product_id)

    def binary_search(self, product_id):
        return self._search(self._lib.sw_binary_search_id, product_id)

    def hash_search(self, product_id):
        return self._search(self._lib.sw_hash_search_id, product_id)

    def search_name(self, query):
        """Case-insensitive substring search (linear) over product names."""
        self._require_open()
        query = (query or "").strip()
        if not query:
            raise ValueError("search text must not be empty")
        out = (ctypes.c_int32 * max(self.count, 1))()
        count, comparisons = ctypes.c_int32(0), ctypes.c_int64(0)
        _check(self._lib.sw_linear_search_name(self._handle, query.encode(), out, self.count,
                                               ctypes.byref(count), ctypes.byref(comparisons)),
               allow_not_found=True)
        return {"products": [self.products[out[i]] for i in range(count.value)],
                "comparisons": comparisons.value}

    def sort(self, key="name", algorithm="merge", descending=False):
        self._require_open()
        if key not in SORT_KEYS or algorithm not in ALGORITHMS:
            raise ValueError(f"key must be one of {list(SORT_KEYS)}, "
                             f"algorithm one of {list(ALGORITHMS)}")
        out = (ctypes.c_int32 * max(self.count, 1))()
        stats = COpStats()
        _check(self._lib.sw_sort_products(self._handle, ALGORITHMS[algorithm], SORT_KEYS[key],
                                          int(descending), out, self.count,
                                          ctypes.byref(stats)))
        return {"products": [self.products[out[i]] for i in range(self.count)],
                "comparisons": stats.comparisons, "moves": stats.moves}

    def restock_ranking(self):
        """Products at/below minimum stock, highest priority first (C max-heap)."""
        self._require_open()
        size = max(self.count, 1)
        out, snapshot = (CRestockItem * size)(), (CRestockItem * size)()
        count, stats = ctypes.c_int32(0), COpStats()
        _check(self._lib.sw_restock_ranking(self._handle, out, self.count, ctypes.byref(count),
                                            snapshot, ctypes.byref(stats)))

        def convert(item):
            p = self.products[item.product_index]
            return {**p, "score": round(item.score, 2),
                    "shortage_score": item.shortage_score, "demand_score": item.demand_score,
                    "importance_score": item.importance_score,
                    "suggested_qty": item.suggested_qty, "reasons": reason_text(item.reasons)}

        n = count.value
        return {"ranking": [convert(out[i]) for i in range(n)],
                "heap_array": [convert(snapshot[i]) for i in range(n)],
                "comparisons": stats.comparisons, "swaps": stats.moves}

    def hash_stats(self):
        self._require_open()
        stats = CHashStats()
        _check(self._lib.sw_hash_stats(self._handle, ctypes.byref(stats)))
        chains = (ctypes.c_int32 * stats.bucket_count)()
        _check(self._lib.sw_hash_chain_lengths(self._handle, chains, stats.bucket_count))
        result = {name: getattr(stats, name) for name, _ in CHashStats._fields_}
        result["chain_lengths"] = list(chains)
        return result

    def price_range(self, min_price, max_price):
        """Products with min_price <= price <= max_price, ascending (C AVL tree)."""
        self._require_open()
        for v in (min_price, max_price):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v):
                raise ValueError("price bounds must be numbers")
        if min_price > max_price:
            raise ValueError("minimum price must not exceed maximum price")
        out = (ctypes.c_int32 * max(self.count, 1))()
        count, visited = ctypes.c_int32(0), ctypes.c_int64(0)
        _check(self._lib.sw_price_range(self._handle, float(min_price), float(max_price), out,
                                        self.count, ctypes.byref(count),
                                        ctypes.byref(visited)), allow_not_found=True)
        return {"products": [self.products[out[i]] for i in range(count.value)],
                "nodes_visited": visited.value}

    def prefix_search(self, prefix):
        """Autocomplete: names with a word starting with `prefix` (C trie)."""
        self._require_open()
        prefix = (prefix or "").strip()
        if not prefix:
            raise ValueError("prefix must not be empty")
        out = (ctypes.c_int32 * max(self.count, 1))()
        count, visited = ctypes.c_int32(0), ctypes.c_int64(0)
        _check(self._lib.sw_prefix_search(self._handle, prefix.encode(), out, self.count,
                                          ctypes.byref(count), ctypes.byref(visited)),
               allow_not_found=True)
        return {"products": [self.products[out[i]] for i in range(count.value)],
                "nodes_visited": visited.value}

    def index_stats(self):
        self._require_open()
        stats = CIndexStats()
        _check(self._lib.sw_index_stats(self._handle, ctypes.byref(stats)))
        return {name: getattr(stats, name) for name, _ in CIndexStats._fields_}

    def avl_nodes(self):
        """Pre-order AVL nodes: product, left/right child positions (-1 = none), height."""
        self._require_open()
        out = (CAvlNodeInfo * max(self.count, 1))()
        count = ctypes.c_int32(0)
        _check(self._lib.sw_avl_snapshot(self._handle, out, self.count, ctypes.byref(count)))
        return [{"product": self.products[out[i].product_index], "left": out[i].left,
                 "right": out[i].right, "height": out[i].height} for i in range(count.value)]


def _knapsack_inputs(costs, values, budget):
    if len(costs) != len(values):
        raise ValueError("costs and values must have the same length")
    costs = [_int(c, "cost", 0) for c in costs]
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) \
                or v < 0:
            raise ValueError("values must be non-negative numbers")
    budget = _int(budget, "budget", 0)
    n = len(costs)
    return (n, (ctypes.c_int32 * max(n, 1))(*costs),
            (ctypes.c_double * max(n, 1))(*map(float, values)), budget)


def knapsack(costs, values, budget, with_table=False):
    """0/1 knapsack by dynamic programming in C. Returns chosen item positions,
    the best total value, cells evaluated, and optionally the DP table."""
    n, c_costs, c_values, budget = _knapsack_inputs(costs, values, budget)
    if n * (budget + 1) > MAX_KNAPSACK_CELLS:
        raise ValueError("budget too large for the DP table; lower it or use fewer items")
    lib = load_library()
    chosen, best, stats = (ctypes.c_uint8 * max(n, 1))(), ctypes.c_double(0), COpStats()
    width = budget + 1
    table = (ctypes.c_double * ((n + 1) * width))() if with_table else None
    _check(lib.sw_knapsack(c_costs, c_values, n, budget, chosen, ctypes.byref(best), table,
                           ctypes.byref(stats)))
    result = {"chosen": [i for i in range(n) if chosen[i]], "value": best.value,
              "cells": stats.comparisons}
    if with_table:
        result["table"] = [list(table[r * width:(r + 1) * width]) for r in range(n + 1)]
    return result


def knapsack_greedy(costs, values, budget):
    """Greedy by value/cost ratio in C (uses the Max-Heap). Not always optimal."""
    n, c_costs, c_values, budget = _knapsack_inputs(costs, values, budget)
    lib = load_library()
    chosen, best, stats = (ctypes.c_uint8 * max(n, 1))(), ctypes.c_double(0), COpStats()
    _check(lib.sw_knapsack_greedy(c_costs, c_values, n, budget, chosen, ctypes.byref(best),
                                  ctypes.byref(stats)))
    return {"chosen": [i for i in range(n) if chosen[i]], "value": best.value,
            "comparisons": stats.comparisons}


def shortest_path(node_count, edges, source, target):
    """Dijkstra in C. edges = [(a, b, distance), ...] (undirected). Returns the
    route as node numbers (empty if unreachable) and every node's distance."""
    node_count = _int(node_count, "node count", 1)
    c_edges = (CEdge * max(len(edges), 1))()
    for i, (a, b, w) in enumerate(edges):
        c_edges[i] = CEdge(_int(a, "edge start", 0, node_count - 1),
                           _int(b, "edge end", 0, node_count - 1), _int(w, "distance", 1))
    source = _int(source, "source", 0, node_count - 1)
    target = _int(target, "target", 0, node_count - 1)
    lib = load_library()
    dist, path = (ctypes.c_int32 * node_count)(), (ctypes.c_int32 * node_count)()
    length, stats = ctypes.c_int32(0), COpStats()
    _check(lib.sw_shortest_path(node_count, c_edges, len(edges), source, target, dist, path,
                                ctypes.byref(length), ctypes.byref(stats)),
           allow_not_found=True)
    return {"path": list(path[:length.value]),
            "distances": [None if d < 0 else d for d in dist],
            "comparisons": stats.comparisons, "relaxations": stats.moves}


def fifo_lots(moves):
    """Replay (signed quantity, unix timestamp) moves through the C circular
    queue. Returns the stock lots still on hand, oldest first."""
    c_moves = (CStockMove * max(len(moves), 1))()
    for i, (qty, ts) in enumerate(moves):
        if _int(qty, "quantity", -INT32_MAX) == 0:
            raise ValueError("quantity must not be zero")
        c_moves[i] = CStockMove(qty, _int(ts, "timestamp", 0, 2**62))
    stock_ins = sum(1 for q, _ in moves if q > 0)
    lib = load_library()
    lots, count, stats = (CStockLot * max(stock_ins, 1))(), ctypes.c_int32(0), COpStats()
    _check(lib.sw_fifo_lots(c_moves, len(moves), lots, stock_ins, ctypes.byref(count),
                            ctypes.byref(stats)))
    return {"lots": [{"quantity": lots[i].quantity, "received": lots[i].received}
                     for i in range(count.value)],
            "queue_operations": stats.moves}
