// Service worker: faz as chamadas ao servidor local.
//
// O content script não pode chamar http://localhost direto: em MV3 ele herda o
// CORS (e o Private Network Access) da página do YouTube. O service worker,
// com host_permissions, pode.

const SERVER = "http://localhost:7997";

async function call(path, init) {
  const resp = await fetch(SERVER + path, init);
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return resp.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  let job;
  if (msg?.type === "pairs") {
    job = call("/pairs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: msg.videoId, cues: msg.cues }),
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
      const resp = await fetch(SERVER + "/pairs/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: msg.videoId, cues: msg.cues, from: msg.from }),
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
