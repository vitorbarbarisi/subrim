// text.h - Text utilities and rendering helpers
#pragma once

#include <SDL2/SDL.h>
#include <SDL2/SDL_ttf.h>
#include <stdbool.h>

int utf8_count_codepoints(const char *s);

// Open a font, trying env R36S_VIEWER_FONT and a list of common paths.
TTF_Font *open_any_font(int pixel_size);

// Render text sized based on window height and message length.
int recreate_text(SDL_Renderer *renderer, int win_w, int win_h, const char *msg, SDL_Texture **out_tex, SDL_Rect *out_rect);

// Render text with fixed pixel size.
int recreate_text_px(SDL_Renderer *renderer, const char *msg, int pixel_size, SDL_Texture **out_tex, SDL_Rect *out_rect);

// Render PT panel text with automatic size adjustment to fit screen constraints.
int recreate_pt_panel(SDL_Renderer *renderer, int win_w, int win_h, const char *msg, SDL_Texture **out_tex, SDL_Rect *out_rect);

// Render hover label text with automatic size adjustment to fit screen constraints.
int recreate_hover_label(SDL_Renderer *renderer, int win_w, int win_h, const char *msg, SDL_Texture **out_tex, SDL_Rect *out_rect);

// Helper to set bottom-centered text with backdrop bookkeeping.
void set_bottom_text(SDL_Renderer *renderer, int win_w, int win_h, const char *msg,
                     SDL_Texture **text_tex, SDL_Rect *text_rect, char **current_msg,
                     bool *show_text);

// Subtitle font bias (in pixels) applied on top of the auto size.
// Positive increases size; negative decreases. Clamped internally.
void set_subtitle_font_bias(int bias_px);
int get_subtitle_font_bias(void);

typedef struct SubtitleLayout {
  int count;       // number of codepoints
  int *x_offsets;  // size count, x in pixels relative to rendered texture
  int *widths;     // size count, width in pixels per codepoint (advance)
  int tex_w;       // texture width
  int tex_h;       // texture height
  int font_px;     // font pixel size used
} SubtitleLayout;

// Render text and also compute per-codepoint layout for highlighting.
// Caller must free layout buffers via free_subtitle_layout.
int recreate_text_with_layout(SDL_Renderer *renderer, int win_w, int win_h, const char *msg,
                              SDL_Texture **out_tex, SDL_Rect *out_rect, SubtitleLayout *out_layout);
void free_subtitle_layout(SubtitleLayout *layout);


