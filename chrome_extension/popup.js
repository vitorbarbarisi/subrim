// Popup: status do servidor local e opções (chrome.storage.sync). O content
// script ouve storage.onChanged, então cada mudança vale na hora.
(() => {
  "use strict";
  const { DEFAULT_OPTIONS } = globalThis.SubrimRender;
  const $ = (id) => document.getElementById(id);
  const toggles = ["enabled", "topTranslation", "multiline", "opaqueBox"];

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
})();
