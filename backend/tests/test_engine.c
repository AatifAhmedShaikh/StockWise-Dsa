/* test_engine.c - C-level tests for the StockWise DSA engine.
 * Build and run: make test */
#include <stdio.h>
#include <string.h>

#include "inventory_types.h"

static int failures = 0, checks = 0;

#define CHECK(cond)                                                       \
    do {                                                                  \
        checks++;                                                         \
        if (!(cond)) {                                                    \
            failures++;                                                   \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);        \
        }                                                                 \
    } while (0)

static Product make(int32_t id, const char *name, double price, int32_t qty, int32_t min_stock,
                    int32_t demand, int32_t importance)
{
    Product p;
    memset(&p, 0, sizeof p);
    p.id = id;
    strncpy(p.name, name, SW_NAME_LEN - 1);
    strncpy(p.category, "Test", SW_CATEGORY_LEN - 1);
    p.price = price;
    p.quantity = qty;
    p.min_stock = min_stock;
    p.demand = demand;
    p.importance = importance;
    return p;
}

/* Unsorted by id on purpose: binary search must rely on the engine's index. */
static Product sample[6];

static void fill_sample(void)
{
    sample[0] = make(50, "Widget", 2.5, 100, 20, 30, 3);
    sample[1] = make(10, "apple juice", 1.0, 0, 10, 60, 5);
    sample[2] = make(40, "Bolt", 0.1, 5, 50, 20, 2);
    sample[3] = make(20, "Cable", 5.0, 8, 8, SW_MISSING, SW_MISSING);
    sample[4] = make(30, "Apple Pie", 3.0, 12, 10, 10, 1);
    sample[5] = make(60, "Drill", 99.0, 3, 4, 5, 5);
}

static void test_searches(void)
{
    SwEngine *e = sw_engine_create(sample, 6, 0, NULL);
    CHECK(e != NULL);
    SearchResult r;

    CHECK(sw_linear_search_id(e, 30, &r) == SW_OK && r.index == 4 && r.comparisons == 5);
    CHECK(sw_binary_search_id(e, 30, &r) == SW_OK && r.index == 4 && r.found == 1);
    CHECK(r.comparisons <= 3); /* ceil(log2(6+1)) */
    CHECK(sw_hash_search_id(e, 30, &r) == SW_OK && r.index == 4);

    for (int32_t i = 0; i < 6; i++) { /* every algorithm finds every id */
        SearchResult a, b, c;
        sw_linear_search_id(e, sample[i].id, &a);
        sw_binary_search_id(e, sample[i].id, &b);
        sw_hash_search_id(e, sample[i].id, &c);
        CHECK(a.index == i && b.index == i && c.index == i);
    }

    /* missing keys */
    CHECK(sw_linear_search_id(e, 999, &r) == SW_ERR_NOT_FOUND && r.index == -1 && !r.found);
    CHECK(r.comparisons == 6);
    CHECK(sw_binary_search_id(e, 999, &r) == SW_ERR_NOT_FOUND && r.index == -1);
    CHECK(sw_binary_search_id(e, 1, &r) == SW_ERR_NOT_FOUND);
    CHECK(sw_binary_search_id(e, 35, &r) == SW_ERR_NOT_FOUND);
    CHECK(sw_hash_search_id(e, 999, &r) == SW_ERR_NOT_FOUND && r.index == -1);

    /* name search: case-insensitive substring */
    int32_t idx[6], count = 0;
    int64_t cmp = 0;
    CHECK(sw_linear_search_name(e, "APPLE", idx, 6, &count, &cmp) == SW_OK);
    CHECK(count == 2 && idx[0] == 1 && idx[1] == 4 && cmp == 6);
    CHECK(sw_linear_search_name(e, "zzz", idx, 6, &count, &cmp) == SW_ERR_NOT_FOUND);
    CHECK(count == 0);
    CHECK(sw_linear_search_name(e, "", idx, 6, &count, &cmp) == SW_ERR_INVALID_VALUE);
    CHECK(sw_linear_search_name(e, "a", idx, 2, &count, &cmp) == SW_ERR_BUFFER_TOO_SMALL);
    sw_engine_destroy(e);
}

static void test_empty_and_invalid(void)
{
    int32_t err = 123;
    SwEngine *e = sw_engine_create(NULL, 0, 0, &err);
    CHECK(e != NULL && err == SW_OK && sw_engine_count(e) == 0);
    SearchResult r;
    CHECK(sw_linear_search_id(e, 1, &r) == SW_ERR_NOT_FOUND && r.comparisons == 0);
    CHECK(sw_binary_search_id(e, 1, &r) == SW_ERR_NOT_FOUND && r.comparisons == 0);
    CHECK(sw_hash_search_id(e, 1, &r) == SW_ERR_NOT_FOUND && r.comparisons == 0);
    int32_t idx[1];
    OpStats st;
    CHECK(sw_sort_products(e, SW_ALGO_MERGE, SW_KEY_NAME, 0, idx, 0, &st) == SW_OK);
    RestockItem items[1];
    int32_t n = -1;
    CHECK(sw_restock_ranking(e, items, 0, &n, NULL, &st) == SW_OK && n == 0);
    sw_engine_destroy(e);
    sw_engine_destroy(NULL); /* must be a no-op */

    CHECK(sw_engine_create(NULL, 3, 0, &err) == NULL && err == SW_ERR_NULL_POINTER);
    CHECK(sw_engine_create(sample, -1, 0, &err) == NULL && err == SW_ERR_INVALID_LENGTH);
    CHECK(sw_linear_search_id(NULL, 1, &r) == SW_ERR_NULL_POINTER);

    Product bad = make(1, "Bad", -1.0, 1, 1, 1, 1);
    CHECK(sw_engine_create(&bad, 1, 0, &err) == NULL && err == SW_ERR_INVALID_VALUE);
    bad = make(1, "Bad", 1.0, -5, 1, 1, 1);
    CHECK(sw_engine_create(&bad, 1, 0, &err) == NULL && err == SW_ERR_INVALID_VALUE);
    bad = make(1, "Bad", 1.0, 1, 1, 1, 9);
    CHECK(sw_engine_create(&bad, 1, 0, &err) == NULL && err == SW_ERR_INVALID_VALUE);
    bad = make(0, "Bad", 1.0, 1, 1, 1, 1);
    CHECK(sw_engine_create(&bad, 1, 0, &err) == NULL && err == SW_ERR_INVALID_VALUE);
    bad = make(1, "Bad", 1.0, 1, 1, 1, 1);
    memset(bad.name, 'x', SW_NAME_LEN); /* no NUL terminator */
    CHECK(sw_engine_create(&bad, 1, 0, &err) == NULL && err == SW_ERR_INVALID_VALUE);

    Product dup[2] = {make(7, "A", 1, 1, 1, 1, 1), make(7, "B", 1, 1, 1, 1, 1)};
    CHECK(sw_engine_create(dup, 2, 0, &err) == NULL && err == SW_ERR_DUPLICATE_ID);
    CHECK(strcmp(sw_error_message(SW_ERR_DUPLICATE_ID), "duplicate product id") == 0);
}

static void test_hash_collisions(void)
{
    /* 3 buckets, keys 3,6,9,12 all hash to bucket 0 -> one chain of 4. */
    Product items[5] = {make(3, "a", 1, 1, 1, 1, 1), make(6, "b", 1, 1, 1, 1, 1),
                        make(9, "c", 1, 1, 1, 1, 1), make(12, "d", 1, 1, 1, 1, 1),
                        make(4, "e", 1, 1, 1, 1, 1)};
    SwEngine *e = sw_engine_create(items, 5, 3, NULL);
    CHECK(e != NULL);
    HashStats hs;
    CHECK(sw_hash_stats(e, &hs) == SW_OK);
    CHECK(hs.bucket_count == 3 && hs.item_count == 5 && hs.used_buckets == 2);
    CHECK(hs.collisions == 3 && hs.longest_chain == 4);

    int32_t chains[3];
    CHECK(sw_hash_chain_lengths(e, chains, 3) == SW_OK);
    CHECK(chains[0] == 4 && chains[1] == 1 && chains[2] == 0);
    CHECK(sw_hash_chain_lengths(e, chains, 2) == SW_ERR_BUFFER_TOO_SMALL);

    SearchResult r;
    for (int32_t i = 0; i < 5; i++)
        CHECK(sw_hash_search_id(e, items[i].id, &r) == SW_OK && r.index == i);
    /* 3 was inserted first, so it sits at the end of the chain: 4 comparisons. */
    sw_hash_search_id(e, 3, &r);
    CHECK(r.comparisons == 4);
    /* missing key in a non-empty chain walks the whole chain */
    CHECK(sw_hash_search_id(e, 15, &r) == SW_ERR_NOT_FOUND && r.comparisons == 4);
    /* missing key in an empty bucket costs nothing */
    CHECK(sw_hash_search_id(e, 5, &r) == SW_ERR_NOT_FOUND && r.comparisons == 0);
    sw_engine_destroy(e);
}

static int is_sorted(const Product *items, const int32_t *idx, int32_t n, int32_t key, int desc)
{
    for (int32_t i = 1; i < n; i++) {
        const Product *a = &items[idx[i - 1]], *b = &items[idx[i]];
        double va = 0, vb = 0;
        if (key == SW_KEY_PRICE) { va = a->price; vb = b->price; }
        if (key == SW_KEY_QUANTITY) { va = a->quantity; vb = b->quantity; }
        if (key == SW_KEY_VALUE) { va = a->price * a->quantity; vb = b->price * b->quantity; }
        if (key == SW_KEY_ID) { va = a->id; vb = b->id; }
        if (desc ? va < vb : va > vb) return 0;
    }
    return 1;
}

static void test_sorting(void)
{
    SwEngine *e = sw_engine_create(sample, 6, 0, NULL);
    int32_t m[6], ins[6];
    OpStats sm, si;
    int32_t keys[] = {SW_KEY_ID, SW_KEY_PRICE, SW_KEY_QUANTITY, SW_KEY_VALUE};
    for (int k = 0; k < 4; k++)
        for (int desc = 0; desc <= 1; desc++) {
            CHECK(sw_sort_products(e, SW_ALGO_MERGE, keys[k], desc, m, 6, &sm) == SW_OK);
            CHECK(sw_sort_products(e, SW_ALGO_INSERTION, keys[k], desc, ins, 6, &si) == SW_OK);
            CHECK(is_sorted(sample, m, 6, keys[k], desc));
            CHECK(memcmp(m, ins, sizeof m) == 0); /* both stable -> identical order */
            CHECK(sm.comparisons > 0 && si.comparisons > 0);
        }

    /* name sort is case-insensitive: apple juice, Apple Pie, Bolt, Cable, Drill, Widget */
    int32_t expected[] = {1, 4, 2, 3, 5, 0};
    CHECK(sw_sort_products(e, SW_ALGO_MERGE, SW_KEY_NAME, 0, m, 6, &sm) == SW_OK);
    CHECK(memcmp(m, expected, sizeof m) == 0);
    CHECK(sw_sort_products(e, SW_ALGO_INSERTION, SW_KEY_NAME, 0, ins, 6, &si) == SW_OK);
    CHECK(memcmp(ins, expected, sizeof ins) == 0);

    CHECK(sw_sort_products(e, 7, SW_KEY_NAME, 0, m, 6, &sm) == SW_ERR_INVALID_VALUE);
    CHECK(sw_sort_products(e, SW_ALGO_MERGE, 42, 0, m, 6, &sm) == SW_ERR_INVALID_VALUE);
    CHECK(sw_sort_products(e, SW_ALGO_MERGE, SW_KEY_NAME, 0, m, 5, &sm) == SW_ERR_BUFFER_TOO_SMALL);
    sw_engine_destroy(e);

    /* Insertion sort on sorted input: exactly n-1 comparisons (best case). */
    Product asc[5];
    for (int i = 0; i < 5; i++) asc[i] = make(i + 1, "x", 1, i, 1, 1, 1);
    e = sw_engine_create(asc, 5, 0, NULL);
    CHECK(sw_sort_products(e, SW_ALGO_INSERTION, SW_KEY_QUANTITY, 0, ins, 5, &si) == SW_OK);
    CHECK(si.comparisons == 4);
    /* Reverse input: worst case n(n-1)/2 comparisons. */
    CHECK(sw_sort_products(e, SW_ALGO_INSERTION, SW_KEY_QUANTITY, 1, ins, 5, &si) == SW_OK);
    CHECK(si.comparisons == 10);
    sw_engine_destroy(e);

    /* Stability: equal prices keep input order. */
    Product ties[3] = {make(3, "c", 5, 1, 1, 1, 1), make(1, "a", 5, 1, 1, 1, 1),
                       make(2, "b", 1, 1, 1, 1, 1)};
    e = sw_engine_create(ties, 3, 0, NULL);
    int32_t expected_ties[] = {2, 0, 1};
    CHECK(sw_sort_products(e, SW_ALGO_MERGE, SW_KEY_PRICE, 0, m, 3, &sm) == SW_OK);
    CHECK(memcmp(m, expected_ties, sizeof expected_ties) == 0);
    CHECK(sw_sort_products(e, SW_ALGO_INSERTION, SW_KEY_PRICE, 0, ins, 3, &si) == SW_OK);
    CHECK(memcmp(ins, expected_ties, sizeof expected_ties) == 0);
    sw_engine_destroy(e);
}

static void test_heap(void)
{
    MaxHeap *h = heap_create(8);
    double scores[] = {10, 80, 30, 99, 5, 80, 60};
    for (int i = 0; i < 7; i++) {
        RestockItem it = {0};
        it.product_id = 100 - i;
        it.score = scores[i];
        CHECK(heap_push(h, &it) == SW_OK);
    }
    CHECK(heap_size(h) == 7);

    RestockItem snap[8];
    CHECK(heap_snapshot(h, snap, 8) == SW_OK);
    for (int i = 1; i < 7; i++) CHECK(snap[(i - 1) / 2].score >= snap[i].score); /* heap property */

    double expected[] = {99, 80, 80, 60, 30, 10, 5};
    RestockItem out, prev = {0};
    for (int i = 0; i < 7; i++) {
        CHECK(heap_pop(h, &out) == SW_OK && out.score == expected[i]);
        if (i == 2) CHECK(prev.product_id < out.product_id); /* tie -> smaller id first */
        prev = out;
    }
    CHECK(heap_pop(h, &out) == SW_ERR_NOT_FOUND); /* extract from empty heap */
    heap_destroy(h);

    h = heap_create(1);
    RestockItem it = {0};
    CHECK(heap_push(h, &it) == SW_OK);
    CHECK(heap_push(h, &it) == SW_ERR_BUFFER_TOO_SMALL);
    heap_destroy(h);
}

static void test_restock(void)
{
    SwEngine *e = sw_engine_create(sample, 6, 0, NULL);
    RestockItem out[6], snap[6];
    int32_t n = 0;
    OpStats st;
    CHECK(sw_restock_ranking(e, out, 6, &n, snap, &st) == SW_OK);
    /* Candidates (qty <= min): apple juice(0/10), Bolt(5/50), Cable(8/8), Drill(3/4). */
    CHECK(n == 4);
    for (int i = 1; i < n; i++) CHECK(out[i - 1].score >= out[i].score);

    /* apple juice: shortage 1, demand 60/60 = 1, importance (5-1)/4 = 1 -> 100 */
    CHECK(out[0].product_id == 10 && out[0].score > 99.999);
    CHECK(out[0].reasons & SW_REASON_OUT_OF_STOCK);
    CHECK(out[0].reasons & SW_REASON_HIGH_DEMAND);
    CHECK(out[0].reasons & SW_REASON_HIGH_IMPORTANCE);
    CHECK(out[0].suggested_qty == 70); /* 10 + 60 - 0 */

    for (int i = 0; i < n; i++) {
        if (out[i].product_id == 20) { /* Cable: at minimum, missing data -> neutral 0.5s */
            CHECK(out[i].shortage_score == 0.0);
            CHECK(out[i].demand_score == 0.5 && out[i].importance_score == 0.5);
            CHECK(out[i].reasons & SW_REASON_MISSING_DATA);
            CHECK(out[i].reasons & SW_REASON_AT_MINIMUM);
            CHECK(out[i].suggested_qty == 8); /* 8 + 8 - 8 */
        }
        if (out[i].product_id == 40) /* Bolt: shortage 0.9 */
            CHECK(out[i].shortage_score > 0.899 && out[i].shortage_score < 0.901);
    }
    CHECK(snap[0].product_id == out[0].product_id); /* heap root = top priority */
    CHECK(sw_restock_ranking(e, out, 5, &n, NULL, &st) == SW_ERR_BUFFER_TOO_SMALL);
    sw_engine_destroy(e);
}

static void test_quick_and_heap_sort(void)
{
    SwEngine *e = sw_engine_create(sample, 6, 0, NULL);
    int32_t idx[6];
    OpStats st;
    int32_t keys[] = {SW_KEY_ID, SW_KEY_PRICE, SW_KEY_QUANTITY, SW_KEY_VALUE};
    int32_t algos[] = {SW_ALGO_QUICK, SW_ALGO_HEAP};
    for (int a = 0; a < 2; a++)
        for (int k = 0; k < 4; k++)
            for (int desc = 0; desc <= 1; desc++) {
                CHECK(sw_sort_products(e, algos[a], keys[k], desc, idx, 6, &st) == SW_OK);
                CHECK(is_sorted(sample, idx, 6, keys[k], desc));
            }
    sw_engine_destroy(e);

    /* 600 items with only 10 distinct quantities: many duplicate keys. */
    static Product many[600];
    for (int i = 0; i < 600; i++)
        many[i] = make(i + 1, "x", (i * 37) % 101, (i * 7) % 10, 1, 1, 1);
    e = sw_engine_create(many, 600, 0, NULL);
    static int32_t big[600];
    for (int a = 0; a < 2; a++) {
        CHECK(sw_sort_products(e, algos[a], SW_KEY_QUANTITY, 0, big, 600, &st) == SW_OK);
        CHECK(is_sorted(many, big, 600, SW_KEY_QUANTITY, 0));
        CHECK(st.comparisons < 600 * 30); /* ~n log n, far below n^2 = 360000 */
        CHECK(sw_sort_products(e, algos[a], SW_KEY_PRICE, 1, big, 600, &st) == SW_OK);
        CHECK(is_sorted(many, big, 600, SW_KEY_PRICE, 1));
    }
    /* Already-sorted input is quick sort's classic worst case; median-of-three avoids it. */
    CHECK(sw_sort_products(e, SW_ALGO_QUICK, SW_KEY_ID, 0, big, 600, &st) == SW_OK);
    CHECK(is_sorted(many, big, 600, SW_KEY_ID, 0) && st.comparisons < 600 * 30);
    sw_engine_destroy(e);
}

static int avl_check(const AvlNodeInfo *n, int32_t i, const Product *items)
{
    if (i < 0) return 0;
    int hl = avl_check(n, n[i].left, items), hr = avl_check(n, n[i].right, items);
    if (hl < 0 || hr < 0 || hl - hr > 1 || hr - hl > 1) return -1; /* AVL balance rule */
    if (n[i].left >= 0 && items[n[n[i].left].product_index].price >
                              items[n[i].product_index].price) return -1; /* BST order */
    if (n[i].right >= 0 && items[n[n[i].right].product_index].price <
                               items[n[i].product_index].price) return -1;
    return 1 + (hl > hr ? hl : hr);
}

static void test_avl(void)
{
    /* Ascending prices would make a plain BST a linked list of height 1000. */
    static Product items[1000];
    for (int i = 0; i < 1000; i++) items[i] = make(i + 1, "x", i * 0.5, 1, 1, 1, 1);
    SwEngine *e = sw_engine_create(items, 1000, 0, NULL);
    IndexStats is;
    CHECK(sw_index_stats(e, &is) == SW_OK);
    CHECK(is.avl_nodes == 1000 && is.avl_height <= 14 && is.avl_rotations > 0);

    static AvlNodeInfo snap[1000];
    int32_t count = 0;
    CHECK(sw_avl_snapshot(e, snap, 1000, &count) == SW_OK && count == 1000);
    CHECK(avl_check(snap, 0, items) == is.avl_height);

    static int32_t out[1000];
    int64_t visited = 0;
    CHECK(sw_price_range(e, 10.0, 20.0, out, 1000, &count, &visited) == SW_OK);
    CHECK(count == 21 && visited < 100); /* prices 10.0, 10.5, ..., 20.0 */
    for (int i = 0; i < count; i++) CHECK(items[out[i]].price == 10.0 + i * 0.5);
    CHECK(sw_price_range(e, 1000, 2000, out, 1000, &count, &visited) == SW_ERR_NOT_FOUND);
    CHECK(count == 0);
    CHECK(sw_price_range(e, 5, 1, out, 1000, &count, &visited) == SW_ERR_INVALID_VALUE);
    CHECK(sw_price_range(e, 0, 1, out, 10, &count, &visited) == SW_ERR_BUFFER_TOO_SMALL);
    sw_engine_destroy(e);

    e = sw_engine_create(sample, 6, 0, NULL); /* ties: Widget 2.5, others distinct */
    CHECK(sw_price_range(e, 0, 1e9, out, 6, &count, &visited) == SW_OK && count == 6);
    for (int i = 1; i < count; i++) CHECK(sample[out[i - 1]].price <= sample[out[i]].price);
    sw_engine_destroy(e);

    e = sw_engine_create(NULL, 0, 0, NULL);
    CHECK(sw_price_range(e, 0, 10, out, 0, &count, &visited) == SW_ERR_NOT_FOUND);
    sw_engine_destroy(e);
}

static void test_trie(void)
{
    SwEngine *e = sw_engine_create(sample, 6, 0, NULL);
    int32_t out[6], count = 0;
    int64_t visited = 0;
    CHECK(sw_prefix_search(e, "APP", out, 6, &count, &visited) == SW_OK);
    CHECK(count == 2 && out[0] == 1 && out[1] == 4); /* apple juice < apple pie */
    CHECK(sw_prefix_search(e, "pie", out, 6, &count, &visited) == SW_OK); /* word start */
    CHECK(count == 1 && out[0] == 4);
    CHECK(sw_prefix_search(e, "bol", out, 6, &count, &visited) == SW_OK && out[0] == 2);
    CHECK(sw_prefix_search(e, "idget", out, 6, &count, &visited) == SW_ERR_NOT_FOUND);
    CHECK(sw_prefix_search(e, "xyz", out, 6, &count, &visited) == SW_ERR_NOT_FOUND);
    CHECK(count == 0);
    CHECK(sw_prefix_search(e, "", out, 6, &count, &visited) == SW_ERR_INVALID_VALUE);
    IndexStats is;
    sw_index_stats(e, &is);
    CHECK(is.trie_keys == 8 && is.trie_nodes > 8); /* 6 names, 2 with two words */
    sw_engine_destroy(e);

    Product dup[2] = {make(1, "Cable Cable", 1, 1, 1, 1, 1), make(2, "USB-C cable", 1, 1, 1, 1, 1)};
    e = sw_engine_create(dup, 2, 0, NULL);
    CHECK(sw_prefix_search(e, "cab", out, 2, &count, &visited) == SW_OK);
    CHECK(count == 2 && out[0] == 0 && out[1] == 1); /* each product listed once */
    CHECK(sw_prefix_search(e, "c", out, 2, &count, &visited) == SW_OK && count == 2);
    sw_engine_destroy(e);
}

static void test_knapsack(void)
{
    int32_t costs[] = {1, 3, 4, 5};
    double values[] = {1, 4, 5, 7};
    uint8_t chosen[4];
    double best = 0, table[5 * 8];
    OpStats st;
    CHECK(sw_knapsack(costs, values, 4, 7, chosen, &best, table, &st) == SW_OK);
    CHECK(best == 9 && !chosen[0] && chosen[1] && chosen[2] && !chosen[3]); /* 3 + 4 */
    CHECK(table[4 * 8 + 7] == 9 && table[1 * 8 + 7] == 1 && table[0 * 8 + 7] == 0);
    CHECK(st.comparisons == 7 + 5 + 4 + 3);

    /* Greedy by ratio takes cost 5 (ratio 1.4) first, then cost 1: value 8, not 9. */
    CHECK(sw_knapsack_greedy(costs, values, 4, 7, chosen, &best, &st) == SW_OK);
    CHECK(best == 8 && chosen[0] && !chosen[1] && !chosen[2] && chosen[3]);

    CHECK(sw_knapsack(costs, values, 4, 0, chosen, &best, NULL, &st) == SW_OK && best == 0);
    CHECK(sw_knapsack(NULL, NULL, 0, 10, NULL, &best, NULL, &st) == SW_OK && best == 0);
    int32_t bad_cost[] = {-1};
    CHECK(sw_knapsack(bad_cost, values, 1, 5, chosen, &best, NULL, &st) == SW_ERR_INVALID_VALUE);
    CHECK(sw_knapsack(costs, values, 4, -1, chosen, &best, NULL, &st) == SW_ERR_INVALID_VALUE);
    CHECK(sw_knapsack(costs, values, 4, 10000000, chosen, &best, NULL, &st) ==
          SW_ERR_INVALID_VALUE); /* 4 * 10M cells is over the limit */
}

static void test_graph(void)
{
    Edge edges[] = {{0, 1, 4}, {0, 2, 1}, {2, 1, 2}, {1, 3, 1}, {2, 3, 5}};
    int32_t dist[5], path[5], len = 0;
    OpStats st;
    CHECK(sw_shortest_path(5, edges, 5, 0, 3, dist, path, &len, &st) == SW_OK);
    CHECK(dist[3] == 4 && dist[1] == 3 && dist[2] == 1 && dist[0] == 0);
    CHECK(len == 4 && path[0] == 0 && path[1] == 2 && path[2] == 1 && path[3] == 3);
    CHECK(dist[4] == SW_UNREACHABLE);
    CHECK(sw_shortest_path(5, edges, 5, 0, 4, dist, path, &len, &st) == SW_ERR_NOT_FOUND);
    CHECK(len == 0);
    CHECK(sw_shortest_path(5, edges, 5, 3, 3, dist, path, &len, &st) == SW_OK && len == 1);
    CHECK(sw_shortest_path(5, edges, 5, 0, 9, dist, path, &len, &st) == SW_ERR_INVALID_VALUE);
    Edge bad[] = {{0, 1, 0}};
    CHECK(sw_shortest_path(2, bad, 1, 0, 1, dist, path, &len, &st) == SW_ERR_INVALID_VALUE);
    CHECK(sw_shortest_path(0, edges, 0, 0, 0, dist, path, &len, &st) == SW_ERR_INVALID_LENGTH);
}

static void test_fifo(void)
{
    StockMove moves[] = {{10, 1}, {5, 2}, {-12, 3}, {7, 4}};
    StockLot lots[3];
    int32_t n = 0;
    OpStats st;
    CHECK(sw_fifo_lots(moves, 4, lots, 3, &n, &st) == SW_OK);
    CHECK(n == 2 && lots[0].quantity == 3 && lots[0].received == 2);
    CHECK(lots[1].quantity == 7 && lots[1].received == 4);

    StockMove over[] = {{2, 1}, {-3, 2}};
    CHECK(sw_fifo_lots(over, 2, lots, 3, &n, &st) == SW_ERR_INVALID_VALUE);
    StockMove backwards[] = {{2, 5}, {1, 4}};
    CHECK(sw_fifo_lots(backwards, 2, lots, 3, &n, &st) == SW_ERR_INVALID_VALUE);
    CHECK(sw_fifo_lots(moves, 4, lots, 2, &n, &st) == SW_ERR_BUFFER_TOO_SMALL);
    CHECK(sw_fifo_lots(NULL, 0, NULL, 0, &n, &st) == SW_OK && n == 0);

    /* Force the ring buffer to wrap around and then grow past its first 4 slots. */
    StockMove ring[9] = {{1, 1}, {1, 2}, {1, 3}, {-2, 4}, {1, 5}, {1, 6}, {1, 7}, {1, 8}, {1, 9}};
    StockLot many[8];
    CHECK(sw_fifo_lots(ring, 9, many, 8, &n, &st) == SW_OK && n == 6);
    for (int i = 0; i < n; i++) CHECK(many[i].received == (i == 0 ? 3 : i + 4));
}

int main(void)
{
    fill_sample();
    test_searches();
    test_empty_and_invalid();
    test_hash_collisions();
    test_sorting();
    test_heap();
    test_restock();
    test_quick_and_heap_sort();
    test_avl();
    test_trie();
    test_knapsack();
    test_graph();
    test_fifo();
    printf("%d/%d checks passed\n", checks - failures, checks);
    return failures == 0 ? 0 : 1;
}
