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
  } else {
    return false;
  }
  job.then(
    (data) => sendResponse({ ok: true, data }),
    (err) => sendResponse({ ok: false, error: String(err?.message || err) }),
  );
  return true; // resposta assíncrona
});
