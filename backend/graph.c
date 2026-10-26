/* graph.c - delivery routes: Dijkstra's shortest path on a weighted graph.
 *
 * The edge list is turned into an adjacency list in CSR form (one array of
 * neighbours plus an offset per node), then Dijkstra runs with a priority
 * queue. The queue is the project's Max-Heap storing -distance, so the
 * largest score is the smallest distance: a max-heap on negated keys is a
 * min-heap. Outdated queue entries are skipped when popped ("lazy deletion"). */
#include <stdlib.h>

#include "inventory_types.h"

int32_t sw_shortest_path(int32_t node_count, const Edge *edges, int32_t edge_count,
                         int32_t source, int32_t target, int32_t *dist_out,
                         int32_t *path_out, int32_t *path_len_out, OpStats *stats)
{
    if (dist_out == NULL || path_out == NULL || path_len_out == NULL || stats == NULL ||
        (edges == NULL && edge_count > 0))
        return SW_ERR_NULL_POINTER;
    if (node_count <= 0 || edge_count < 0) return SW_ERR_INVALID_LENGTH;
    if (source < 0 || source >= node_count || target < 0 || target >= node_count)
        return SW_ERR_INVALID_VALUE;
    for (int32_t e = 0; e < edge_count; e++)
        if (edges[e].from < 0 || edges[e].from >= node_count || edges[e].to < 0 ||
            edges[e].to >= node_count || edges[e].weight <= 0)
            return SW_ERR_INVALID_VALUE;

    /* CSR adjacency: neighbours of u are adj_to[offset[u] .. offset[u+1]). */
    int32_t *offset = calloc((size_t)node_count + 1, sizeof *offset);
    int32_t *adj_to = malloc((size_t)(2 * edge_count + 1) * sizeof *adj_to);
    int32_t *adj_w = malloc((size_t)(2 * edge_count + 1) * sizeof *adj_w);
    int32_t *fill = malloc((size_t)node_count * sizeof *fill);
    int32_t *prev = malloc((size_t)node_count * sizeof *prev);
    int64_t *dist = malloc((size_t)node_count * sizeof *dist);
    MaxHeap *queue = heap_create(2 * edge_count + 1); /* <= 1 push per relaxation + source */
    int32_t err = SW_OK;
    if (!offset || !adj_to || !adj_w || !fill || !prev || !dist || !queue) {
        err = SW_ERR_NO_MEMORY;
        goto done;
    }

    for (int32_t e = 0; e < edge_count; e++) {
        offset[edges[e].from + 1]++;
        offset[edges[e].to + 1]++;
    }
    for (int32_t u = 0; u < node_count; u++) {
        offset[u + 1] += offset[u];
        fill[u] = offset[u];
        dist[u] = INT64_MAX;
        prev[u] = -1;
    }
    for (int32_t e = 0; e < edge_count; e++) { /* undirected: store both directions */
        int32_t a = edges[e].from, b = edges[e].to;
        adj_to[fill[a]] = b;
        adj_w[fill[a]++] = edges[e].weight;
        adj_to[fill[b]] = a;
        adj_w[fill[b]++] = edges[e].weight;
    }

    int64_t relaxations = 0;
    RestockItem item = {0};
    dist[source] = 0;
    item.product_index = item.product_id = source;
    heap_push(queue, &item);
    while (heap_pop(queue, &item) == SW_OK) {
        int32_t u = item.product_index;
        int64_t d = (int64_t)(-item.score);
        if (d > dist[u]) continue; /* stale entry: u was already settled closer */
        for (int32_t k = offset[u]; k < offset[u + 1]; k++) {
            int32_t v = adj_to[k];
            int64_t nd = d + adj_w[k];
            if (nd < dist[v]) { /* relax edge u -> v */
                dist[v] = nd;
                prev[v] = u;
                relaxations++;
                RestockItem next = {0};
                next.product_index = next.product_id = v;
                next.score = -(double)nd;
                heap_push(queue, &next);
            }
        }
    }

    for (int32_t u = 0; u < node_count; u++)
        dist_out[u] = dist[u] == INT64_MAX ? SW_UNREACHABLE
                      : dist[u] > INT32_MAX ? INT32_MAX : (int32_t)dist[u];

    *path_len_out = 0;
    if (dist[target] == INT64_MAX) {
        err = SW_ERR_NOT_FOUND;
    } else { /* follow prev[] back from the target, then reverse */
        for (int32_t v = target; v >= 0; v = prev[v]) path_out[(*path_len_out)++] = v;
        for (int32_t i = 0, j = *path_len_out - 1; i < j; i++, j--) {
            int32_t t = path_out[i];
            path_out[i] = path_out[j];
            path_out[j] = t;
        }
    }
    heap_stats(queue, stats);
    stats->moves = relaxations;

done:
    free(offset);
    free(adj_to);
    free(adj_w);
    free(fill);
    free(prev);
    free(dist);
    heap_destroy(queue);
    return err;
}
