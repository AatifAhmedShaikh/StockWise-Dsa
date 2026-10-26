/* hash_table.c - hash table with separate chaining (key: product id). */
#include <stdlib.h>

#include "inventory_types.h"

typedef struct HashNode {
    int32_t key;
    int32_t value;
    struct HashNode *next;
} HashNode;

struct HashTable {
    HashNode **buckets; /* array of chain heads, NULL = empty bucket */
    int32_t bucket_count;
    int32_t size;
};

/* Division method: h(k) = k mod m. Ids are positive, so no sign issues. */
static int32_t hash_key(int32_t key, int32_t bucket_count)
{
    return (int32_t)((uint32_t)key % (uint32_t)bucket_count);
}

HashTable *ht_create(int32_t bucket_count)
{
    if (bucket_count <= 0) return NULL;
    HashTable *ht = malloc(sizeof *ht);
    if (ht == NULL) return NULL;
    ht->buckets = calloc((size_t)bucket_count, sizeof *ht->buckets);
    if (ht->buckets == NULL) {
        free(ht);
        return NULL;
    }
    ht->bucket_count = bucket_count;
    ht->size = 0;
    return ht;
}

/* Average O(1 + load factor). Rejects duplicate keys. */
int32_t ht_insert(HashTable *ht, int32_t key, int32_t value)
{
    if (ht == NULL) return SW_ERR_NULL_POINTER;
    int32_t b = hash_key(key, ht->bucket_count);
    for (HashNode *node = ht->buckets[b]; node != NULL; node = node->next)
        if (node->key == key) return SW_ERR_DUPLICATE_ID;

    HashNode *node = malloc(sizeof *node);
    if (node == NULL) return SW_ERR_NO_MEMORY;
    node->key = key;
    node->value = value;
    node->next = ht->buckets[b]; /* insert at head of the chain */
    ht->buckets[b] = node;
    ht->size++;
    return SW_OK;
}

/* Walk only the chain of bucket h(key). One comparison per visited node. */
int32_t ht_find(const HashTable *ht, int32_t key, int32_t *value_out, int64_t *comparisons)
{
    if (ht == NULL || value_out == NULL || comparisons == NULL) return SW_ERR_NULL_POINTER;
    *comparisons = 0;
    *value_out = -1;
    for (HashNode *node = ht->buckets[hash_key(key, ht->bucket_count)]; node != NULL;
         node = node->next) {
        (*comparisons)++;
        if (node->key == key) {
            *value_out = node->value;
            return SW_OK;
        }
    }
    return SW_ERR_NOT_FOUND;
}

void ht_stats(const HashTable *ht, HashStats *out)
{
    if (ht == NULL || out == NULL) return;
    out->bucket_count = ht->bucket_count;
    out->item_count = ht->size;
    out->used_buckets = 0;
    out->longest_chain = 0;
    for (int32_t b = 0; b < ht->bucket_count; b++) {
        int32_t len = 0;
        for (HashNode *node = ht->buckets[b]; node != NULL; node = node->next) len++;
        if (len > 0) out->used_buckets++;
        if (len > out->longest_chain) out->longest_chain = len;
    }
    out->collisions = ht->size - out->used_buckets;
    out->load_factor = (double)ht->size / ht->bucket_count;
}

int32_t ht_chain_lengths(const HashTable *ht, int32_t *out, int32_t capacity)
{
    if (ht == NULL || out == NULL) return SW_ERR_NULL_POINTER;
    if (capacity < ht->bucket_count) return SW_ERR_BUFFER_TOO_SMALL;
    for (int32_t b = 0; b < ht->bucket_count; b++) {
        int32_t len = 0;
        for (HashNode *node = ht->buckets[b]; node != NULL; node = node->next) len++;
        out[b] = len;
    }
    return SW_OK;
}

void ht_destroy(HashTable *ht)
{
    if (ht == NULL) return;
    for (int32_t b = 0; b < ht->bucket_count; b++) {
        HashNode *node = ht->buckets[b];
        while (node != NULL) {
            HashNode *next = node->next;
            free(node);
            node = next;
        }
    }
    free(ht->buckets);
    free(ht);
}
