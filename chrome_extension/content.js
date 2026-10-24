// Content script (mundo isolado): navegação SPA, legendas capturadas por
// inject_main.js, chamada ao servidor local (via background.js) e sincronia
// do overlay com o vídeo.
(() => {
  "use strict";
  const { parsePinyinTranslations, displayPairs, displayItems, json3ToCues, findActiveCue, Overlay, DEFAULT_OPTIONS } =
    globalThis.SubrimRender;

  const FALLBACK_DELAY_MS = 2500; // espera o player baixar a legenda sozinho
  const RETRY_MS = 15000; // nova tentativa quando o servidor não responde
  const LANG_RANK = ["zh-Hant", "zh-TW", "zh-Hans", "zh"];

  const overlay = new Overlay();
  const cache = new Map(); // videoId -> cues enriquecidas do servidor
  let mastered = new Set();

  let state = null; // { videoId, rank, cues, status, display, timers[] }
  let options = { ...DEFAULT_OPTIONS };

  // Opções do popup (chrome.storage.sync), aplicadas na hora em todas as abas.
  chrome.storage.sync.get(DEFAULT_OPTIONS, (o) => {
    options = { ...DEFAULT_OPTIONS, ...o };
    overlay.setOptions(options);
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "sync") return;
    for (const [k, { newValue }] of Object.entries(changes)) if (k in DEFAULT_OPTIONS) options[k] = newValue;
    overlay.setOptions(options);
  });

  function log(...args) {
    console.debug("[subrim]", ...args);
  }

  function send(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (resp) => {
          if (chrome.runtime.lastError) resolve({ ok: false, error: chrome.runtime.lastError.message });
          else resolve(resp || { ok: false, error: "sem resposta" });
        });
      } catch (e) {
        resolve({ ok: false, error: String(e) }); // extensão recarregada
      }
    });
  }

  function currentVideoId() {
    if (location.pathname !== "/watch") return null;
    return new URLSearchParams(location.search).get("v");
  }

  function langRank(lang, kind) {
    if (kind === "asr") return LANG_RANK.length + 1;
    const i = LANG_RANK.indexOf(lang);
    return i >= 0 ? i : LANG_RANK.length;
  }

  function refreshMastered() {
    send({ type: "mastered" }).then((r) => {
      if (r.ok && Array.isArray(r.data?.words)) {
        mastered = new Set(r.data.words);
        if (state?.status === "ready") buildDisplay(state);
      }
    });
  }

  // ------------------------------------------------------------ navegação

  function reset() {
    if (state) state.timers.forEach(clearTimeout);
    state = null;
    overlay.hide();
    overlay.detach();
  }

  function onNavigate() {
    const videoId = currentVideoId();
    if (state?.videoId === videoId) return;
    reset();
    if (!videoId) return;
    state = { videoId, rank: Infinity, cues: null, status: "waiting", display: null, timers: [] };
    log("vídeo", videoId);
    refreshMastered();
    const s = state;
    s.timers.push(
      setTimeout(() => {
        if (state === s && !s.cues) {
          log("nenhuma legenda capturada; tentando playerResponse");
          window.postMessage({ source: "subrim-content", type: "request-tracks", videoId }, "*");
        }
      }, FALLBACK_DELAY_MS),
    );
  }

  document.addEventListener("yt-navigate-start", () => {
    if (state && state.videoId !== currentVideoId()) reset();
  });
  document.addEventListener("yt-navigate-finish", onNavigate);
  window.addEventListener("popstate", () => setTimeout(onNavigate, 0));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onNavigate);
  else onNavigate();

  // ------------------------------------------------------------ legendas

  window.addEventListener("message", (ev) => {
    if (ev.source !== window || ev.data?.source !== "subrim-main") return;
    const msg = ev.data;
    if (!state) return;
    if (msg.videoId && msg.videoId !== state.videoId) return;

    if (msg.type === "no-tracks") {
      if (!state.cues) {
        log("sem legenda chinesa", msg.error || "");
        state.status = "no-tracks";
      }
      return;
    }
    if (msg.type !== "timedtext") return;

    const rank = langRank(msg.lang, msg.kind);
    if (rank >= state.rank) return; // já temos uma faixa igual ou melhor
    let cues;
    try {
      cues = json3ToCues(msg.body);
    } catch (e) {
      log("json3 inválido", e);
      return;
    }
    if (!cues.length) return;
    log(`legenda ${msg.lang}${msg.kind ? " (" + msg.kind + ")" : ""} via ${msg.origin}: ${cues.length} cues`);
    state.rank = rank;
    state.cues = cues;
    requestPairs(state);
  });

  async function requestPairs(s) {
    const cached = cache.get(s.videoId + "|" + s.rank);
    if (cached) {
      s.serverCues = cached;
      s.status = "ready";
      buildDisplay(s);
      return;
    }
    s.status = "loading";
    const cues = s.cues;
    const r = await send({ type: "pairs", videoId: s.videoId, cues });
    if (state !== s || s.cues !== cues) return; // navegou ou trocou de faixa
    if (r.ok && Array.isArray(r.data?.cues)) {
      cache.set(s.videoId + "|" + s.rank, r.data.cues);
      s.serverCues = r.data.cues;
      s.status = "ready";
      buildDisplay(s);
      log("pares recebidos");
    } else {
      log("servidor indisponível:", r.error);
      s.status = "offline";
      s.timers.push(setTimeout(() => state === s && s.cues === cues && requestPairs(s), RETRY_MS));
    }
  }

  function buildDisplay(s) {
    s.gen = (s.gen || 0) + 1; // invalida o que o overlay está mostrando
    s.display = s.serverCues
      .map((c) => {
        const pairs = displayPairs(parsePinyinTranslations(c.pairs || []), mastered);
        return { start: c.start, end: c.end, items: displayItems(c.zh, pairs), pt: c.pt || "" };
      })
      .sort((a, b) => a.start - b.start);
  }

  // ------------------------------------------------------------ sincronia

  function tick() {
    requestAnimationFrame(tick);
    const s = state;
    if (!s || !s.cues) return;
    const player = document.getElementById("movie_player");
    const video = player?.querySelector("video");
    if (!player || !video) return;
    if (!options.enabled) return overlay.detach(); // devolve a legenda nativa
    overlay.attach(player);
    if (player.classList.contains("ad-showing")) return overlay.hide();

    const t = video.currentTime;
    if (s.status === "ready") {
      const i = findActiveCue(s.display, t);
      if (i < 0) return overlay.hide();
      const c = s.display[i];
      overlay.show(`${s.videoId}:${s.gen}:${i}`, c.items, c.pt);
    } else if (findActiveCue(s.cues, t) >= 0) {
      overlay.status(s.status === "offline" ? "subrim: servidor local (7997) não respondeu" : "subrim: carregando…");
    } else {
      overlay.hide();
    }
  }
  requestAnimationFrame(tick);
})();
