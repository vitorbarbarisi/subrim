#include <SDL2/SDL.h>
#include <SDL2/SDL_image.h>
#include <SDL2/SDL_ttf.h>
#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

typedef struct ImageList {
  char **paths;
  int count;
} ImageList;

static int compare_strings(const void *a, const void *b) {
  const char *sa = *(const char **)a;
  const char *sb = *(const char **)b;
  return strcmp(sa, sb);
}

static bool basename_numeric_value(const char *path, long *out_value) {
  if (!path) return false;
  const char *name = strrchr(path, '/');
  name = name ? (name + 1) : path;
  // Strip extension
  const char *dot = strrchr(name, '.');
  size_t len = dot && dot > name ? (size_t)(dot - name) : strlen(name);
  if (len == 0) return false;
  // Ensure all digits
  long value = 0;
  for (size_t i = 0; i < len; ++i) {
    unsigned char ch = (unsigned char)name[i];
    if (!isdigit(ch)) return false;
    value = value * 10 + (long)(ch - '0');
  }
  *out_value = value;
  return true;
}

static int compare_numeric_paths(const void *a, const void *b) {
  const char *sa = *(const char **)a;
  const char *sb = *(const char **)b;
  long va = 0, vb = 0;
  bool ha = basename_numeric_value(sa, &va);
  bool hb = basename_numeric_value(sb, &vb);
  if (ha && hb) {
    if (va < vb) return -1;
    if (va > vb) return 1;
    // Same numeric value: fallback to lexical for stability
    return strcmp(sa, sb);
  }
  // If only one is numeric, put numeric first
  if (ha && !hb) return -1;
  if (!ha && hb) return 1;
  // Neither numeric: fallback to lexical
  return strcmp(sa, sb);
}

static bool has_image_ext(const char *name) {
  const char *dot = strrchr(name, '.');
  if (!dot) return false;
  // Restrito a PNG conforme requisito atual
  if (strcasecmp(dot, ".png") == 0) return true;
  return false;
}

static ImageList scan_images(const char *directory) {
  ImageList list = {0};
  DIR *dir = opendir(directory);
  if (!dir) {
    fprintf(stderr, "Failed to open directory '%s': %s\n", directory, strerror(errno));
    return list;
  }

  struct dirent *ent;
  size_t cap = 32;
  list.paths = (char **)malloc(cap * sizeof(char *));
  if (!list.paths) {
    closedir(dir);
    return list;
  }

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

  if (list.count > 1) {
    qsort(list.paths, list.count, sizeof(char *), compare_numeric_paths);
  }

  return list;
}

static void free_images(ImageList *list) {
  if (!list || !list->paths) return;
  for (int i = 0; i < list->count; ++i) free(list->paths[i]);
  free(list->paths);
  list->paths = NULL;
  list->count = 0;
}

static SDL_Texture *load_texture_scaled(SDL_Renderer *renderer, const char *path, int win_w, int win_h, SDL_Rect *dst) {
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

  // Preserve aspect ratio and letterbox/pillarbox to fit window
  double scale = 1.0;
  if (tex_w > 0 && tex_h > 0) {
    double sx = (double)win_w / (double)tex_w;
    double sy = (double)win_h / (double)tex_h;
    scale = sx < sy ? sx : sy;
  }
  int dst_w = (int)(tex_w * scale);
  int dst_h = (int)(tex_h * scale);
  dst->w = dst_w;
  dst->h = dst_h;
  dst->x = (win_w - dst_w) / 2;
  dst->y = (win_h - dst_h) / 2;

  return texture;
}

static void render_message(SDL_Renderer *renderer, int win_w, int win_h, const char *msg) {
  // Simple fallback message as a filled rectangle and we can't draw text without TTF; just clear and leave.
  (void)msg;
  SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
  SDL_RenderClear(renderer);
  SDL_RenderPresent(renderer);
}

// Simple font discovery (override with env var R36S_VIEWER_FONT)
static const char *try_font_paths[] = {
  "./DejaVuSans.ttf",
  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
  "/Library/Fonts/Arial.ttf",
  "/System/Library/Fonts/Supplemental/Arial.ttf",
  NULL
};

static TTF_Font *open_any_font(int pixel_size) {
  const char *env = SDL_getenv("R36S_VIEWER_FONT");
  if (env && *env) {
    TTF_Font *f = TTF_OpenFont(env, pixel_size);
    if (f) return f;
  }
  for (int i = 0; try_font_paths[i]; ++i) {
    TTF_Font *f = TTF_OpenFont(try_font_paths[i], pixel_size);
    if (f) return f;
  }
  return NULL;
}

static int recreate_text(SDL_Renderer *renderer, int win_w, int win_h, const char *msg, SDL_Texture **out_tex, SDL_Rect *out_rect) {
  if (*out_tex) { SDL_DestroyTexture(*out_tex); *out_tex = NULL; }
  int font_px = win_h / 3;
  if (font_px < 24) font_px = 24;
  if (font_px > 200) font_px = 200;
  TTF_Font *font = open_any_font(font_px);
  if (!font) {
    fprintf(stderr, "Failed to open a font. Set R36S_VIEWER_FONT to a TTF path.\n");
    return -1;
  }
  SDL_Color white = {255, 255, 255, 255};
  SDL_Surface *surf = TTF_RenderUTF8_Blended(font, msg, white);
  if (!surf) {
    fprintf(stderr, "TTF_RenderUTF8_Blended failed: %s\n", TTF_GetError());
    TTF_CloseFont(font);
    return -1;
  }
  *out_tex = SDL_CreateTextureFromSurface(renderer, surf);
  out_rect->w = surf->w;
  out_rect->h = surf->h;
  // Position at top-center with a small margin
  out_rect->x = (win_w - out_rect->w) / 2;
  out_rect->y = 24; // top margin
  SDL_FreeSurface(surf);
  TTF_CloseFont(font);
  return 0;
}

typedef struct Menu {
  char **names;           // folder names under assets/
  int count;
  SDL_Texture **tex;      // rendered name textures
  SDL_Rect *rects;        // destination rects for each item
  int selected;
} Menu;

static void free_menu(Menu *menu) {
  if (!menu) return;
  if (menu->tex) {
    for (int i = 0; i < menu->count; ++i) if (menu->tex[i]) SDL_DestroyTexture(menu->tex[i]);
    free(menu->tex);
  }
  if (menu->rects) free(menu->rects);
  if (menu->names) {
    for (int i = 0; i < menu->count; ++i) free(menu->names[i]);
    free(menu->names);
  }
  memset(menu, 0, sizeof(*menu));
}

static int compare_cstr(const void *a, const void *b) {
  const char *const *sa = (const char *const *)a;
  const char *const *sb = (const char *const *)b;
  return strcasecmp(*sa, *sb);
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

static Menu build_menu(SDL_Renderer *renderer, int win_w, int win_h, const char *assets_root) {
  Menu menu = {0};
  DIR *dir = opendir(assets_root);
  if (!dir) {
    fprintf(stderr, "Failed to open assets directory '%s': %s\n", assets_root, strerror(errno));
    return menu;
  }

  // First pass: count eligible directories
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

  // Render each name as a texture; layout vertically
  int y = 80;
  int padding_y = 16;
  for (int i = 0; i < menu.count; ++i) {
    SDL_Texture *t = NULL; SDL_Rect r = {0,0,0,0};
    if (recreate_text(renderer, win_w, win_h, menu.names[i], &t, &r) == 0 && t) {
      // Left align near 64px, keep y stacking
      r.x = 64;
      r.y = y;
      y += r.h + padding_y;
      menu.tex[i] = t;
      menu.rects[i] = r;
    }
  }
  menu.selected = 0;
  return menu;
}

int main(int argc, char **argv) {
  const char *assets_root = "assets";
  const char *directory = (argc > 1) ? argv[1] : NULL;
  bool windowed = (argc > 2 && (strcmp(argv[2], "--windowed") == 0));

  if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER | SDL_INIT_EVENTS) != 0) {
    fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
    return 1;
  }

  int img_flags = IMG_INIT_PNG | IMG_INIT_JPG;
  if ((IMG_Init(img_flags) & img_flags) == 0) {
    fprintf(stderr, "IMG_Init failed: %s\n", IMG_GetError());
    SDL_Quit();
    return 1;
  }

  if (TTF_Init() != 0) {
    fprintf(stderr, "TTF_Init failed: %s\n", TTF_GetError());
  }

  // Create window (fullscreen by default; use --windowed to run in a window)
  Uint32 win_flags = SDL_WINDOW_SHOWN;
  if (!windowed) win_flags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
  SDL_Window *window = SDL_CreateWindow(
      "R36S Viewer", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 640, 480, win_flags);
  if (!window) {
    fprintf(stderr, "SDL_CreateWindow failed: %s\n", SDL_GetError());
    IMG_Quit();
    SDL_Quit();
    return 1;
  }

  SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
  if (!renderer) {
    fprintf(stderr, "SDL_CreateRenderer failed: %s\n", SDL_GetError());
    SDL_DestroyWindow(window);
    IMG_Quit();
    SDL_Quit();
    return 1;
  }

  int win_w = 0, win_h = 0;
  SDL_GetRendererOutputSize(renderer, &win_w, &win_h);

  ImageList list = {0};
  int index = 0;
  bool running = true;
  bool menu_active = (directory == NULL);
  Menu menu = {0};
  if (menu_active) {
    menu = build_menu(renderer, win_w, win_h, assets_root);
  } else {
    // If directory provided and not an absolute path, treat as assets/<directory>
    char pathbuf[1024];
    if (strchr(directory, '/')) {
      snprintf(pathbuf, sizeof(pathbuf), "%s", directory);
    } else {
      snprintf(pathbuf, sizeof(pathbuf), "%s/%s", assets_root, directory);
    }
    list = scan_images(pathbuf);
    fprintf(stdout, "Found %d images in '%s'\n", list.count, pathbuf);
  }

  SDL_Texture *current = NULL;
  SDL_Rect dst_rect = {0, 0, 0, 0};

  // Text overlay state
  bool show_text = false;
  SDL_Texture *text_tex = NULL;
  SDL_Rect text_rect = (SDL_Rect){0, 0, 0, 0};

  if (!menu_active) {
    if (list.count == 0) {
      render_message(renderer, win_w, win_h, "No images found");
    } else {
      current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
      if (current) fprintf(stdout, "Showing (1/%d): %s\n", list.count, list.paths[index]);
    }
  }

  // Try to open the first available controller
  for (int i = 0; i < SDL_NumJoysticks(); ++i) {
    if (SDL_IsGameController(i)) {
      SDL_GameController *ctrl = SDL_GameControllerOpen(i);
      if (ctrl) break;
    }
  }

  while (running) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
      if (e.type == SDL_QUIT) {
        running = false;
      } else if (e.type == SDL_KEYDOWN) {
        SDL_Keycode key = e.key.keysym.sym;
        if (key == SDLK_ESCAPE || key == SDLK_q) {
          running = false;
        } else if (key == SDLK_m) {
          // Toggle menu
          menu_active = !menu_active;
          if (menu_active) {
            // Enter menu: free image and build menu
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            free_images(&list);
            free_menu(&menu);
            menu = build_menu(renderer, win_w, win_h, assets_root);
          } else {
            // Exit menu: load selected folder
            if (menu.count > 0) {
              char pathbuf[1024];
              snprintf(pathbuf, sizeof(pathbuf), "%s/%s", assets_root, menu.names[menu.selected]);
              free_images(&list);
              list = scan_images(pathbuf);
              index = 0;
              if (current) { SDL_DestroyTexture(current); current = NULL; }
              if (list.count > 0) current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            }
          }
        } else if (!menu_active && key == SDLK_b) {
          show_text = !show_text;
          if (show_text) {
            recreate_text(renderer, win_w, win_h, "palavras", &text_tex, &text_rect);
          } else {
            if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
          }
        } else if (!menu_active && key == SDLK_RIGHT) {
          if (list.count > 0) {
            index = (index + 1) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current) fprintf(stdout, "Showing (%d/%d): %s\n", index + 1, list.count, list.paths[index]);
          }
        } else if (!menu_active && key == SDLK_LEFT) {
          if (list.count > 0) {
            index = (index - 1 + list.count) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current) fprintf(stdout, "Showing (%d/%d): %s\n", index + 1, list.count, list.paths[index]);
          }
        } else if (menu_active && (key == SDLK_DOWN || key == SDLK_s)) {
          if (menu.count > 0) menu.selected = (menu.selected + 1) % menu.count;
        } else if (menu_active && (key == SDLK_UP || key == SDLK_w)) {
          if (menu.count > 0) menu.selected = (menu.selected - 1 + menu.count) % menu.count;
        } else if (menu_active && (key == SDLK_RETURN || key == SDLK_KP_ENTER)) {
          if (menu.count > 0) {
            char pathbuf[1024];
            snprintf(pathbuf, sizeof(pathbuf), "%s/%s", assets_root, menu.names[menu.selected]);
            free_images(&list);
            list = scan_images(pathbuf);
            index = 0;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            if (list.count > 0) current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            menu_active = false;
          }
        }
      } else if (e.type == SDL_MOUSEMOTION && menu_active) {
        int mx = e.motion.x, my = e.motion.y;
        (void)mx;
        for (int i = 0; i < menu.count; ++i) {
          SDL_Rect r = menu.rects[i];
          if (my >= r.y - 4 && my <= r.y + r.h + 4) { menu.selected = i; break; }
        }
      } else if (e.type == SDL_MOUSEBUTTONDOWN && menu_active) {
        if (e.button.button == SDL_BUTTON_LEFT && menu.count > 0) {
          char pathbuf[1024];
          snprintf(pathbuf, sizeof(pathbuf), "%s/%s", assets_root, menu.names[menu.selected]);
          free_images(&list);
          list = scan_images(pathbuf);
          index = 0;
          if (current) { SDL_DestroyTexture(current); current = NULL; }
          if (list.count > 0) current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
          menu_active = false;
        }
      } else if (e.type == SDL_CONTROLLERBUTTONDOWN) {
        if (e.cbutton.button == SDL_CONTROLLER_BUTTON_START && SDL_GameControllerGetButton(SDL_GameControllerFromInstanceID(e.cbutton.which), SDL_CONTROLLER_BUTTON_BACK)) {
          running = false; // Start+Back to quit
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
          if (list.count > 0) {
            index = (index + 1) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current) fprintf(stdout, "Showing (%d/%d): %s\n", index + 1, list.count, list.paths[index]);
          }
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_LEFT) {
          if (list.count > 0) {
            index = (index - 1 + list.count) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current) fprintf(stdout, "Showing (%d/%d): %s\n", index + 1, list.count, list.paths[index]);
          }
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_B) {
          show_text = !show_text;
          if (show_text) {
            recreate_text(renderer, win_w, win_h, "palavras", &text_tex, &text_rect);
          } else {
            if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
          }
        } else if (menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
          if (menu.count > 0) menu.selected = (menu.selected + 1) % menu.count;
        } else if (menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_UP) {
          if (menu.count > 0) menu.selected = (menu.selected - 1 + menu.count) % menu.count;
        } else if (menu_active && (e.cbutton.button == SDL_CONTROLLER_BUTTON_A)) {
          if (menu.count > 0) {
            char pathbuf[1024];
            snprintf(pathbuf, sizeof(pathbuf), "%s/%s", assets_root, menu.names[menu.selected]);
            free_images(&list);
            list = scan_images(pathbuf);
            index = 0;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            if (list.count > 0) current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            menu_active = false;
          }
        }
      }
    }

    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    if (!menu_active && current) {
      SDL_RenderCopy(renderer, current, NULL, &dst_rect);
    }
    if (menu_active && menu.count > 0) {
      // Draw menu background dim
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
      SDL_SetRenderDrawColor(renderer, 0, 0, 0, 200);
      SDL_Rect bg = { 40, 40, win_w - 80, win_h - 80 };
      SDL_RenderFillRect(renderer, &bg);
      // Draw each item; highlight selected
      for (int i = 0; i < menu.count; ++i) {
        SDL_Rect r = menu.rects[i];
        if (i == menu.selected) {
          SDL_SetRenderDrawColor(renderer, 40, 40, 80, 220);
          SDL_Rect hl = { r.x - 16, r.y - 8, r.w + 32, r.h + 16 };
          SDL_RenderFillRect(renderer, &hl);
        }
        if (menu.tex[i]) {
          SDL_RenderCopy(renderer, menu.tex[i], NULL, &r);
        }
      }
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
    }
    if (show_text && text_tex) {
      // Draw translucent backdrop for readability
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
      SDL_SetRenderDrawColor(renderer, 0, 0, 0, 128);
      SDL_Rect bg = { text_rect.x - 12, text_rect.y - 8, text_rect.w + 24, text_rect.h + 16 };
      SDL_RenderFillRect(renderer, &bg);
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
      SDL_RenderCopy(renderer, text_tex, NULL, &text_rect);
    }
    SDL_RenderPresent(renderer);
  }

  if (current) SDL_DestroyTexture(current);
  if (text_tex) SDL_DestroyTexture(text_tex);
  free_images(&list);
  free_menu(&menu);
  SDL_DestroyRenderer(renderer);
  SDL_DestroyWindow(window);
  TTF_Quit();
  IMG_Quit();
  SDL_Quit();
  return 0;
}


