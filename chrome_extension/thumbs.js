// Selo "S" nas miniaturas do YouTube: borda preta fixa, interior roxo de
// baixo para cima conforme o base do vídeo no servidor (cache/yt/<id>_base.txt).
//   sem base → oco · parcial → roxo até done/total · completa → roxo cheio
// Funções puras exportadas para os testes (node --test).
((root) => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const PURPLE = "#9370db";
  const STALE_MS = 60000; // sem base / parcial: pergunta de novo depois disso
  const RETRY_MS = 15000; // servidor fora: nova tentativa
  const SCAN_DEBOUNCE_MS = 300;
  const MAX_IDS = 200; // limite do POST /bases

  // Âncoras de miniatura: layout antigo (ytd-thumbnail), novo (lockup) e Shorts.
  const THUMB_SELECTOR = [
    "ytd-thumbnail a#thumbnail",
    "a.yt-lockup-view-model__content-image",
    "a.yt-lockup-view-model-wiz__content-image",
    "ytm-shorts-lockup-view-model a[href^='/shorts/']",
    "ytm-shorts-lockup-view-model-v2 a[href^='/shorts/']",
  ].join(",");

  const ID_RE = /^[A-Za-z0-9_-]{6,20}$/;

  function videoIdFromHref(href) {
    if (!href) return null;
    let url;
    try {
      url = new URL(href, "https://www.youtube.com");
    } catch {
      return null;
    }
    let id = null;
    if (url.pathname === "/watch") id = url.searchParams.get("v");
    else {
      const m = url.pathname.match(/^\/shorts\/([^/?#]+)/);
      if (m) id = m[1];
    }
    return id && ID_RE.test(id) ? id : null;
  }

  // Completa = ≥95% das frases: a LLM às vezes nunca resolve uma frase, e o
  // base fica 55/56 para sempre.
  function badgeState(st) {
    if (!st || !st.total || !st.done) return { kind: "none", pct: 0, title: "subrim: sem base" };
    const { done, total } = st;
    const full = done >= total * 0.95;
    return {
      kind: full ? "full" : "partial",
      pct: full ? 1 : done / total,
      title: `subrim: ${done} de ${total} frases traduzidas`,
    };
  }

  // ------------------------------------------------------------ DOM

  let gradSeq = 0;

  function makeBadge() {
    const gid = "subrim-g" + ++gradSeq;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 30 30");
    svg.setAttribute("class", "subrim-badge");
    svg.innerHTML =
      `<title></title>` +
      `<defs><linearGradient id="${gid}" x1="0" y1="1" x2="0" y2="0">` +
      `<stop offset="0" stop-color="${PURPLE}"/>` +
      `<stop offset="0" stop-color="${PURPLE}" stop-opacity="0"/>` +
      `</linearGradient></defs>` +
      `<text x="15" y="25" text-anchor="middle" fill="url(#${gid})">S</text>`;
    return svg;
  }

  // Só toca no DOM quando o estado muda: o <title> gera mutação, e o
  // MutationObserver voltaria a escanear sem parar.
  function paintBadge(svg, st) {
    const b = badgeState(st);
    const key = `${b.kind}:${b.pct}:${b.title}`;
    if (svg.dataset.subrimState === key) return;
    svg.dataset.subrimState = key;
    svg.setAttribute("class", `subrim-badge subrim-badge--${b.kind}`);
    for (const stop of svg.querySelectorAll("stop")) stop.setAttribute("offset", String(b.pct));
    svg.querySelector("title").textContent = b.title;
  }

  function createThumbBadges({ send }) {
    const known = new Map(); // id -> {st, at}
    let retryAt = 0;
    let inflight = false;
    let timer = null;
    const html = document.documentElement;

    function badgesFor(id) {
      return document.querySelectorAll(`svg.subrim-badge[data-subrim-id="${id}"]`);
    }

    function repaint(id) {
      const k = known.get(id);
      for (const svg of badgesFor(id)) paintBadge(svg, k.st);
    }

    async function fetchMissing(ids) {
      if (inflight || !ids.length || Date.now() < retryAt) return;
      inflight = true;
      const r = await send({ type: "bases", videoIds: ids.slice(0, MAX_IDS) });
      inflight = false;
      if (!r.ok) {
        retryAt = Date.now() + RETRY_MS;
        html.classList.add("subrim-thumbs-off");
        return;
      }
      html.classList.remove("subrim-thumbs-off");
      const bases = r.data?.bases || {};
      const now = Date.now();
      for (const id of ids.slice(0, MAX_IDS)) {
        known.set(id, { st: bases[id] || null, at: now });
        repaint(id);
      }
      if (ids.length > MAX_IDS) schedule(); // resto no próximo lote
    }

    function fresh(id) {
      const k = known.get(id);
      if (!k) return false;
      return badgeState(k.st).kind === "full" || Date.now() - k.at < STALE_MS;
    }

    function scan() {
      timer = null;
      const missing = new Set();
      for (const a of document.querySelectorAll(THUMB_SELECTOR)) {
        const id = videoIdFromHref(a.getAttribute("href"));
        let svg = a.querySelector(":scope > svg.subrim-badge");
        if (!id) {
          svg?.remove();
          continue;
        }
        if (!svg) {
          svg = makeBadge();
          if (getComputedStyle(a).position === "static") a.classList.add("subrim-thumb-host");
          a.appendChild(svg);
        }
        // O YouTube recicla os nós: a mesma âncora pode trocar de vídeo.
        if (svg.dataset.subrimId !== id) {
          svg.dataset.subrimId = id;
          delete svg.dataset.subrimState;
          svg.setAttribute("class", "subrim-badge");
        }
        const k = known.get(id);
        if (k) paintBadge(svg, k.st);
        if (!fresh(id)) missing.add(id);
      }
      fetchMissing([...missing]);
    }

    function schedule() {
      if (!timer) timer = setTimeout(scan, SCAN_DEBOUNCE_MS);
    }

    // Atributo href: âncoras recicladas trocam de vídeo sem mudar a árvore.
    function observe() {
      new MutationObserver(schedule).observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["href"],
      });
      schedule();
    }
    if (document.body) observe();
    else document.addEventListener("DOMContentLoaded", observe);

    return {
      scan: schedule,
      setEnabled(on) {
        html.classList.toggle("subrim-thumbs-hidden", !on);
      },
      // Progresso do vídeo aberto, sem ir ao servidor.
      setLocal(id, st) {
        known.set(id, { st, at: Date.now() });
        repaint(id);
      },
    };
  }

  const api = { videoIdFromHref, badgeState, createThumbBadges };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SubrimThumbs = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
