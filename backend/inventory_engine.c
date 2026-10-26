/* inventory_engine.c - public API exposed to Python through ctypes.
 *
 * The engine is a read-only snapshot of the inventory: Python (SQLite) owns
 * the real data and rebuilds the engine after every change, so the C indexes
 * can never drift from the database. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "inventory_types.h"

struct SwEngine {
    Product *products;  /* engine-owned copy of the caller's array */
    int32_t count;
    int32_t *id_sorted; /* indices ordered by id, used by binary search */
    HashTable *index;   /* id -> array index */
    AvlTree *by_price;  /* price range queries */
    Trie *names;        /* name prefix search */
};

int32_t sw_api_version(void)
{
    return SW_API_VERSION;
}

const char *sw_error_message(int32_t code)
{
    switch (code) {
    case SW_OK: return "OK";
    case SW_ERR_NULL_POINTER: return "a required pointer was NULL";
    case SW_ERR_INVALID_LENGTH: return "array length is negative or too large";
    case SW_ERR_INVALID_VALUE: return "an argument or product field is out of range";
    case SW_ERR_DUPLICATE_ID: return "duplicate product id";
    case SW_ERR_NOT_FOUND: return "not found";
    case SW_ERR_NO_MEMORY: return "out of memory";
    case SW_ERR_BUFFER_TOO_SMALL: return "output buffer is too small";
    default: return "unknown error";
    }
}

static int is_terminated(const char *s, size_t size)
{
    return memchr(s, '\0', size) != NULL;
}

static int32_t validate_product(const Product *p)
{
    if (p->id <= 0 || !isfinite(p->price) || p->price < 0 || p->quantity < 0 ||
        p->min_stock < 0 || p->demand < SW_MISSING ||
        (p->importance != SW_MISSING && (p->importance < 1 || p->importance > 5)) ||
        !is_terminated(p->name, SW_NAME_LEN) || p->name[0] == '\0' ||
        !is_terminated(p->category, SW_CATEGORY_LEN))
        return SW_ERR_INVALID_VALUE;
    return SW_OK;
}

static int is_prime(int32_t n)
{
    if (n < 2) return 0;
    for (int32_t d = 2; (int64_t)d * d <= n; d++)
        if (n % d == 0) return 0;
    return 1;
}

/* Smallest prime >= 2n (load factor <= 0.5), at least 11. Primes spread
 * "k mod m" keys better than round numbers. */
static int32_t auto_bucket_count(int32_t n)
{
    int32_t m = n * 2 > 11 ? n * 2 : 11;
    while (!is_prime(m)) m++;
    return m;
}

static SwEngine *fail(SwEngine *engine, int32_t code, int32_t *error_out)
{
    sw_engine_destroy(engine);
    if (error_out != NULL) *error_out = code;
    return NULL;
}

SwEngine *sw_engine_create(const Product *products, int32_t count, int32_t bucket_count,
                           int32_t *error_out)
{
    if (error_out != NULL) *error_out = SW_OK;
    if (count < 0 || count > SW_MAX_PRODUCTS) return fail(NULL, SW_ERR_INVALID_LENGTH, error_out);
    if (products == NULL && count > 0) return fail(NULL, SW_ERR_NULL_POINTER, error_out);
    if (bucket_count > SW_MAX_BUCKETS) return fail(NULL, SW_ERR_INVALID_VALUE, error_out);
    for (int32_t i = 0; i < count; i++)
        if (validate_product(&products[i]) != SW_OK)
            return fail(NULL, SW_ERR_INVALID_VALUE, error_out);

    SwEngine *engine = calloc(1, sizeof *engine);
    if (engine == NULL) return fail(NULL, SW_ERR_NO_MEMORY, error_out);

    size_t slots = count > 0 ? (size_t)count : 1;
    engine->products = malloc(slots * sizeof *engine->products);
    engine->id_sorted = malloc(slots * sizeof *engine->id_sorted);
    engine->index = ht_create(bucket_count > 0 ? bucket_count : auto_bucket_count(count));
    engine->by_price = avl_create(engine->products, count);
    engine->names = trie_create(count);
    if (engine->products == NULL || engine->id_sorted == NULL || engine->index == NULL ||
        engine->by_price == NULL || engine->names == NULL)
        return fail(engine, SW_ERR_NO_MEMORY, error_out);

    engine->count = count;
    if (count > 0) memcpy(engine->products, products, (size_t)count * sizeof *products);

    /* Build the hash index; it also detects duplicate ids. */
    for (int32_t i = 0; i < count; i++) {
        int32_t err = ht_insert(engine->index, engine->products[i].id, i);
        if (err == SW_OK) err = avl_insert(engine->by_price, i);
        if (err == SW_OK) err = trie_insert(engine->names, engine->products[i].name, i);
        if (err != SW_OK) return fail(engine, err, error_out);
        engine->id_sorted[i] = i;
    }

    /* Binary search needs data ordered by id: sort once with Merge Sort. */
    OpStats ignored;
    int32_t err = merge_sort_indices(engine->products, engine->id_sorted, count, SW_KEY_ID, 0,
                                     &ignored);
    if (err != SW_OK) return fail(engine, err, error_out);
    return engine;
}

void sw_engine_destroy(SwEngine *engine)
{
    if (engine == NULL) return;
    free(engine->products);
    free(engine->id_sorted);
    ht_destroy(engine->index);
    avl_destroy(engine->by_price);
    trie_destroy(engine->names);
    free(engine);
}

int32_t sw_engine_count(const SwEngine *engine)
{
    return engine == NULL ? 0 : engine->count;
}

int32_t sw_linear_search_id(const SwEngine *engine, int32_t id, SearchResult *out)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    return linear_search_id(engine->products, engine->count, id, out);
}

int32_t sw_binary_search_id(const SwEngine *engine, int32_t id, SearchResult *out)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    return binary_search_id(engine->products, engine->id_sorted, engine->count, id, out);
}

int32_t sw_hash_search_id(const SwEngine *engine, int32_t id, SearchResult *out)
{
    if (engine == NULL || out == NULL) return SW_ERR_NULL_POINTER;
    int32_t index;
    int32_t err = ht_find(engine->index, id, &index, &out->comparisons);
    out->index = index;
    out->found = err == SW_OK;
    return err;
}

int32_t sw_linear_search_name(const SwEngine *engine, const char *query, int32_t *out_indices,
                              int32_t capacity, int32_t *out_count, int64_t *comparisons)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    if (capacity < engine->count) return SW_ERR_BUFFER_TOO_SMALL;
    return linear_search_name(engine->products, engine->count, query, out_indices, out_count,
                              comparisons);
}

int32_t sw_sort_products(const SwEngine *engine, int32_t algorithm, int32_t key,
                         int32_t descending, int32_t *out_indices, int32_t capacity,
                         OpStats *stats)
{
    if (engine == NULL || out_indices == NULL || stats == NULL) return SW_ERR_NULL_POINTER;
    if (capacity < engine->count) return SW_ERR_BUFFER_TOO_SMALL;
    for (int32_t i = 0; i < engine->count; i++) out_indices[i] = i;

    if (algorithm == SW_ALGO_MERGE)
        return merge_sort_indices(engine->products, out_indices, engine->count, key, descending,
                                  stats);
    if (algorithm == SW_ALGO_INSERTION)
        return insertion_sort_indices(engine->products, out_indices, engine->count, key,
                                      descending, stats);
    if (algorithm == SW_ALGO_QUICK)
        return quick_sort_indices(engine->products, out_indices, engine->count, key,
                                  descending, stats);
    if (algorithm == SW_ALGO_HEAP)
        return heap_sort_indices(engine->products, out_indices, engine->count, key,
                                 descending, stats);
    return SW_ERR_INVALID_VALUE;
}

/* Priority = 100 * (0.5*shortage + 0.3*demand + 0.2*importance), each in 0..1.
 *   shortage   = (min_stock - quantity) / min_stock, clamped to 0..1
 *                (min_stock == 0: 1 if out of stock, else 0)
 *   demand     = demand / highest demand in the inventory (missing -> 0.5)
 *   importance = (importance - 1) / 4                    (missing -> 0.5)
 * Only products at or below their minimum stock are recommended. */
static RestockItem score_product(const Product *p, int32_t index, int32_t max_demand)
{
    RestockItem item = {0};
    item.product_index = index;
    item.product_id = p->id;

    if (p->min_stock > 0) {
        double s = (double)(p->min_stock - p->quantity) / p->min_stock;
        item.shortage_score = s < 0 ? 0 : (s > 1 ? 1 : s);
    } else {
        item.shortage_score = p->quantity == 0 ? 1.0 : 0.0;
    }

    if (p->demand == SW_MISSING) {
        item.demand_score = SW_NEUTRAL_SCORE;
        item.reasons |= SW_REASON_MISSING_DATA;
    } else {
        item.demand_score = max_demand > 0 ? (double)p->demand / max_demand : 0.0;
        if (item.demand_score >= 0.7) item.reasons |= SW_REASON_HIGH_DEMAND;
    }

    if (p->importance == SW_MISSING) {
        item.importance_score = SW_NEUTRAL_SCORE;
        item.reasons |= SW_REASON_MISSING_DATA;
    } else {
        item.importance_score = (p->importance - 1) / 4.0;
        if (p->importance >= 4) item.reasons |= SW_REASON_HIGH_IMPORTANCE;
    }

    if (p->quantity == 0)
        item.reasons |= SW_REASON_OUT_OF_STOCK;
    else if (p->quantity < p->min_stock)
        item.reasons |= SW_REASON_BELOW_MINIMUM;
    else
        item.reasons |= SW_REASON_AT_MINIMUM;

    item.score = 100.0 * (SW_W_SHORTAGE * item.shortage_score +
                          SW_W_DEMAND * item.demand_score +
                          SW_W_IMPORTANCE * item.importance_score);

    /* Refill to the safety level plus one period of demand (or 2x minimum
     * when demand is unknown). Always suggest at least one unit. */
    int64_t cover = p->demand == SW_MISSING ? p->min_stock : p->demand;
    int64_t suggested = (int64_t)p->min_stock + cover - p->quantity;
    if (suggested < 1) suggested = 1;
    item.suggested_qty = suggested > INT32_MAX ? INT32_MAX : (int32_t)suggested;
    return item;
}

int32_t sw_restock_ranking(const SwEngine *engine, RestockItem *out, int32_t capacity,
                           int32_t *out_count, RestockItem *heap_snapshot_out, OpStats *stats)
{
    if (engine == NULL || out == NULL || out_count == NULL || stats == NULL)
        return SW_ERR_NULL_POINTER;
    if (capacity < engine->count) return SW_ERR_BUFFER_TOO_SMALL;

    int32_t max_demand = 0;
    for (int32_t i = 0; i < engine->count; i++)
        if (engine->products[i].demand > max_demand) max_demand = engine->products[i].demand;

    MaxHeap *heap = heap_create(engine->count);
    if (heap == NULL) return SW_ERR_NO_MEMORY;

    for (int32_t i = 0; i < engine->count; i++) {
        const Product *p = &engine->products[i];
        if (p->quantity > p->min_stock) continue; /* stock is healthy */
        RestockItem item = score_product(p, i, max_demand);
        heap_push(heap, &item); /* cannot fail: capacity == product count */
    }

    if (heap_snapshot_out != NULL) heap_snapshot(heap, heap_snapshot_out, capacity);

    int32_t n = 0;
    while (heap_pop(heap, &out[n]) == SW_OK) n++;
    *out_count = n;
    heap_stats(heap, stats);
    heap_destroy(heap);
    return SW_OK;
}

int32_t sw_hash_stats(const SwEngine *engine, HashStats *out)
{
    if (engine == NULL || out == NULL) return SW_ERR_NULL_POINTER;
    ht_stats(engine->index, out);
    return SW_OK;
}

int32_t sw_hash_chain_lengths(const SwEngine *engine, int32_t *out, int32_t capacity)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    return ht_chain_lengths(engine->index, out, capacity);
}

int32_t sw_price_range(const SwEngine *engine, double min_price, double max_price,
                       int32_t *out_indices, int32_t capacity, int32_t *out_count,
                       int64_t *nodes_visited)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    return avl_range(engine->by_price, min_price, max_price, out_indices, capacity, out_count,
                     nodes_visited);
}

int32_t sw_prefix_search(const SwEngine *engine, const char *prefix, int32_t *out_indices,
                         int32_t capacity, int32_t *out_count, int64_t *nodes_visited)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    return trie_prefix(engine->names, prefix, out_indices, capacity, out_count, nodes_visited);
}

int32_t sw_index_stats(const SwEngine *engine, IndexStats *out)
{
    if (engine == NULL || out == NULL) return SW_ERR_NULL_POINTER;
    avl_stats(engine->by_price, out);
    trie_stats(engine->names, out);
    return SW_OK;
}

int32_t sw_avl_snapshot(const SwEngine *engine, AvlNodeInfo *out, int32_t capacity,
                        int32_t *out_count)
{
    if (engine == NULL) return SW_ERR_NULL_POINTER;
    return avl_snapshot(engine->by_price, out, capacity, out_count);
}
