"""webui/api.py - the data behind the web UI. Standard library only.

Every function takes a database connection (plus parameters) and returns a
JSON-ready dict. A ValueError means "bad input" and becomes an HTTP 400.
All searching, sorting, tree, trie, heap, graph, queue and DP work is done by
the C engine through c_bridge.py; this module only shapes the results.
"""
import math
from datetime import datetime, timedelta

import core
import database as db
from c_bridge import (ALGORITHMS, INT32_MAX, STABLE_ALGORITHMS, Engine, StockWiseError,
                      fifo_lots, knapsack, knapsack_greedy, shortest_path)

ALGO_NAMES = {"merge": "Merge Sort", "insertion": "Insertion Sort", "quick": "Quick Sort",
              "heap": "Heap Sort"}
ALGO_COMPLEXITY = {"merge": "O(n log n)", "insertion": "O(n²)", "quick": "O(n log n)",
                   "heap": "O(n log n)"}
SORT_KEYS = ("name", "price", "quantity", "value")
MAX_LAB_PRODUCTS, MAX_BUCKETS = 5000, 100_000


# ---------------------------------------------------------------- small helpers
def status_of(p):
    if p["quantity"] == 0:
        return "Out of stock"
    return "Low stock" if p["quantity"] <= p["min_stock"] else "In stock"


def decorate(p):
    """Product dict plus its inventory value and stock status."""
    return dict(p, value=round(p["price"] * p["quantity"], 2), status=status_of(p))


def price_ceiling(products):
    """Upper end of a price slider: highest price rounded up, at least $1."""
    return float(max(1, math.ceil(max((p["price"] for p in products), default=0))))


def to_int(value, field, low=None, high=None):
    """Whole number from JSON/query input (accepts 5, 5.0 and '5'); ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number")
    if isinstance(value, str):
        value = value.strip()
        try:
            value = int(value)
        except ValueError:
            raise ValueError(f"{field} must be a whole number") from None
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    elif not isinstance(value, int):
        raise ValueError(f"{field} must be a whole number")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"{field} must be between {low} and {high}")
    return value


def to_float(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a number")
    return number


def optional_int(value, field, low, high):
    return None if value in (None, "") else to_int(value, field, low, high)


def clean_product(body):
    """Product fields from a JSON body, converted to the types the database expects."""
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    return {
        "id": to_int(body.get("id"), "id", 1, INT32_MAX),
        "name": body.get("name") or "",
        "category": body.get("category") or "",
        "price": to_float(body.get("price"), "price"),
        "quantity": to_int(body.get("quantity", 0), "quantity", 0, INT32_MAX),
        "min_stock": to_int(body.get("min_stock", 0), "min_stock", 0, INT32_MAX),
        "demand": optional_int(body.get("demand"), "demand", 0, INT32_MAX),
        "importance": optional_int(body.get("importance"), "importance", 1, 5),
    }


def day_of(timestamp):
    return datetime.strptime(timestamp[:10], "%Y-%m-%d").date()


def epoch_of(timestamp):
    return int(datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").timestamp())


def stock_history(conn, days=30):
    """Units on hand per day and units in/out per day for the last `days` days."""
    rows = db.list_transactions(conn)
    if not rows:
        return [], []
    signed, moved = {}, {}
    for t in rows:
        d = day_of(t["created_at"])
        signed[d] = signed.get(d, 0) + (t["quantity"] if t["type"] == "IN" else -t["quantity"])
        entry = moved.setdefault(d, {"in": 0, "out": 0})
        entry["in" if t["type"] == "IN" else "out"] += t["quantity"]
    first, last = min(signed), max(max(signed), datetime.now().date())
    level, series, total, d = [], [], 0, first
    while d <= last:
        total += signed.get(d, 0)
        level.append({"date": d.isoformat(), "units": total})
        series.append({"date": d.isoformat(), "in": moved.get(d, {}).get("in", 0),
                       "out": moved.get(d, {}).get("out", 0)})
        d += timedelta(days=1)
    return level[-days:], series[-days:]


def stock_lots(conn, product_id):
    """Replay a product's history through the C FIFO queue; lots carry their age in days."""
    rows = sorted(db.list_transactions(conn, product_id), key=lambda t: (t["created_at"], t["id"]))
    moves = [(t["quantity"] if t["type"] == "IN" else -t["quantity"], epoch_of(t["created_at"]))
             for t in rows]
    result = fifo_lots(moves)
    now = datetime.now().timestamp()
    lots = [{"quantity": lot["quantity"], "received": lot["received"],
             "date": datetime.fromtimestamp(lot["received"]).strftime("%Y-%m-%d"),
             "age_days": int((now - lot["received"]) // 86400)} for lot in result["lots"]]
    return {"lots": lots, "queue_operations": result["queue_operations"]}


def restock_costs(ranking):
    """Whole-dollar cost of restocking each ranked product by its suggested quantity."""
    return [math.ceil(p["suggested_qty"] * p["price"]) for p in ranking]


# ---------------------------------------------------------------- static content
def bootstrap():
    return {"locations": db.LOCATIONS, "routes": db.ROUTES,
            "complexity": {"columns": core.COMPLEXITY_COLUMNS, "rows": core.COMPLEXITY_ROWS},
            "pseudocode": core.PSEUDOCODE,
            "algorithms": [{"key": k, "name": ALGO_NAMES[k], "complexity": ALGO_COMPLEXITY[k],
                            "stable": k in STABLE_ALGORITHMS} for k in ALGORITHMS]}


def summary(conn):
    return {"products": len(db.list_products(conn))}


# ---------------------------------------------------------------- dashboard
def dashboard(conn):
    products = db.list_products(conn)
    with Engine(products) as eng:
        top = eng.sort("value", "merge", True)
        attention = eng.restock_ranking()["ranking"][:5]
    by_category = {}
    for p in products:
        by_category[p["category"]] = by_category.get(p["category"], 0) + p["price"] * p["quantity"]
    level, moves = stock_history(conn)
    return {
        "kpis": {"products": len(products), "units": sum(p["quantity"] for p in products),
                 "value": round(sum(p["price"] * p["quantity"] for p in products), 2),
                 "low": sum(0 < p["quantity"] <= p["min_stock"] for p in products),
                 "out": sum(p["quantity"] == 0 for p in products)},
        "level": level, "movement": moves,
        "level_change": level[-1]["units"] - level[0]["units"] if level else 0,
        "attention": [dict(decorate(p), score=p["score"]) for p in attention],
        "by_category": sorted(({"category": k, "value": round(v, 2)}
                               for k, v in by_category.items()), key=lambda r: -r["value"]),
        "top_value": {"items": [decorate(p) for p in top["products"][:8]],
                      "comparisons": top["comparisons"]},
        "recent": db.list_transactions(conn, limit=8),
    }


# ---------------------------------------------------------------- products
def products_view(conn, q="", categories=None, low=None, high=None):
    """Catalog query: ID -> C hash table, text -> C trie (then C substring search),
    price range -> C AVL tree."""
    products = db.list_products(conn)
    ceiling = price_ceiling(products)
    notes, shown, found = [], products, None
    q = (q or "").strip()
    with Engine(products) as eng:
        if q:
            if q.isdigit():
                try:
                    r = eng.hash_search(int(q))
                except ValueError:  # more digits than any product ID can have
                    r = {"found": False, "product": None, "comparisons": 0}
                found = [r["product"]] if r["found"] else []
                notes.append(f"Hash table lookup in C · {r['comparisons']} comparison(s)")
            else:
                r = eng.prefix_search(q)
                if r["products"]:
                    found = r["products"]
                    notes.append(f"Trie prefix search in C · {r['nodes_visited']} trie nodes visited")
                else:
                    r = eng.search_name(q)
                    found = r["products"]
                    notes.append("No word starts with that, so C linear substring search ran · "
                                 f"{r['comparisons']} comparison(s)")
            shown = found
        lo = 0.0 if low in (None, "") else to_float(low, "minimum price")
        hi = ceiling if high in (None, "") else to_float(high, "maximum price")
        lo, hi = min(lo, hi), max(lo, hi)
        if (lo, hi) != (0.0, ceiling):
            r = eng.price_range(lo, hi)
            in_range = {p["id"] for p in r["products"]}
            shown = r["products"] if found is None else [p for p in found if p["id"] in in_range]
            notes.append(f"AVL range query in C · {r['nodes_visited']} of {eng.count} tree "
                         "nodes visited")
    if categories:
        shown = [p for p in shown if p["category"] in categories]
    return {"products": [decorate(p) for p in shown], "total": len(products), "notes": notes,
            "categories": sorted({p["category"] for p in products}), "price_ceiling": ceiling}


def add_product(conn, body):
    p = db.add_product(conn, clean_product(body))
    return {"product": p}


def update_product(conn, product_id, body):
    changes = clean_product(dict(body, id=product_id))
    return {"product": db.update_product(conn, product_id, changes)}


def delete_product(conn, product_id):
    db.delete_product(conn, product_id)
    return {"deleted": product_id}


# ---------------------------------------------------------------- transactions
def record_transaction(conn, body):
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    pid = to_int(body.get("product_id"), "product", 1, INT32_MAX)
    qty = to_int(body.get("quantity"), "quantity", 1, INT32_MAX)
    balance = db.record_transaction(conn, pid, body.get("type"), qty, str(body.get("note") or ""))
    return {"balance": balance, "product": db.get_product(conn, pid)}


def transactions_view(conn, product_id=None):
    products = db.list_products(conn)
    out = {"rows": db.list_transactions(conn, product_id=product_id, limit=300),
           "products": [{"id": p["id"], "name": p["name"], "quantity": p["quantity"]}
                        for p in products]}
    if product_id is not None:
        out["lots"] = stock_lots(conn, product_id)
    else:
        aging = []
        for p in products:
            lots = stock_lots(conn, p["id"])["lots"]
            if lots:
                aging.append({"name": p["name"], "oldest_days": lots[0]["age_days"],
                              "lots": len(lots)})
        out["aging"] = sorted(aging, key=lambda r: -r["oldest_days"])[:10]
    return out


# ---------------------------------------------------------------- restocking
def restock_view(conn):
    products = db.list_products(conn)
    with Engine(products) as eng:
        result = eng.restock_ranking()
    costs = restock_costs(result["ranking"])
    items = [dict(p, cost=costs[i], rank=i + 1, status=status_of(p))
             for i, p in enumerate(result["ranking"])]
    return {"items": items, "comparisons": result["comparisons"], "swaps": result["swaps"],
            "total_cost": sum(costs), "total_units": sum(p["suggested_qty"] for p in items),
            "out_of_stock": sum(p["quantity"] == 0 for p in items)}


def restock_plan(conn, budget):
    """0/1 knapsack (C dynamic programming) against the greedy heuristic."""
    ranking = restock_view(conn)["items"]
    budget = to_int(budget, "budget", 0, INT32_MAX)
    costs, values = [p["cost"] for p in ranking], [p["score"] for p in ranking]
    out = {"budget": budget, "total_cost": sum(costs)}
    try:
        dp, greedy = knapsack(costs, values, budget), knapsack_greedy(costs, values, budget)
    except (ValueError, StockWiseError) as exc:
        out["error"] = str(exc)
        return out
    dp_set, greedy_set = set(dp["chosen"]), set(greedy["chosen"])
    out.update({
        "dp": {"value": dp["value"], "cost": sum(costs[i] for i in dp_set), "cells": dp["cells"]},
        "greedy": {"value": greedy["value"], "cost": sum(costs[i] for i in greedy_set)},
        "items": [{"id": p["id"], "name": p["name"], "cost": costs[i], "score": p["score"],
                   "per_dollar": p["score"] / costs[i] if costs[i] else None,
                   "dp": i in dp_set, "greedy": i in greedy_set,
                   "suggested_qty": p["suggested_qty"]} for i, p in enumerate(ranking)]})
    return out


def restock_order(conn, budget):
    """Record a delivery for every product in the DP plan."""
    plan = restock_plan(conn, budget)
    if "error" in plan:
        raise ValueError(plan["error"])
    chosen = [p for p in plan["items"] if p["dp"]]
    for p in chosen:
        db.record_transaction(conn, p["id"], "IN", p["suggested_qty"], "Budget plan delivery")
    return {"ordered": len(chosen), "cost": plan["dp"]["cost"]}


# ---------------------------------------------------------------- routes
def routes_view(source, target):
    count = len(db.LOCATIONS)
    source, target = to_int(source, "from", 0, count - 1), to_int(target, "to", 0, count - 1)
    r = shortest_path(count, db.ROUTES, source, target)
    return {"path": r["path"], "distances": r["distances"], "relaxations": r["relaxations"],
            "comparisons": r["comparisons"], "source": source, "target": target}


# ---------------------------------------------------------------- search and sort
def search_view(conn, params):
    method = params.get("method", "hash")
    products = db.list_products(conn)
    with Engine(products) as eng:
        if method in ("hash", "binary", "linear"):
            fn = {"hash": eng.hash_search, "binary": eng.binary_search,
                  "linear": eng.linear_search}[method]
            pid = to_int(params.get("id", 1042), "product id", -2**31, INT32_MAX)
            r = fn(pid)
            return {"products": [decorate(r["product"])] if r["found"] else [],
                    "work": r["comparisons"], "label": "Comparisons", "searched": pid}
        if method in ("trie", "substring"):
            text = (params.get("q") or "").strip()
            if not text:
                return {"products": [], "work": 0, "label": "Comparisons", "empty": True}
            if method == "trie":
                r = eng.prefix_search(text)
                return {"products": [decorate(p) for p in r["products"]],
                        "work": r["nodes_visited"], "label": "Trie nodes visited"}
            r = eng.search_name(text)
            return {"products": [decorate(p) for p in r["products"]],
                    "work": r["comparisons"], "label": "Comparisons"}
        if method == "range":
            lo, hi = to_float(params.get("min", 0), "minimum"), to_float(params.get("max", 0), "maximum")
            r = eng.price_range(min(lo, hi), max(lo, hi))
            return {"products": [decorate(p) for p in r["products"]],
                    "work": f"{r['nodes_visited']} of {eng.count}", "label": "Tree nodes visited"}
    raise ValueError("unknown search method")


def sort_view(conn, key, algorithm, descending):
    if key not in SORT_KEYS or algorithm not in ALGORITHMS:
        raise ValueError("unknown sort key or algorithm")
    with Engine(db.list_products(conn)) as eng:
        r = eng.sort(key, algorithm, bool(descending))
    return {"products": [decorate(p) for p in r["products"]], "comparisons": r["comparisons"],
            "moves": r["moves"], "complexity": ALGO_COMPLEXITY[algorithm],
            "stable": algorithm in STABLE_ALGORITHMS}


# ---------------------------------------------------------------- laboratory
class LabData:
    """Context manager: a C engine over the real inventory or a generated sample."""

    def __init__(self, conn, params):
        self.generated = params.get("source") == "generated"
        self.n = to_int(params.get("n", 200), "sample size", 0, MAX_LAB_PRODUCTS)
        seed = to_int(params.get("seed", 42), "seed", 0, 10_000)
        self.buckets = to_int(params.get("buckets", 0), "buckets", 0, MAX_BUCKETS)
        self.params = params
        self.data = core.generate_products(self.n, seed) if self.generated else db.list_products(conn)

    def __enter__(self):
        self.engine = Engine(self.data, bucket_count=self.buckets)
        return self

    def __exit__(self, *exc):
        self.engine.close()


def trim_tree(nodes, label, max_depth=5):
    """Copy a binary tree (nodes with left/right positions, -1 = none) down to max_depth levels."""
    out = []

    def walk(i, depth):
        pos = len(out)
        out.append({"label": label(nodes[i]), "left": -1, "right": -1})
        if depth + 1 < max_depth:
            if nodes[i]["left"] >= 0:
                out[pos]["left"] = walk(nodes[i]["left"], depth + 1)
            if nodes[i]["right"] >= 0:
                out[pos]["right"] = walk(nodes[i]["right"], depth + 1)
        return pos

    if nodes:
        walk(0, 0)
    return out


def lab_search(conn, params):
    with LabData(conn, params) as lab:
        eng, data = lab.engine, lab.data
        default = data[len(data) // 2]["id"] if data else 1
        pid = to_int(params.get("id", default), "target product id", 1, INT32_MAX)
        rows = []
        for name, fn, cx in (("Linear search", eng.linear_search, "O(n)"),
                             ("Binary search", eng.binary_search, "O(log n)"),
                             ("Hash table", eng.hash_search, "O(1) average")):
            r = fn(pid)
            rows.append({"algorithm": name, "found": r["found"], "comparisons": r["comparisons"],
                         "product": r["product"]["name"] if r["found"] else None,
                         "complexity": cx})
        return {"rows": rows, "id": pid, "count": len(data)}


def lab_sort(conn, params):
    key = params.get("key", "price")
    if key not in SORT_KEYS:
        raise ValueError("unknown sort key")
    with LabData(conn, params) as lab:
        rows, orders = [], {}
        for algo in ALGORITHMS:
            r = lab.engine.sort(key, algo)
            orders[algo] = [p[key] for p in r["products"]]
            rows.append({"algorithm": ALGO_NAMES[algo], "comparisons": r["comparisons"],
                         "moves": r["moves"], "stable": algo in STABLE_ALGORITHMS,
                         "time": ALGO_COMPLEXITY[algo]})
        return {"rows": rows, "same_order": all(o == orders["merge"] for o in orders.values()),
                "count": len(lab.data)}


_SCALING = []


def lab_scaling():
    """Comparisons to sort random data as n grows. Deterministic, so computed once."""
    if not _SCALING:
        for size in (50, 100, 200, 400, 800, 1600):
            with Engine(core.generate_products(size, size)) as eng:
                for algo in ALGORITHMS:
                    _SCALING.append({"n": size, "algorithm": ALGO_NAMES[algo],
                                     "comparisons": eng.sort("price", algo)["comparisons"]})
    return {"points": list(_SCALING)}


def lab_hash(conn, params):
    with LabData(conn, params) as lab:
        stats = lab.engine.hash_stats()
        stats["chain_lengths"] = stats["chain_lengths"][:300]
        return stats


def lab_heap(conn, params):
    with LabData(conn, params) as lab:
        r = lab.engine.restock_ranking()
        heap = r["heap_array"]
        n = len(heap)
        tree = [{"label": f"{p['id']}\n{p['score']:.1f}", "left": 2 * i + 1 if 2 * i + 1 < n else -1,
                 "right": 2 * i + 2 if 2 * i + 2 < n else -1} for i, p in enumerate(heap)]
        return {"count": n, "comparisons": r["comparisons"], "swaps": r["swaps"],
                "heap": [{"index": i, "parent": (i - 1) // 2 if i else None, "id": p["id"],
                          "score": p["score"]} for i, p in enumerate(heap)],
                "ranking": [{"rank": i + 1, "id": p["id"], "name": p["name"], "score": p["score"]}
                            for i, p in enumerate(r["ranking"])],
                "tree": trim_tree(tree, lambda t: t["label"])}


def lab_avl(conn, params):
    with LabData(conn, params) as lab:
        eng, data = lab.engine, lab.data
        stats = eng.index_stats()
        ceiling = price_ceiling(data)
        low = to_float(params.get("min", ceiling * 0.2), "minimum price")
        high = to_float(params.get("max", ceiling * 0.4), "maximum price")
        r = eng.price_range(min(low, high), max(low, high)) if data else {"products": [], "nodes_visited": 0}
        nodes = eng.avl_nodes()
        return {"stats": stats, "count": eng.count, "ceiling": ceiling,
                "ideal_height": math.ceil(math.log2(eng.count + 1)) if eng.count else 0,
                "min": min(low, high), "max": max(low, high),
                "matches": len(r["products"]), "visited": r["nodes_visited"],
                "tree": trim_tree(nodes, lambda n: f"${n['product']['price']:.2f}")}


def lab_trie(conn, params):
    prefix = (params.get("prefix") or "").strip()
    with LabData(conn, params) as lab:
        eng = lab.engine
        out = {"stats": eng.index_stats(), "count": eng.count, "prefix": prefix}
        if prefix and lab.data:
            trie, linear = eng.prefix_search(prefix), eng.search_name(prefix)
            out.update({"trie": {"work": trie["nodes_visited"], "matches": len(trie["products"])},
                        "linear": {"work": linear["comparisons"], "matches": len(linear["products"])},
                        "suggestions": [{"id": p["id"], "name": p["name"]}
                                        for p in trie["products"][:20]]})
        return out


def lab_knapsack(body):
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise ValueError("expected items")
    items = body["items"][:30]
    names = [str(i.get("name") or f"Item {n + 1}")[:40] for n, i in enumerate(items)]
    costs = [to_int(i.get("cost"), "cost", 0, 1000) for i in items]
    values = [to_float(i.get("value"), "priority") for i in items]
    budget = to_int(body.get("budget", 0), "budget", 0, 1000)
    dp = knapsack(costs, values, budget, with_table=True)
    greedy = knapsack_greedy(costs, values, budget)
    return {"names": names, "dp": dp, "greedy": greedy, "budget": budget}


def lab_edge():
    return {"cases": core.run_edge_cases()}
