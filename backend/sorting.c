/* sorting.c - Merge, Insertion, Quick and Heap Sort on an array of product indices.
 * Sorting indices (not whole records) keeps the caller's data untouched and
 * makes each "move" a cheap 4-byte write. Merge and Insertion Sort are stable. */
#include <ctype.h>
#include <stdlib.h>

#include "inventory_types.h"

static int compare_names(const char *a, const char *b)
{
    while (*a != '\0' && *b != '\0') {
        int ca = tolower((unsigned char)*a), cb = tolower((unsigned char)*b);
        if (ca != cb) return ca < cb ? -1 : 1;
        a++;
        b++;
    }
    return (*a != '\0') - (*b != '\0');
}

static int compare_doubles(double a, double b)
{
    return (a > b) - (a < b);
}

/* Returns <0, 0, >0 like strcmp; counts one comparison. */
static int compare_products(const Product *a, const Product *b, int32_t key,
                            int32_t descending, OpStats *stats)
{
    int result;
    stats->comparisons++;
    switch (key) {
    case SW_KEY_NAME: result = compare_names(a->name, b->name); break;
    case SW_KEY_PRICE: result = compare_doubles(a->price, b->price); break;
    case SW_KEY_QUANTITY: result = (a->quantity > b->quantity) - (a->quantity < b->quantity); break;
    case SW_KEY_VALUE:
        result = compare_doubles(a->price * a->quantity, b->price * b->quantity);
        break;
    default: result = (a->id > b->id) - (a->id < b->id); break;
    }
    return descending ? -result : result;
}

static int valid_args(const Product *items, const int32_t *idx, int32_t n, int32_t key,
                      OpStats *stats)
{
    if (stats == NULL || ((items == NULL || idx == NULL) && n > 0)) return SW_ERR_NULL_POINTER;
    if (n < 0) return SW_ERR_INVALID_LENGTH;
    if (key < SW_KEY_ID || key > SW_KEY_VALUE) return SW_ERR_INVALID_VALUE;
    return SW_OK;
}

/* Merge idx[lo..mid) and idx[mid..hi) using tmp as scratch space. */
static void merge(const Product *items, int32_t *idx, int32_t *tmp, int32_t lo, int32_t mid,
                  int32_t hi, int32_t key, int32_t descending, OpStats *stats)
{
    int32_t i = lo, j = mid, k = lo;
    while (i < mid && j < hi) {
        /* "<= 0" takes from the left run on ties, which keeps the sort stable. */
        if (compare_products(&items[idx[i]], &items[idx[j]], key, descending, stats) <= 0)
            tmp[k++] = idx[i++];
        else
            tmp[k++] = idx[j++];
        stats->moves++;
    }
    while (i < mid) { tmp[k++] = idx[i++]; stats->moves++; }
    while (j < hi) { tmp[k++] = idx[j++]; stats->moves++; }
    for (k = lo; k < hi; k++) { idx[k] = tmp[k]; stats->moves++; }
}

static void merge_sort_rec(const Product *items, int32_t *idx, int32_t *tmp, int32_t lo,
                           int32_t hi, int32_t key, int32_t descending, OpStats *stats)
{
    if (hi - lo < 2) return;
    int32_t mid = lo + (hi - lo) / 2;
    merge_sort_rec(items, idx, tmp, lo, mid, key, descending, stats);
    merge_sort_rec(items, idx, tmp, mid, hi, key, descending, stats);
    merge(items, idx, tmp, lo, mid, hi, key, descending, stats);
}

/* O(n log n) time in every case, O(n) extra space. */
int32_t merge_sort_indices(const Product *items, int32_t *idx, int32_t n, int32_t key,
                           int32_t descending, OpStats *stats)
{
    int32_t err = valid_args(items, idx, n, key, stats);
    if (err != SW_OK) return err;
    stats->comparisons = stats->moves = 0;
    if (n < 2) return SW_OK;

    int32_t *tmp = malloc((size_t)n * sizeof *tmp);
    if (tmp == NULL) return SW_ERR_NO_MEMORY;
    merge_sort_rec(items, idx, tmp, 0, n, key, descending, stats);
    free(tmp);
    return SW_OK;
}

/* O(n^2) worst/average, O(n) best (already sorted), O(1) extra space. */
int32_t insertion_sort_indices(const Product *items, int32_t *idx, int32_t n, int32_t key,
                               int32_t descending, OpStats *stats)
{
    int32_t err = valid_args(items, idx, n, key, stats);
    if (err != SW_OK) return err;
    stats->comparisons = stats->moves = 0;

    for (int32_t i = 1; i < n; i++) {
        int32_t current = idx[i];
        int32_t j = i - 1;
        /* Shift larger elements right; strict ">" keeps equal keys in order. */
        while (j >= 0 &&
               compare_products(&items[idx[j]], &items[current], key, descending, stats) > 0) {
            idx[j + 1] = idx[j];
            stats->moves++;
            j--;
        }
        idx[j + 1] = current;
        stats->moves++;
    }
    return SW_OK;
}

static void swap_idx(int32_t *idx, int32_t a, int32_t b, OpStats *stats)
{
    int32_t t = idx[a];
    idx[a] = idx[b];
    idx[b] = t;
    stats->moves += 2;
}

/* Index (into idx) of the median of idx[lo], idx[mid], idx[hi]: a cheap pivot
 * that avoids the O(n^2) worst case on already-sorted input. */
static int32_t median_of_three(const Product *items, const int32_t *idx, int32_t lo,
                               int32_t hi, int32_t key, int32_t descending, OpStats *stats)
{
    int32_t mid = lo + (hi - lo) / 2;
    const Product *a = &items[idx[lo]], *b = &items[idx[mid]], *c = &items[idx[hi]];
    if (compare_products(a, b, key, descending, stats) < 0) {
        if (compare_products(b, c, key, descending, stats) < 0) return mid;
        return compare_products(a, c, key, descending, stats) < 0 ? hi : lo;
    }
    if (compare_products(a, c, key, descending, stats) < 0) return lo;
    return compare_products(b, c, key, descending, stats) < 0 ? hi : mid;
}

/* Three-way partition (Dijkstra's "Dutch national flag"): after it,
 * idx[lo..lt) < pivot, idx[lt..gt] == pivot, idx(gt..hi] > pivot.
 * Equal keys are never recursed into again, so duplicates stay fast. */
static void quick_sort_rec(const Product *items, int32_t *idx, int32_t lo, int32_t hi,
                           int32_t key, int32_t descending, OpStats *stats)
{
    while (lo < hi) {
        const Product *pivot =
            &items[idx[median_of_three(items, idx, lo, hi, key, descending, stats)]];
        int32_t lt = lo, i = lo, gt = hi;
        while (i <= gt) {
            int c = compare_products(&items[idx[i]], pivot, key, descending, stats);
            if (c < 0)
                swap_idx(idx, lt++, i++, stats);
            else if (c > 0)
                swap_idx(idx, i, gt--, stats);
            else
                i++;
        }
        /* Recurse into the smaller side and loop on the larger one, so the
         * recursion depth stays O(log n). */
        if (lt - lo < hi - gt) {
            quick_sort_rec(items, idx, lo, lt - 1, key, descending, stats);
            lo = gt + 1;
        } else {
            quick_sort_rec(items, idx, gt + 1, hi, key, descending, stats);
            hi = lt - 1;
        }
    }
}

/* O(n log n) average, O(n^2) worst case (very unlikely with median-of-three),
 * O(log n) stack space. */
int32_t quick_sort_indices(const Product *items, int32_t *idx, int32_t n, int32_t key,
                           int32_t descending, OpStats *stats)
{
    int32_t err = valid_args(items, idx, n, key, stats);
    if (err != SW_OK) return err;
    stats->comparisons = stats->moves = 0;
    if (n > 1) quick_sort_rec(items, idx, 0, n - 1, key, descending, stats);
    return SW_OK;
}

/* Restore the max-heap property for the subtree rooted at `root` in idx[0..end). */
static void sift_down(const Product *items, int32_t *idx, int32_t root, int32_t end,
                      int32_t key, int32_t descending, OpStats *stats)
{
    for (;;) {
        int32_t child = 2 * root + 1;
        if (child >= end) return;
        if (child + 1 < end &&
            compare_products(&items[idx[child]], &items[idx[child + 1]], key, descending,
                             stats) < 0)
            child++;
        if (compare_products(&items[idx[root]], &items[idx[child]], key, descending,
                             stats) >= 0)
            return;
        swap_idx(idx, root, child, stats);
        root = child;
    }
}

/* O(n log n) in every case, O(1) extra space: build a max-heap, then
 * repeatedly move the maximum to the end of the array. */
int32_t heap_sort_indices(const Product *items, int32_t *idx, int32_t n, int32_t key,
                          int32_t descending, OpStats *stats)
{
    int32_t err = valid_args(items, idx, n, key, stats);
    if (err != SW_OK) return err;
    stats->comparisons = stats->moves = 0;
    for (int32_t start = n / 2 - 1; start >= 0; start--)
        sift_down(items, idx, start, n, key, descending, stats);
    for (int32_t end = n - 1; end > 0; end--) {
        swap_idx(idx, 0, end, stats);
        sift_down(items, idx, 0, end, key, descending, stats);
    }
    return SW_OK;
}
