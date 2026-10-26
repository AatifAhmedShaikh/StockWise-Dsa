# Algorithms, Pseudocode and Complexity

**n** = number of products. **m** = number of hash buckets. **α = n/m** is the load
factor. **σ** = alphabet size, **W** = budget, **V/E** = graph nodes/edges.

A *comparison* is one key-vs-key check, and the C code counts it exactly where it
happens. A *move* is one write of an element: a 4-byte index in sorting, or one swap
in the heap.

## Complexity table

| Algorithm | Best | Average | Worst | Extra space | Where |
|---|---|---|---|---|---|
| Linear search (id / name) | O(1) | O(n) | O(n) | O(1) | `search.c` |
| Binary search (id) | O(1) | O(log n) | O(log n) | O(1) | `search.c` |
| Hash table insert / find | O(1) | O(1 + α) | O(n) | O(n + m) | `hash_table.c` |
| Merge Sort | O(n log n) | O(n log n) | O(n log n) | O(n) | `sorting.c` |
| Insertion Sort | O(n) | O(n²) | O(n²) | O(1) | `sorting.c` |
| Heap push (sift up) | O(1) | O(log n) | O(log n) | O(1) | `max_heap.c` |
| Heap pop / extract-max (sift down) | O(log n) | O(log n) | O(log n) | O(1) | `max_heap.c` |
| Restock ranking (n pushes + n pops) | O(n log n) | O(n log n) | O(n log n) | O(n) | `inventory_engine.c` |
| Quick Sort (3-way, median-of-three) | O(n log n) | O(n log n) | O(n²) | O(log n) | `sorting.c` |
| Heap Sort | O(n log n) | O(n log n) | O(n log n) | O(1) | `sorting.c` |
| AVL insert | O(log n) | O(log n) | O(log n) | O(n) total | `avl_tree.c` |
| AVL price range (k results) | O(log n) | O(log n + k) | O(log n + k) | O(log n) stack | `avl_tree.c` |
| Trie insert (key length L) | O(L) | O(L) | O(L·σ) | O(total key length) | `trie.c` |
| Trie prefix search (prefix P, k results) | O(P) | O(P + subtree) | O(P·σ + subtree) | O(n) | `trie.c` |
| 0/1 Knapsack DP (budget W) | O(n·W) | O(n·W) | O(n·W) | O(n·W) | `knapsack.c` |
| Knapsack greedy | O(n log n) | O(n log n) | O(n log n) | O(n) | `knapsack.c` |
| Dijkstra (binary heap) | O((V+E) log V) | O((V+E) log V) | O((V+E) log V) | O(V + E) | `graph.c` |
| Circular queue enqueue / dequeue | O(1) | O(1) amortized | O(n) on resize | O(n) | `fifo_queue.c` |
| Engine build (hash index + Merge Sort by id) | O(n log n) | O(n log n) | O(n log n) | O(n + m) | `inventory_engine.c` |

## Linear search

```
LINEAR-SEARCH(A, n, target):
    for i = 0 to n-1:
        comparisons += 1
        if A[i].id == target: return i
    return NOT_FOUND
```

It works on unsorted data. A missing key always costs n comparisons.

## Binary search

The products arrive from SQLite ordered by *name*. The engine therefore keeps a
separate index array `S`, sorted by id with Merge Sort when the engine is built.

```
BINARY-SEARCH(A, S, n, target):
    low = 0; high = n - 1
    while low <= high:
        mid = low + (high - low) / 2      # avoids int overflow of (low + high)
        comparisons += 1
        if A[S[mid]].id == target: return S[mid]
        else if A[S[mid]].id < target: low = mid + 1
        else: high = mid - 1
    return NOT_FOUND
```

There are at most ⌊log₂ n⌋ + 1 probes. With 2,000 products that is at most 11.

## Hash table (separate chaining)

```
hash(k) = k mod m                          # division method; m is prime by default

INSERT(T, k, v):
    b = hash(k)
    for node in T.bucket[b]: if node.key == k: return DUPLICATE_ID
    node = new Node(k, v); node.next = T.bucket[b]; T.bucket[b] = node   # O(1) head insert

FIND(T, k):
    for node in T.bucket[hash(k)]:
        comparisons += 1
        if node.key == k: return node.value
    return NOT_FOUND
```

- **Collisions.** Two keys with the same `k mod m` share a linked list, called a chain.
  `collisions = items − non-empty buckets`.
- **Missing key.** The lookup walks only that one chain. An empty bucket costs
  0 comparisons.
- **Auto size.** The smallest prime ≥ 2n (minimum 11), so α ≤ 0.5.
- **Forcing collisions.** The Lab lets you choose m. With m = 7 and 200 items,
  α ≈ 28.6, and lookups slow down toward O(n).

## Merge Sort (stable)

```
MERGE-SORT(A, lo, hi):                     # sorts A[lo..hi)
    if hi - lo < 2: return
    mid = lo + (hi - lo) / 2
    MERGE-SORT(A, lo, mid)
    MERGE-SORT(A, mid, hi)
    MERGE(A, lo, mid, hi)

MERGE(A, lo, mid, hi):
    i = lo; j = mid; k = lo
    while i < mid and j < hi:
        if A[i] <= A[j]: tmp[k++] = A[i++]   # "<=" takes left on ties → stable
        else:            tmp[k++] = A[j++]
    copy the rest of either run into tmp
    copy tmp[lo..hi) back to A
```

The recurrence is T(n) = 2T(n/2) + O(n), so T(n) = O(n log n). The `tmp` buffer is
allocated once, for O(n) extra space.

## Insertion Sort (stable)

```
INSERTION-SORT(A, n):
    for i = 1 to n-1:
        current = A[i]; j = i - 1
        while j >= 0 and A[j] > current:     # strict ">" → stable
            A[j+1] = A[j]; j -= 1
        A[j+1] = current
```

- Sorted input costs n−1 comparisons (best case).
- Reverse-sorted input costs n(n−1)/2 (worst case).
- Both counts are verified in `test_engine.c`.

Both sorts work on an **array of indices**, not on whole records:
- The caller's data is never modified.
- Each move is a cheap 4-byte write.

The sort keys are id, name (case-insensitive), price, quantity, and value
(price × quantity).

## Max-Heap priority queue

The heap is stored in an array:
- parent(i) = (i−1)/2
- left(i) = 2i+1
- right(i) = 2i+2

```
PUSH(H, x):
    H[size] = x; i = size; size += 1
    while i > 0 and H[i] > H[parent(i)]:
        swap(H[i], H[parent(i)]); i = parent(i)

POP(H):
    top = H[0]; H[0] = H[size-1]; size -= 1
    i = 0
    loop:
        largest = the biggest of i, left(i), right(i)   (those that exist)
        if largest == i: break
        swap(H[i], H[largest]); i = largest
    return top
```

"Bigger" means a higher score. When two scores are equal, the **smaller product id**
wins, so the order is deterministic.

## Restock priority formula

```
Priority = 100 × (0.5 × S + 0.3 × D + 0.2 × I)          range 0..100
```

| Component | Formula (each normalized to 0..1) | Missing value |
|---|---|---|
| S, shortage | `(min_stock − quantity) / min_stock`, clamped to [0, 1]. If `min_stock = 0`: 1 when quantity = 0, else 0 | not possible (required field) |
| D, demand | `demand / max(demand of all products)`. 0 if every demand is 0 | 0.5 (neutral) |
| I, importance | `(importance − 1) / 4` for importance 1..5 | 0.5 (neutral) |

- **Candidates.** Only products with `quantity ≤ min_stock` are pushed onto the heap.
- **Suggested quantity.**
  - Normally: `min_stock + demand − quantity`. This refills to the safety level plus
    one period of demand.
  - If demand is unknown: `2 × min_stock − quantity`.
  - Always at least 1.
- **Reasons**, stored as a bitmask in C and turned into text in Python:
  - out of stock
  - below minimum
  - at minimum
  - high demand (D ≥ 0.7)
  - high importance (≥ 4)
  - missing data

Worked example: AA Batteries. quantity 0, min 50, demand 90 (max 220), importance 5.

- S = 1
- D = 90/220 ≈ 0.409
- I = 1
- Priority = 100 × (0.5 + 0.1227 + 0.2) = **82.27**
- Suggested = 50 + 90 − 0 = **140**

## Quick Sort (3-way partition)

```
QUICK-SORT(A, lo, hi):
    while lo < hi:
        pivot = median of A[lo], A[mid], A[hi]     # avoids the sorted-input worst case
        lt = lo; i = lo; gt = hi                   # Dijkstra's "Dutch national flag"
        while i <= gt:
            if A[i] < pivot: swap(A[lt++], A[i++])
            elif A[i] > pivot: swap(A[i], A[gt--])
            else: i++
        # A[lo..lt) < pivot, A[lt..gt] == pivot, A(gt..hi] > pivot
        recurse into the smaller side, loop on the larger   # O(log n) stack depth
```

The three-way split puts all keys equal to the pivot in their final place at once.
Inventory data has many repeated quantities and prices, which would slow a two-way
partition down to O(n²). The sort is not stable.

## Heap Sort

```
HEAP-SORT(A, n):
    for i = n/2 - 1 down to 0: SIFT-DOWN(A, i, n)     # build a max-heap, O(n)
    for end = n - 1 down to 1:
        swap(A[0], A[end])                            # largest goes to the back
        SIFT-DOWN(A, 0, end)
```

O(n log n) in every case, with O(1) extra space. It is not stable. It reuses the same
sift-down idea as the restock priority queue.

## AVL tree (price index)

The AVL tree is a binary search tree ordered by `(price, id)`. Every node stores its
height, and its **balance factor** is `height(left) − height(right)`. After a normal
BST insert, each node on the way back up is fixed if its balance factor leaves
[−1, 1]:

| Case | Shape | Fix |
|---|---|---|
| Left-Left | inserted into left child's left subtree | rotate right |
| Left-Right | inserted into left child's right subtree | rotate left (child), then right |
| Right-Right | mirror of Left-Left | rotate left |
| Right-Left | mirror of Left-Right | rotate right (child), then left |

```
RANGE(node, lo, hi):                     # in-order, skipping impossible subtrees
    if node is null: return
    if node.price >= lo: RANGE(node.left, lo, hi)
    if lo <= node.price <= hi: output node
    if node.price <= hi: RANGE(node.right, lo, hi)
```

The height stays at most 1.44 log₂ n.
- Inserting 1,000 products in ascending price order (a plain BST's worst case) gives
  height ≤ 14 instead of 1,000. `test_engine.c` checks this.
- A range query visits O(log n + k) nodes. The app shows "nodes visited" next to the
  result.

## Trie (name autocomplete)

Each node holds one character. Children are a **sorted linked list** (first child /
next sibling), which keeps memory small.

**What gets inserted.** Every *word start* of a name: "USB-C Charging Cable" inserts
"usb-c charging cable", "c charging cable", "charging cable" and "cable". So typing
"cab" or "charg" both find it.

```
PREFIX(p):
    node = root
    for ch in lower(p): node = child of node labelled ch (stop if missing)
    DFS(node): output node's products, then visit children in sorted order
```

A DFS of the sorted children returns results in alphabetical order. A `seen[]` array
stops a product from appearing twice. If no word starts with the text, the app falls
back to linear substring search.

## 0/1 Knapsack: budget restock planner

Each restock candidate has:
- **cost** = suggested quantity × price, rounded up to whole dollars
- **value** = its priority score

The goal is to choose the set with the highest total priority whose cost fits budget W.

```
dp[0..W] = 0
for each item i with (cost c, value v):
    for w = W down to c:                 # downwards, so each item is used at most once
        if dp[w - c] + v > dp[w]:
            dp[w] = dp[w - c] + v
            keep[i][w] = 1
w = W
for i = n-1 down to 0: if keep[i][w]: choose i; w -= c_i
```

**Greedy comparison.** Sort the items by value/cost using the Max-Heap and take each
one that still fits. It is fast but not optimal.

Classic counterexample (the Lab's default): costs 1, 3, 4, 5 with values 1, 4, 5, 7
and W = 7.
- Greedy takes the cost-5 item first (best ratio, 1.4), then the cost-1 item, for a
  value of 8.
- The DP picks the cost-3 and cost-4 items, for a value of **9**.

The DP is O(n·W). This is *pseudo-polynomial*: the running time grows with the size of
the budget number, so the C code caps n·(W+1) at 20 million cells.

## Dijkstra: delivery routes

```
dist[*] = ∞; dist[s] = 0; push (0, s)
while queue not empty:
    (d, u) = pop smallest
    if d > dist[u]: continue                  # stale entry (lazy deletion)
    for each edge (u, v, w):
        if d + w < dist[v]:
            dist[v] = d + w; prev[v] = u; push (dist[v], v)
route = follow prev[] from target back to s, then reverse
```

- **Graph storage.** The edge list is converted to a compressed adjacency list (CSR):
  one array of neighbours plus an offset per node.
- **Priority queue.** It reuses the project's Max-Heap storing `−distance`. A max-heap
  on negated keys behaves as a min-heap.
- **Correctness.** All road lengths are positive, which Dijkstra's algorithm requires.
  The sample network contains a case where the direct road (Warehouse → Airport, 26 km)
  is longer than the route via Harbor Depot (15 + 9 = 24 km).

## Circular queue: FIFO stock lots

Stock usually leaves first-in, first-out. Replaying a product's history through a queue
gives the units still on hand and their age:
- **Stock in:** enqueue a lot (quantity, received time).
- **Stock out:** take units from the front lot, and dequeue it when it is empty.

```
ENQUEUE(x): if size == capacity: copy into an array twice as big (unwrapped), head = 0
            A[(head + size) mod capacity] = x; size += 1
DEQUEUE():  head = (head + 1) mod capacity; size -= 1
```

- **Ring buffer.** The head and tail wrap around the array, so dequeuing never shifts
  elements.
- **Growth.** Doubling the capacity makes enqueue amortized O(1).
- **Errors.** Removing more units than are on hand returns an error.
