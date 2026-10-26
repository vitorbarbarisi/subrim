// Service worker: faz as chamadas ao servidor do subrim.
//
// O servidor roda em outra máquina da rede local; o IP vem do popup
// (chrome.storage.local "serverHost", ex.: "192.168.0.42" ou "192.168.0.42:7997").
// O content script não pode chamá-lo direto: em MV3 ele herda o CORS (e o
// Private Network Access) da página do YouTube. O service worker, com a
// permissão de host concedida no popup, pode.

const DEFAULT_PORT = 7997;

/** "192.168.0.42[:porta]" → "http://192.168.0.42:porta", ou null se inválido. */
function serverUrl(host) {
  const m = String(host || "").trim().replace(/^https?:\/\//, "").replace(/\/+$/, "")
    .match(/^([\w.-]+)(?::(\d+))?$/);
  return m ? `http://${m[1]}:${m[2] || DEFAULT_PORT}` : null;
}

async function server() {
  const { serverHost } = await chrome.storage.local.get({ serverHost: "" });
  const url = serverUrl(serverHost);
  if (!url) throw new Error("servidor não configurado: informe o IP no popup da extensão");
  return url;
}

async function call(path, init) {
  const resp = await fetch((await server()) + path, init);
  if (!resp.ok) {
    const detail = await resp.json().then((b) => b?.error, () => null);
    throw new Error(detail || `${path}: HTTP ${resp.status}`);
  }
  return resp.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  let job;
  if (msg?.type === "pairs") {
    job = call("/pairs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: msg.videoId, cues: msg.cues, provider: msg.provider }),
    });
  } else if (msg?.type === "mastered") {
    job = call("/mastered");
  } else if (msg?.type === "health") {
    job = call("/health");
  } else if (msg?.type === "transcribe") {
    job = call("/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: msg.videoId }),
    });
  } else if (msg?.type === "set-level") {
    job = call("/mastered", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: msg.word, pinyin: msg.pinyin, translation: msg.translation, level: msg.level }),
    });
  } else if (msg?.type === "bases") {
    job = call("/bases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_ids: msg.videoIds }),
    });
  } else if (msg?.type === "base") {
    job = call("/base/" + encodeURIComponent(msg.videoId));
  } else if (msg?.type === "job") {
    job = call("/jobs/" + encodeURIComponent(msg.videoId));
  } else {
    return false;
  }
  job.then(
    (data) => sendResponse({ ok: true, data }),
    (err) => sendResponse({ ok: false, error: String(err?.message || err) }),
  );
  return true; // resposta assíncrona
});

// /pairs/stream: o content script abre uma porta, manda {videoId, cues, from}
// e recebe cada linha NDJSON ({total} | {cues} | {done} | {error}) assim que o
// servidor termina um lote. A porta aberta mantém o service worker vivo.
chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "pairs-stream") return;
  const abort = new AbortController();
  port.onDisconnect.addListener(() => abort.abort());
  port.onMessage.addListener(async (msg) => {
    try {
      const resp = await fetch((await server()) + "/pairs/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: msg.videoId, cues: msg.cues, from: msg.from, provider: msg.provider }),
        signal: abort.signal,
      });
      if (!resp.ok) throw new Error(`/pairs/stream: HTTP ${resp.status}`);
      const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value;
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (line) port.postMessage(JSON.parse(line));
        }
      }
    } catch (e) {
      if (!abort.signal.aborted) port.postMessage({ error: String(e?.message || e) });
    }
    if (!abort.signal.aborted) port.disconnect();
  });
});
