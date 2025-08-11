#include "text.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

int utf8_count_codepoints(const char *s) {
  if (!s) return 0;
  int count = 0;
  const unsigned char *p = (const unsigned char *)s;
  while (*p) {
    if ((*p & 0xC0) != 0x80) count++;
    p++;
  }
  return count;
}

static const char *try_font_paths[] = {
  "./DejaVuSans.ttf",
  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
  "/usr/share/fonts/opentype/noto/NotoSansCJKtc-Regular.otf",
  "/System/Library/Fonts/PingFang.ttc",
  "/System/Library/Fonts/Hiragino Sans GB W3.ttc",
  "/System/Library/Fonts/STHeiti Light.ttc",
  "/System/Library/Fonts/STHeiti Medium.ttc",
  "/Library/Fonts/Arial Unicode.ttf",
  "/Library/Fonts/NotoSansCJKtc-Regular.otf",
  "/Library/Fonts/NotoSansCJK-Regular.ttc",
  "/Library/Fonts/Arial.ttf",
  "/System/Library/Fonts/Supplemental/Arial.ttf",
  NULL
};

// User-controlled subtitle font bias (px)
static int g_subtitle_font_bias_px = 0;

void set_subtitle_font_bias(int bias_px) {
  if (bias_px < -100) bias_px = -100;
  if (bias_px > 200) bias_px = 200;
  g_subtitle_font_bias_px = bias_px;
}

int get_subtitle_font_bias(void) { return g_subtitle_font_bias_px; }

static TTF_Font *open_font_any_index(const char *path, int pixel_size) {
  for (int idx = 0; idx < 16; ++idx) {
    TTF_Font *f = TTF_OpenFontIndex(path, pixel_size, idx);
    if (f) return f;
  }
  return TTF_OpenFont(path, pixel_size);
}

TTF_Font *open_any_font(int pixel_size) {
  const char *env = SDL_getenv("R36S_VIEWER_FONT");
  if (env && *env) {
    TTF_Font *f = open_font_any_index(env, pixel_size);
    if (f) return f;
  }
  for (int i = 0; try_font_paths[i]; ++i) {
    TTF_Font *f = open_font_any_index(try_font_paths[i], pixel_size);
    if (f) return f;
  }
  return NULL;
}

int recreate_text(SDL_Renderer *renderer, int win_w, int win_h, const char *msg, SDL_Texture **out_tex, SDL_Rect *out_rect) {
  if (*out_tex) { SDL_DestroyTexture(*out_tex); *out_tex = NULL; }
  // Start with a conservative size and adapt to fit width/height constraints
  int font_px = win_h / 5; // smaller base than 1/3 to avoid clipping
  int cp = utf8_count_codepoints(msg);
  if (cp > 6) font_px = (int)(font_px * 0.6);
  // Apply user bias
  font_px += g_subtitle_font_bias_px;
  if (font_px < 18) font_px = 18;
  if (font_px > 200) font_px = 200;

  SDL_Color white = {255,255,255,255};
  const int max_height = (int)(win_h * 0.28); // keep text below ~28% of screen height
  const int max_width  = win_w - 64;          // margins left/right

  for (int attempt = 0; attempt < 6; ++attempt) {
    TTF_Font *font = open_any_font(font_px);
    if (!font) {
      fprintf(stderr, "Failed to open a font. Set R36S_VIEWER_FONT to a TTF path.\n");
      return -1;
    }
    SDL_Surface *surf = TTF_RenderUTF8_Blended(font, msg, white);
    if (!surf) {
      TTF_CloseFont(font);
      fprintf(stderr, "TTF_RenderUTF8_Blended failed: %s\n", TTF_GetError());
      return -1;
    }
    // Check constraints
    int too_wide = (surf->w > max_width);
    int too_tall = (surf->h > max_height);
    if (!too_wide && !too_tall) {
      *out_tex = SDL_CreateTextureFromSurface(renderer, surf);
      out_rect->w = surf->w;
      out_rect->h = surf->h;
      out_rect->x = (win_w - out_rect->w) / 2;
      out_rect->y = 24;
      SDL_FreeSurface(surf);
      TTF_CloseFont(font);
      return 0;
    }
    SDL_FreeSurface(surf);
    TTF_CloseFont(font);
    // Reduce size and retry
    font_px = (int)(font_px * 0.85);
    if (font_px < 14) font_px = 14;
  }
  // Last resort: render with minimal size
  TTF_Font *font = open_any_font(14);
  if (!font) return -1;
  SDL_Surface *surf = TTF_RenderUTF8_Blended(font, msg, white);
  if (!surf) { TTF_CloseFont(font); return -1; }
  *out_tex = SDL_CreateTextureFromSurface(renderer, surf);
  out_rect->w = surf->w; out_rect->h = surf->h;
  out_rect->x = (win_w - out_rect->w) / 2; out_rect->y = 24;
  SDL_FreeSurface(surf); TTF_CloseFont(font);
  return 0;
}

int recreate_text_px(SDL_Renderer *renderer, const char *msg, int pixel_size, SDL_Texture **out_tex, SDL_Rect *out_rect) {
  if (*out_tex) { SDL_DestroyTexture(*out_tex); *out_tex = NULL; }
  if (pixel_size < 8) pixel_size = 8;
  if (pixel_size > 128) pixel_size = 128;
  TTF_Font *font = open_any_font(pixel_size);
  if (!font) {
    fprintf(stderr, "Failed to open a font for label.\n");
    return -1;
  }
  SDL_Color white = {255,255,255,255};
  SDL_Surface *surf = TTF_RenderUTF8_Blended(font, msg, white);
  if (!surf) {
    TTF_CloseFont(font);
    return -1;
  }
  *out_tex = SDL_CreateTextureFromSurface(renderer, surf);
  out_rect->w = surf->w;
  out_rect->h = surf->h;
  SDL_FreeSurface(surf);
  TTF_CloseFont(font);
  return 0;
}

static void allocate_layout_arrays(SubtitleLayout *layout, int count) {
  layout->count = count;
  layout->x_offsets = (int *)calloc((size_t)count, sizeof(int));
  layout->widths = (int *)calloc((size_t)count, sizeof(int));
}

void free_subtitle_layout(SubtitleLayout *layout) {
  if (!layout) return;
  free(layout->x_offsets); layout->x_offsets = NULL;
  free(layout->widths); layout->widths = NULL;
  layout->count = 0; layout->tex_w = 0; layout->tex_h = 0; layout->font_px = 0;
}

// Naive per-codepoint layout approximating advance using TTF_SizeUTF8 on substrings.
int recreate_text_with_layout(SDL_Renderer *renderer, int win_w, int win_h, const char *msg,
                              SDL_Texture **out_tex, SDL_Rect *out_rect, SubtitleLayout *out_layout) {
  if (!out_layout) return -1;
  free_subtitle_layout(out_layout);
  if (*out_tex) { SDL_DestroyTexture(*out_tex); *out_tex = NULL; }
  // Determine font size similarly to recreate_text
  int font_px = win_h / 5;
  int cp_total = utf8_count_codepoints(msg);
  if (cp_total > 6) font_px = (int)(font_px * 0.6);
  font_px += g_subtitle_font_bias_px;
  if (font_px < 18) font_px = 18;
  if (font_px > 200) font_px = 200;
  SDL_Color white = {255,255,255,255};
  const int max_height = (int)(win_h * 0.28);
  const int max_width = win_w - 64;
  for (int attempt = 0; attempt < 6; ++attempt) {
    TTF_Font *font = open_any_font(font_px);
    if (!font) return -1;
    SDL_Surface *surf = TTF_RenderUTF8_Blended(font, msg, white);
    if (!surf) { TTF_CloseFont(font); return -1; }
    int too_wide = (surf->w > max_width);
    int too_tall = (surf->h > max_height);
    if (!too_wide && !too_tall) {
      *out_tex = SDL_CreateTextureFromSurface(renderer, surf);
      out_rect->w = surf->w; out_rect->h = surf->h;
      out_rect->x = (win_w - out_rect->w) / 2; out_rect->y = 24;
      // Build per-codepoint x offsets
      allocate_layout_arrays(out_layout, cp_total);
      out_layout->tex_w = surf->w; out_layout->tex_h = surf->h; out_layout->font_px = font_px;
      // Iterate utf8
      int idx = 0; int accum_w = 0;
      const unsigned char *p = (const unsigned char *)msg;
      char buf[8];
      while (*p && idx < cp_total) {
        // copy one UTF-8 codepoint into buf
        int len = 1;
        if ((*p & 0xE0) == 0xC0) len = 2; else if ((*p & 0xF0) == 0xE0) len = 3; else if ((*p & 0xF8) == 0xF0) len = 4;
        for (int i = 0; i < len; ++i) buf[i] = (char)p[i];
        buf[len] = '\0';
        // measure width of this codepoint
        int w_cp = 0, h_cp = 0;
        TTF_SizeUTF8(font, buf, &w_cp, &h_cp);
        out_layout->x_offsets[idx] = accum_w;
        out_layout->widths[idx] = w_cp;
        accum_w += w_cp;
        p += len; idx++;
      }
      SDL_FreeSurface(surf); TTF_CloseFont(font);
      return 0;
    }
    SDL_FreeSurface(surf); TTF_CloseFont(font);
    font_px = (int)(font_px * 0.85);
    if (font_px < 14) font_px = 14;
  }
  return -1;
}

void set_bottom_text(SDL_Renderer *renderer, int win_w, int win_h, const char *msg,
                     SDL_Texture **text_tex, SDL_Rect *text_rect, char **current_msg,
                     bool *show_text) {
  if (!msg || !*msg) {
    if (*text_tex) { SDL_DestroyTexture(*text_tex); *text_tex = NULL; }
    if (*current_msg) { free(*current_msg); *current_msg = NULL; }
    *show_text = false;
    return;
  }
  if (*current_msg) { free(*current_msg); *current_msg = NULL; }
  *current_msg = SDL_strdup(msg);
  if (recreate_text(renderer, win_w, win_h, msg, text_tex, text_rect) == 0 && *text_tex) {
    text_rect->x = (win_w - text_rect->w) / 2;
    text_rect->y = win_h - text_rect->h - 24;
    *show_text = true;
  } else {
    *show_text = false;
  }
}


