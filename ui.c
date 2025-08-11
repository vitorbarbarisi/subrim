#include "ui.h"
#include "text.h"

#include <SDL2/SDL_image.h>
#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

int compare_strings(const void *a, const void *b) {
  const char *sa = *(const char *const *)a;
  const char *sb = *(const char *const *)b;
  return strcmp(sa, sb);
}

static bool has_image_ext(const char *name) {
  const char *dot = strrchr(name, '.');
  if (!dot) return false;
  return strcasecmp(dot, ".png") == 0; // Restrito a PNG
}

int basename_numeric_value(const char *path, long *out_value) {
  if (!path) return 0;
  const char *name = strrchr(path, '/');
  name = name ? (name + 1) : path;
  const char *dot = strrchr(name, '.');
  size_t len = dot && dot > name ? (size_t)(dot - name) : strlen(name);
  if (len == 0) return 0;
  long value = 0;
  for (size_t i = 0; i < len; ++i) {
    unsigned char ch = (unsigned char)name[i];
    if (ch < '0' || ch > '9') return 0;
    value = value * 10 + (long)(ch - '0');
  }
  *out_value = value;
  return 1;
}

int compare_numeric_paths(const void *a, const void *b) {
  const char *sa = *(const char *const *)a;
  const char *sb = *(const char *const *)b;
  long va = 0, vb = 0;
  int ha = basename_numeric_value(sa, &va);
  int hb = basename_numeric_value(sb, &vb);
  if (ha && hb) {
    if (va < vb) return -1;
    if (va > vb) return 1;
    return strcmp(sa, sb);
  }
  if (ha && !hb) return -1;
  if (!ha && hb) return 1;
  return strcmp(sa, sb);
}

ImageList scan_images(const char *directory) {
  ImageList list; list.paths = NULL; list.count = 0;
  DIR *dir = opendir(directory);
  if (!dir) {
    fprintf(stderr, "Failed to open directory '%s': %s\n", directory, strerror(errno));
    return list;
  }
  struct dirent *ent;
  size_t cap = 32;
  list.paths = (char **)malloc(cap * sizeof(char *));
  if (!list.paths) { closedir(dir); return list; }

  while ((ent = readdir(dir)) != NULL) {
    if (ent->d_name[0] == '.') continue;
    if (!has_image_ext(ent->d_name)) continue;
    if (list.count == (int)cap) {
      cap *= 2;
      char **np = (char **)realloc(list.paths, cap * sizeof(char *));
      if (!np) break;
      list.paths = np;
    }
    size_t needed = strlen(directory) + 1 + strlen(ent->d_name) + 1;
    char *full = (char *)malloc(needed);
    if (!full) continue;
    snprintf(full, needed, "%s/%s", directory, ent->d_name);
    list.paths[list.count++] = full;
  }
  closedir(dir);

  if (list.count > 1) qsort(list.paths, list.count, sizeof(char *), compare_numeric_paths);
  return list;
}

void free_images(ImageList *list) {
  if (!list || !list->paths) return;
  for (int i = 0; i < list->count; ++i) free(list->paths[i]);
  free(list->paths);
  list->paths = NULL;
  list->count = 0;
}

SDL_Texture *load_texture_scaled(SDL_Renderer *renderer, const char *path, int win_w, int win_h, SDL_Rect *dst) {
  SDL_Texture *texture = IMG_LoadTexture(renderer, path);
  if (!texture) {
    fprintf(stderr, "IMG_LoadTexture failed for %s: %s\n", path, IMG_GetError());
    return NULL;
  }
  int tex_w = 0, tex_h = 0;
  if (SDL_QueryTexture(texture, NULL, NULL, &tex_w, &tex_h) != 0) {
    fprintf(stderr, "SDL_QueryTexture failed: %s\n", SDL_GetError());
    SDL_DestroyTexture(texture);
    return NULL;
  }
  double sx = (double)win_w / (double)tex_w;
  double sy = (double)win_h / (double)tex_h;
  double scale = sx < sy ? sx : sy;
  int dst_w = (int)(tex_w * scale);
  int dst_h = (int)(tex_h * scale);
  dst->w = dst_w; dst->h = dst_h;
  dst->x = (win_w - dst_w) / 2; dst->y = (win_h - dst_h) / 2;
  return texture;
}

void compute_dst_from_texture(SDL_Texture *texture, int win_w, int win_h, SDL_Rect *dst) {
  if (!texture || !dst) return;
  int tex_w = 0, tex_h = 0;
  if (SDL_QueryTexture(texture, NULL, NULL, &tex_w, &tex_h) != 0) {
    dst->x = dst->y = 0; dst->w = win_w; dst->h = win_h; return;
  }
  double sx = (double)win_w / (double)tex_w;
  double sy = (double)win_h / (double)tex_h;
  double scale = sx < sy ? sx : sy;
  int dst_w = (int)(tex_w * scale);
  int dst_h = (int)(tex_h * scale);
  dst->w = dst_w; dst->h = dst_h;
  dst->x = (win_w - dst_w) / 2; dst->y = (win_h - dst_h) / 2;
}

void compute_cover_src_dst(SDL_Texture *texture, int win_w, int win_h, SDL_Rect *src, SDL_Rect *dst) {
  if (!texture || !src || !dst) return;
  int tex_w = 0, tex_h = 0;
  if (SDL_QueryTexture(texture, NULL, NULL, &tex_w, &tex_h) != 0 || tex_w <= 0 || tex_h <= 0) {
    src->x = src->y = 0; src->w = tex_w; src->h = tex_h;
    dst->x = 0; dst->y = 0; dst->w = win_w; dst->h = win_h;
    return;
  }
  // Aspect ratios
  double tex_ar = (double)tex_w / (double)tex_h;
  double win_ar = (double)win_w / (double)win_h;
  // Start with full texture
  int crop_w = tex_w;
  int crop_h = tex_h;
  if (tex_ar > win_ar) {
    // Texture is wider than window: crop width
    crop_w = (int)(win_ar * tex_h);
  } else if (tex_ar < win_ar) {
    // Texture is taller than window: crop height
    crop_h = (int)(tex_w / win_ar);
  }
  // Center crop
  int sx = (tex_w - crop_w) / 2;
  int sy = (tex_h - crop_h) / 2;
  src->x = sx; src->y = sy; src->w = crop_w; src->h = crop_h;
  // Destination fills the window entirely
  dst->x = 0; dst->y = 0; dst->w = win_w; dst->h = win_h;
}

static bool is_directory(const char *base, const char *name) {
  if (!base || !name) return false;
  size_t need = strlen(base) + 1 + strlen(name) + 1;
  char *full = (char *)malloc(need);
  if (!full) return false;
  snprintf(full, need, "%s/%s", base, name);
  DIR *d = opendir(full);
  if (d) { closedir(d); free(full); return true; }
  free(full);
  return false;
}

int compare_cstr(const void *a, const void *b) {
  const char *const *sa = (const char *const *)a;
  const char *const *sb = (const char *const *)b;
  return strcasecmp(*sa, *sb);
}

void free_menu(Menu *menu) {
  if (!menu) return;
  if (menu->tex) {
    for (int i = 0; i < menu->count; ++i) if (menu->tex[i]) SDL_DestroyTexture(menu->tex[i]);
    free(menu->tex);
  }
  if (menu->rects) free(menu->rects);
  if (menu->names) { for (int i = 0; i < menu->count; ++i) free(menu->names[i]); free(menu->names); }
  memset(menu, 0, sizeof(*menu));
}

Menu build_menu(SDL_Renderer *renderer, int win_w, int win_h, const char *assets_root) {
  Menu menu; memset(&menu, 0, sizeof(menu));
  DIR *dir = opendir(assets_root);
  if (!dir) {
    fprintf(stderr, "Failed to open assets directory '%s': %s\n", assets_root, strerror(errno));
    return menu;
  }
  struct dirent *ent;
  size_t cap = 32;
  menu.names = (char **)malloc(cap * sizeof(char *));
  if (!menu.names) { closedir(dir); return menu; }
  while ((ent = readdir(dir)) != NULL) {
    if (ent->d_name[0] == '.') continue;
    if (!is_directory(assets_root, ent->d_name)) continue;
    if (menu.count == (int)cap) {
      cap *= 2;
      char **np = (char **)realloc(menu.names, cap * sizeof(char *));
      if (!np) break;
      menu.names = np;
    }
    menu.names[menu.count] = strdup(ent->d_name);
    if (menu.names[menu.count]) menu.count++;
  }
  closedir(dir);
  if (menu.count <= 0) return menu;
  qsort(menu.names, menu.count, sizeof(char *), compare_cstr);

  menu.tex = (SDL_Texture **)calloc(menu.count, sizeof(SDL_Texture *));
  menu.rects = (SDL_Rect *)calloc(menu.count, sizeof(SDL_Rect));
  if (!menu.tex || !menu.rects) return menu;

  int y = 80; int padding_y = 16;
  for (int i = 0; i < menu.count; ++i) {
    SDL_Texture *t = NULL; SDL_Rect r = {0,0,0,0};
    if (recreate_text(renderer, win_w, win_h, menu.names[i], &t, &r) == 0 && t) {
      r.x = 64; r.y = y; y += r.h + padding_y;
      menu.tex[i] = t; menu.rects[i] = r;
    }
  }
  menu.selected = 0;
  return menu;
}


