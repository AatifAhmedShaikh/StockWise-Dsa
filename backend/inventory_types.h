/*
 * inventory_types.h - shared structures and the public C API of the
 * StockWise DSA engine.
 *
 * Ownership rules (read these before calling from Python/ctypes):
 *   - sw_engine_create() COPIES the caller's Product array. The caller may
 *     free or reuse its array immediately after the call returns.
 *   - The engine owns all of its memory. Release it with sw_engine_destroy()
 *     exactly once. Passing NULL to sw_engine_destroy() is a no-op.
 *   - Every output buffer is allocated by the CALLER. Buffers of indices or
 *     RestockItems must hold at least sw_engine_count() elements; the chain
 *     length buffer must hold at least the bucket count (HashStats.bucket_count).
 *   - Indices returned by the engine refer to positions in the array that was
 *     passed to sw_engine_create() (the same order the caller used).
 *   - sw_error_message() returns a pointer to a static string literal; never
 *     free it.
 *
 * All functions that can fail return an int32_t error code (SW_OK == 0).
 */
#ifndef INVENTORY_TYPES_H
#define INVENTORY_TYPES_H

#include <stdint.h>

#define SW_API_VERSION 1
#define SW_NAME_LEN 64      /* bytes incl. terminating NUL -> max 63 chars */
#define SW_CATEGORY_LEN 32  /* bytes incl. terminating NUL -> max 31 chars */
#define SW_MISSING (-1)     /* value used for an unknown demand/importance */
#define SW_MAX_PRODUCTS 1000000
#define SW_MAX_BUCKETS 10000000

/* ---------- error codes ---------- */
#define SW_OK 0
#define SW_ERR_NULL_POINTER (-1)
#define SW_ERR_INVALID_LENGTH (-2)
#define SW_ERR_INVALID_VALUE (-3)
#define SW_ERR_DUPLICATE_ID (-4)
#define SW_ERR_NOT_FOUND (-5)
#define SW_ERR_NO_MEMORY (-6)
#define SW_ERR_BUFFER_TOO_SMALL (-7)

/* ---------- sort keys and algorithms ---------- */
#define SW_KEY_ID 0
#define SW_KEY_NAME 1
#define SW_KEY_PRICE 2
#define SW_KEY_QUANTITY 3
#define SW_KEY_VALUE 4 /* price * quantity */

#define SW_ALGO_MERGE 0
#define SW_ALGO_INSERTION 1

/* ---------- restock reason flags (bitmask) ---------- */
#define SW_REASON_OUT_OF_STOCK 1u
#define SW_REASON_BELOW_MINIMUM 2u
#define SW_REASON_AT_MINIMUM 4u
#define SW_REASON_HIGH_DEMAND 8u
#define SW_REASON_HIGH_IMPORTANCE 16u
#define SW_REASON_MISSING_DATA 32u

/* ---------- restock formula weights ---------- */
#define SW_W_SHORTAGE 0.5
#define SW_W_DEMAND 0.3
#define SW_W_IMPORTANCE 0.2
#define SW_NEUTRAL_SCORE 0.5 /* used when demand/importance is missing */

/* ---------- shared structures (mirrored in c_bridge.py) ---------- */
typedef struct {
    int32_t id;                    /* > 0, unique */
    char name[SW_NAME_LEN];        /* NUL-terminated */
    char category[SW_CATEGORY_LEN];/* NUL-terminated */
    double price;                  /* >= 0 */
    int32_t quantity;              /* >= 0 */
    int32_t min_stock;             /* >= 0 */
    int32_t demand;                /* units per period, >= 0 or SW_MISSING */
    int32_t importance;            /* 1..5 or SW_MISSING */
} Product;

typedef struct {
    int32_t index;       /* position in the input array, -1 if not found */
    int32_t found;       /* 1 if found, 0 otherwise */
    int64_t comparisons; /* key comparisons performed */
} SearchResult;

typedef struct {
    int64_t comparisons; /* element comparisons */
    int64_t moves;       /* element writes (sorting) or swaps (heap) */
} OpStats;

typedef struct {
    int32_t product_index;   /* position in the input array */
    int32_t product_id;
    double score;            /* 0..100 */
    double shortage_score;   /* 0..1 */
    double demand_score;     /* 0..1 */
    double importance_score; /* 0..1 */
    int32_t suggested_qty;
    uint32_t reasons;        /* SW_REASON_* bitmask */
} RestockItem;

typedef struct {
    int32_t bucket_count;
    int32_t item_count;
    int32_t used_buckets;
    int32_t collisions;     /* items stored in an already-occupied bucket */
    int32_t longest_chain;
    double load_factor;     /* item_count / bucket_count */
} HashStats;

/* ---------- internal module APIs (used by inventory_engine.c and tests) ---------- */

/* search.c - operate on caller-provided arrays */
int32_t linear_search_id(const Product *items, int32_t n, int32_t id, SearchResult *out);
/* `sorted_idx` holds n indices into `items`, ordered by ascending id. */
int32_t binary_search_id(const Product *items, const int32_t *sorted_idx, int32_t n,
                         int32_t id, SearchResult *out);
/* Case-insensitive substring match. Writes up to n matching indices. */
int32_t linear_search_name(const Product *items, int32_t n, const char *query,
                           int32_t *out_idx, int32_t *out_count, int64_t *comparisons);

/* hash_table.c - separate chaining, key = product id, value = array index */
typedef struct HashTable HashTable;
HashTable *ht_create(int32_t bucket_count);
int32_t ht_insert(HashTable *ht, int32_t key, int32_t value);
int32_t ht_find(const HashTable *ht, int32_t key, int32_t *value_out, int64_t *comparisons);
void ht_stats(const HashTable *ht, HashStats *out);
int32_t ht_chain_lengths(const HashTable *ht, int32_t *out, int32_t capacity);
void ht_destroy(HashTable *ht);

/* sorting.c - sort an index array (idx[0..n-1]) by a product key; stable */
int32_t merge_sort_indices(const Product *items, int32_t *idx, int32_t n,
                           int32_t key, int32_t descending, OpStats *stats);
int32_t insertion_sort_indices(const Product *items, int32_t *idx, int32_t n,
                               int32_t key, int32_t descending, OpStats *stats);

/* max_heap.c - max-heap priority queue of RestockItem ordered by score */
typedef struct MaxHeap MaxHeap;
MaxHeap *heap_create(int32_t capacity);
int32_t heap_push(MaxHeap *h, const RestockItem *item);
int32_t heap_pop(MaxHeap *h, RestockItem *out);
int32_t heap_size(const MaxHeap *h);
/* Copies the internal array (level order) into out; out must hold heap_size() items. */
int32_t heap_snapshot(const MaxHeap *h, RestockItem *out, int32_t capacity);
void heap_stats(const MaxHeap *h, OpStats *out);
void heap_destroy(MaxHeap *h);

/* ---------- public engine API (inventory_engine.c, called from Python) ---------- */
typedef struct SwEngine SwEngine;

int32_t sw_api_version(void);
const char *sw_error_message(int32_t code);

/* bucket_count <= 0 selects an automatic size. Returns NULL on error and
 * stores the reason in *error_out (if error_out is not NULL). */
SwEngine *sw_engine_create(const Product *products, int32_t count,
                           int32_t bucket_count, int32_t *error_out);
void sw_engine_destroy(SwEngine *engine);
int32_t sw_engine_count(const SwEngine *engine);

/* Searches return SW_OK when found, SW_ERR_NOT_FOUND when missing. */
int32_t sw_linear_search_id(const SwEngine *engine, int32_t id, SearchResult *out);
int32_t sw_binary_search_id(const SwEngine *engine, int32_t id, SearchResult *out);
int32_t sw_hash_search_id(const SwEngine *engine, int32_t id, SearchResult *out);
int32_t sw_linear_search_name(const SwEngine *engine, const char *query,
                              int32_t *out_indices, int32_t capacity,
                              int32_t *out_count, int64_t *comparisons);

int32_t sw_sort_products(const SwEngine *engine, int32_t algorithm, int32_t key,
                         int32_t descending, int32_t *out_indices, int32_t capacity,
                         OpStats *stats);

/* Writes the ranking (highest priority first) to out. heap_snapshot may be
 * NULL; otherwise it receives the heap array before extraction. Both buffers
 * need `capacity` >= sw_engine_count(). */
int32_t sw_restock_ranking(const SwEngine *engine, RestockItem *out, int32_t capacity,
                           int32_t *out_count, RestockItem *heap_snapshot,
                           OpStats *stats);

int32_t sw_hash_stats(const SwEngine *engine, HashStats *out);
int32_t sw_hash_chain_lengths(const SwEngine *engine, int32_t *out, int32_t capacity);

#endif /* INVENTORY_TYPES_H */
