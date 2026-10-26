/* max_heap.c - array-based binary Max-Heap used as a priority queue.
 * For node i: parent = (i-1)/2, left = 2i+1, right = 2i+2. */
#include <stdlib.h>
#include <string.h>

#include "inventory_types.h"

struct MaxHeap {
    RestockItem *data;
    int32_t size;
    int32_t capacity;
    int64_t comparisons;
    int64_t swaps;
};

MaxHeap *heap_create(int32_t capacity)
{
    if (capacity < 0) return NULL;
    MaxHeap *h = malloc(sizeof *h);
    if (h == NULL) return NULL;
    /* Allocate at least one slot so an empty heap still has a valid buffer. */
    h->data = malloc((size_t)(capacity > 0 ? capacity : 1) * sizeof *h->data);
    if (h->data == NULL) {
        free(h);
        return NULL;
    }
    h->size = 0;
    h->capacity = capacity;
    h->comparisons = h->swaps = 0;
    return h;
}

/* Higher score wins; equal scores fall back to the smaller product id so the
 * order is deterministic. */
static int higher_priority(MaxHeap *h, const RestockItem *a, const RestockItem *b)
{
    h->comparisons++;
    if (a->score != b->score) return a->score > b->score;
    return a->product_id < b->product_id;
}

static void swap_items(MaxHeap *h, int32_t i, int32_t j)
{
    RestockItem t = h->data[i];
    h->data[i] = h->data[j];
    h->data[j] = t;
    h->swaps++;
}

/* O(log n): append at the end, then sift up while the parent is smaller. */
int32_t heap_push(MaxHeap *h, const RestockItem *item)
{
    if (h == NULL || item == NULL) return SW_ERR_NULL_POINTER;
    if (h->size >= h->capacity) return SW_ERR_BUFFER_TOO_SMALL;

    int32_t i = h->size++;
    h->data[i] = *item;
    while (i > 0) {
        int32_t parent = (i - 1) / 2;
        if (!higher_priority(h, &h->data[i], &h->data[parent])) break;
        swap_items(h, i, parent);
        i = parent;
    }
    return SW_OK;
}

/* O(log n): take the root, move the last item to the root, sift down. */
int32_t heap_pop(MaxHeap *h, RestockItem *out)
{
    if (h == NULL || out == NULL) return SW_ERR_NULL_POINTER;
    if (h->size == 0) return SW_ERR_NOT_FOUND;

    *out = h->data[0];
    h->data[0] = h->data[--h->size];
    int32_t i = 0;
    for (;;) {
        int32_t left = 2 * i + 1, right = left + 1, largest = i;
        if (left < h->size && higher_priority(h, &h->data[left], &h->data[largest]))
            largest = left;
        if (right < h->size && higher_priority(h, &h->data[right], &h->data[largest]))
            largest = right;
        if (largest == i) break;
        swap_items(h, i, largest);
        i = largest;
    }
    return SW_OK;
}

int32_t heap_size(const MaxHeap *h)
{
    return h == NULL ? 0 : h->size;
}

int32_t heap_snapshot(const MaxHeap *h, RestockItem *out, int32_t capacity)
{
    if (h == NULL || out == NULL) return SW_ERR_NULL_POINTER;
    if (capacity < h->size) return SW_ERR_BUFFER_TOO_SMALL;
    if (h->size > 0) memcpy(out, h->data, (size_t)h->size * sizeof *out);
    return SW_OK;
}

void heap_stats(const MaxHeap *h, OpStats *out)
{
    if (h == NULL || out == NULL) return;
    out->comparisons = h->comparisons;
    out->moves = h->swaps;
}

void heap_destroy(MaxHeap *h)
{
    if (h == NULL) return;
    free(h->data);
    free(h);
}
