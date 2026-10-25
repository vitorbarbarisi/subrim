// Content script (mundo isolado): navegação SPA, legendas capturadas por
// inject_main.js, chamada ao servidor local (via background.js) e sincronia
// do overlay com o vídeo.
(() => {
  "use strict";
  const {
    parsePinyinTranslations,
    displayPairs,
    displayItems,
    json3ToCues,
    mergeAsrCues,
    findActiveCue,
    Overlay,
    DEFAULT_OPTIONS,
  } = globalThis.SubrimRender;

  const FALLBACK_DELAY_MS = 2500; // espera o player baixar a legenda sozinho
  const RETRY_MS = 15000; // nova tentativa quando o servidor não responde
  const JOB_POLL_MS = 3000; // acompanhamento do job do Whisper
  const LANG_RANK = ["zh-Hant", "zh-TW", "zh-Hans", "zh"];

  const overlay = new Overlay();
  const thumbs = globalThis.SubrimThumbs.createThumbBadges({ send });
  const cache = new Map(); // videoId -> cues enriquecidas do servidor
  let mastered = new Set();

  // status: waiting | loading | ready | offline | no-tracks | transcribing | transcribe-error
  let state = null; // { videoId, rank, cues, status, ready(Map), total, display, job, timers[] }
  let options = { ...DEFAULT_OPTIONS };

  // Opções do popup (chrome.storage.sync), aplicadas na hora em todas as abas.
  chrome.storage.sync.get(DEFAULT_OPTIONS, (o) => {
    options = { ...DEFAULT_OPTIONS, ...o };
    overlay.setOptions(options);
    thumbs.setEnabled(options.enabled);
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "sync") return;
    for (const [k, { newValue }] of Object.entries(changes)) if (k in DEFAULT_OPTIONS) options[k] = newValue;
    overlay.setOptions(options);
    thumbs.setEnabled(options.enabled);
    // Trocou de LLM no meio da tradução: o resto do vídeo segue com a nova.
    // O que já está no cache do servidor não é refeito.
    if (changes.provider && state?.port && state.status === "loading") {
      state.port.disconnect();
      state.port = null;
      requestPairs(state);
    }
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
        if (state?.ready) buildDisplay(state);
      }
    });
  }

  // ------------------------------------------------------------ navegação

  function reset() {
    if (state) {
      state.timers.forEach(clearTimeout);
      state.port?.disconnect();
    }
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
    loadBase(s);
    s.timers.push(
      setTimeout(() => {
        if (state === s && !s.cues) {
          log("nenhuma legenda capturada; tentando playerResponse");
          window.postMessage({ source: "subrim-content", type: "request-tracks", videoId }, "*");
        }
      }, FALLBACK_DELAY_MS),
    );
  }

  // Base já gravado no servidor: a legenda aparece logo, sem esperar o player
  // baixar a do YouTube. Quando ela chega, requestPairs completa o que faltar.
  async function loadBase(s) {
    const r = await send({ type: "base", videoId: s.videoId });
    if (state !== s || s.ready || !r.ok || !Array.isArray(r.data?.cues) || !r.data.cues.length) return;
    s.ready = new Map(r.data.cues.map((c) => [cueKey(c), c]));
    s.total = r.data.total || s.ready.size;
    if (s.status === "waiting" || s.status === "no-tracks") s.status = "ready"; // não esconde o Whisper
    buildDisplay(s);
    log(`base do servidor: ${s.ready.size}/${s.total} frases`);
  }

  document.addEventListener("yt-navigate-start", () => {
    if (state && state.videoId !== currentVideoId()) reset();
  });
  document.addEventListener("yt-navigate-finish", () => {
    onNavigate();
    thumbs.scan();
  });
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
        onNoTracks(state);
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
    // Legenda automática vem em fragmentos curtos: junta em frases.
    if (msg.kind === "asr") cues = mergeAsrCues(cues);
    if (!cues.length) return;
    log(`legenda ${msg.lang}${msg.kind ? " (" + msg.kind + ")" : ""} via ${msg.origin}: ${cues.length} cues`);
    useCues(state, rank, cues);
  });

  function useCues(s, rank, cues) {
    s.rank = rank;
    s.cues = cues;
    s.port?.disconnect();
    requestPairs(s);
  }

  const cueKey = (c) => Number(c.start).toFixed(3);

  // Pares em streaming: cada lote que o servidor termina já aparece na tela.
  function requestPairs(s) {
    const cached = cache.get(s.videoId + "|" + s.rank);
    if (cached) {
      s.ready = new Map(cached.map((c) => [cueKey(c), c]));
      s.status = "ready";
      buildDisplay(s);
      thumbs.setLocal(s.videoId, { done: cached.length, total: cached.length });
      return;
    }
    const cues = s.cues;
    s.status = "loading";
    // Mantém o que veio do base (loadBase) nas frases desta faixa: a legenda
    // não pisca enquanto o stream repete o que já está no cache.
    const keys = new Set(cues.map(cueKey));
    s.ready = new Map([...(s.ready || [])].filter(([k]) => keys.has(k)));
    s.total = cues.length;
    buildDisplay(s);
    let port;
    try {
      port = chrome.runtime.connect({ name: "pairs-stream" });
    } catch (e) {
      return offline(s, cues, String(e)); // extensão recarregada
    }
    s.port = port;
    let finished = false;
    port.onMessage.addListener((m) => {
      if (state !== s || s.cues !== cues) return port.disconnect(); // navegou ou trocou de faixa
      if (m.total != null) s.total = m.total;
      if (Array.isArray(m.cues)) {
        for (const c of m.cues) s.ready.set(cueKey(c), c);
        buildDisplay(s);
        // O selo S do vídeo (nas sugestões, histórico…) enche junto.
        thumbs.setLocal(s.videoId, { done: s.ready.size, total: s.total });
      }
      if (m.done) {
        finished = true;
        s.status = "ready";
        cache.set(s.videoId + "|" + s.rank, [...s.ready.values()]);
        log("pares recebidos");
        port.disconnect();
      }
      if (m.error) {
        finished = true;
        port.disconnect();
        offline(s, cues, m.error);
      }
    });
    port.onDisconnect.addListener(() => {
      if (s.port === port) s.port = null;
      if (!finished && state === s && s.cues === cues) offline(s, cues, "conexão encerrada");
    });
    const video = document.querySelector("#movie_player video");
    port.postMessage({ videoId: s.videoId, cues, from: video ? video.currentTime : 0, provider: options.provider });
  }

  function offline(s, cues, error) {
    log("servidor indisponível:", error);
    s.status = "offline";
    // O servidor guarda cada lote no cache: a nova tentativa continua de onde parou.
    s.timers.push(setTimeout(() => state === s && s.cues === cues && requestPairs(s), RETRY_MS));
  }

  function buildDisplay(s) {
    s.gen = (s.gen || 0) + 1; // invalida o que o overlay está mostrando
    s.display = [...s.ready.values()]
      .map((c) => {
        const pairs = displayPairs(parsePinyinTranslations(c.pairs || []), mastered);
        return { start: c.start, end: c.end, items: displayItems(c.zh, pairs), pt: c.pt || "" };
      })
      .sort((a, b) => a.start - b.start);
  }

  // ------------------------------------------------------------ dominadas

  // Clique numa palavra: some a ajuda na hora (otimista) e grava na word-api.
  // O aviso oferece Desfazer, que volta ao nível anterior.
  overlay.onWordClick = async (word, pinyin, translation) => {
    if (mastered.has(word)) return;
    setMasteredLocal(word, true);
    const r = await send({ type: "set-level", word, pinyin, translation, level: 3 });
    if (!r.ok) {
      setMasteredLocal(word, false);
      overlay.toast(`Não deu para marcar ${word}: ${r.error}`);
      return;
    }
    const previous = r.data?.previous;
    overlay.toast(`${word} marcada como dominada`, "Desfazer", async () => {
      setMasteredLocal(word, false);
      // Palavra criada agora não tem nível anterior: volta para 1 (aprendendo).
      const u = await send({ type: "set-level", word, level: previous && previous !== 3 ? previous : 1 });
      if (!u.ok) {
        setMasteredLocal(word, true);
        overlay.toast(`Não deu para desfazer ${word}: ${u.error}`);
      }
    });
  };

  function setMasteredLocal(word, on) {
    if (on) mastered.add(word);
    else mastered.delete(word);
    if (state?.ready) buildDisplay(state);
  }

  // ------------------------------------------------------------ Whisper

  // Sem legenda chinesa: usa uma transcrição já feita, transcreve sozinho
  // (opção do popup) ou espera o botão do popup.
  async function onNoTracks(s) {
    // Com o base já na tela, o status segue "ready"; só o Whisper pode trazer
    // a lista completa de frases (job já feito), sem transcrever de novo.
    if (!s.ready) s.status = "no-tracks";
    const r = await send({ type: "job", videoId: s.videoId });
    if (state !== s || s.cues) return;
    if (r.ok && r.data?.state && r.data.state !== "error") return followJob(s, r.data);
    if (options.autoTranscribe && !s.ready) startTranscribe(s);
  }

  async function startTranscribe(s) {
    if (!s || s.cues || s.status === "transcribing") return;
    s.status = "transcribing";
    s.job = { state: "downloading", progress: 0 };
    const r = await send({ type: "transcribe", videoId: s.videoId });
    if (state !== s) return;
    if (!r.ok) {
      s.status = "transcribe-error";
      s.job = { state: "error", error: r.error };
      return;
    }
    followJob(s, r.data);
  }

  async function followJob(s, job) {
    while (state === s && !s.cues) {
      s.job = job;
      if (job.state === "done") {
        log(`transcrição do Whisper: ${job.cues?.length || 0} cues`);
        return useCues(s, LANG_RANK.length + 2, job.cues || []);
      }
      if (job.state === "error") {
        s.status = "transcribe-error";
        return;
      }
      s.status = "transcribing";
      await new Promise((res) => setTimeout(res, JOB_POLL_MS));
      const r = await send({ type: "job", videoId: s.videoId });
      if (!r.ok) {
        s.status = "transcribe-error";
        s.job = { state: "error", error: r.error };
        return;
      }
      job = r.data;
    }
  }

  // Popup: estado deste vídeo e o botão "Transcrever com Whisper".
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "popup-state") {
      const s = state;
      sendResponse(
        s && {
          videoId: s.videoId,
          status: s.status,
          ready: s.ready?.size || 0,
          total: s.total || 0,
          job: s.job || null,
        },
      );
    } else if (msg?.type === "popup-transcribe") {
      startTranscribe(state);
      sendResponse(true);
    }
  });

  // ------------------------------------------------------------ sincronia

  function statusText(s) {
    switch (s.status) {
      case "offline":
        return "subrim: servidor local (7997) não respondeu";
      case "no-tracks":
        return "subrim: sem legenda chinesa (ver popup)";
      case "transcribing":
        return s.job?.state === "downloading"
          ? "subrim: baixando o áudio…"
          : `subrim: transcrevendo… ${Math.round((s.job?.progress || 0) * 100)}%`;
      case "transcribe-error":
        return "subrim: a transcrição falhou (ver popup)";
      case "loading":
        return s.total ? `subrim: traduzindo… ${s.ready.size}/${s.total} frases` : "subrim: carregando…";
      default:
        return null;
    }
  }

  function tick() {
    requestAnimationFrame(tick);
    const s = state;
    if (!s || s.status === "waiting") return;
    const player = document.getElementById("movie_player");
    const video = player?.querySelector("video");
    if (!player || !video) return;
    if (!options.enabled) return overlay.detach(); // devolve a legenda nativa
    overlay.attach(player);
    if (player.classList.contains("ad-showing")) return overlay.hide();

    // Sem cues nem base (sem legenda / transcrevendo): o status fica na tela.
    if (!s.cues && !s.display) return overlay.status(statusText(s) || "");

    const t = video.currentTime;
    const i = s.display ? findActiveCue(s.display, t) : -1;
    if (i >= 0) {
      const c = s.display[i];
      return overlay.show(`${s.videoId}:${s.gen}:${i}`, c.items, c.pt);
    }
    // Fala sem pares ainda: diz por quê (traduzindo / servidor fora).
    const text = statusText(s);
    if (text && s.cues && findActiveCue(s.cues, t) >= 0) overlay.status(text);
    else overlay.hide();
  }
  requestAnimationFrame(tick);
})();
