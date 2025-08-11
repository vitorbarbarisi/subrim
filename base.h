// base.h - Loading `_zht_secs_base.txt` data
#pragma once

#include <stddef.h>

typedef struct BaseData {
  char **zht_by_index;   // 1-based; index 0 unused
  char **pairs_by_index; // optional pairs text per index (kept for future use)
  char **pt_by_index;    // optional PT translation per index
  int capacity;          // allocated slots
} BaseData;

// Load base data from a directory containing the txt. Prefer *_zht_secs_base.txt
// and fallback to *_secs_base.txt. Returns allocated BaseData; call free_base_data.
BaseData load_base_file_for_directory(const char *directory);

// Free all memory from a BaseData structure.
void free_base_data(BaseData *bd);


