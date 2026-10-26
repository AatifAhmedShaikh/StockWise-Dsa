# Algorithms, Pseudocode and Complexity

**n** = number of products. **m** = number of hash buckets. **α = n/m** is the load
factor.

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
