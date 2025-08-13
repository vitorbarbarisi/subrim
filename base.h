// base.h - Loading `_zht_secs_base.txt` data
#pragma once

#include <stddef.h>

typedef struct BaseEntry {
  int time_seconds;      // time in seconds from field1 (e.g., "120s" -> 120)
  char *zht_text;        // Chinese text from field2
  char *pairs_text;      // pairs from field3
  char *pt_text;         // Portuguese text from field4
} BaseEntry;

typedef struct BaseData {
  BaseEntry *entries;    // array of entries sorted by time_seconds
  int count;             // number of entries
  int entries_capacity;  // allocated slots for entries
  
  // Legacy fields for backward compatibility (can be removed later)
  char **zht_by_index;   // 1-based; index 0 unused
  char **pairs_by_index; // optional pairs text per index (kept for future use)
  char **pt_by_index;    // optional PT translation per index
  int capacity;          // allocated slots for legacy arrays
} BaseData;

// Load base data from a directory containing the txt. Prefer *_zht_secs_base.txt
// and fallback to *_secs_base.txt. Returns allocated BaseData; call free_base_data.
BaseData load_base_file_for_directory(const char *directory);

// Find base entry by time in seconds. Returns NULL if not found.
const BaseEntry* find_entry_by_time(const BaseData *bd, int time_seconds);

// Free all memory from a BaseData structure.
void free_base_data(BaseData *bd);


