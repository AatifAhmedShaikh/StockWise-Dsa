"""core.py - logic shared by the web UI (webui/) and the Streamlit app (app.py).

Standard library only, so it runs on a machine with nothing installed.
"""
import random
import sqlite3

import database as db
from c_bridge import Engine, StockWiseError, fifo_lots, knapsack, shortest_path

COMPLEXITY_COLUMNS = ['Algorithm', 'Best', 'Average', 'Worst', 'Space', 'Notes']

# (algorithm, best, average, worst, space, notes)
COMPLEXITY_ROWS = [('Linear search', 'O(1)', 'O(n)', 'O(n)', 'O(1)', 'Works on unsorted data'),
 ('Binary search', 'O(1)', 'O(log n)', 'O(log n)', 'O(1)', 'Needs data sorted by id'),
 ('Hash table lookup', 'O(1)', 'O(1)', 'O(n)', 'O(n + m)', 'Separate chaining, m buckets'),
 ('Trie prefix search',
  'O(P)',
  'O(P + k)',
  'O(P·σ + k)',
  'O(total key length)',
  'P = prefix length, k = matches, σ = alphabet'),
 ('AVL price range',
  'O(log n)',
  'O(log n + k)',
  'O(log n + k)',
  'O(n)',
  'Height stays ≤ 1.44 log₂ n'),
 ('Merge Sort', 'O(n log n)', 'O(n log n)', 'O(n log n)', 'O(n)', 'Stable, divide & conquer'),
 ('Insertion Sort', 'O(n)', 'O(n²)', 'O(n²)', 'O(1)', 'Stable, fast on nearly sorted data'),
 ('Quick Sort',
  'O(n log n)',
  'O(n log n)',
  'O(n²)',
  'O(log n)',
  '3-way partition, median-of-three pivot'),
 ('Heap Sort', 'O(n log n)', 'O(n log n)', 'O(n log n)', 'O(1)', 'In place, not stable'),
 ('Heap push / pop', 'O(1)', 'O(log n)', 'O(log n)', 'O(1)', 'Sift up / sift down'),
 ('Restock ranking', 'O(n log n)', 'O(n log n)', 'O(n log n)', 'O(n)', 'n pushes + n pops'),
 ('FIFO queue (ring buffer)',
  'O(1)',
  'O(1) amortized',
  'O(n) on resize',
  'O(n)',
  'Doubles capacity when full'),
 ('Dijkstra',
  'O((V+E) log V)',
  'O((V+E) log V)',
  'O((V+E) log V)',
  'O(V + E)',
  'Binary heap, lazy deletion'),
 ('Knapsack DP', 'O(n·W)', 'O(n·W)', 'O(n·W)', 'O(n·W)', 'W = budget; exact'),
 ('Knapsack greedy',
  'O(n log n)',
  'O(n log n)',
  'O(n log n)',
  'O(n)',
  'Heap by value per cost; can miss the optimum')]

PSEUDOCODE = {'0/1 Knapsack (DP)': 'dp[0..W] = 0\n'
                      'for each item i (cost c, value v):\n'
                      '    for w = W down to c:              # downwards: each item used once\n'
                      '        if dp[w-c] + v > dp[w]: dp[w] = dp[w-c] + v; keep[i][w] = 1\n'
                      'walk keep[][] back from W to list the chosen items',
 'AVL tree': 'insert(node, x):\n'
             '    BST insert by (price, id), then on the way back up:\n'
             '    update height; balance = height(left) - height(right)\n'
             '    balance > 1:  left-right case? rotate_left(left); rotate_right(node)\n'
             '    balance < -1: right-left case? rotate_right(right); rotate_left(node)\n'
             'range(node, lo, hi):           # in-order, pruned\n'
             '    if price >= lo: range(left)\n'
             '    if lo <= price <= hi: output node\n'
             '    if price <= hi: range(right)',
 'Binary search': 'low = 0, high = n-1            # A sorted by id\n'
                  'while low <= high:\n'
                  '    mid = low + (high - low) / 2\n'
                  '    if A[mid].id == target: return mid\n'
                  '    if A[mid].id < target: low = mid + 1\n'
                  '    else: high = mid - 1\n'
                  'return NOT_FOUND',
 'Circular FIFO queue': 'enqueue(x): if size == capacity: double the array (unwrapped)\n'
                        '            A[(head + size) mod capacity] = x; size += 1\n'
                        'dequeue():  x = A[head]; head = (head + 1) mod capacity; size -= 1\n'
                        'stock in  -> enqueue(lot)\n'
                        'stock out -> take units from the front lot; dequeue it when empty',
 'Dijkstra': 'dist[s] = 0; push (0, s)\n'
             'while queue not empty:\n'
             '    (d, u) = pop smallest\n'
             '    if d > dist[u]: continue           # stale entry\n'
             '    for (v, w) in adj[u]:\n'
             '        if d + w < dist[v]: dist[v] = d + w; prev[v] = u; push (dist[v], v)',
 'Hash table (separate chaining)': 'hash(k) = k mod m\n'
                                   'insert(k, v): if k in chain[hash(k)]: DUPLICATE\n'
                                   '              else: new node -> head of chain[hash(k)]\n'
                                   'find(k):      walk chain[hash(k)] comparing keys',
 'Heap Sort': 'for i = n/2-1 down to 0: sift_down(A, i, n)     # build max-heap\n'
              'for end = n-1 down to 1:\n'
              '    swap(A[0], A[end])                           # max to the end\n'
              '    sift_down(A, 0, end)',
 'Insertion Sort': 'for i = 1 to n-1:\n'
                   '    current = A[i]; j = i - 1\n'
                   '    while j >= 0 and A[j] > current:   # strict > keeps it stable\n'
                   '        A[j+1] = A[j]; j -= 1\n'
                   '    A[j+1] = current',
 'Linear search': 'for i = 0 to n-1:\n'
                  '    comparisons += 1\n'
                  '    if A[i].id == target: return i\n'
                  'return NOT_FOUND',
 'Max-Heap priority queue': 'push(x):  A[size] = x; sift up while A[i] > A[parent(i)]\n'
                            'pop():    top = A[0]; A[0] = A[size-1]; sift down; return top\n'
                            'parent(i) = (i-1)/2, left(i) = 2i+1, right(i) = 2i+2',
 'Merge Sort': 'merge_sort(A, lo, hi):\n'
               '    if hi - lo < 2: return\n'
               '    mid = (lo + hi) / 2\n'
               '    merge_sort(A, lo, mid); merge_sort(A, mid, hi)\n'
               '    merge(A, lo, mid, hi)        # take from left on ties -> stable',
 'Quick Sort (3-way)': 'quick_sort(A, lo, hi):\n'
                       '    while lo < hi:\n'
                       '        pivot = median of A[lo], A[mid], A[hi]\n'
                       '        lt = lo, i = lo, gt = hi            # Dutch national flag\n'
                       '        while i <= gt:\n'
                       '            if A[i] < pivot: swap(A[lt++], A[i++])\n'
                       '            elif A[i] > pivot: swap(A[i], A[gt--])\n'
                       '            else: i++\n'
                       '        recurse into the smaller side, loop on the larger',
 'Trie (prefix tree)': 'insert(word):                # for every word start of a name\n'
                       '    node = root\n'
                       '    for ch in lower(word): node = child(node, ch) or create it\n'
                       '    node.entries.append(product)\n'
                       'prefix(p):\n'
                       '    walk p character by character from the root (missing child -> '
                       'none)\n'
                       '    DFS the subtree, collecting entries (alphabetical, de-duplicated)'}


def generate_products(n, seed):
    """Random but valid inventory for the lab (ids are shuffled, not sorted)."""
    rng = random.Random(seed)
    words = ["Steel", "Blue", "Organic", "Mini", "Pro", "Eco", "Classic", "Smart", "Ultra"]
    things = ["Bolt", "Lamp", "Tea", "Cable", "Notebook", "Soap", "Juice", "Fan", "Mug"]
    cats = ["Electronics", "Grocery", "Stationery", "Cleaning", "Beverages"]
    ids = rng.sample(range(1, max(n * 10, 10)), n)
    return [{"id": i, "name": f"{rng.choice(words)} {rng.choice(things)} {k}",
             "category": rng.choice(cats), "price": round(rng.uniform(0.5, 120), 2),
             "quantity": rng.randint(0, 150), "min_stock": rng.randint(5, 60),
             "demand": None if rng.random() < 0.05 else rng.randint(0, 100),
             "importance": None if rng.random() < 0.05 else rng.randint(1, 5)}
            for k, i in enumerate(ids)]


def run_edge_cases():
    """Execute real edge-case calls against the C engine and a scratch database.
    Returns a list of {Case, Expected, Actual, Result} rows."""
    cases = []

    def case(name, expected, fn):
        try:
            actual = fn()
        except (ValueError, StockWiseError) as exc:
            actual = f"Error: {exc}"
        cases.append({"Case": name, "Expected": expected, "Actual": str(actual),
                      "Result": "Passed" if str(actual).startswith(expected) else "Failed"})

    sample = generate_products(5, 1)
    with Engine([]) as empty, Engine(sample) as eng:
        case("Hash search on empty array", "not found",
             lambda: "found" if empty.hash_search(1)["found"] else "not found")
        case("Binary search on empty array", "not found",
             lambda: "found" if empty.binary_search(1)["found"] else "not found")
        case("Sort empty array", "[]", lambda: empty.sort("name")["products"])
        case("Restock on empty array", "[]", lambda: empty.restock_ranking()["ranking"])
        case("Price range on empty tree", "[]", lambda: empty.price_range(0, 10)["products"])
        case("Missing product id (all 3 searches)", "not found",
             lambda: "found" if any(f(10**7)["found"] for f in
                                    (eng.linear_search, eng.binary_search, eng.hash_search))
             else "not found")
        case("Empty name query", "Error", lambda: eng.search_name(""))
        case("Empty trie prefix", "Error", lambda: eng.prefix_search(" "))
        case("Unknown trie prefix", "[]", lambda: eng.prefix_search("zzzz")["products"])
        case("Price range with min > max", "Error", lambda: eng.price_range(10, 1))
    case("Duplicate product ids", "Error", lambda: Engine([sample[0], sample[0]]))
    case("Negative price", "Error", lambda: Engine([{**sample[0], "price": -5}]))
    case("Negative quantity", "Error", lambda: Engine([{**sample[0], "quantity": -1}]))
    case("Knapsack with negative budget", "Error", lambda: knapsack([1], [1.0], -1))
    case("Knapsack with zero budget", "[]", lambda: knapsack([3], [5.0], 0)["chosen"])
    case("Route to an unreachable node", "[]",
         lambda: shortest_path(3, [(0, 1, 5)], 0, 2)["path"])
    case("FIFO: remove more than on hand", "Error", lambda: fifo_lots([(2, 1), (-3, 2)]))

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn, seed=False)
    db.add_product(conn, {**sample[0], "quantity": 3})
    case("Remove more stock than available", "Error",
         lambda: db.record_transaction(conn, sample[0]["id"], "OUT", 4))
    case("Stock unchanged after rejected removal", "3",
         lambda: db.get_product(conn, sample[0]["id"])["quantity"])
    conn.close()
    return cases
