// Parser dos pares, casamento por termo mais longo e overlay sobre o player.
//
// As funções puras (parsePinyinTranslations, displayItems, displayPairs,
// json3ToCues, findActiveCue) também são exportadas para os testes em node.
(function (root) {
  "use strict";

  const PAIR_RE = /^([^\s(]+)\s*\(([^)]+)\)\s*:\s*(.+)$/;

  /**
   * Port de process_chunks.parse_pinyin_translations. Aceita a lista já
   * decodificada (como vem do servidor) ou a string '["三 (sān): três", ...]'.
   * Devolve [[hanzi, pinyin, pt], ...]; item fora do formato vira [hanzi, "", ""].
   */
  function parsePinyinTranslations(input) {
    let items;
    if (Array.isArray(input)) {
      items = input.filter((x) => typeof x === "string");
    } else if (typeof input === "string") {
      const s = input.trim();
      if (!s.startsWith("[") || !s.endsWith("]")) return [];
      items = [...s.slice(1, -1).matchAll(/"([^"]*)"/g)].map((m) => m[1]);
    } else {
      return [];
    }
    const result = [];
    for (const item of items) {
      const m = PAIR_RE.exec(item);
      if (m) {
        result.push([m[1].trim(), m[2].trim(), m[3].trim()]);
      } else {
        const z = /^([^\s(]+)/.exec(item);
        if (z) result.push([z[1], "", ""]);
      }
    }
    return result;
  }

  /** Port de word_vocab.display_pairs: dominadas perdem pinyin/tradução. */
  function displayPairs(pairs, mastered) {
    if (!mastered || mastered.size === 0) return pairs.slice();
    return pairs.map(([w, py, tr]) => (mastered.has(w) ? [w, "", ""] : [w, py, tr]));
  }

  // Mesmos caracteres que _display_items remove antes de casar.
  const CLEAN_RE = /[ 　（）.《》"]/g;

  /**
   * Port de process_chunks._display_items: a cada posição casa o maior termo
   * do glossário; o que sobra vira caractere avulso sem ajuda.
   */
  function displayItems(chineseText, wordData) {
    const text = Array.from(String(chineseText || "").replace(CLEAN_RE, ""));
    const byLength = wordData
      .map((w) => [Array.from(w[0]), w])
      .filter(([chars]) => chars.length > 0)
      .sort((a, b) => b[0].length - a[0].length); // sort estável, como o sorted() do Python
    const out = [];
    let i = 0;
    while (i < text.length) {
      const hit = byLength.find(([chars]) => chars.every((c, k) => text[i + k] === c));
      if (hit) {
        out.push(hit[1]);
        i += hit[0].length;
      } else {
        out.push([text[i], "", ""]);
        i += 1;
      }
    }
    return out;
  }

  /** json3 do timedtext -> [{start, end, zh}] ordenadas, sem sobreposição. */
  function json3ToCues(json) {
    const data = typeof json === "string" ? JSON.parse(json) : json;
    const cues = [];
    for (const ev of data?.events || []) {
      if (!ev.segs || ev.tStartMs == null) continue;
      const zh = ev.segs
        .map((s) => s.utf8 || "")
        .join("")
        .replace(/\s*\n\s*/g, "")
        .trim();
      if (!zh) continue;
      const start = ev.tStartMs / 1000;
      const end = (ev.tStartMs + (ev.dDurationMs || 0)) / 1000;
      cues.push({ start, end, zh });
    }
    cues.sort((a, b) => a.start - b.start);
    // Faixas ASR se sobrepõem (janela rolante): corta cada cue no início da próxima.
    for (let k = 0; k < cues.length - 1; k++) {
      if (cues[k].end > cues[k + 1].start) cues[k].end = cues[k + 1].start;
    }
    return cues.filter((c) => c.end > c.start);
  }

  /** Busca binária: índice da cue ativa em t (segundos) ou -1. */
  function findActiveCue(cues, t) {
    let lo = 0;
    let hi = cues.length - 1;
    let idx = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (cues[mid].start <= t) {
        idx = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return idx >= 0 && t < cues[idx].end ? idx : -1;
  }

  // ---------------------------------------------------------------- overlay

  // Hanzi = 6% da altura do vídeo, entre 24 e 120px (como no queimado).
  const HZ_RATIO = 0.06;
  const HZ_MIN = 24;
  const HZ_MAX = 120;
  // Tradução da frase no topo. O queimado só a desenha com
  // BURN_TOP_TRANSLATION=1; aqui aparece sempre que o servidor manda `pt`.
  const SHOW_TOP_TRANSLATION = true;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  class Overlay {
    constructor() {
      this.player = null;
      this.root = el("div", "subrim-overlay");
      this.top = el("div", "subrim-top");
      this.box = el("div", "subrim-box");
      this.root.append(this.top, this.box);
      this.resizeObs = new ResizeObserver(() => this._resize());
      this.shown = null;
      this.hide();
    }

    attach(player) {
      if (this.player === player && player.contains(this.root)) return;
      this.detach();
      this.player = player;
      player.appendChild(this.root);
      player.classList.add("subrim-active");
      this.resizeObs.observe(player);
      this._resize();
    }

    detach() {
      if (!this.player) return;
      this.resizeObs.disconnect();
      this.player.classList.remove("subrim-active");
      this.root.remove();
      this.player = null;
      this.shown = null;
    }

    _resize() {
      if (!this.player) return;
      const h = this.player.clientHeight || 360;
      const hz = Math.max(HZ_MIN, Math.min(HZ_MAX, Math.round(h * HZ_RATIO)));
      this.root.style.setProperty("--subrim-hz", hz + "px");
    }

    hide() {
      this.shown = null;
      this.top.style.display = "none";
      this.box.style.display = "none";
    }

    status(text) {
      if (this.shown === "status:" + text) return;
      this.shown = "status:" + text;
      this.top.style.display = "none";
      this.box.replaceChildren(el("span", "subrim-status", text));
      this.box.style.display = "";
    }

    /** items = [[hanzi, pinyin, pt], ...]; pt = tradução da frase (opcional). */
    show(key, items, pt) {
      if (this.shown === key) return;
      this.shown = key;
      const cols = items.map(([z, py, tr]) => {
        const col = el("div", "subrim-word");
        col.append(el("span", "subrim-py", py), el("span", "subrim-hz", z), el("span", "subrim-tr", tr));
        return col;
      });
      this.box.replaceChildren(...cols);
      this.box.style.display = cols.length ? "" : "none";
      if (SHOW_TOP_TRANSLATION && pt) {
        this.top.textContent = pt;
        this.top.style.display = "";
      } else {
        this.top.style.display = "none";
      }
    }
  }

  const api = { parsePinyinTranslations, displayPairs, displayItems, json3ToCues, findActiveCue, Overlay };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SubrimRender = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
