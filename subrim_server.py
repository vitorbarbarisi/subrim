#!/usr/bin/env python3
"""Servidor local do subrim para a extensão Chrome (legenda ao vivo no YouTube).

A extensão captura a legenda chinesa do YouTube e pede aqui os pares
"palavra (pinyin): tradução" + a tradução PT de cada frase — os mesmos dados do
``*_base.txt`` gerado pelo processor.py, só que sob demanda. A chave da DeepSeek
fica no .env deste projeto, nunca no navegador.

Endpoints:
  GET  /health    → {"ok": true}
  GET  /mastered  → {"words": [...]}  (palavras dominadas via word-api)
  POST /pairs     {video_id, cues:[{start,end,zh}]}
                  → {cues:[{start,end,zh,pairs:[...],pt}]}

Cache: ``cache/yt/<video_id>_base.txt`` no mesmo TSV do base
(índice, begin, end, zht, pares, pt) — reaproveitável no pipeline de queima.

Uso:
  python subrim_server.py [--port 7997]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest

import processor
import word_vocab

DEFAULT_PORT = 7997
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "yt"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
ALLOWED_ORIGINS = ("https://www.youtube.com", "https://m.youtube.com")

# Um lock por vídeo: duas abas do mesmo vídeo não disparam a LLM em dobro.
_video_locks: dict[str, threading.Lock] = {}
_video_locks_guard = threading.Lock()


def _video_lock(video_id: str) -> threading.Lock:
    with _video_locks_guard:
        return _video_locks.setdefault(video_id, threading.Lock())


# ── Cache (TSV do base) ───────────────────────────────────────────────────────

def _cache_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}_base.txt"


def _load_cache(video_id: str) -> dict[str, tuple[list[str], str]]:
    """{zht: (pares, pt)} das linhas já processadas (com pares) do cache."""
    path = _cache_path(video_id)
    out: dict[str, tuple[list[str], str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or parts[4].strip() in ("", "N/A"):
            continue
        try:
            pairs = json.loads(parts[4])
        except ValueError:
            continue
        pt = parts[5] if len(parts) >= 6 else "N/A"
        out[parts[3]] = (pairs, pt)
    return out


def _write_cache(video_id: str, cues: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    san = processor._sanitize_tsv_field
    lines = []
    for i, c in enumerate(cues, start=1):
        pairs = json.dumps(c["pairs"], ensure_ascii=False) if c["pairs"] else "N/A"
        lines.append(
            f"{i}\t{c['start']:.3f}s\t{c['end']:.3f}s\t{san(c['zh'])}\t{san(pairs)}\t{san(c['pt'] or 'N/A')}"
        )
    _cache_path(video_id).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── LLM ───────────────────────────────────────────────────────────────────────

def _call_deepseek_translate_to_pt_batch(sentences: list[str]) -> dict[str, str]:
    """Tradução PT de várias frases numa chamada só ({frase: tradução}).

    Frases ausentes da resposta ficam fora do dict; o chamador cai para a
    tradução 1-a-1 de ``processor._call_deepseek_translate_to_pt``.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY não encontrada ou vazia no ambiente")
    api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    prompt = (
        "Traduza CADA fala de legenda em chinês abaixo para português brasileiro "
        "natural e coloquial (são diálogos de vídeo).\n"
        "RETORNE SOMENTE um objeto JSON onde a chave é o número da frase (string) e "
        "o valor é a tradução. Sem explicações, sem markdown.\n\n"
        f"Frases:\n{numbered}"
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": processor._deepseek_max_tokens(len(sentences), per_item=80),
    }
    req = urlrequest.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"), method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urlrequest.urlopen(req, timeout=processor._deepseek_timeout(len(sentences)),
                                context=processor._get_ssl_context()) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - o retry decide se tenta de novo
        raise RuntimeError(f"Falha no batch de tradução PT via DeepSeek: {exc}")

    content = (obj.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    content = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content)
    try:
        parsed = json.loads(content)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {s: parsed[str(i)].strip() for i, s in enumerate(sentences, start=1)
            if isinstance(parsed.get(str(i)), str) and parsed[str(i)].strip()}


def _fetch_pairs(batch: list[str]) -> dict[str, list[str]]:
    """Pares de um lote; cai para 1-a-1 nas frases que o lote não cobriu."""
    try:
        got = processor._retry_api_call(processor._call_deepseek_pairs_batch, batch)
    except Exception:
        got = {}
    out: dict[str, list[str]] = {}
    for s in batch:
        raw = got.get(s)
        if raw is None:
            try:
                raw = processor._retry_api_call(processor._call_deepseek_pairs, s)
            except Exception as e:  # noqa: BLE001 - uma frase ruim não derruba o vídeo
                print(f"⚠️  pares falharam para {s!r}: {e}", file=sys.stderr)
                continue
        try:
            pairs = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(pairs, list):
            out[s] = [p for p in pairs if isinstance(p, str)]
    return out


def _fetch_pt(batch: list[str]) -> dict[str, str]:
    try:
        got = processor._retry_api_call(_call_deepseek_translate_to_pt_batch, batch)
    except Exception:
        got = {}
    for s in batch:
        if s not in got:
            try:
                got[s] = processor._retry_api_call(processor._call_deepseek_translate_to_pt, s)
            except Exception as e:  # noqa: BLE001
                print(f"⚠️  tradução falhou para {s!r}: {e}", file=sys.stderr)
    return got


def build_cues(video_id: str, raw_cues: list[dict]) -> list[dict]:
    """Normaliza as cues, completa pares/pt (cache → DeepSeek) e grava o cache."""
    cues = []
    for c in raw_cues:
        zh = processor._sanitize_tsv_field(str(c.get("zh") or ""))
        if not zh:
            continue
        zh = processor.convert_simplified_to_traditional(zh)
        cues.append({"start": float(c.get("start", 0)), "end": float(c.get("end", 0)),
                     "zh": zh, "pairs": [], "pt": ""})
    cues.sort(key=lambda c: c["start"])

    with _video_lock(video_id):
        cache = _load_cache(video_id)
        need = list(dict.fromkeys(c["zh"] for c in cues if c["zh"] not in cache))
        if need:
            batch_size = max(1, processor._env_int("DEEPSEEK_PAIRS_BATCH", 20))
            batches = [need[i:i + batch_size] for i in range(0, len(need), batch_size)]
            pairs: dict[str, list[str]] = {}
            pts: dict[str, str] = {}
            # Pares e PT são chamadas independentes: rodam lado a lado.
            with ThreadPoolExecutor(max_workers=2) as ex:
                fp = ex.submit(lambda: [_fetch_pairs(b) for b in batches])
                ft = ex.submit(lambda: [_fetch_pt(b) for b in batches])
                for d in fp.result():
                    pairs.update(d)
                for d in ft.result():
                    pts.update(d)
            for s in need:
                if s in pairs:
                    cache[s] = (pairs[s], pts.get(s, "N/A"))

        for c in cues:
            if c["zh"] in cache:
                c["pairs"], c["pt"] = cache[c["zh"]]
        if need:
            _write_cache(video_id, cues)
    return cues


# ── HTTP ──────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "subrim/1"

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS or origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            # Chrome bloqueia sites públicos → localhost sem isto (Private Network Access).
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, status: int, payload) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
        elif self.path == "/mastered":
            self._json(200, {"words": sorted(word_vocab.mastered_words(force=True))})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/pairs":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "JSON inválido"})
            return
        video_id = str(body.get("video_id") or "")
        raw_cues = body.get("cues")
        if not VIDEO_ID_RE.match(video_id) or not isinstance(raw_cues, list):
            self._json(400, {"error": "esperado {video_id, cues:[...]}"})
            return
        try:
            cues = build_cues(video_id, raw_cues)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        self._json(200, {"video_id": video_id, "cues": cues})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[subrim_server] {fmt % args}\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(os.getenv("SUBRIM_SERVER_PORT", DEFAULT_PORT)))
    args = ap.parse_args(argv)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"🎧 subrim_server em http://127.0.0.1:{args.port}  (cache: {CACHE_DIR})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
