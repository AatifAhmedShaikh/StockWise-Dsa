/* search.c - linear search and binary search over product records. */
#include <ctype.h>
#include <stddef.h>
#include <string.h>

#include "inventory_types.h"

static void set_result(SearchResult *out, int32_t index, int64_t comparisons)
{
    out->index = index;
    out->found = index >= 0;
    out->comparisons = comparisons;
}

/* O(n): check every element until the id matches. */
int32_t linear_search_id(const Product *items, int32_t n, int32_t id, SearchResult *out)
{
    if (out == NULL || (items == NULL && n > 0)) return SW_ERR_NULL_POINTER;
    if (n < 0) return SW_ERR_INVALID_LENGTH;

    int64_t comparisons = 0;
    for (int32_t i = 0; i < n; i++) {
        comparisons++;
        if (items[i].id == id) {
            set_result(out, i, comparisons);
            return SW_OK;
        }
    }
    set_result(out, -1, comparisons);
    return SW_ERR_NOT_FOUND;
}

/* O(log n): halve the id-sorted range each step. One comparison = one probe. */
int32_t binary_search_id(const Product *items, const int32_t *sorted_idx, int32_t n,
                         int32_t id, SearchResult *out)
{
    if (out == NULL || ((items == NULL || sorted_idx == NULL) && n > 0))
        return SW_ERR_NULL_POINTER;
    if (n < 0) return SW_ERR_INVALID_LENGTH;

    int32_t low = 0, high = n - 1;
    int64_t comparisons = 0;
    while (low <= high) {
        int32_t mid = low + (high - low) / 2; /* avoids (low + high) overflow */
        int32_t mid_id = items[sorted_idx[mid]].id;
        comparisons++;
        if (mid_id == id) {
            set_result(out, sorted_idx[mid], comparisons);
            return SW_OK;
        }
        if (mid_id < id)
            low = mid + 1;
        else
            high = mid - 1;
    }
    set_result(out, -1, comparisons);
    return SW_ERR_NOT_FOUND;
}

/* Case-insensitive "does haystack contain needle". */
static int contains_ignore_case(const char *haystack, const char *needle)
{
    size_t nlen = strlen(needle);
    for (const char *h = haystack; *h != '\0'; h++) {
        size_t k = 0;
        while (k < nlen && h[k] != '\0' &&
               tolower((unsigned char)h[k]) == tolower((unsigned char)needle[k]))
            k++;
        if (k == nlen) return 1;
    }
    return 0;
}

/* O(n * m): every product name is checked; out_idx must hold n entries. */
int32_t linear_search_name(const Product *items, int32_t n, const char *query,
                           int32_t *out_idx, int32_t *out_count, int64_t *comparisons)
{
    if (query == NULL || out_count == NULL || comparisons == NULL ||
        ((items == NULL || out_idx == NULL) && n > 0))
        return SW_ERR_NULL_POINTER;
    if (n < 0) return SW_ERR_INVALID_LENGTH;
    if (query[0] == '\0') return SW_ERR_INVALID_VALUE;

    int32_t count = 0;
    *comparisons = 0;
    for (int32_t i = 0; i < n; i++) {
        (*comparisons)++;
        if (contains_ignore_case(items[i].name, query)) out_idx[count++] = i;
    }
    *out_count = count;
    return count > 0 ? SW_OK : SW_ERR_NOT_FOUND;
}
