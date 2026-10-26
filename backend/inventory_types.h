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

/* Public functions are exported from the shared library explicitly, so the
 * Windows DLL exposes exactly the sw_* API (other platforms export by default). */
#if defined(_WIN32)
#define SW_EXPORT __declspec(dllexport)
#else
#define SW_EXPORT __attribute__((visibility("default")))
#endif

#define SW_API_VERSION 2
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
#define SW_ALGO_QUICK 2 /* median-of-three, not stable */
#define SW_ALGO_HEAP 3  /* in-place heap sort, not stable */

/* ---------- limits for the planning algorithms ---------- */
#define SW_MAX_KNAPSACK_CELLS 20000000 /* n * (budget + 1) */
#define SW_UNREACHABLE (-1)            /* distance to a node with no path */

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

typedef struct {
    int32_t avl_nodes;
    int32_t avl_height;     /* a single node has height 1 */
    int32_t avl_rotations;  /* rotations performed while building the tree */
    int32_t trie_nodes;
    int32_t trie_keys;      /* word-start suffixes inserted (several per name) */
} IndexStats;

typedef struct {
    int32_t product_index;  /* position in the input array */
    int32_t left;           /* position of the left child in the snapshot, -1 = none */
    int32_t right;          /* position of the right child in the snapshot, -1 = none */
    int32_t height;
} AvlNodeInfo;

typedef struct {
    int32_t from, to;       /* node numbers 0..node_count-1 (undirected edge) */
    int32_t weight;         /* distance, > 0 */
} Edge;

typedef struct {
    int32_t quantity;       /* + for stock in, - for stock out */
    int64_t timestamp;      /* seconds since the epoch; moves must be in time order */
} StockMove;

typedef struct {
    int32_t quantity;       /* units still on hand from this delivery */
    int64_t received;       /* timestamp of the delivery */
} StockLot;

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

/* sorting.c - sort an index array (idx[0..n-1]) by a product key.
 * Merge and insertion sort are stable; quick and heap sort are not. */
int32_t merge_sort_indices(const Product *items, int32_t *idx, int32_t n,
                           int32_t key, int32_t descending, OpStats *stats);
int32_t insertion_sort_indices(const Product *items, int32_t *idx, int32_t n,
                               int32_t key, int32_t descending, OpStats *stats);
int32_t quick_sort_indices(const Product *items, int32_t *idx, int32_t n,
                           int32_t key, int32_t descending, OpStats *stats);
int32_t heap_sort_indices(const Product *items, int32_t *idx, int32_t n,
                          int32_t key, int32_t descending, OpStats *stats);

/* avl_tree.c - self-balancing BST keyed by (price, id), value = array index */
typedef struct AvlTree AvlTree;
AvlTree *avl_create(const Product *items, int32_t capacity);
int32_t avl_insert(AvlTree *t, int32_t index);
/* In-order (ascending price) indices with min_price <= price <= max_price. */
int32_t avl_range(const AvlTree *t, double min_price, double max_price, int32_t *out,
                  int32_t capacity, int32_t *out_count, int64_t *visited);
int32_t avl_snapshot(const AvlTree *t, AvlNodeInfo *out, int32_t capacity, int32_t *out_count);
void avl_stats(const AvlTree *t, IndexStats *out);
void avl_destroy(AvlTree *t);

/* trie.c - prefix tree over every word start of each product name */
typedef struct Trie Trie;
Trie *trie_create(int32_t product_count);
int32_t trie_insert(Trie *t, const char *name, int32_t index);
/* Case-insensitive prefix match; results are alphabetical and de-duplicated. */
int32_t trie_prefix(const Trie *t, const char *prefix, int32_t *out, int32_t capacity,
                    int32_t *out_count, int64_t *visited);
void trie_stats(const Trie *t, IndexStats *out);
void trie_destroy(Trie *t);

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

SW_EXPORT int32_t sw_api_version(void);
SW_EXPORT const char *sw_error_message(int32_t code);

/* bucket_count <= 0 selects an automatic size. Returns NULL on error and
 * stores the reason in *error_out (if error_out is not NULL). */
SW_EXPORT SwEngine *sw_engine_create(const Product *products, int32_t count,
                           int32_t bucket_count, int32_t *error_out);
SW_EXPORT void sw_engine_destroy(SwEngine *engine);
SW_EXPORT int32_t sw_engine_count(const SwEngine *engine);

/* Searches return SW_OK when found, SW_ERR_NOT_FOUND when missing. */
SW_EXPORT int32_t sw_linear_search_id(const SwEngine *engine, int32_t id, SearchResult *out);
SW_EXPORT int32_t sw_binary_search_id(const SwEngine *engine, int32_t id, SearchResult *out);
SW_EXPORT int32_t sw_hash_search_id(const SwEngine *engine, int32_t id, SearchResult *out);
SW_EXPORT int32_t sw_linear_search_name(const SwEngine *engine, const char *query,
                              int32_t *out_indices, int32_t capacity,
                              int32_t *out_count, int64_t *comparisons);

SW_EXPORT int32_t sw_sort_products(const SwEngine *engine, int32_t algorithm, int32_t key,
                         int32_t descending, int32_t *out_indices, int32_t capacity,
                         OpStats *stats);

/* Writes the ranking (highest priority first) to out. heap_snapshot may be
 * NULL; otherwise it receives the heap array before extraction. Both buffers
 * need `capacity` >= sw_engine_count(). */
SW_EXPORT int32_t sw_restock_ranking(const SwEngine *engine, RestockItem *out, int32_t capacity,
                           int32_t *out_count, RestockItem *heap_snapshot,
                           OpStats *stats);

SW_EXPORT int32_t sw_hash_stats(const SwEngine *engine, HashStats *out);
SW_EXPORT int32_t sw_hash_chain_lengths(const SwEngine *engine, int32_t *out, int32_t capacity);

/* AVL tree range query and trie prefix search. Buffers need sw_engine_count()
 * slots. Both return SW_ERR_NOT_FOUND when nothing matches. */
SW_EXPORT int32_t sw_price_range(const SwEngine *engine, double min_price, double max_price,
                       int32_t *out_indices, int32_t capacity, int32_t *out_count,
                       int64_t *nodes_visited);
SW_EXPORT int32_t sw_prefix_search(const SwEngine *engine, const char *prefix, int32_t *out_indices,
                         int32_t capacity, int32_t *out_count, int64_t *nodes_visited);
SW_EXPORT int32_t sw_index_stats(const SwEngine *engine, IndexStats *out);
SW_EXPORT int32_t sw_avl_snapshot(const SwEngine *engine, AvlNodeInfo *out, int32_t capacity,
                        int32_t *out_count);

/* ---------- planning algorithms (knapsack.c, graph.c, fifo_queue.c) ----------
 * These are stateless: every input and output buffer belongs to the caller. */

/* 0/1 knapsack by dynamic programming. chosen_out[i] = 1 if item i is picked.
 * table_out may be NULL; otherwise it receives the (n+1) x (budget+1) DP table
 * row by row. stats->comparisons counts DP cells evaluated. */
SW_EXPORT int32_t sw_knapsack(const int32_t *costs, const double *values, int32_t n, int32_t budget,
                    uint8_t *chosen_out, double *best_value_out, double *table_out,
                    OpStats *stats);
/* Greedy by value/cost ratio (uses the Max-Heap). Fast but not always optimal. */
SW_EXPORT int32_t sw_knapsack_greedy(const int32_t *costs, const double *values, int32_t n,
                           int32_t budget, uint8_t *chosen_out, double *best_value_out,
                           OpStats *stats);

/* Dijkstra on an undirected weighted graph. dist_out and path_out hold
 * node_count entries; unreachable nodes get SW_UNREACHABLE. path_out lists the
 * route source..target. Returns SW_ERR_NOT_FOUND if target is unreachable. */
SW_EXPORT int32_t sw_shortest_path(int32_t node_count, const Edge *edges, int32_t edge_count,
                         int32_t source, int32_t target, int32_t *dist_out,
                         int32_t *path_out, int32_t *path_len_out, OpStats *stats);

/* FIFO stock lots: replays moves through a circular queue (stock in = enqueue,
 * stock out = consume from the front). lots_out needs one slot per stock-in move.
 * Returns SW_ERR_INVALID_VALUE if a move removes more than is on hand. */
SW_EXPORT int32_t sw_fifo_lots(const StockMove *moves, int32_t n, StockLot *lots_out, int32_t capacity,
                     int32_t *lot_count, OpStats *stats);

#endif /* INVENTORY_TYPES_H */
