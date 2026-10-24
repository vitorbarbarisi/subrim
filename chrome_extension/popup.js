// Popup: status do servidor local e opções (chrome.storage.sync). O content
// script ouve storage.onChanged, então cada mudança vale na hora.
(() => {
  "use strict";
  const { DEFAULT_OPTIONS } = globalThis.SubrimRender;
  const $ = (id) => document.getElementById(id);
  const toggles = ["enabled", "topTranslation", "multiline", "opaqueBox", "autoTranscribe"];

  chrome.storage.sync.get(DEFAULT_OPTIONS, (o) => {
    for (const k of toggles) $(k).checked = !!o[k];
    $("fontScale").value = Math.round(o.fontScale * 100);
    $("fontScaleOut").textContent = Math.round(o.fontScale * 100) + "%";
  });

  for (const k of toggles) {
    $(k).addEventListener("change", (e) => chrome.storage.sync.set({ [k]: e.target.checked }));
  }
  $("fontScale").addEventListener("input", (e) => {
    const pct = Number(e.target.value);
    $("fontScaleOut").textContent = pct + "%";
    chrome.storage.sync.set({ fontScale: pct / 100 });
  });

  chrome.runtime.sendMessage({ type: "health" }, (r) => {
    const ok = !chrome.runtime.lastError && r?.ok;
    $("server").textContent = ok ? "servidor ok" : "servidor offline";
    $("server").className = ok ? "ok" : "bad";
    $("hint").hidden = ok;
  });

  // ------------------------------------------------------------ este vídeo

  function describe(st) {
    if (!st) return ["Abra um vídeo do YouTube.", false];
    const pct = Math.round((st.job?.progress || 0) * 100);
    switch (st.status) {
      case "waiting":
        return ["Procurando a legenda chinesa…", false];
      case "loading":
        return [`Traduzindo: ${st.ready} de ${st.total} frases prontas.`, false];
      case "ready":
        return [`${st.total || st.ready} frases prontas.`, false];
      case "offline":
        return ["O servidor local não respondeu; nova tentativa em 15 s.", false];
      case "no-tracks":
        return ["Sem legenda chinesa no YouTube.", true];
      case "transcribing":
        return [st.job?.state === "downloading" ? "Baixando o áudio…" : `Transcrevendo com Whisper: ${pct}%.`, false];
      case "transcribe-error":
        return [`A transcrição falhou: ${st.job?.error || "erro desconhecido"}`, true];
      default:
        return [st.status, false];
    }
  }

  let tabId = null;
  function refresh() {
    if (tabId == null) return;
    chrome.tabs.sendMessage(tabId, { type: "popup-state" }, (st) => {
      if (chrome.runtime.lastError) st = null; // não é aba do YouTube
      const [text, canTranscribe] = describe(st);
      $("videoStatus").textContent = text;
      $("transcribe").hidden = !canTranscribe;
      $("transcribe").textContent = st?.status === "transcribe-error" ? "Tentar de novo" : "Transcrever com Whisper";
    });
  }
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    tabId = tab?.id ?? null;
    refresh();
    setInterval(refresh, 1000);
  });
  $("transcribe").addEventListener("click", () => {
    chrome.tabs.sendMessage(tabId, { type: "popup-transcribe" }, () => setTimeout(refresh, 300));
  });
})();
