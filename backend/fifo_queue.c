/* fifo_queue.c - FIFO stock lots with a growable circular queue.
 *
 * Inventory is usually sold first-in, first-out: the oldest delivery leaves
 * the shelf first. Replaying a product's transactions through a queue
 * (stock in = enqueue a lot, stock out = consume lots from the front) leaves
 * exactly the lots still on hand and how old each one is. The queue is a
 * ring buffer: head and tail wrap around the array, and when it is full it
 * doubles in size, so enqueue is amortized O(1). */
#include <stdlib.h>

#include "inventory_types.h"

typedef struct {
    StockLot *data;
    int32_t head;     /* position of the front element */
    int32_t size;
    int32_t capacity;
} LotQueue;

static int enqueue(LotQueue *q, StockLot lot)
{
    if (q->size == q->capacity) { /* full: copy into an array twice as big, unwrapped */
        int32_t cap = q->capacity * 2;
        StockLot *bigger = malloc((size_t)cap * sizeof *bigger);
        if (bigger == NULL) return 0;
        for (int32_t i = 0; i < q->size; i++) bigger[i] = q->data[(q->head + i) % q->capacity];
        free(q->data);
        q->data = bigger;
        q->head = 0;
        q->capacity = cap;
    }
    q->data[(q->head + q->size) % q->capacity] = lot;
    q->size++;
    return 1;
}

static void dequeue(LotQueue *q)
{
    q->head = (q->head + 1) % q->capacity;
    q->size--;
}

int32_t sw_fifo_lots(const StockMove *moves, int32_t n, StockLot *lots_out, int32_t capacity,
                     int32_t *lot_count, OpStats *stats)
{
    if (lot_count == NULL || stats == NULL || (moves == NULL && n > 0))
        return SW_ERR_NULL_POINTER;
    if (n < 0) return SW_ERR_INVALID_LENGTH;
    int32_t stock_ins = 0;
    for (int32_t i = 0; i < n; i++) {
        if (moves[i].quantity == 0 || (i > 0 && moves[i].timestamp < moves[i - 1].timestamp))
            return SW_ERR_INVALID_VALUE;
        if (moves[i].quantity > 0) stock_ins++;
    }
    if (capacity < stock_ins) return SW_ERR_BUFFER_TOO_SMALL;
    if (lots_out == NULL && stock_ins > 0) return SW_ERR_NULL_POINTER;

    LotQueue q = {malloc(4 * sizeof(StockLot)), 0, 0, 4};
    if (q.data == NULL) return SW_ERR_NO_MEMORY;
    stats->comparisons = stats->moves = 0;
    int32_t err = SW_OK;

    for (int32_t i = 0; i < n && err == SW_OK; i++) {
        if (moves[i].quantity > 0) {
            if (!enqueue(&q, (StockLot){moves[i].quantity, moves[i].timestamp}))
                err = SW_ERR_NO_MEMORY;
            stats->moves++;
            continue;
        }
        int64_t need = -(int64_t)moves[i].quantity;
        while (need > 0) {
            if (q.size == 0) { /* removing more than is on hand */
                err = SW_ERR_INVALID_VALUE;
                break;
            }
            StockLot *front = &q.data[q.head];
            int32_t take = front->quantity < need ? front->quantity : (int32_t)need;
            front->quantity -= take;
            need -= take;
            stats->comparisons++;
            if (front->quantity == 0) {
                dequeue(&q);
                stats->moves++;
            }
        }
    }

    *lot_count = 0;
    if (err == SW_OK)
        for (int32_t i = 0; i < q.size; i++) lots_out[(*lot_count)++] = q.data[(q.head + i) % q.capacity];
    free(q.data);
    return err;
}
