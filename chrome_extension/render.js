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

  /**
   * Legenda automática (ASR) chega em fragmentos de 2–3 palavras, sem
   * pontuação. Junta fragmentos vizinhos (pausa < maxGap s) até maxChars
   * caracteres ou até uma pontuação final, para virar frase de legenda.
   */
  function mergeAsrCues(cues, maxGap = 0.8, maxChars = 18) {
    const out = [];
    for (const c of cues) {
      const last = out[out.length - 1];
      if (
        last &&
        c.start - last.end < maxGap &&
        Array.from(last.zh + c.zh).length <= maxChars &&
        !/[。！？!?]$/.test(last.zh)
      ) {
        last.zh += c.zh;
        last.end = c.end;
      } else {
        out.push({ ...c });
      }
    }
    return out;
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
  // Coluna mínima = 5% da largura do vídeo (como no queimado).
  const COL_MIN_RATIO = 0.05;
  // Se a legenda não cabe, a fonte encolhe em passos de 5% até 40%
  // (process_chunks.py: mesma regra do queimado em várias linhas).
  const FIT_STEP = 0.05;
  const FIT_MIN = 0.4;

  const DEFAULT_OPTIONS = {
    enabled: true,
    topTranslation: true,
    multiline: true,
    opaqueBox: true,
    fontScale: 1,
    autoTranscribe: false, // vídeo sem legenda zh → Whisper sem perguntar
    clickToMaster: true, // clicar numa palavra com ajuda marca como dominada
  };

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
      this.toastEl = el("div", "subrim-toast");
      this.toastEl.style.display = "none";
      this.root.append(this.top, this.box, this.toastEl);
      this.onWordClick = null; // (hanzi, pinyin, tradução) => void
      // Clique numa palavra com ajuda. Não deixa o clique chegar ao player
      // (que pausaria/daria play no vídeo).
      for (const type of ["click", "mousedown", "mouseup", "dblclick"]) {
        this.box.addEventListener(type, (e) => {
          const col = e.target.closest(".subrim-learn");
          if (!col || !this.opts.clickToMaster) return;
          e.stopPropagation();
          e.preventDefault();
          if (type === "click" && this.onWordClick) this.onWordClick(col.dataset.word, col.dataset.py, col.dataset.tr);
        });
      }
      this.toastEl.addEventListener("click", (e) => e.stopPropagation());
      this.resizeObs = new ResizeObserver(() => this._resize());
      this.shown = null;
      this.baseHz = 40;
      this.setOptions(DEFAULT_OPTIONS);
      this.hide();
    }

    setOptions(opts) {
      this.opts = { ...DEFAULT_OPTIONS, ...opts };
      this.root.classList.toggle("subrim-single", !this.opts.multiline);
      this.root.classList.toggle("subrim-translucent", !this.opts.opaqueBox);
      this.root.classList.toggle("subrim-clickable", !!this.opts.clickToMaster);
      this.shown = null; // força redesenhar com as opções novas
      this._resize();
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
      const w = this.player.clientWidth || 640;
      this.baseHz = Math.max(HZ_MIN, Math.min(HZ_MAX, Math.round(h * HZ_RATIO))) * this.opts.fontScale;
      this.root.style.setProperty("--subrim-colmin", Math.round(w * COL_MIN_RATIO) + "px");
      this._fit();
    }

    /** A legenda passa da largura (uma linha) ou sobe demais (várias linhas)? */
    _overflows() {
      const box = this.box;
      if (!this.opts.multiline) return box.scrollWidth > box.clientWidth + 1;
      const p = this.player.getBoundingClientRect();
      let limit = p.top + p.height * 0.02;
      if (this.top.style.display !== "none") limit = this.top.getBoundingClientRect().bottom + p.height * 0.02;
      return box.getBoundingClientRect().top < limit;
    }

    _fit() {
      const set = (k) => this.root.style.setProperty("--subrim-hz", (this.baseHz * k).toFixed(1) + "px");
      const cols = [...this.box.querySelectorAll(".subrim-word")];
      cols.forEach((c) => c.classList.remove("subrim-bare"));
      set(1);
      if (!this.player || this.box.style.display === "none") return;
      for (let k = 1 - FIT_STEP; k >= FIT_MIN - 1e-9 && this._overflows(); k -= FIT_STEP) set(k);
      this._collapseBareRows(cols);
    }

    /**
     * Linha só com dominadas não reserva as faixas vazias de pinyin/tradução
     * (no queimado cada linha tem a altura da própria ajuda). Antes do colapso
     * todas as colunas têm a mesma altura, então offsetTop identifica a linha.
     */
    _collapseBareRows(cols) {
      const rows = new Map();
      for (const c of cols) {
        if (!rows.has(c.offsetTop)) rows.set(c.offsetTop, []);
        rows.get(c.offsetTop).push(c);
      }
      for (const row of rows.values()) {
        if (row.every((c) => !c.firstChild.textContent && !c.lastChild.textContent)) {
          row.forEach((c) => c.classList.add("subrim-bare"));
        }
      }
    }

    hide() {
      this.shown = null;
      this.top.style.display = "none";
      this.box.style.display = "none";
    }

    status(text) {
      if (!text) return this.hide();
      if (this.shown === "status:" + text) return;
      this.shown = "status:" + text;
      this.top.style.display = "none";
      this.box.replaceChildren(el("span", "subrim-status", text));
      this.box.style.display = "";
      this._fit();
    }

    /** Aviso no canto do player, com um botão opcional (ex.: Desfazer). */
    toast(text, action, onAction, ms = 6000) {
      clearTimeout(this.toastTimer);
      const parts = [el("span", null, text)];
      if (action) {
        const btn = el("button", "subrim-toast-action", action);
        btn.addEventListener("click", () => {
          this.toastEl.style.display = "none";
          onAction();
        });
        parts.push(btn);
      }
      this.toastEl.replaceChildren(...parts);
      // Logo abaixo da tradução do topo, para não cobri-la.
      let top = "4%";
      if (this.player && this.top.style.display !== "none") {
        const gap = this.player.clientHeight * 0.015;
        top = Math.round(this.top.getBoundingClientRect().bottom - this.player.getBoundingClientRect().top + gap) + "px";
      }
      this.toastEl.style.top = top;
      this.toastEl.style.display = "";
      this.toastTimer = setTimeout(() => (this.toastEl.style.display = "none"), ms);
    }

    /** items = [[hanzi, pinyin, pt], ...]; pt = tradução da frase (opcional). */
    show(key, items, pt) {
      if (this.shown === key) return;
      this.shown = key;
      const cols = items.map(([z, py, tr]) => {
        const col = el("div", "subrim-word");
        col.append(el("span", "subrim-py", py), el("span", "subrim-hz", z), el("span", "subrim-tr", tr));
        if (py && tr) {
          col.classList.add("subrim-learn");
          Object.assign(col.dataset, { word: z, py, tr });
        }
        return col;
      });
      this.box.replaceChildren(...cols);
      this.box.style.display = cols.length ? "" : "none";
      if (this.opts.topTranslation && pt && pt !== "N/A") {
        this.top.textContent = pt;
        this.top.style.display = "";
      } else {
        this.top.style.display = "none";
      }
      this._fit();
    }
  }

  const api = {
    parsePinyinTranslations,
    displayPairs,
    displayItems,
    json3ToCues,
    mergeAsrCues,
    findActiveCue,
    Overlay,
    DEFAULT_OPTIONS,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SubrimRender = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
