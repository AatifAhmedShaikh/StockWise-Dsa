# College Report Outline and Viva Preparation

## Report outline

1. **Title page**: StockWise: Inventory Optimization System Using Data Structures and
   Algorithms. Include names, roll numbers, guide, department, and year.
2. **Certificate / Declaration / Acknowledgement**
3. **Abstract** (150–200 words): the problem, the DSA-based approach, the C engine
   behind a Python UI, and the results.
4. **Introduction**
   1. Background: why small businesses lose money through stock-outs and overstock
   2. Problem statement
   3. Objectives: fast product lookup, sorted views, prioritized restocking,
      consistent stock history
   4. Scope and limitations: single user, local SQLite, heuristic demand
5. **Literature / Concept review**: searching, hashing, sorting and priority queues,
   plus the ABC/priority idea in inventory management.
6. **System analysis**
   1. Functional requirements (the 7 pages)
   2. Non-functional requirements: correctness, no negative stock, responsiveness
   3. Hardware and software requirements
7. **System design**
   1. Architecture diagram (README §1) and the Python ↔ C flow
   2. Module design: one subsection per C file
   3. Data structure design: the `Product`, `SearchResult`, `RestockItem` and
      `HashStats` structs, plus the hash node, chain, and heap array
   4. Database design: ER diagram (Products 1—N Transactions), `schema.sql`,
      constraints
   5. API design: function table, ownership rules, error codes
8. **Algorithms**: pseudocode, complexity table and the priority formula, from
   `docs/ALGORITHMS.md`
9. **Implementation**: key code excerpts, ctypes struct mirroring, and the SQL
   transaction for stock updates
10. **Testing**
    1. Strategy: C unit tests, Python unittest, sanitizer run, live edge-case tab
    2. Test case table: ID, description, input, expected, actual, status. Fill it from
       *your own* test run output.
11. **Results and analysis**
    - Screenshots of every page
    - The Lab scaling chart: insertion vs merge comparisons for n = 50…1600
    - Linear vs binary vs hash comparisons for the same ID
    - The effect of the bucket count on collisions
12. **Conclusion and future scope**
    - Demand forecasting from transaction history, AVL/B-tree indexes, multi-user
      server database, barcode scanning
13. **References**: CLRS *Introduction to Algorithms*; the Python ctypes and sqlite3
    docs; the Streamlit docs
14. **Appendix**: build instructions and the user manual

---

## Viva questions with answers

**1. Why is the DSA engine in C instead of Python?**
C makes the data structures explicit: you allocate nodes with `malloc`, link them with
pointers, and manage arrays yourself. Python's built-in `dict` and `sorted` would hide
the algorithms we are meant to show. C is also fast and is easily called from Python
through a shared library.

**2. How does Python call the C code?**
- `ctypes.CDLL` loads `libstockwise.so` (or `stockwise.dll` on Windows).
- `c_bridge.py` declares `argtypes` and `restype` for every function, and mirrors each
  C struct as a `ctypes.Structure` with identical field order and types.
- Python allocates the output buffers, C fills them, and Python converts the results
  into dicts.

**3. Who owns the memory? How do you avoid leaks?**
- `sw_engine_create` copies the input, and the engine owns that copy.
  `sw_engine_destroy` frees the products, the index array, every hash node and the
  bucket array.
- Python calls destroy from `Engine.close()`, which runs from the `with` block and from
  `__del__`.
- Output buffers are Python-owned. C never returns heap memory to Python.
- The C tests run clean under AddressSanitizer.

**4. Why does binary search need sorted data, and how do you guarantee it?**
Binary search discards half the range after each comparison, which is only valid if
the keys are ordered. SQLite returns products ordered by name. While building the
engine, we therefore sort an *index array* by id using our Merge Sort, and binary
search runs over that index.

**5. What is a hash collision and how do you handle it?**
A collision is when two different keys map to the same bucket, for example keys 3 and
6 with m = 3. We use **separate chaining**: each bucket is a linked list, and a lookup
walks only that bucket's list. The Lab shows chain lengths. A small m creates long
chains.

**6. Why is the default bucket count a prime ≥ 2n?**
- With `k mod m`, a prime m spreads patterned keys (such as multiples of 10) more
  evenly than a round number.
- Using 2n keeps the load factor ≤ 0.5, so the average chain is short and lookups are
  O(1).

**7. What happens when you search for a missing product?**
- Linear search: n comparisons.
- Binary search: about log₂ n comparisons, until low > high.
- Hash table: only the bucket's chain, so 0 comparisons if the bucket is empty.

All three return `SW_ERR_NOT_FOUND` with `index = -1`, and the UI shows "not found".

**8. How do you detect duplicate product IDs?**
- In SQLite, the PRIMARY KEY rejects them.
- In C, `ht_insert` scans the chain before inserting and returns `SW_ERR_DUPLICATE_ID`.
  The engine refuses to build.
- `c_bridge` also checks before calling C.

**9. Compare Merge Sort and Insertion Sort.**
- Merge Sort is O(n log n) in every case, but needs O(n) extra space.
- Insertion Sort is O(n²) on average and worst case, O(n) on nearly-sorted data, and
  uses O(1) extra space.
- Both are stable.
- For 1,600 random items, the Lab shows roughly 15k comparisons for Merge Sort versus
  roughly 640k for Insertion Sort.

**10. What does "stable" mean and why does it matter here?**
Equal keys keep their original relative order. If two products have the same price,
they stay in name order, which keeps tables predictable. Merge uses `<=` (take from the
left run on ties), and Insertion uses a strict `>` when shifting.

**11. Why sort indices instead of the Product structs?**
- A Product is 128 bytes and an index is 4 bytes, so each move is much cheaper.
- The original array is untouched, so the same data can be sorted many ways.

**12. Explain the Max-Heap.**
- It is a complete binary tree stored in an array.
- Every parent's score is ≥ its children's.
- Push appends the item and sifts it up. Pop removes the root, moves the last item to
  the root, and sifts it down. Both are O(log n).
- The root is always the most urgent product.

**13. Why a heap instead of just sorting by score?**
- Both cost O(n log n) for a full ranking.
- A priority queue also supports getting the top k items in O(n + k log n), and adding
  new urgent items in O(log n) without re-sorting.
- It is the natural data structure for "what should I restock next?".

**14. Explain the priority formula.**
- Priority = 100 × (0.5·S + 0.3·D + 0.2·I).
- Shortage gets the highest weight, because a stock-out loses sales immediately.
- Demand is normalized by the highest demand in the inventory.
- Importance is mapped from 1..5 to 0..1.
- Missing demand or importance gets a neutral 0.5, so an unknown value neither hides
  nor exaggerates a product.

**15. How is negative inventory prevented?**
There are three layers:
- SQLite CHECK constraints (`quantity >= 0`).
- The atomic `UPDATE … WHERE quantity + delta >= 0`, inside a transaction together
  with the history INSERT.
- Python validation before any SQL runs. The C engine also rejects negative values.

**16. How do you keep the C data structures from becoming stale?**
The engine is a read-only snapshot, rebuilt from SQLite on every Streamlit rerun, which
happens after every user action. There is no second copy of the inventory that could
drift. The rebuild costs O(n log n), which is negligible for a small business
inventory.

**17. What is the time complexity of building the engine?**
- Validation and copying: O(n).
- Hash insertion: O(n) on average.
- Merge Sort by id: O(n log n).
- Total: O(n log n). Space: O(n + m).

**18. What is the worst case of the hash table and when does it happen?**
O(n), when every key lands in the same bucket. For example, with m = 1, or with keys
that are all multiples of m. The prime size and load factor ≤ 0.5 make this unlikely.

**19. Why use fixed-width types like `int32_t` and `int64_t`?**
`int` and `long` sizes differ between platforms. Windows has a 32-bit `long`, Linux
has a 64-bit one. Fixed-width types guarantee that the C struct layout matches the
ctypes definition on every OS. Comparison counters are `int64_t` so they cannot
overflow.

**20. How did you test the project?**
- `backend/tests/test_engine.c` covers:
  - every search, including missing keys and an empty array
  - forced collisions
  - sort correctness, stability, and best and worst-case counts
  - heap order and ties
  - restock scores
  - invalid inputs and duplicates
- Python unittest covers:
  - the ctypes integration, checking C sorts against Python's `sorted`
  - SQLite persistence, insufficient stock, and cascade delete
- The C tests were also run under ASan/UBSan.

**21. What would you improve with more time?**
- Forecast demand from transaction history (moving average) instead of entering it
  manually.
- Incremental index updates instead of full rebuilds.
- A self-balancing BST for range queries, such as "price between X and Y".
- User accounts.
