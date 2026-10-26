/* knapsack.c - choose which products to restock within a budget.
 *
 * Each candidate has a cost (whole currency units) and a value (its priority
 * score). The 0/1 knapsack problem picks the subset with the largest total
 * value whose cost fits the budget. Dynamic programming solves it exactly in
 * O(n * W); the greedy ratio heuristic is faster but can miss the optimum. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "inventory_types.h"

static int32_t validate(const int32_t *costs, const double *values, int32_t n, int32_t budget,
                        const uint8_t *chosen, const double *best, const OpStats *stats)
{
    if (best == NULL || stats == NULL ||
        ((costs == NULL || values == NULL || chosen == NULL) && n > 0))
        return SW_ERR_NULL_POINTER;
    if (n < 0) return SW_ERR_INVALID_LENGTH;
    if (budget < 0) return SW_ERR_INVALID_VALUE;
    for (int32_t i = 0; i < n; i++)
        if (costs[i] < 0 || !isfinite(values[i]) || values[i] < 0) return SW_ERR_INVALID_VALUE;
    return SW_OK;
}

/* dp[w] = best value using the items seen so far with total cost <= w.
 * Item i either stays out (dp[w]) or goes in (dp[w - cost] + value).
 * Iterating w downwards lets one array hold both the old and new rows.
 * keep[i][w] records the choice so the chosen set can be rebuilt. */
int32_t sw_knapsack(const int32_t *costs, const double *values, int32_t n, int32_t budget,
                    uint8_t *chosen_out, double *best_value_out, double *table_out,
                    OpStats *stats)
{
    int32_t err = validate(costs, values, n, budget, chosen_out, best_value_out, stats);
    if (err != SW_OK) return err;
    int64_t width = (int64_t)budget + 1;
    if ((int64_t)n * width > SW_MAX_KNAPSACK_CELLS) return SW_ERR_INVALID_VALUE;

    double *dp = calloc((size_t)width, sizeof *dp);
    uint8_t *keep = calloc((size_t)(n > 0 ? n * width : 1), 1);
    if (dp == NULL || keep == NULL) {
        free(dp);
        free(keep);
        return SW_ERR_NO_MEMORY;
    }
    stats->comparisons = stats->moves = 0;
    if (table_out != NULL) memset(table_out, 0, (size_t)width * sizeof *table_out);

    for (int32_t i = 0; i < n; i++) {
        for (int64_t w = budget; w >= costs[i]; w--) {
            stats->comparisons++;
            double with_item = dp[w - costs[i]] + values[i];
            if (with_item > dp[w] + 1e-9) { /* epsilon: ignore float rounding ties */
                dp[w] = with_item;
                keep[i * width + w] = 1;
            }
        }
        if (table_out != NULL)
            memcpy(table_out + (i + 1) * width, dp, (size_t)width * sizeof *dp);
    }

    int64_t w = budget; /* walk back from the full budget */
    for (int32_t i = n - 1; i >= 0; i--) {
        chosen_out[i] = keep[i * width + w];
        if (chosen_out[i]) {
            w -= costs[i];
            stats->moves++;
        }
    }
    *best_value_out = dp[budget];
    free(dp);
    free(keep);
    return SW_OK;
}

/* Take items in order of value per unit cost while they still fit. The
 * Max-Heap supplies that order: score = value / cost. O(n log n). */
int32_t sw_knapsack_greedy(const int32_t *costs, const double *values, int32_t n,
                           int32_t budget, uint8_t *chosen_out, double *best_value_out,
                           OpStats *stats)
{
    int32_t err = validate(costs, values, n, budget, chosen_out, best_value_out, stats);
    if (err != SW_OK) return err;
    MaxHeap *heap = heap_create(n);
    if (heap == NULL) return SW_ERR_NO_MEMORY;

    for (int32_t i = 0; i < n; i++) {
        RestockItem item = {0};
        item.product_index = item.product_id = i;
        item.score = costs[i] > 0 ? values[i] / costs[i] : 1e300; /* free items first */
        heap_push(heap, &item); /* cannot fail: capacity == n */
        chosen_out[i] = 0;
    }
    int64_t remaining = budget;
    double total = 0;
    RestockItem top;
    while (heap_pop(heap, &top) == SW_OK) {
        int32_t i = top.product_index;
        if (costs[i] <= remaining) {
            chosen_out[i] = 1;
            remaining -= costs[i];
            total += values[i];
        }
    }
    *best_value_out = total;
    heap_stats(heap, stats);
    heap_destroy(heap);
    return SW_OK;
}
