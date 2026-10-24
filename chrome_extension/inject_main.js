// Roda no mundo MAIN da página (document_start): captura as legendas chinesas
// que o próprio player baixa de /api/timedtext e repassa ao content script via
// window.postMessage. Também atende pedidos de fallback, lendo as faixas do
// playerResponse (só acessível deste mundo).
(() => {
  if (window.__subrimInjected) return;
  window.__subrimInjected = true;

  const SOURCE = "subrim-main";

  function trackInfo(url) {
    let u;
    try {
      u = new URL(url, location.href);
    } catch {
      return null;
    }
    if (!u.pathname.includes("/api/timedtext")) return null;
    // Com tlang, o conteúdo é a tradução automática para tlang.
    const lang = u.searchParams.get("tlang") || u.searchParams.get("lang") || "";
    if (!/^zh/i.test(lang)) return null;
    const fmt = u.searchParams.get("fmt");
    if (fmt && fmt !== "json3") return null;
    return { lang, videoId: u.searchParams.get("v") || "", kind: u.searchParams.get("kind") || "" };
  }

  function post(info, body, url, origin) {
    window.postMessage({ source: SOURCE, type: "timedtext", ...info, url, body, origin }, "*");
  }

  // --- fetch ---
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input?.url;
    const p = origFetch.apply(this, arguments);
    const info = url && trackInfo(url);
    if (info) {
      p.then((resp) => resp.clone().text())
        .then((body) => body && post(info, body, url, "fetch"))
        .catch(() => {});
    }
    return p;
  };

  // --- XMLHttpRequest ---
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__subrimUrl = String(url);
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    const info = this.__subrimUrl && trackInfo(this.__subrimUrl);
    if (info) {
      this.addEventListener("load", () => {
        try {
          const body =
            this.responseType === "" || this.responseType === "text"
              ? this.responseText
              : this.responseType === "json"
                ? JSON.stringify(this.response)
                : null;
          if (body) post(info, body, this.__subrimUrl, "xhr");
        } catch {}
      });
    }
    return origSend.apply(this, arguments);
  };

  // --- fallback: faixas do playerResponse ---
  const PREF = ["zh-Hant", "zh-TW", "zh-Hans", "zh"];

  function playerResponse(videoId) {
    const player = document.getElementById("movie_player");
    const candidates = [player?.getPlayerResponse?.(), window.ytInitialPlayerResponse];
    return candidates.find((r) => r?.videoDetails?.videoId === videoId) || null;
  }

  function pickTrack(tracks) {
    const manual = tracks.filter((t) => t.kind !== "asr");
    for (const code of PREF) {
      const t = manual.find((x) => x.languageCode === code);
      if (t) return t;
    }
    const anyZh = manual.find((x) => /^zh/i.test(x.languageCode || ""));
    if (anyZh) return anyZh;
    return tracks.find((x) => x.kind === "asr" && /^zh/i.test(x.languageCode || "")) || null;
  }

  async function fallback(videoId) {
    const resp = playerResponse(videoId);
    const tracks = resp?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    const track = pickTrack(tracks);
    if (!track?.baseUrl) {
      window.postMessage({ source: SOURCE, type: "no-tracks", videoId }, "*");
      return;
    }
    const url = track.baseUrl + "&fmt=json3";
    try {
      const body = await (await origFetch(url, { credentials: "include" })).text();
      if (!body) throw new Error("resposta vazia");
      post({ lang: track.languageCode, videoId, kind: track.kind || "" }, body, url, "fallback");
    } catch (e) {
      window.postMessage({ source: SOURCE, type: "no-tracks", videoId, error: String(e) }, "*");
    }
  }

  window.addEventListener("message", (ev) => {
    if (ev.source !== window || ev.data?.source !== "subrim-content") return;
    if (ev.data.type === "request-tracks") fallback(ev.data.videoId);
  });
})();
