// ui.h - Image loading and menu structures
#pragma once

#include <SDL2/SDL.h>

typedef struct ImageList {
  char **paths;
  int count;
} ImageList;

typedef struct Menu {
  char **names;           // folder names under assets/
  int count;
  SDL_Texture **tex;      // rendered name textures
  SDL_Rect *rects;        // destination rects for each item
  int selected;
} Menu;

ImageList scan_images(const char *directory);
void free_images(ImageList *list);

SDL_Texture *load_texture_scaled(SDL_Renderer *renderer, const char *path, int win_w, int win_h, SDL_Rect *dst);
void compute_dst_from_texture(SDL_Texture *texture, int win_w, int win_h, SDL_Rect *dst);

// Compute source and destination to "cover" the window by cropping the texture
// center to match window aspect ratio (no letterboxing). dst becomes the
// whole window; src selects the interior of the texture.
void compute_cover_src_dst(SDL_Texture *texture, int win_w, int win_h, SDL_Rect *src, SDL_Rect *dst);

Menu build_menu(SDL_Renderer *renderer, int win_w, int win_h, const char *assets_root);
void free_menu(Menu *menu);

// Utility
int compare_strings(const void *a, const void *b);
int compare_numeric_paths(const void *a, const void *b);
int compare_cstr(const void *a, const void *b);
int basename_numeric_value(const char *path, long *out_value);


