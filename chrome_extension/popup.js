// Popup: status do servidor local e opções (chrome.storage.sync). O content
// script ouve storage.onChanged, então cada mudança vale na hora.
(() => {
  "use strict";
  const { DEFAULT_OPTIONS } = globalThis.SubrimRender;
  const $ = (id) => document.getElementById(id);
  const toggles = ["enabled", "topTranslation", "multiline", "opaqueBox", "clickToMaster", "autoTranscribe"];
  const radios = document.querySelectorAll('input[name="provider"]');
  let providers = null; // /health → {deepseek: {ok, detail}, local: {...}}

  chrome.storage.sync.get(DEFAULT_OPTIONS, (o) => {
    for (const k of toggles) $(k).checked = !!o[k];
    $("fontScale").value = Math.round(o.fontScale * 100);
    $("fontScaleOut").textContent = Math.round(o.fontScale * 100) + "%";
    setProvider(o.provider);
  });

  // ------------------------------------------------------------ LLM

  function setProvider(p) {
    for (const r of radios) r.checked = r.value === p;
    const st = providers?.[p];
    $("providerStatus").textContent = st ? st.detail : "";
    $("providerStatus").className = st ? (st.ok ? "ok" : "bad") : "";
  }
  for (const r of radios) {
    r.addEventListener("change", () => {
      chrome.storage.sync.set({ provider: r.value });
      setProvider(r.value);
    });
  }

  for (const k of toggles) {
    $(k).addEventListener("change", (e) => chrome.storage.sync.set({ [k]: e.target.checked }));
  }
  $("fontScale").addEventListener("input", (e) => {
    const pct = Number(e.target.value);
    $("fontScaleOut").textContent = pct + "%";
    chrome.storage.sync.set({ fontScale: pct / 100 });
  });

  // ------------------------------------------------------------ servidor

  // Mesmo formato do background.js: "IP" ou "IP:porta" (default 7997).
  function hostOrigin(host) {
    const m = String(host || "").trim().replace(/^https?:\/\//, "").replace(/\/+$/, "")
      .match(/^([\w.-]+)(?::(\d+))?$/);
    return m ? `http://${m[1]}:${m[2] || 7997}/*` : null;
  }

  function checkHealth() {
    $("server").textContent = "verificando…";
    $("server").className = "";
    $("hostDot").className = "";
    chrome.runtime.sendMessage({ type: "health" }, (r) => {
      const ok = !chrome.runtime.lastError && r?.ok;
      $("server").textContent = ok ? "servidor ok" : "servidor offline";
      $("server").className = ok ? "ok" : "bad";
      $("hostDot").className = ok ? "ok" : "bad";
      $("hostDot").title = ok ? "Conectado" : (r?.error || "Sem conexão");
      $("hint").hidden = ok;
      providers = ok ? r.data?.providers || null : null;
      setProvider([...radios].find((x) => x.checked)?.value || DEFAULT_OPTIONS.provider);
    });
  }

  // Enter grava o IP (o último digitado fica salvo) e pede a permissão de
  // acesso a ele — o pedido precisa partir de um gesto do usuário.
  $("serverHost").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const host = e.target.value.trim();
    const origin = hostOrigin(host);
    if (!origin) {
      $("hostDot").className = "bad";
      $("hostDot").title = "IP inválido";
      return;
    }
    chrome.permissions.request({ origins: [origin] }, (granted) => {
      if (!granted) {
        $("hostDot").className = "bad";
        $("hostDot").title = "Permissão negada para " + origin;
        return;
      }
      chrome.storage.local.set({ serverHost: host }, checkHealth);
    });
  });

  chrome.storage.local.get({ serverHost: "" }, ({ serverHost }) => {
    $("serverHost").value = serverHost;
    checkHealth();
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
