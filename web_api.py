"""Página web "subrim" (celular/tablet) servida pelo subrim_server.

  GET  /  e  /subrim             → web/subrim.html (Palavras · Jogos · Manager)
  GET  /web/manifest.json        → manifest do "Adicionar à tela inicial"
  GET  /web/icon.png             → subrim_icon.png
  GET  /web/games                → {"games": [{name, created, size, done, total, pct}]}
                                   bundles do ditado (dictation/*_ditado_*.html),
                                   mais novo primeiro.
  GET  /web/game/<nome>          → o bundle, com um shim que sincroniza o
                                   progresso com o servidor
  POST /web/game/<nome>/progress {done: {source: 1, ...}} → {done, total}

O Manager da página usa os endpoints ``/mgr/*`` do manager_api, como o client
desktop.

Progresso dos jogos: o bundle guarda o que foi feito no ``localStorage`` do
navegador (``subrim.dictation.<impressão digital>`` → ``{source: 1}``). Servido
por aqui, ele ganha um shim que (1) une ao ``getItem`` o que o servidor já sabe
e (2) manda cada ``setItem`` para o servidor, que marca ``done: true`` no
``index.json`` da coleção de origem. Assim vale para os bundles já gerados, sem
regerar nada, e o arquivo continua funcionando offline. O progresso só soma:
nada é desmarcado. Bundle cuja coleção não está no servidor (renomeado ou
apagado) guarda o progresso em ``dictation/.progress/<bundle>.json``.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).absolute().parent
WEB = REPO / "web"
DICTATION = REPO / "dictation"
PROGRESS_DIR = DICTATION / ".progress"
COLLECTION_DIRS = (REPO / "warehouse" / "collections",
                   REPO / "warehouse" / "text" / "collections")
BUNDLE_RE = re.compile(r"^(?P<col>.+)_ditado_\d+\.html$")
PAYLOAD_START = "window.__DICTATION__="

_write_lock = threading.Lock()
# {nome: ((mtime, size), [sources])} — reler 8 MB a cada listagem seria caro.
_sources_cache: dict[str, tuple] = {}
_cache_lock = threading.Lock()


# ── Bundles ───────────────────────────────────────────────────────────────────

def _bundles() -> dict[str, Path]:
    if not DICTATION.is_dir():
        return {}
    return {p.name: p for p in DICTATION.iterdir()
            if p.is_file() and BUNDLE_RE.match(p.name)}


def _bundle(name: str) -> Path:
    """Só nomes que existem de fato em dictation/ (nada de ../)."""
    p = _bundles().get(name)
    if p is None:
        raise LookupError(f"jogo não encontrado: {name}")
    return p


def _bundle_sources(p: Path) -> list[str]:
    st = p.stat()
    key = (st.st_mtime, st.st_size)
    with _cache_lock:
        hit = _sources_cache.get(p.name)
        if hit and hit[0] == key:
            return hit[1]
    text = p.read_text(encoding="utf-8")
    sources: list[str] = []
    i = text.find(PAYLOAD_START)
    if i >= 0:
        j = text.find(";</script>", i)
        try:
            items = json.loads(text[i + len(PAYLOAD_START):j])
            sources = [str(it.get("source") or "") for it in items if it.get("source")]
        except ValueError:
            sources = []
    with _cache_lock:
        _sources_cache[p.name] = (key, sources)
    return sources


def _collection_index(name: str) -> Path | None:
    """index.json da coleção que gerou o bundle.

    O nome do bundle é ``<pasta da coleção>_ditado_NN.html``; bundles renomeados
    à mão ganham um prefixo (``10A-…``), então vale também a coleção cujo nome é
    sufixo do nome — a mais longa, para não confundir coleções parecidas.
    """
    m = BUNDLE_RE.match(name)
    if not m:
        return None
    col = m.group("col")
    best = None
    for root in COLLECTION_DIRS:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not (d / "index.json").is_file():
                continue
            if d.name == col:
                return d / "index.json"
            if col.endswith(d.name) and (best is None or len(d.name) > len(best.parent.name)):
                best = d / "index.json"
    return best


def _sidecar(name: str) -> Path:
    return PROGRESS_DIR / f"{name}.json"


def _done_set(name: str) -> set[str]:
    """Fontes já feitas, segundo o servidor (index.json ou sidecar)."""
    idx = _collection_index(name)
    try:
        if idx is not None:
            return {str(e.get("source")) for e in json.loads(idx.read_text(encoding="utf-8"))
                    if isinstance(e, dict) and e.get("done")}
        side = _sidecar(name)
        if side.is_file():
            return set(json.loads(side.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return set()


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def save_progress(name: str, done: dict) -> dict:
    p = _bundle(name)
    sources = set(_bundle_sources(p))
    novos = {str(s) for s, v in (done or {}).items() if v} & sources
    with _write_lock:
        idx = _collection_index(name)
        if idx is not None:
            entries = json.loads(idx.read_text(encoding="utf-8"))
            changed = False
            for e in entries:
                if isinstance(e, dict) and e.get("source") in novos and not e.get("done"):
                    e["done"] = True
                    changed = True
            if changed:
                _write_json(idx, entries)
        else:
            atual = _done_set(name)
            if not novos <= atual:
                PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
                _write_json(_sidecar(name), sorted(atual | novos))
    feitos = _done_set(name) & sources
    return {"done": len(feitos), "total": len(sources)}


def list_games() -> list[dict]:
    out = []
    for name, p in _bundles().items():
        st = p.stat()
        sources = _bundle_sources(p)
        done = len(_done_set(name) & set(sources))
        total = len(sources)
        out.append({"name": name, "created": st.st_mtime, "size": st.st_size,
                    "done": done, "total": total,
                    "pct": round(100 * done / total) if total else 0})
    out.sort(key=lambda g: (g["created"], g["name"]), reverse=True)
    return out


SHIM = """<script>
(function () {
  var NAME = %(name)s;
  var SERVER = %(done)s;
  var PREFIX = "subrim.dictation.";
  var S = Storage.prototype, get = S.getItem, set = S.setItem;
  function parse(raw) { try { return JSON.parse(raw) || {}; } catch (e) { return {}; } }
  S.getItem = function (k) {
    var v = get.call(this, k);
    if (this !== window.localStorage || String(k).indexOf(PREFIX) !== 0) return v;
    var d = parse(v);
    for (var s in SERVER) d[s] = 1;
    return JSON.stringify(d);
  };
  S.setItem = function (k, v) {
    set.call(this, k, v);
    if (this !== window.localStorage || String(k).indexOf(PREFIX) !== 0) return;
    var d = parse(v);
    for (var s in d) SERVER[s] = 1;
    fetch("/web/game/" + encodeURIComponent(NAME) + "/progress", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({done: SERVER}), keepalive: true
    }).catch(function () {});
  };
})();
</script>"""


def game_html(name: str) -> bytes:
    p = _bundle(name)
    done = {s: 1 for s in _done_set(name)}
    shim = SHIM % {"name": json.dumps(name, ensure_ascii=False),
                   "done": json.dumps(done, ensure_ascii=False).replace("<", "\\u003c")}
    html = p.read_text(encoding="utf-8")
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    at = m.end() if m else 0
    return (html[:at] + shim + html[at:]).encode("utf-8")


# ── HTTP ──────────────────────────────────────────────────────────────────────

MANIFEST = {
    "name": "subrim", "short_name": "subrim", "start_url": "/subrim",
    "display": "standalone", "background_color": "#1c1c1e", "theme_color": "#1c1c1e",
    "icons": [{"src": "/web/icon.png", "sizes": "512x512", "type": "image/png"}],
}


def _send(h, status: int, data: bytes, ctype: str, cache: str = "no-cache") -> None:
    h.send_response(status)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data)))
    h.send_header("Cache-Control", cache)
    h.end_headers()
    h.wfile.write(data)


def handle_get(h) -> bool:
    path = h.path.partition("?")[0]
    if path in ("/", "/subrim", "/subrim/"):
        _send(h, 200, (WEB / "subrim.html").read_bytes(), "text/html; charset=utf-8")
        return True
    if not path.startswith("/web/"):
        return False
    try:
        if path == "/web/games":
            h._json(200, {"games": list_games()})
        elif path == "/web/manifest.json":
            _send(h, 200, json.dumps(MANIFEST).encode(), "application/manifest+json")
        elif path == "/web/icon.png":
            _send(h, 200, (REPO / "subrim_icon.png").read_bytes(), "image/png", "max-age=86400")
        elif path.startswith("/web/game/"):
            _send(h, 200, game_html(unquote(path[len("/web/game/"):])),
                  "text/html; charset=utf-8", "no-store")
        else:
            h._json(404, {"error": "not found"})
    except LookupError as e:
        h._json(404, {"error": str(e)})
    except Exception as e:  # noqa: BLE001
        h._json(500, {"error": f"{type(e).__name__}: {e}"})
    return True


def handle_post(h, body: dict) -> bool:
    path = h.path.partition("?")[0]
    if not path.startswith("/web/"):
        return False
    m = re.match(r"^/web/game/(.+)/progress$", path)
    try:
        if m:
            done = body.get("done")
            if not isinstance(done, dict):
                h._json(400, {"error": "esperado {done: {source: 1}}"})
            else:
                h._json(200, save_progress(unquote(m.group(1)), done))
        else:
            h._json(404, {"error": "not found"})
    except LookupError as e:
        h._json(404, {"error": str(e)})
    except Exception as e:  # noqa: BLE001
        h._json(500, {"error": f"{type(e).__name__}: {e}"})
    return True
