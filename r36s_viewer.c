// Main entry includes
#include <SDL2/SDL.h>
#include <SDL2/SDL_image.h>
#include <SDL2/SDL_ttf.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "base.h"
#include "text.h"
#include "ui.h"

static void render_message(SDL_Renderer *renderer, int win_w, int win_h, const char *msg) {
  // Simple fallback message as a filled rectangle and we can't draw text without TTF; just clear and leave.
  (void)msg;
  SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
  SDL_RenderClear(renderer);
  SDL_RenderPresent(renderer);
}

// Text helpers are provided by text.h/text.c

// Types and functions for menu/images come from ui.h/ui.c

typedef struct WordSpan {
  int start_cp; // inclusive
  int end_cp;   // exclusive
  int x;        // pixels within text texture
  int w;        // width in pixels
} WordSpan;

typedef struct WordLayout {
  WordSpan *spans;
  int count;
} WordLayout;

static void free_word_layout(WordLayout *wl) {
  if (!wl) return;
  free(wl->spans); wl->spans = NULL; wl->count = 0;
}

static char *strdup_trim_range(const char *s, int start, int end) {
  while (start < end && (s[start] == ' ' || s[start] == '\t')) start++;
  while (end > start && (s[end-1] == ' ' || s[end-1] == '\t')) end--;
  int len = end - start;
  char *out = (char *)malloc((size_t)len + 1);
  if (!out) return NULL;
  memcpy(out, s + start, (size_t)len);
  out[len] = '\0';
  return out;
}

// Extract word tokens (left of '(' preferred, else ':' fallback) from a pairs string that is
// usually uma lista JSON de strings no formato "palavra(pinyin): tradução" ou "palavra: tradução".
// Retorna array de palavras (strdup) para mapeamento na frase.
static void extract_words_from_pairs(const char *pairs_str, char ***out_words, int *out_count) {
  *out_words = NULL; *out_count = 0;
  if (!pairs_str || !*pairs_str) return;
  const char *s = pairs_str;
  // Heuristic JSON-like parsing
  if (s[0] == '[') {
    int cap = 8; char **words = (char **)malloc(sizeof(char *) * (size_t)cap);
    int cnt = 0; int i = 0; int n = (int)strlen(s);
    while (i < n) {
      // find next opening quote
      while (i < n && s[i] != '"') i++;
      if (i >= n) break; int q1 = ++i; // after quote
      while (i < n && s[i] != '"') i++;
      if (i >= n) break; int q2 = i; // closing quote index
      // content is s[q1:q2)
      // split preferring '(' or '（' (fullwidth). Fallback to ':'
      int j = q1; int end = q2;
      while (j < q2 && s[j] != '(') j++;
      if (j < q2) end = j; else {
        j = q1; while (j < q2 && s[j] != ':') j++;
        if (j < q2) end = j;
      }
      char *w = strdup_trim_range(s, q1, end);
      if (w && *w) {
        if (cnt == cap) { cap *= 2; words = (char **)realloc(words, sizeof(char *) * (size_t)cap); }
        words[cnt++] = w;
      } else if (w) { free(w); }
      i = q2 + 1;
    }
    *out_words = words; *out_count = cnt; return;
  }
  // Fallback: split by commas then by colon
  int cap = 8; char **words = (char **)malloc(sizeof(char *) * (size_t)cap); int cnt = 0;
  const char *p = s; const char *seg = p;
  while (*p) {
    if (*p == ',') {
      int seglen = (int)(p - seg);
      // find '(' or '（' inside seg; fallback ':'
      int k = 0; while (k < seglen && seg[k] != '(' && seg[k] != ':') k++;
      char *w = strdup_trim_range(seg, 0, (k < seglen) ? k : seglen);
      if (w && *w) { if (cnt == cap) { cap *= 2; words = (char **)realloc(words, sizeof(char *) * (size_t)cap); } words[cnt++] = w; } else if (w) free(w);
      seg = p + 1;
    }
    p++;
  }
  if (p != seg) {
    int seglen = (int)(p - seg);
    int k = 0; while (k < seglen && seg[k] != '(' && seg[k] != ':') k++;
    char *w = strdup_trim_range(seg, 0, (k < seglen) ? k : seglen);
    if (w && *w) { if (cnt == cap) { cap *= 2; words = (char **)realloc(words, sizeof(char *) * (size_t)cap); } words[cnt++] = w; } else if (w) free(w);
  }
  *out_words = words; *out_count = cnt;
}

// Parse words and their full "word: tradução" items from pairs
static void extract_words_and_items_from_pairs(const char *pairs_str, char ***out_words, char ***out_items, int *out_count) {
  *out_words = NULL; if (out_items) *out_items = NULL; if (out_count) *out_count = 0;
  if (!pairs_str || !*pairs_str) return;
  const char *s = pairs_str;
  int cap = 8; int cnt = 0;
  char **words = (char **)malloc(sizeof(char *) * (size_t)cap);
  char **items = (char **)malloc(sizeof(char *) * (size_t)cap);
  if (!words || !items) { if (words) free(words); if (items) free(items); return; }
  if (s[0] == '[') {
    int i = 0; int n = (int)strlen(s);
    while (i < n) {
      while (i < n && s[i] != '"') i++;
      if (i >= n) break; int q1 = ++i;
      while (i < n && s[i] != '"') i++;
      if (i >= n) break; int q2 = i; // [q1,q2)
      int j = q1; int end = q2;
      while (j < q2 && s[j] != '(') j++;
      if (j < q2) end = j; else { j = q1; while (j < q2 && s[j] != ':') j++; if (j < q2) end = j; }
      char *w = strdup_trim_range(s, q1, end);
      char *it = strdup_trim_range(s, q1, q2);
      if (w && *w && it && *it) {
        if (cnt == cap) { cap *= 2; words = (char **)realloc(words, sizeof(char *) * (size_t)cap); items = (char **)realloc(items, sizeof(char *) * (size_t)cap); }
        words[cnt] = w; items[cnt] = it; cnt++;
      } else { if (w) free(w); if (it) free(it); }
      i = q2 + 1;
    }
  } else {
    const char *p = s; const char *seg = p;
    while (*p) {
      if (*p == ',') {
        int seglen = (int)(p - seg);
        int k = 0; while (k < seglen && seg[k] != '(' && seg[k] != ':') k++;
        char *w = strdup_trim_range(seg, 0, (k < seglen) ? k : seglen);
        char *it = strdup_trim_range(seg, 0, seglen);
        if (w && *w && it && *it) {
          if (cnt == cap) { cap *= 2; words = (char **)realloc(words, sizeof(char *) * (size_t)cap); items = (char **)realloc(items, sizeof(char *) * (size_t)cap); }
          words[cnt] = w; items[cnt] = it; cnt++;
        } else { if (w) free(w); if (it) free(it); }
        seg = p + 1;
      }
      p++;
    }
    if (p != seg) {
      int seglen = (int)(p - seg);
      int k = 0; while (k < seglen && seg[k] != '(' && seg[k] != ':') k++;
      char *w = strdup_trim_range(seg, 0, (k < seglen) ? k : seglen);
      char *it = strdup_trim_range(seg, 0, seglen);
      if (w && *w && it && *it) {
        if (cnt == cap) { cap *= 2; words = (char **)realloc(words, sizeof(char *) * (size_t)cap); items = (char **)realloc(items, sizeof(char *) * (size_t)cap); }
        words[cnt] = w; items[cnt] = it; cnt++;
      } else { if (w) free(w); if (it) free(it); }
    }
  }
  *out_words = words; if (out_items) *out_items = items; if (out_count) *out_count = cnt;
}
// Compute word spans based on zht text and list of words; uses subtitle layout mapping x offsets for cps
static int byte_to_cp_linear(const int *cp_byte_index, int total_cp, int bidx) {
  int i = 0; while (i + 1 < total_cp && cp_byte_index[i + 1] <= bidx) i++; return i;
}

static void build_word_layout(const char *zht_text, const SubtitleLayout *layout, char **words, int word_count, WordLayout *out_layout) {
  free_word_layout(out_layout);
  if (!zht_text || !*zht_text || !layout || layout->count <= 0 || word_count <= 0) return;
  // Precompute byte positions of each codepoint start
  int total_cp = layout->count;
  const unsigned char *s = (const unsigned char *)zht_text;
  int *cp_byte_index = (int *)malloc(sizeof(int) * (size_t)total_cp);
  int cp = 0; int byte_idx = 0; int slen = (int)strlen(zht_text);
  while (byte_idx < slen && cp < total_cp) {
    cp_byte_index[cp++] = byte_idx;
    unsigned char c = s[byte_idx];
    int adv = 1; if ((c & 0xE0) == 0xC0) adv = 2; else if ((c & 0xF0) == 0xE0) adv = 3; else if ((c & 0xF8) == 0xF0) adv = 4;
    byte_idx += adv;
  }

  int cap = 8; WordSpan *spans = (WordSpan *)malloc(sizeof(WordSpan) * (size_t)cap); int cnt = 0;
  for (int w = 0; w < word_count; ++w) {
    const char *needle = words[w]; if (!needle || !*needle) continue;
    const char *pos = zht_text; int off = 0; int needle_len = (int)strlen(needle);
    while ((pos = strstr(pos, needle)) != NULL) {
      off = (int)(pos - zht_text);
      int start_cp = byte_to_cp_linear(cp_byte_index, total_cp, off);
      int len_cp = utf8_count_codepoints(needle);
      int end_cp = start_cp + len_cp; if (end_cp > total_cp) end_cp = total_cp;
      int x = layout->x_offsets[start_cp];
      int end_x = (end_cp - 1 >= 0) ? (layout->x_offsets[end_cp - 1] + layout->widths[end_cp - 1]) : x;
      int wpx = end_x - x; if (wpx <= 0) { pos += needle_len; continue; }
      if (cnt == cap) { cap *= 2; spans = (WordSpan *)realloc(spans, sizeof(WordSpan) * (size_t)cap); }
      spans[cnt++] = (WordSpan){ start_cp, end_cp, x, wpx };
      pos += needle_len;
    }
  }
  free(cp_byte_index);
  out_layout->spans = spans; out_layout->count = cnt;
}

static void rebuild_subtitle(
    SDL_Renderer *renderer,
    int win_w,
    int win_h,
    const char *msg,
    SDL_Texture **text_tex,
    SDL_Rect *text_rect,
    SubtitleLayout *layout,
    bool *show_text,
    int *hover_index
) {
  if (!msg || !*msg) {
    if (*text_tex) { SDL_DestroyTexture(*text_tex); *text_tex = NULL; }
    free_subtitle_layout(layout);
    *show_text = false;
    *hover_index = -1;
    return;
  }
  if (*text_tex) { SDL_DestroyTexture(*text_tex); *text_tex = NULL; }
  free_subtitle_layout(layout);
  if (recreate_text_with_layout(renderer, win_w, win_h, msg, text_tex, text_rect, layout) == 0 && *text_tex) {
    text_rect->x = (win_w - text_rect->w) / 2;
    text_rect->y = win_h - text_rect->h - 24;
    *show_text = true;
    *hover_index = -1;
  } else {
    *show_text = false;
    *hover_index = -1;
  }
}

static void refresh_word_layout_for_time(
    const BaseData *base,
    int time_seconds,
    const char *current_text_msg,
    const SubtitleLayout *sub_layout,
    WordLayout *word_layout,
    char ***out_pair_words,
    char ***out_pair_items,
    int *out_pair_count
) {
  free_word_layout(word_layout);
  if (!current_text_msg || !*current_text_msg || !sub_layout || sub_layout->count <= 0) return;
  
  // Find entry by time instead of index
  const BaseEntry *entry = find_entry_by_time(base, time_seconds);
  const char *pairs = entry ? entry->pairs_text : NULL;
  
  char **words = NULL; int wc = 0;
  extract_words_from_pairs(pairs, &words, &wc);
  build_word_layout(current_text_msg, sub_layout, words, wc, word_layout);
  if (out_pair_words) {
    if (*out_pair_words) { for (int i = 0; i < (out_pair_count ? *out_pair_count : 0); ++i) free((*out_pair_words)[i]); free(*out_pair_words); }
    *out_pair_words = words; // transfer ownership
  } else {
    for (int i = 0; i < wc; ++i) free(words[i]);
    free(words);
  }
  if (out_pair_items) {
    // We also store the original items; since our parser keeps only words, reuse words as items placeholder
    // For now, mirror words into items; the 4th column full string will still be shown when no match
    *out_pair_items = NULL; // unused placeholder
  }
  if (out_pair_count) *out_pair_count = wc;
}

static void refresh_word_layout_for_index(
    const BaseData *base,
    long img_idx,
    const char *current_text_msg,
    const SubtitleLayout *sub_layout,
    WordLayout *word_layout,
    char ***out_pair_words,
    char ***out_pair_items,
    int *out_pair_count
) {
  free_word_layout(word_layout);
  if (!current_text_msg || !*current_text_msg || !sub_layout || sub_layout->count <= 0) return;
  const char *pairs = (base && base->pairs_by_index && img_idx > 0 && base->capacity > img_idx)
                          ? base->pairs_by_index[img_idx]
                          : NULL;
  char **words = NULL; int wc = 0;
  extract_words_from_pairs(pairs, &words, &wc);
  build_word_layout(current_text_msg, sub_layout, words, wc, word_layout);
  if (out_pair_words) {
    if (*out_pair_words) { for (int i = 0; i < (out_pair_count ? *out_pair_count : 0); ++i) free((*out_pair_words)[i]); free(*out_pair_words); }
    *out_pair_words = words; // transfer ownership
  } else {
    for (int i = 0; i < wc; ++i) free(words[i]);
    free(words);
  }
  if (out_pair_items) {
    // We also store the original items; since our parser keeps only words, reuse words as items placeholder
    // For now, mirror words into items; the 4th column full string will still be shown when no match
    *out_pair_items = NULL; // unused placeholder
  }
  if (out_pair_count) *out_pair_count = wc;
  // Fallback: if we didn't detect any words, make each codepoint a span so hover still works
  if (word_layout->count == 0 && sub_layout->count > 0) {
    word_layout->spans = (WordSpan *)malloc(sizeof(WordSpan) * (size_t)sub_layout->count);
    word_layout->count = sub_layout->count;
    for (int i = 0; i < sub_layout->count; ++i) {
      int x = sub_layout->x_offsets[i];
      int w = sub_layout->widths[i];
      word_layout->spans[i] = (WordSpan){ i, i + 1, x, w };
    }
  }
}

static char *utf8_substr_by_cp(const char *s, int start_cp, int end_cp) {
  if (!s || start_cp < 0 || end_cp <= start_cp) return NULL;
  int cp = 0; int i = 0; int len = (int)strlen(s);
  int start_byte = 0, end_byte = len;
  while (i < len && cp < start_cp) {
    unsigned char c = (unsigned char)s[i]; int adv = 1; if ((c & 0xE0) == 0xC0) adv = 2; else if ((c & 0xF0) == 0xE0) adv = 3; else if ((c & 0xF8) == 0xF0) adv = 4; i += adv; cp++;
  }
  start_byte = i;
  while (i < len && cp < end_cp) {
    unsigned char c = (unsigned char)s[i]; int adv = 1; if ((c & 0xE0) == 0xC0) adv = 2; else if ((c & 0xF0) == 0xE0) adv = 3; else if ((c & 0xF8) == 0xF0) adv = 4; i += adv; cp++;
  }
  end_byte = i;
  int out_len = end_byte - start_byte; if (out_len <= 0) return NULL;
  char *out = (char *)malloc((size_t)out_len + 1); if (!out) return NULL;
  memcpy(out, s + start_byte, (size_t)out_len); out[out_len] = '\0';
  return out;
}

static void update_hover_info_by_time(SDL_Renderer *renderer, int win_w, int win_h,
                              const char *current_text_msg, const BaseData *base, int time_seconds,
                              const SubtitleLayout *sub_layout, const WordLayout *word_layout,
                              char **pair_words, int pair_count, int hover_index,
                              SDL_Texture **hover_tex, SDL_Rect *hover_rect,
                              const SDL_Rect *subtitle_rect) {
  if (*hover_tex) { SDL_DestroyTexture(*hover_tex); *hover_tex = NULL; }
  if (!current_text_msg || !sub_layout || !word_layout || hover_index < 0 || hover_index >= word_layout->count) return;
  // Extract hovered word text
  WordSpan span = word_layout->spans[hover_index];
  char *hover_word = utf8_substr_by_cp(current_text_msg, span.start_cp, span.end_cp);
  char *display_owned = NULL; // we will allocate a safe copy to avoid use-after-free
  // Try to find matching item in pairs by word equality
  if (hover_word && pair_words && pair_count > 0) {
    // Find entry by time and get pairs text
    const BaseEntry *entry = find_entry_by_time(base, time_seconds);
    const char *pairs_full = entry ? entry->pairs_text : NULL;
    if (pairs_full && *pairs_full) {
      // find item whose prefix before ':' equals hover_word
      int cnt = 0; char **words = NULL; char **items = NULL; extract_words_and_items_from_pairs(pairs_full, &words, &items, &cnt);
      for (int i = 0; i < cnt; ++i) {
        if (words[i] && strcmp(words[i], hover_word) == 0) {
          // duplicate the matched item so we can safely free arrays
          display_owned = strdup(items[i]);
          break;
        }
      }
      for (int i = 0; i < cnt; ++i) { if (words && words[i]) free(words[i]); if (items && items[i]) free(items[i]); }
      free(words); free(items);
    }
  }
  if (!display_owned) {
    // If not matched, fallback to full pairs text from entry
    const BaseEntry *entry = find_entry_by_time(base, time_seconds);
    const char *pairs = entry ? entry->pairs_text : NULL;
    display_owned = strdup(pairs && *pairs ? pairs : "N/A");
  }
  // Normalize formatting: ensure single space before '(' if missing
  if (display_owned) {
    char *lp = strchr(display_owned, '(');
    if (lp && lp > display_owned && *(lp - 1) != ' ') {
      size_t pre_len = (size_t)(lp - display_owned);
      size_t rest_len = strlen(lp); // includes '('
      char *norm = (char *)malloc(pre_len + 1 + rest_len + 1);
      if (norm) {
        memcpy(norm, display_owned, pre_len);
        norm[pre_len] = ' ';
        memcpy(norm + pre_len + 1, lp, rest_len + 1); // includes terminator
        free(display_owned);
        display_owned = norm;
      }
    }
  }
  if (display_owned) {
    if (recreate_hover_label(renderer, win_w, win_h, display_owned, hover_tex, hover_rect) == 0 && *hover_tex) {
      // Position above the subtitle (ZHT text), centered horizontally like PT panel
      hover_rect->x = (win_w - hover_rect->w) / 2;
      hover_rect->y = subtitle_rect->y - hover_rect->h - 8;
    }
    free(display_owned);
  }
  if (hover_word) free(hover_word);
}


static void update_hover_info(SDL_Renderer *renderer, int win_w, int win_h,
                              const char *current_text_msg, const BaseData *base, long img_idx,
                              const SubtitleLayout *sub_layout, const WordLayout *word_layout,
                              char **pair_words, int pair_count, int hover_index,
                              SDL_Texture **hover_tex, SDL_Rect *hover_rect,
                              const SDL_Rect *subtitle_rect) {
  if (*hover_tex) { SDL_DestroyTexture(*hover_tex); *hover_tex = NULL; }
  if (!current_text_msg || !sub_layout || !word_layout || hover_index < 0 || hover_index >= word_layout->count) return;
  // Extract hovered word text
  WordSpan span = word_layout->spans[hover_index];
  char *hover_word = utf8_substr_by_cp(current_text_msg, span.start_cp, span.end_cp);
  char *display_owned = NULL; // we will allocate a safe copy to avoid use-after-free
  // Try to find matching item in pairs by word equality
  if (hover_word && pair_words && pair_count > 0) {
    // We will search for the full string "word: tradução" in the base column
    const char *pairs_full = (base && base->pairs_by_index && img_idx > 0 && base->capacity > img_idx) ? base->pairs_by_index[img_idx] : NULL;
    if (pairs_full && *pairs_full) {
      // find item whose prefix before ':' equals hover_word
      int cnt = 0; char **words = NULL; char **items = NULL; extract_words_and_items_from_pairs(pairs_full, &words, &items, &cnt);
      for (int i = 0; i < cnt; ++i) {
        if (words[i] && strcmp(words[i], hover_word) == 0) {
          // duplicate the matched item so we can safely free arrays
          display_owned = strdup(items[i]);
          break;
        }
      }
      for (int i = 0; i < cnt; ++i) { if (words && words[i]) free(words[i]); if (items && items[i]) free(items[i]); }
      free(words); free(items);
    }
  }
  if (!display_owned) {
    // If not matched, fallback to full 4th column
    const char *pairs = (base && base->pairs_by_index && img_idx > 0 && base->capacity > img_idx) ? base->pairs_by_index[img_idx] : NULL;
    display_owned = strdup(pairs && *pairs ? pairs : "N/A");
  }
  // Normalize formatting: ensure single space before '(' if missing
  if (display_owned) {
    char *lp = strchr(display_owned, '(');
    if (lp && lp > display_owned && *(lp - 1) != ' ') {
      size_t pre_len = (size_t)(lp - display_owned);
      size_t rest_len = strlen(lp); // includes '('
      char *norm = (char *)malloc(pre_len + 1 + rest_len + 1);
      if (norm) {
        memcpy(norm, display_owned, pre_len);
        norm[pre_len] = ' ';
        memcpy(norm + pre_len + 1, lp, rest_len + 1);
        free(display_owned);
        display_owned = norm;
      }
    }
  }
  recreate_hover_label(renderer, win_w, win_h, display_owned ? display_owned : "N/A", hover_tex, hover_rect);
  // Position above the hovered span
  hover_rect->x = win_w/2 - hover_rect->w/2;
  hover_rect->y = subtitle_rect->y - hover_rect->h - 20;
  if (hover_rect->y < 8) hover_rect->y = 8;
  free(hover_word);
  if (display_owned) free(display_owned);
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
  bool locked_on_subtitle = false; // True when stopped on an image with subtitle
  Menu menu = {0};
  if (menu_active) {
    menu = build_menu(renderer, win_w, win_h, assets_root);
    
    // Render initial menu immediately so it's visible on startup
    fprintf(stdout, "DEBUG: Rendering initial menu (count=%d)\n", menu.count);
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    if (menu.count > 0) {
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
    SDL_RenderPresent(renderer);
    fprintf(stdout, "DEBUG: Initial menu render complete\n");
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
  SDL_Rect src_rect = {0, 0, 0, 0}; // when using cover mode
  bool cover_mode = true; // fill the screen by default

  // Text overlay state
  bool show_text = false;
  SDL_Texture *text_tex = NULL;
  SDL_Rect text_rect = (SDL_Rect){0, 0, 0, 0};
  char *current_text_msg = NULL; // keep last message to reflow on resize
  SubtitleLayout sub_layout = {0};
  int hover_index = -1; // selected word index
  WordLayout word_layout = {0};

  // Hover info (pairs/word display)
  SDL_Texture *hover_info_tex = NULL;
  SDL_Rect hover_info_rect = (SDL_Rect){0, 0, 0, 0};
  char **pair_words_cache = NULL;
  char **pair_items_cache = NULL; // full "word: tradução"
  int pair_words_count = 0;

  // PT translation panel state (toggle with B)
  bool show_pt = false;
  SDL_Texture *pt_tex = NULL;
  SDL_Rect pt_rect = (SDL_Rect){0, 0, 0, 0};
  char *current_pt_msg = NULL;

  // Small index label (top-left)
  SDL_Texture *idx_tex = NULL;
  SDL_Rect idx_rect = (SDL_Rect){0, 0, 0, 0};

  // Base data for the current directory
  BaseData base = {0};

  if (!menu_active) {
    if (list.count == 0) {
      render_message(renderer, win_w, win_h, "No images found");
    } else {
      current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
      if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);

      // On first load, attempt to load base file for the directory
      // Determine directory from first image path
      if (list.count > 0 && list.paths[0]) {
        const char *first_path = list.paths[0];
        // Build directory string
        const char *last_slash = strrchr(first_path, '/');
        if (last_slash) {
          size_t dirlen = (size_t)(last_slash - first_path);
          char *dircopy = (char *)malloc(dirlen + 1);
          if (dircopy) {
            memcpy(dircopy, first_path, dirlen);
            dircopy[dirlen] = '\0';
            free_base_data(&base);
            base = load_base_file_for_directory(dircopy);
            free(dircopy);
          }
        }
      }
      // If there is a base entry matching the image time, render its zht at bottom
      long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
      const BaseEntry *entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
      if (entry && entry->zht_text) {
        if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
        current_text_msg = strdup(entry->zht_text);
        rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
        refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
      } else {
        if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
        if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
        show_text = false;
      }
      // Build top-left small label with current numeric index
      {
        char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
        if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
        if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) {
          idx_rect.x = 8; idx_rect.y = 8;
        }
      }
      
      // Render the first image immediately so it's visible on startup
      SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
      SDL_RenderClear(renderer);
      if (current) {
        if (cover_mode) SDL_RenderCopy(renderer, current, &src_rect, &dst_rect);
        else SDL_RenderCopy(renderer, current, NULL, &dst_rect);
      }
      if (show_text && text_tex) {
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 160);
        SDL_Rect bg = { text_rect.x - 12, text_rect.y - 8, text_rect.w + 24, text_rect.h + 16 };
        SDL_RenderFillRect(renderer, &bg);
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
        SDL_RenderCopy(renderer, text_tex, NULL, &text_rect);
      }
      if (idx_tex) {
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 120);
        SDL_Rect bg = { idx_rect.x - 4, idx_rect.y - 2, idx_rect.w + 8, idx_rect.h + 4 };
        SDL_RenderFillRect(renderer, &bg);
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
        SDL_RenderCopy(renderer, idx_tex, NULL, &idx_rect);
      }
      SDL_RenderPresent(renderer);
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
      } else if (e.type == SDL_WINDOWEVENT) {
        if (e.window.event == SDL_WINDOWEVENT_SIZE_CHANGED || e.window.event == SDL_WINDOWEVENT_RESIZED) {
          SDL_GetRendererOutputSize(renderer, &win_w, &win_h);
          // Recompute destination rect to fit new window while preserving aspect ratio
          if (current) {
            if (cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);
            else compute_dst_from_texture(current, win_w, win_h, &dst_rect);
          }
          // Recreate text at new size/position if visible
          if (show_text && current_text_msg) rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
          // rebuild word layout on resize
          if (current_text_msg) { long tmp_time = 0; basename_numeric_value(list.paths[index], &tmp_time);
            refresh_word_layout_for_time(&base, (int)tmp_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count); }
          if (show_pt && current_pt_msg) {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
              pt_rect.x = (win_w - pt_rect.w) / 2;
              int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
              if (base_y < 8) base_y = 8;
              pt_rect.y = base_y;
            }
          }
          if (idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
        }
      } else if (e.type == SDL_KEYDOWN) {
        SDL_Keycode key = e.key.keysym.sym;
        if (key == SDLK_ESCAPE || key == SDLK_q) {
          running = false;
        } else if (key == SDLK_m) {
        } else if (!menu_active && (key == SDLK_y || key == SDLK_x)) {
          // Manual font size bias for subtitle
          int bias = get_subtitle_font_bias();
          if (key == SDLK_y) bias += 2; // increase
          else bias -= 2;               // decrease
          if (bias < -50) bias = -50;
          if (bias > 100) bias = 100;
          set_subtitle_font_bias(bias);
          // Recreate current subtitle texture with new bias
          if (show_text && current_text_msg) rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
          // Also adjust PT panel position since subtitle height may change
          if (show_pt && current_pt_msg) {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
              pt_rect.x = (win_w - pt_rect.w) / 2;
              int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
              if (base_y < 8) base_y = 8;
              pt_rect.y = base_y;
            }
          }
        } else if (!menu_active && key == SDLK_b) {
          // Toggle PT translation panel (from base file column 5)
          // Clear hover state and label when toggling PT, and unlock navigation
          hover_index = -1;
          locked_on_subtitle = false; // Unlock navigation when toggling PT
          if (hover_info_tex) { SDL_DestroyTexture(hover_info_tex); hover_info_tex = NULL; }
          show_pt = !show_pt;
          if (show_pt) {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            const char *pt = NULL;
            long img_time = 0; bool ok = (!menu_active && list.count > 0) ? basename_numeric_value(list.paths[index], &img_time) : false;
            if (ok) {
              const BaseEntry *entry = find_entry_by_time(&base, (int)img_time);
              pt = entry ? entry->pt_text : NULL;
            } else {
              pt = NULL;
            }
            if (pt) { /* found via time lookup */ }
            if (!pt || !*pt) pt = "N/A";
            current_pt_msg = strdup(pt);
            if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
              pt_rect.x = (win_w - pt_rect.w) / 2;
              int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
              if (base_y < 8) base_y = 8;
              pt_rect.y = base_y;
            }
          } else {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
          }
        } else if (!menu_active && key == SDLK_r) {
          // R key unlocks navigation (mirrors R1 shoulder button)
          locked_on_subtitle = false;
        } else if (!menu_active && key == SDLK_l) {
          // L key jumps forward 100 images (mirrors L1 shoulder button)
          if (list.count > 0) {
            // Hide PT panel when changing images
            show_pt = false;
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            
            // Jump forward 100 images (with wrap-around)
            index = (index + 100) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);
            
            // Check if this image has a subtitle - if so, lock navigation
            long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
            const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
            if (zht_entry && zht_entry->zht_text) {
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              current_text_msg = strdup(zht_entry->zht_text);
              rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
              refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
              locked_on_subtitle = true; // Lock when we find an image with subtitle
              hover_index = -1; // Reset hover to start
            } else {
              if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              show_text = false;
              locked_on_subtitle = false; // Don't lock on images without subtitle
            }
            if (show_pt) {
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
              const BaseEntry *pt_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
              const char *pt = pt_entry ? pt_entry->pt_text : NULL;
              if (!pt || !*pt) pt = "N/A";
              current_pt_msg = strdup(pt);
              if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
                pt_rect.x = (win_w - pt_rect.w) / 2;
                int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
                if (base_y < 8) base_y = 8;
                pt_rect.y = base_y;
              }
            }
            // Update small index label
            {
              char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
              if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
              if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
            }
          }
        } else if (!menu_active && key == SDLK_a) {
          // Restore default view via keyboard 'A': image + ZHT, no hover, no translation label, PT panel closed, and unlock navigation
          show_pt = false;
          if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
          if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
          hover_index = -1;
          locked_on_subtitle = false; // Unlock navigation when resetting view
          if (hover_info_tex) { SDL_DestroyTexture(hover_info_tex); hover_info_tex = NULL; }
          long img_time = 0; bool ok = (!menu_active && list.count > 0) ? basename_numeric_value(list.paths[index], &img_time) : false;
          const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
          const char *zht = zht_entry ? zht_entry->zht_text : NULL;
          if (zht && *zht) {
            if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
            current_text_msg = strdup(zht);
            rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
            refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
          }
        } else if (!menu_active && key == SDLK_UP) {
          if (list.count > 0 && !locked_on_subtitle) {
            // Hide PT panel when changing images
            show_pt = false;
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            
            index = (index - 1 + list.count) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);

            // Check if this image has a subtitle - if so, lock navigation
            long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
            const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
            if (zht_entry && zht_entry->zht_text) {
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              current_text_msg = strdup(zht_entry->zht_text);
              rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
              refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
              locked_on_subtitle = true; // Lock when we find an image with subtitle
              hover_index = -1; // Reset hover to start
            } else {
              if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              show_text = false;
              locked_on_subtitle = false; // Don't lock on images without subtitle
            }
            if (show_pt) {
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
              const BaseEntry *pt_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
              const char *pt = pt_entry ? pt_entry->pt_text : NULL;
              if (!pt || !*pt) pt = "N/A";
              current_pt_msg = strdup(pt);
              if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
                pt_rect.x = (win_w - pt_rect.w) / 2;
                int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
                if (base_y < 8) base_y = 8;
                pt_rect.y = base_y;
              }
            }
            // Update small index label
            {
              char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
              if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
              if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
            }
          }
        } else if (!menu_active && key == SDLK_DOWN) {
          if (list.count > 0 && !locked_on_subtitle) {
            // Hide PT panel when changing images
            show_pt = false;
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            
            // Move to next image sequentially
            index = (index + 1) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);
            
            // Check if this image has a subtitle - if so, lock navigation
            long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
            const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
            if (zht_entry && zht_entry->zht_text) {
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              current_text_msg = strdup(zht_entry->zht_text);
              rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
              refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, NULL, &pair_words_count);
              locked_on_subtitle = true; // Lock when we find an image with subtitle
              hover_index = -1; // Reset hover to start
            } else {
              if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              show_text = false;
              locked_on_subtitle = false; // Don't lock on images without subtitle
            }
            
            if (show_pt) {
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
              const BaseEntry *pt_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
              const char *pt = pt_entry ? pt_entry->pt_text : NULL;
              if (!pt || !*pt) pt = "N/A";
              current_pt_msg = strdup(pt);
              if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
                pt_rect.x = (win_w - pt_rect.w) / 2;
                int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
                if (base_y < 8) base_y = 8;
                pt_rect.y = base_y;
              }
            }
            // Update small index label
            {
              char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
              if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
              if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
            }
          }
        } else if (!menu_active && key == SDLK_RIGHT) {
          // Move hover to next word
          if (show_text && word_layout.count > 0) {
            // Hide PT panel when navigating hover
            if (show_pt) {
              show_pt = false;
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            }
            if (hover_index < 0) hover_index = 0; else hover_index = (hover_index + 1) % word_layout.count;
            long img_time = 0; basename_numeric_value(list.paths[index], &img_time);
            update_hover_info_by_time(renderer, win_w, win_h, current_text_msg, &base, (int)img_time, &sub_layout, &word_layout, pair_words_cache, pair_words_count, hover_index, &hover_info_tex, &hover_info_rect, &text_rect);
            locked_on_subtitle = false; // Unlock when user navigates words
          }
        } else if (!menu_active && key == SDLK_LEFT) {
          if (show_text && word_layout.count > 0) {
            // Hide PT panel when navigating hover
            if (show_pt) {
              show_pt = false;
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            }
            if (hover_index < 0) hover_index = word_layout.count - 1; else hover_index = (hover_index - 1 + word_layout.count) % word_layout.count;
            long img_time = 0; basename_numeric_value(list.paths[index], &img_time);
            update_hover_info_by_time(renderer, win_w, win_h, current_text_msg, &base, (int)img_time, &sub_layout, &word_layout, pair_words_cache, pair_words_count, hover_index, &hover_info_tex, &hover_info_rect, &text_rect);
            locked_on_subtitle = false; // Unlock when user navigates words
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
            free_base_data(&base);
            base = load_base_file_for_directory(pathbuf);
            index = 0;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            if (list.count > 0) {
              current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
              // set overlay for first image
              long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
              const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
              if (zht_entry && zht_entry->zht_text) {
                if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
                current_text_msg = strdup(zht_entry->zht_text);
                rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
                // Build word layout for the newly selected first image
                free_word_layout(&word_layout);
                char **words_m = NULL; int wc_m = 0;
                const char *pairs_m = zht_entry ? zht_entry->pairs_text : NULL;
                extract_words_from_pairs(pairs_m, &words_m, &wc_m);
                build_word_layout(current_text_msg, &sub_layout, words_m, wc_m, &word_layout);
                for (int ii = 0; ii < wc_m; ++ii) free(words_m[ii]);
                free(words_m);
              } else {
                if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
                if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
                show_text = false;
              }
              // Update small index label
              {
                char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
                if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
                if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
              }
            }
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
        if (!menu_active && (e.cbutton.button == SDL_CONTROLLER_BUTTON_Y || e.cbutton.button == SDL_CONTROLLER_BUTTON_X)) {
          int bias = get_subtitle_font_bias();
          if (e.cbutton.button == SDL_CONTROLLER_BUTTON_Y) bias += 2; else bias -= 2;
          if (bias < -50) bias = -50;
          if (bias > 100) bias = 100;
          set_subtitle_font_bias(bias);
          if (show_text && current_text_msg) {
            set_bottom_text(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &current_text_msg, &show_text);
          }
          if (show_pt && current_pt_msg) {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
              pt_rect.x = (win_w - pt_rect.w) / 2;
              int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
              if (base_y < 8) base_y = 8;
              pt_rect.y = base_y;
            }
          }
        } else if (e.cbutton.button == SDL_CONTROLLER_BUTTON_START && SDL_GameControllerGetButton(SDL_GameControllerFromInstanceID(e.cbutton.which), SDL_CONTROLLER_BUTTON_BACK)) {
          running = false; // Start+Back to quit
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_UP) {
          if (list.count > 0 && !locked_on_subtitle) {
            // Hide PT panel when changing images
            show_pt = false;
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            
            index = (index - 1 + list.count) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);

            // Check if this image has a subtitle - if so, lock navigation
            long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
            const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
            if (zht_entry && zht_entry->zht_text) {
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              current_text_msg = strdup(zht_entry->zht_text);
              rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
              refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
              locked_on_subtitle = true; // Lock when we find an image with subtitle
              hover_index = -1; // Reset hover to start
            } else {
              if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              show_text = false;
              locked_on_subtitle = false; // Don't lock on images without subtitle
            }
            if (show_pt) {
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
              const BaseEntry *pt_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
              const char *pt = pt_entry ? pt_entry->pt_text : NULL;
              if (!pt || !*pt) pt = "N/A";
              current_pt_msg = strdup(pt);
              if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
                pt_rect.x = (win_w - pt_rect.w) / 2;
                int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
                if (base_y < 8) base_y = 8;
                pt_rect.y = base_y;
              }
            }
            // Update small index label
            {
              char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
              if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
              if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
            }
          }
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
          if (list.count > 0 && !locked_on_subtitle) {
            // Hide PT panel when changing images
            show_pt = false;
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            
            // Move to next image sequentially
            index = (index + 1) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);
            
            // Check if this image has a subtitle - if so, lock navigation
            long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
            const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
            if (zht_entry && zht_entry->zht_text) {
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              current_text_msg = strdup(zht_entry->zht_text);
              rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
              locked_on_subtitle = true; // Lock when we find an image with subtitle
              hover_index = -1; // Reset hover to start
            } else {
              if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              show_text = false;
              locked_on_subtitle = false; // Don't lock on images without subtitle
            }
            
            // Update small index label
            {
              char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
              if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
              if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
            }
          }
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
          if (show_text && word_layout.count > 0) {
            // Hide PT panel when navigating hover
            if (show_pt) {
              show_pt = false;
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            }
            if (hover_index < 0) hover_index = 0; else hover_index = (hover_index + 1) % word_layout.count;
            locked_on_subtitle = false; // Unlock when user navigates words
          }
                  } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_LEFT) {
            if (show_text && word_layout.count > 0) {
              // Hide PT panel when navigating hover
              if (show_pt) {
                show_pt = false;
                if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
                if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
              }
              if (hover_index < 0) hover_index = word_layout.count - 1; else hover_index = (hover_index - 1 + word_layout.count) % word_layout.count;
              locked_on_subtitle = false; // Unlock when user navigates words
            }
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_A) {
          // Restore to default viewing state: image + ZHT text visible, no hover, no translation label, PT panel closed, and unlock navigation
          // Close PT panel
          show_pt = false;
          if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
          if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
          // Clear hover state and its label, and unlock navigation
          hover_index = -1;
          locked_on_subtitle = false; // Unlock navigation when resetting view
          if (hover_info_tex) { SDL_DestroyTexture(hover_info_tex); hover_info_tex = NULL; }
          // Ensure ZHT subtitle is visible for current image (when available)
          long img_time = 0; bool ok = (!menu_active && list.count > 0) ? basename_numeric_value(list.paths[index], &img_time) : false;
          const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
          const char *zht = zht_entry ? zht_entry->zht_text : NULL;
          if (zht && *zht) {
            if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
            current_text_msg = strdup(zht);
            rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
            // Prepare word layout for future hovers (even though hover is off now)
            refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
          }
        } else if (menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
          if (menu.count > 0) menu.selected = (menu.selected + 1) % menu.count;
        } else if (menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_DPAD_UP) {
          if (menu.count > 0) menu.selected = (menu.selected - 1 + menu.count) % menu.count;
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_B) {
          // Controller B toggles PT (mirrors keyboard B)
          // Clear hover state and label when toggling PT, and unlock navigation
          hover_index = -1;
          locked_on_subtitle = false; // Unlock navigation when toggling PT
          if (hover_info_tex) { SDL_DestroyTexture(hover_info_tex); hover_info_tex = NULL; }
          show_pt = !show_pt;
          if (show_pt) {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            const char *pt = NULL;
            long img_time = 0; bool ok = (!menu_active && list.count > 0) ? basename_numeric_value(list.paths[index], &img_time) : false;
            if (ok) {
              const BaseEntry *entry = find_entry_by_time(&base, (int)img_time);
              pt = entry ? entry->pt_text : NULL;
            } else {
              pt = NULL;
            }
            if (pt) { /* found via time lookup */ }
            if (!pt || !*pt) pt = "N/A";
            current_pt_msg = strdup(pt);
            if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
              pt_rect.x = (win_w - pt_rect.w) / 2;
              int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
              if (base_y < 8) base_y = 8;
              pt_rect.y = base_y;
            }
          } else {
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
          }
        } else if (menu_active && (e.cbutton.button == SDL_CONTROLLER_BUTTON_B)) {
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
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_RIGHTSHOULDER) {
          // R1 button unlocks navigation (allows continuing navigation after being locked on subtitle)
          locked_on_subtitle = false;
        } else if (!menu_active && e.cbutton.button == SDL_CONTROLLER_BUTTON_LEFTSHOULDER) {
          // L1 button jumps forward 100 images (mirrors keyboard L)
          if (list.count > 0) {
            // Hide PT panel when changing images
            show_pt = false;
            if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
            if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
            
            // Jump forward 100 images (with wrap-around)
            index = (index + 100) % list.count;
            if (current) { SDL_DestroyTexture(current); current = NULL; }
            current = load_texture_scaled(renderer, list.paths[index], win_w, win_h, &dst_rect);
            if (current && cover_mode) compute_cover_src_dst(current, win_w, win_h, &src_rect, &dst_rect);
            
            // Check if this image has a subtitle - if so, lock navigation
            long img_time = 0; bool ok = basename_numeric_value(list.paths[index], &img_time);
            const BaseEntry *zht_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
            if (zht_entry && zht_entry->zht_text) {
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              current_text_msg = strdup(zht_entry->zht_text);
              rebuild_subtitle(renderer, win_w, win_h, current_text_msg, &text_tex, &text_rect, &sub_layout, &show_text, &hover_index);
              refresh_word_layout_for_time(&base, (int)img_time, current_text_msg, &sub_layout, &word_layout, &pair_words_cache, &pair_items_cache, &pair_words_count);
              locked_on_subtitle = true; // Lock when we find an image with subtitle
              hover_index = -1; // Reset hover to start
            } else {
              if (text_tex) { SDL_DestroyTexture(text_tex); text_tex = NULL; }
              if (current_text_msg) { free(current_text_msg); current_text_msg = NULL; }
              show_text = false;
              locked_on_subtitle = false; // Don't lock on images without subtitle
            }
            if (show_pt) {
              if (pt_tex) { SDL_DestroyTexture(pt_tex); pt_tex = NULL; }
              if (current_pt_msg) { free(current_pt_msg); current_pt_msg = NULL; }
              const BaseEntry *pt_entry = ok ? find_entry_by_time(&base, (int)img_time) : NULL;
              const char *pt = pt_entry ? pt_entry->pt_text : NULL;
              if (!pt || !*pt) pt = "N/A";
              current_pt_msg = strdup(pt);
              if (recreate_pt_panel(renderer, win_w, win_h, current_pt_msg, &pt_tex, &pt_rect) == 0 && pt_tex) {
                pt_rect.x = (win_w - pt_rect.w) / 2;
                int base_y = show_text ? (text_rect.y - pt_rect.h - 16) : (win_h - pt_rect.h - 24);
                if (base_y < 8) base_y = 8;
                pt_rect.y = base_y;
              }
            }
            // Update small index label
            {
              char buf[32]; snprintf(buf, sizeof(buf), "%ld", (ok && img_time > 0) ? img_time : (index + 1));
              if (idx_tex) { SDL_DestroyTexture(idx_tex); idx_tex = NULL; }
              if (recreate_text_px(renderer, buf, 14, &idx_tex, &idx_rect) == 0 && idx_tex) { idx_rect.x = 8; idx_rect.y = 8; }
            }
          }
        }
      }
    }

    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    if (!menu_active && current) {
      if (cover_mode) SDL_RenderCopy(renderer, current, &src_rect, &dst_rect);
      else SDL_RenderCopy(renderer, current, NULL, &dst_rect);
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
      // Hover info label (draw only if there's an active hover)
      if (hover_index >= 0 && hover_info_tex) {
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 180);
        SDL_Rect bg2 = { hover_info_rect.x - 10, hover_info_rect.y - 6, hover_info_rect.w + 20, hover_info_rect.h + 12 };
        SDL_RenderFillRect(renderer, &bg2);
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
        SDL_RenderCopy(renderer, hover_info_tex, NULL, &hover_info_rect);
      }
      // Draw hover outline if any (word-based)
      if (hover_index >= 0 && word_layout.count > 0 && hover_index < word_layout.count) {
        int hx = text_rect.x + word_layout.spans[hover_index].x;
        int hw = word_layout.spans[hover_index].w;
        int hy = text_rect.y;
        int hh = text_rect.h;
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
        SDL_SetRenderDrawColor(renderer, 30, 200, 255, 220);
        // Draw thicker outline by drawing multiple rectangles
        for (int thickness = 0; thickness < 3; thickness++) {
          SDL_Rect outline = { hx - 2 - thickness, hy - 2 - thickness, hw + 4 + 2*thickness, hh + 4 + 2*thickness };
          SDL_RenderDrawRect(renderer, &outline);
        }
        SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
      }
    }
    // Draw PT panel if visible
    if (!menu_active && show_pt && pt_tex) {
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
      SDL_SetRenderDrawColor(renderer, 0, 0, 0, 160);
      SDL_Rect bg = { pt_rect.x - 12, pt_rect.y - 8, pt_rect.w + 24, pt_rect.h + 16 };
      SDL_RenderFillRect(renderer, &bg);
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
      SDL_RenderCopy(renderer, pt_tex, NULL, &pt_rect);
    }
    // Draw small index in the top-left when viewing images
    if (!menu_active && idx_tex) {
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
      SDL_SetRenderDrawColor(renderer, 0, 0, 0, 120);
      SDL_Rect bg = { idx_rect.x - 4, idx_rect.y - 2, idx_rect.w + 8, idx_rect.h + 4 };
      SDL_RenderFillRect(renderer, &bg);
      SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_NONE);
      SDL_RenderCopy(renderer, idx_tex, NULL, &idx_rect);
    }
    SDL_RenderPresent(renderer);
  }

  if (current) SDL_DestroyTexture(current);
  if (text_tex) SDL_DestroyTexture(text_tex);
  if (idx_tex) SDL_DestroyTexture(idx_tex);
  if (current_text_msg) free(current_text_msg);
  free_images(&list);
  free_menu(&menu);
  free_base_data(&base);
  SDL_DestroyRenderer(renderer);
  SDL_DestroyWindow(window);
  TTF_Quit();
  IMG_Quit();
  SDL_Quit();
  return 0;
}


