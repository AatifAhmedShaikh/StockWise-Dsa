/* avl_tree.c - AVL tree (self-balancing binary search tree) keyed by price.
 *
 * Nodes live in one array and refer to each other by array position (-1 = no
 * child), so the whole tree is freed with two calls. Equal prices are ordered
 * by product id, which keeps every key unique. After each insertion, a node
 * whose subtrees differ in height by more than 1 is fixed with one or two
 * rotations, so the height stays O(log n). */
#include <math.h>
#include <stdlib.h>

#include "inventory_types.h"

typedef struct {
    int32_t index;  /* product position in the engine array */
    int32_t left, right;
    int32_t height;
} AvlNode;

struct AvlTree {
    const Product *items;
    AvlNode *nodes;
    int32_t size, capacity, root, rotations;
};

AvlTree *avl_create(const Product *items, int32_t capacity)
{
    if (capacity < 0 || (items == NULL && capacity > 0)) return NULL;
    AvlTree *t = malloc(sizeof *t);
    if (t == NULL) return NULL;
    t->nodes = malloc((size_t)(capacity > 0 ? capacity : 1) * sizeof *t->nodes);
    if (t->nodes == NULL) {
        free(t);
        return NULL;
    }
    t->items = items;
    t->size = t->rotations = 0;
    t->capacity = capacity;
    t->root = -1;
    return t;
}

static int32_t height(const AvlTree *t, int32_t n)
{
    return n < 0 ? 0 : t->nodes[n].height;
}

static void update_height(AvlTree *t, int32_t n)
{
    int32_t hl = height(t, t->nodes[n].left), hr = height(t, t->nodes[n].right);
    t->nodes[n].height = 1 + (hl > hr ? hl : hr);
}

/*      y            x
 *     / \          / \
 *    x   C  -->   A   y
 *   / \              / \
 *  A   B            B   C      */
static int32_t rotate_right(AvlTree *t, int32_t y)
{
    int32_t x = t->nodes[y].left;
    t->nodes[y].left = t->nodes[x].right;
    t->nodes[x].right = y;
    update_height(t, y);
    update_height(t, x);
    t->rotations++;
    return x;
}

static int32_t rotate_left(AvlTree *t, int32_t x)
{
    int32_t y = t->nodes[x].right;
    t->nodes[x].right = t->nodes[y].left;
    t->nodes[y].left = x;
    update_height(t, x);
    update_height(t, y);
    t->rotations++;
    return y;
}

/* Fix node n if its balance factor left of [-1, 1]; returns the subtree root. */
static int32_t rebalance(AvlTree *t, int32_t n)
{
    update_height(t, n);
    int32_t l = t->nodes[n].left, r = t->nodes[n].right;
    int32_t balance = height(t, l) - height(t, r);
    if (balance > 1) {                                       /* left heavy */
        if (height(t, t->nodes[l].left) < height(t, t->nodes[l].right))
            t->nodes[n].left = rotate_left(t, l);            /* left-right case */
        return rotate_right(t, n);
    }
    if (balance < -1) {                                      /* right heavy */
        if (height(t, t->nodes[r].right) < height(t, t->nodes[r].left))
            t->nodes[n].right = rotate_right(t, r);          /* right-left case */
        return rotate_left(t, n);
    }
    return n;
}

/* Key order: price first, then id. */
static int key_less(const AvlTree *t, int32_t a, int32_t b)
{
    const Product *pa = &t->items[t->nodes[a].index], *pb = &t->items[t->nodes[b].index];
    if (pa->price != pb->price) return pa->price < pb->price;
    return pa->id < pb->id;
}

static int32_t insert_rec(AvlTree *t, int32_t node, int32_t fresh)
{
    if (node < 0) return fresh;
    if (key_less(t, fresh, node))
        t->nodes[node].left = insert_rec(t, t->nodes[node].left, fresh);
    else
        t->nodes[node].right = insert_rec(t, t->nodes[node].right, fresh);
    return rebalance(t, node);
}

/* O(log n): ordinary BST insert, then rebalance on the way back up. */
int32_t avl_insert(AvlTree *t, int32_t index)
{
    if (t == NULL) return SW_ERR_NULL_POINTER;
    if (t->size >= t->capacity) return SW_ERR_BUFFER_TOO_SMALL;
    int32_t fresh = t->size++;
    t->nodes[fresh] = (AvlNode){index, -1, -1, 1};
    t->root = insert_rec(t, t->root, fresh);
    return SW_OK;
}

/* In-order walk that skips subtrees that cannot contain matches:
 * O(log n + k) for k results. */
static void range_rec(const AvlTree *t, int32_t node, double lo, double hi, int32_t *out,
                      int32_t *count, int64_t *visited)
{
    if (node < 0) return;
    (*visited)++;
    double price = t->items[t->nodes[node].index].price;
    if (price >= lo) range_rec(t, t->nodes[node].left, lo, hi, out, count, visited);
    if (price >= lo && price <= hi) out[(*count)++] = t->nodes[node].index;
    if (price <= hi) range_rec(t, t->nodes[node].right, lo, hi, out, count, visited);
}

int32_t avl_range(const AvlTree *t, double min_price, double max_price, int32_t *out,
                  int32_t capacity, int32_t *out_count, int64_t *visited)
{
    if (t == NULL || out == NULL || out_count == NULL || visited == NULL)
        return SW_ERR_NULL_POINTER;
    if (isnan(min_price) || isnan(max_price) || min_price > max_price)
        return SW_ERR_INVALID_VALUE;
    if (capacity < t->size) return SW_ERR_BUFFER_TOO_SMALL;
    *out_count = 0;
    *visited = 0;
    range_rec(t, t->root, min_price, max_price, out, out_count, visited);
    return *out_count > 0 ? SW_OK : SW_ERR_NOT_FOUND;
}

/* Pre-order copy of the tree; children refer to positions in `out`. */
static int32_t snapshot_rec(const AvlTree *t, int32_t node, AvlNodeInfo *out, int32_t *pos)
{
    if (node < 0) return -1;
    int32_t me = (*pos)++;
    out[me].product_index = t->nodes[node].index;
    out[me].height = t->nodes[node].height;
    out[me].left = snapshot_rec(t, t->nodes[node].left, out, pos);
    out[me].right = snapshot_rec(t, t->nodes[node].right, out, pos);
    return me;
}

int32_t avl_snapshot(const AvlTree *t, AvlNodeInfo *out, int32_t capacity, int32_t *out_count)
{
    if (t == NULL || out_count == NULL || (out == NULL && t->size > 0))
        return SW_ERR_NULL_POINTER;
    if (capacity < t->size) return SW_ERR_BUFFER_TOO_SMALL;
    *out_count = 0;
    snapshot_rec(t, t->root, out, out_count);
    return SW_OK;
}

void avl_stats(const AvlTree *t, IndexStats *out)
{
    if (t == NULL || out == NULL) return;
    out->avl_nodes = t->size;
    out->avl_height = height(t, t->root);
    out->avl_rotations = t->rotations;
}

void avl_destroy(AvlTree *t)
{
    if (t == NULL) return;
    free(t->nodes);
    free(t);
}
