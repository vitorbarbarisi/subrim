#include "base.h"

#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool ends_with_case_insensitive(const char *str, const char *suffix) {
  if (!str || !suffix) return false;
  size_t ls = strlen(str), lf = strlen(suffix);
  if (lf > ls) return false;
  const char *tail = str + (ls - lf);
  return strcasecmp(tail, suffix) == 0;
}

static void strip_trailing_newline(char *s) {
  if (!s) return;
  size_t len = strlen(s);
  while (len > 0 && (s[len - 1] == '\n' || s[len - 1] == '\r')) {
    s[len - 1] = '\0';
    len--;
  }
}

static char *strdup_safe(const char *s) {
  if (!s) return NULL;
  size_t len = strlen(s);
  char *d = (char *)malloc(len + 1);
  if (!d) return NULL;
  memcpy(d, s, len + 1);
  return d;
}

static void ensure_capacity_zht(BaseData *bd, int needed_index) {
  if (needed_index < bd->capacity) return;
  int new_cap = bd->capacity > 0 ? bd->capacity : 16;
  while (new_cap <= needed_index) new_cap *= 2;
  char **new_zht = (char **)calloc((size_t)new_cap, sizeof(char *));
  char **new_pairs = (char **)calloc((size_t)new_cap, sizeof(char *));
  char **new_pt = (char **)calloc((size_t)new_cap, sizeof(char *));
  if (!new_zht || !new_pairs || !new_pt) { if (new_zht) free(new_zht); if (new_pairs) free(new_pairs); if (new_pt) free(new_pt); return; }
  for (int i = 0; i < bd->capacity; ++i) {
    new_zht[i] = bd->zht_by_index ? bd->zht_by_index[i] : NULL;
    new_pairs[i] = bd->pairs_by_index ? bd->pairs_by_index[i] : NULL;
    new_pt[i] = bd->pt_by_index ? bd->pt_by_index[i] : NULL;
  }
  if (bd->zht_by_index) free(bd->zht_by_index);
  if (bd->pairs_by_index) free(bd->pairs_by_index);
  if (bd->pt_by_index) free(bd->pt_by_index);
  bd->zht_by_index = new_zht;
  bd->pairs_by_index = new_pairs;
  bd->pt_by_index = new_pt;
  bd->capacity = new_cap;
}

void free_base_data(BaseData *bd) {
  if (!bd) return;
  if (bd->zht_by_index) {
    for (int i = 0; i < bd->capacity; ++i) {
      if (bd->zht_by_index[i]) free(bd->zht_by_index[i]);
    }
    free(bd->zht_by_index);
  }
  if (bd->pairs_by_index) {
    for (int i = 0; i < bd->capacity; ++i) {
      if (bd->pairs_by_index[i]) free(bd->pairs_by_index[i]);
    }
    free(bd->pairs_by_index);
  }
  if (bd->pt_by_index) {
    for (int i = 0; i < bd->capacity; ++i) {
      if (bd->pt_by_index[i]) free(bd->pt_by_index[i]);
    }
    free(bd->pt_by_index);
  }
  bd->zht_by_index = NULL;
  bd->pairs_by_index = NULL;
  bd->pt_by_index = NULL;
  bd->capacity = 0;
}

BaseData load_base_file_for_directory(const char *directory) {
  BaseData bd = {0};

  DIR *dir = opendir(directory);
  if (!dir) {
    fprintf(stderr, "No directory for base file: %s (%s)\n", directory, strerror(errno));
    return bd;
  }

  char *preferred = NULL;
  char *fallback = NULL;
  struct dirent *ent;
  while ((ent = readdir(dir)) != NULL) {
    if (ent->d_name[0] == '.') continue;
    size_t need = strlen(directory) + 1 + strlen(ent->d_name) + 1;
    char *full = (char *)malloc(need);
    if (!full) continue;
    snprintf(full, need, "%s/%s", directory, ent->d_name);
    if (ends_with_case_insensitive(full, ".txt")) {
      if (strstr(ent->d_name, "_zht_secs_base.txt")) {
        if (!preferred) preferred = full; else free(full);
      } else if (strstr(ent->d_name, "_secs_base.txt")) {
        if (!fallback) fallback = full; else free(full);
      } else {
        free(full);
      }
    } else {
      free(full);
    }
  }
  closedir(dir);

  const char *chosen = preferred ? preferred : fallback;
  if (!chosen) {
    if (preferred) free(preferred);
    if (fallback) free(fallback);
    fprintf(stderr, "Base file not found in %s (looking for *_zht_secs_base.txt or *_secs_base.txt)\n", directory);
    return bd;
  }

  FILE *fp = fopen(chosen, "rb");
  if (!fp) {
    fprintf(stderr, "Failed to open base file %s: %s\n", chosen, strerror(errno));
    if (preferred) free(preferred);
    if (fallback) free(fallback);
    return bd;
  }

  char line[8192];
  while (fgets(line, (int)sizeof(line), fp)) {
    strip_trailing_newline(line);
    if (line[0] == '\0') continue;
    char *saveptr = NULL;
    char *field0 = strtok_r(line, "\t", &saveptr);
    if (!field0) continue;
    char *field1 = strtok_r(NULL, "\t", &saveptr); (void)field1;
    char *field2 = strtok_r(NULL, "\t", &saveptr);
    char *field3 = strtok_r(NULL, "\t", &saveptr);
    char *field4 = strtok_r(NULL, "\t", &saveptr); // pt (optional)
    if (!field2) continue;
    char *endptr = NULL;
    long idx = strtol(field0, &endptr, 10);
    if (endptr == field0 || idx <= 0 || idx > 1000000) continue;
    ensure_capacity_zht(&bd, (int)idx + 1);
    if (bd.zht_by_index[(int)idx]) { free(bd.zht_by_index[(int)idx]); bd.zht_by_index[(int)idx] = NULL; }
    bd.zht_by_index[(int)idx] = strdup_safe(field2);
    if (field3) {
      if (bd.pairs_by_index[(int)idx]) { free(bd.pairs_by_index[(int)idx]); bd.pairs_by_index[(int)idx] = NULL; }
      bd.pairs_by_index[(int)idx] = strdup_safe(field3);
    }
    if (field4) {
      if (bd.pt_by_index[(int)idx]) { free(bd.pt_by_index[(int)idx]); bd.pt_by_index[(int)idx] = NULL; }
      bd.pt_by_index[(int)idx] = strdup_safe(field4);
    }
  }

  fclose(fp);
  if (preferred) free(preferred);
  if (fallback) free(fallback);
  return bd;
}


