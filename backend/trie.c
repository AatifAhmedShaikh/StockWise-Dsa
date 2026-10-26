/* trie.c - prefix tree (trie) for product-name autocomplete.
 *
 * Every word start of a name is inserted, so "USB-C Charging Cable" can be
 * found by typing "usb", "charg" or "cab". Children are stored as a sorted
 * linked list (first child / next sibling), which keeps memory small and
 * makes a depth-first walk return results in alphabetical order. Nodes and
 * result entries live in growable arrays and refer to each other by
 * position (-1 = none). */
#include <ctype.h>
#include <stdlib.h>

#include "inventory_types.h"

typedef struct {
    unsigned char c;  /* lowercased byte on the edge into this node */
    int32_t child;    /* first child, children sorted by c */
    int32_t sibling;  /* next child of the same parent */
    int32_t entries;  /* head of the list of products whose key ends here */
} TrieNode;

struct Trie {
    TrieNode *nodes;
    int32_t node_count, node_cap;
    int32_t *entry_product, *entry_next; /* linked lists of product indices */
    int32_t entry_count, entry_cap;
    int32_t product_count;
};

static int grow(void **array, int32_t *cap, size_t elem_size)
{
    int32_t new_cap = *cap * 2;
    void *p = realloc(*array, (size_t)new_cap * elem_size);
    if (p == NULL) return 0;
    *array = p;
    *cap = new_cap;
    return 1;
}

static int32_t new_node(Trie *t, unsigned char c)
{
    if (t->node_count == t->node_cap &&
        !grow((void **)&t->nodes, &t->node_cap, sizeof *t->nodes))
        return -1;
    t->nodes[t->node_count] = (TrieNode){c, -1, -1, -1};
    return t->node_count++;
}

Trie *trie_create(int32_t product_count)
{
    if (product_count < 0) return NULL;
    Trie *t = calloc(1, sizeof *t);
    if (t == NULL) return NULL;
    t->node_cap = t->entry_cap = 64;
    t->nodes = malloc((size_t)t->node_cap * sizeof *t->nodes);
    t->entry_product = malloc((size_t)t->entry_cap * sizeof *t->entry_product);
    t->entry_next = malloc((size_t)t->entry_cap * sizeof *t->entry_next);
    t->product_count = product_count;
    if (t->nodes == NULL || t->entry_product == NULL || t->entry_next == NULL ||
        new_node(t, 0) != 0) { /* node 0 is the root */
        trie_destroy(t);
        return NULL;
    }
    return t;
}

/* Find the child of `parent` labelled c, creating it in sorted position if
 * `create` is set. Counts each sibling looked at in *visited (may be NULL). */
static int32_t find_child(Trie *t, int32_t parent, unsigned char c, int create,
                          int64_t *visited)
{
    int32_t prev = -1, cur = t->nodes[parent].child;
    while (cur >= 0 && t->nodes[cur].c < c) {
        if (visited) (*visited)++;
        prev = cur;
        cur = t->nodes[cur].sibling;
    }
    if (cur >= 0) {
        if (visited) (*visited)++;
        if (t->nodes[cur].c == c) return cur;
    }
    if (!create) return -1;
    int32_t fresh = new_node(t, c);
    if (fresh < 0) return -1;
    t->nodes[fresh].sibling = cur;
    if (prev < 0)
        t->nodes[parent].child = fresh;
    else
        t->nodes[prev].sibling = fresh;
    return fresh;
}

/* O(L) for a key of length L (times the alphabet size in the worst case). */
static int32_t insert_key(Trie *t, const char *key, int32_t index)
{
    int32_t node = 0;
    for (const char *p = key; *p != '\0'; p++) {
        node = find_child(t, node, (unsigned char)tolower((unsigned char)*p), 1, NULL);
        if (node < 0) return SW_ERR_NO_MEMORY;
    }
    if (t->entry_count == t->entry_cap) {
        int32_t cap = t->entry_cap;
        if (!grow((void **)&t->entry_product, &cap, sizeof *t->entry_product) ||
            !grow((void **)&t->entry_next, &t->entry_cap, sizeof *t->entry_next))
            return SW_ERR_NO_MEMORY;
    }
    /* Append, so products sharing a key keep their input order. */
    int32_t fresh = t->entry_count++;
    t->entry_product[fresh] = index;
    t->entry_next[fresh] = -1;
    int32_t *link = &t->nodes[node].entries;
    while (*link >= 0) link = &t->entry_next[*link];
    *link = fresh;
    return SW_OK;
}

int32_t trie_insert(Trie *t, const char *name, int32_t index)
{
    if (t == NULL || name == NULL) return SW_ERR_NULL_POINTER;
    if (index < 0 || index >= t->product_count) return SW_ERR_INVALID_VALUE;
    for (int32_t i = 0; name[i] != '\0'; i++) {
        int word_start = isalnum((unsigned char)name[i]) &&
                         (i == 0 || !isalnum((unsigned char)name[i - 1]));
        if (word_start) {
            int32_t err = insert_key(t, name + i, index);
            if (err != SW_OK) return err;
        }
    }
    return SW_OK;
}

/* Pre-order DFS: a node's own entries first, then children in sorted order,
 * so shorter and alphabetically smaller keys come first. */
static void collect(const Trie *t, int32_t node, uint8_t *seen, int32_t *out, int32_t *count,
                    int64_t *visited)
{
    (*visited)++;
    for (int32_t e = t->nodes[node].entries; e >= 0; e = t->entry_next[e]) {
        int32_t p = t->entry_product[e];
        if (!seen[p]) {
            seen[p] = 1;
            out[(*count)++] = p;
        }
    }
    for (int32_t c = t->nodes[node].child; c >= 0; c = t->nodes[c].sibling)
        collect(t, c, seen, out, count, visited);
}

int32_t trie_prefix(const Trie *t, const char *prefix, int32_t *out, int32_t capacity,
                    int32_t *out_count, int64_t *visited)
{
    if (t == NULL || prefix == NULL || out_count == NULL || visited == NULL ||
        (out == NULL && t->product_count > 0))
        return SW_ERR_NULL_POINTER;
    if (prefix[0] == '\0') return SW_ERR_INVALID_VALUE;
    if (capacity < t->product_count) return SW_ERR_BUFFER_TOO_SMALL;
    *out_count = 0;
    *visited = 0;

    int32_t node = 0;
    for (const char *p = prefix; *p != '\0' && node >= 0; p++)
        node = find_child((Trie *)t, node, (unsigned char)tolower((unsigned char)*p), 0,
                          visited);
    if (node < 0) return SW_ERR_NOT_FOUND;

    uint8_t *seen = calloc((size_t)(t->product_count > 0 ? t->product_count : 1), 1);
    if (seen == NULL) return SW_ERR_NO_MEMORY;
    collect(t, node, seen, out, out_count, visited);
    free(seen);
    return *out_count > 0 ? SW_OK : SW_ERR_NOT_FOUND;
}

void trie_stats(const Trie *t, IndexStats *out)
{
    if (t == NULL || out == NULL) return;
    out->trie_nodes = t->node_count;
    out->trie_keys = t->entry_count;
}

void trie_destroy(Trie *t)
{
    if (t == NULL) return;
    free(t->nodes);
    free(t->entry_product);
    free(t->entry_next);
    free(t);
}
