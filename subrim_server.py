#!/usr/bin/env python3
"""Servidor local do subrim para a extensão Chrome (legenda ao vivo no YouTube).

A extensão captura a legenda chinesa do YouTube e pede aqui os pares
"palavra (pinyin): tradução" + a tradução PT de cada frase — os mesmos dados do
``*_base.txt`` gerado pelo processor.py, só que sob demanda. A chave da DeepSeek
fica no .env deste projeto, nunca no navegador.

Endpoints:
  GET  /health    → {"ok": true}
  GET  /mastered  → {"words": [...]}  (palavras dominadas via word-api)
  POST /mastered  {word, pinyin, translation, level=3}
                  → muda o confidence_level na word-api (PATCH; cria a
                    palavra se ela ainda não existe) → {word, level, previous}
                    ``previous`` é o nível anterior (None = criada agora),
                    para a extensão poder desfazer.
  POST /pairs     {video_id, cues:[{start,end,zh}]}
                  → {cues:[{start,end,zh,pairs:[...],pt}]}
  POST /pairs/stream  {video_id, cues, from}
                  → NDJSON, um {"cues":[...]} por lote pronto: primeiro o que
                    já está no cache, depois a partir de ``from`` (segundos —
                    o ponto atual do vídeo) e por fim o trecho anterior.
  POST /transcribe {video_id}  → inicia (ou devolve) o job do Whisper para
                  vídeos sem legenda chinesa: yt-dlp baixa o áudio, whisper
                  transcreve. → {state, progress, error}
  GET  /jobs/<video_id>  → {state, progress, error, cues?}
                  state: downloading | transcribing | done | error

Cache: ``cache/yt/<video_id>_base.txt`` no mesmo TSV do base
(índice, begin, end, zht, pares, pt) — reaproveitável no pipeline de queima.
A transcrição do Whisper fica em ``cache/yt/<video_id>_whisper.json``.

Áudio: yt-dlp com o ``cookies.txt`` do projeto (o do youtube_monitor) ou, sem
ele, os cookies do navegador ``SUBRIM_COOKIES_BROWSER`` (default chrome).
Whisper: ``SUBRIM_WHISPER_BIN`` (default: ``whisper`` no PATH ou
``whisper_env_py313/bin/whisper``) e ``SUBRIM_WHISPER_MODEL`` (default medium,
como o transcribe_video.py).

Uso:
  python subrim_server.py [--port 7997]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror, parse as urlparse, request as urlrequest

import processor
import word_vocab
import youtube_downloader

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


def _load_cache(video_id: str) -> dict[str, dict]:
    """{zht: cue} das linhas já processadas (com pares) do cache."""
    path = _cache_path(video_id)
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or parts[4].strip() in ("", "N/A"):
            continue
        try:
            pairs = json.loads(parts[4])
            start = float(parts[1].rstrip("s"))
            end = float(parts[2].rstrip("s"))
        except ValueError:
            continue
        pt = parts[5] if len(parts) >= 6 else "N/A"
        out[parts[3]] = {"start": start, "end": end, "zh": parts[3], "pairs": pairs, "pt": pt}
    return out


def _write_cache(video_id: str, cues: list[dict], cache: dict[str, dict]) -> None:
    """Grava as cues do pedido + as do cache que o pedido não trouxe.

    Um pedido com só parte das frases não apaga o resto do vídeo do cache.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    san = processor._sanitize_tsv_field
    sent = {c["zh"] for c in cues}
    rows = sorted(cues + [c for z, c in cache.items() if z not in sent], key=lambda c: c["start"])
    lines = []
    for i, c in enumerate(rows, start=1):
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


def _normalize_cues(raw_cues: list[dict]) -> list[dict]:
    cues = []
    for c in raw_cues:
        zh = processor._sanitize_tsv_field(str(c.get("zh") or ""))
        if not zh:
            continue
        zh = processor.convert_simplified_to_traditional(zh)
        cues.append({"start": float(c.get("start", 0)), "end": float(c.get("end", 0)),
                     "zh": zh, "pairs": [], "pt": ""})
    cues.sort(key=lambda c: c["start"])
    return cues


def iter_cues(video_id: str, cues: list[dict], from_t: float = 0.0):
    """Completa pares/pt das cues (cache → DeepSeek), lote a lote.

    Gera listas de cues prontas: primeiro as do cache, depois cada lote da
    DeepSeek — a partir de ``from_t`` e por fim o trecho anterior, para a
    legenda do ponto atual do vídeo chegar logo. O cache é gravado a cada lote.
    """
    with _video_lock(video_id):
        cache = _load_cache(video_id)
        ready = []
        for c in cues:
            if c["zh"] in cache:
                c["pairs"], c["pt"] = cache[c["zh"]]["pairs"], cache[c["zh"]]["pt"]
                ready.append(c)
        if ready:
            yield ready

        ahead = [c["zh"] for c in cues if c["zh"] not in cache and c["end"] >= from_t]
        behind = [c["zh"] for c in cues if c["zh"] not in cache and c["end"] < from_t]
        need = list(dict.fromkeys(ahead + behind))
        batch_size = max(1, processor._env_int("DEEPSEEK_PAIRS_BATCH", 20))
        for i in range(0, len(need), batch_size):
            batch = need[i:i + batch_size]
            # Pares e PT são chamadas independentes: rodam lado a lado.
            with ThreadPoolExecutor(max_workers=2) as ex:
                fp = ex.submit(_fetch_pairs, batch)
                ft = ex.submit(_fetch_pt, batch)
                pairs, pts = fp.result(), ft.result()
            done = []
            for c in cues:
                if c["zh"] in pairs and c["zh"] in batch:
                    c["pairs"], c["pt"] = pairs[c["zh"]], pts.get(c["zh"], "N/A")
                    done.append(c)
            for c in done:
                cache[c["zh"]] = dict(c)
            if done:
                _write_cache(video_id, cues, cache)
                yield done


def build_cues(video_id: str, raw_cues: list[dict]) -> list[dict]:
    """Versão sem streaming: devolve todas as cues já completadas."""
    cues = _normalize_cues(raw_cues)
    for _ in iter_cues(video_id, cues):
        pass
    return cues


# ── Whisper (vídeos sem legenda chinesa) ──────────────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_guard = threading.Lock()
_SEG_RE = re.compile(r"-->\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]")


def _whisper_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}_whisper.json"


def _whisper_bin() -> str:
    env = os.getenv("SUBRIM_WHISPER_BIN")
    if env:
        return env
    local = Path(__file__).resolve().parent / "whisper_env_py313" / "bin" / "whisper"
    return shutil.which("whisper") or str(local)


def _audio_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _yt_dlp_flags(work: Path) -> list[str]:
    """Flags do youtube_downloader, mas com o cookies.txt do projeto quando existe.

    É o mesmo arquivo do youtube_monitor; sem ele, lê os cookies do navegador
    em ``SUBRIM_COOKIES_BROWSER`` (default chrome).
    """
    flags = youtube_downloader._base_flags(os.getenv("SUBRIM_COOKIES_BROWSER", "chrome"), work, "audio")
    cookies = Path(__file__).resolve().parent / "cookies.txt"
    if cookies.exists():
        i = flags.index("--cookies-from-browser")
        flags[i:i + 2] = ["--cookies", str(cookies)]
    return flags


def _run_transcribe(video_id: str) -> None:
    job = _jobs[video_id]
    work = CACHE_DIR / f"{video_id}_audio"
    try:
        work.mkdir(parents=True, exist_ok=True)
        yt = youtube_downloader._check_yt_dlp()
        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = [yt] + _yt_dlp_flags(work) + ["--format", "bestaudio/best", url]
        r = subprocess.run(cmd, capture_output=True, text=True)
        audio = next((f for f in work.glob("audio.*") if f.suffix not in (".part", ".json")), None)
        if r.returncode != 0 or audio is None:
            raise RuntimeError("yt-dlp falhou: " + (r.stderr.strip().splitlines() or ["?"])[-1])

        job.update(state="transcribing", progress=0.0)
        duration = _audio_duration(audio)
        model = os.getenv("SUBRIM_WHISPER_MODEL", "medium")
        proc = subprocess.Popen(
            [_whisper_bin(), str(audio), "--model", model, "--language", "zh",
             "--output_format", "json", "--output_dir", str(work), "--verbose", "True"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        tail: list[str] = []
        for line in proc.stdout:
            tail = (tail + [line.strip()])[-5:]
            m = _SEG_RE.search(line)
            if m and duration > 0:
                secs = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                job["progress"] = round(min(1.0, secs / duration), 3)
        if proc.wait() != 0:
            raise RuntimeError("whisper falhou: " + " | ".join(tail))

        data = json.loads((work / f"{audio.stem}.json").read_text(encoding="utf-8"))
        cues = [{"start": round(seg["start"], 3), "end": round(seg["end"], 3), "zh": seg["text"].strip()}
                for seg in data.get("segments", []) if seg.get("text", "").strip()]
        _whisper_path(video_id).write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
        job.update(state="done", progress=1.0, cues=cues)
    except BaseException as e:  # noqa: BLE001 - inclui o SystemExit do _check_yt_dlp
        job.update(state="error", error=str(e) or type(e).__name__)
        print(f"⚠️  transcrição de {video_id} falhou: {job['error']}", file=sys.stderr)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def start_transcribe(video_id: str) -> dict:
    with _jobs_guard:
        job = _jobs.get(video_id)
        if job and job["state"] != "error":
            return job
        path = _whisper_path(video_id)
        if path.exists():
            job = {"state": "done", "progress": 1.0, "error": None,
                   "cues": json.loads(path.read_text(encoding="utf-8"))}
            _jobs[video_id] = job
            return job
        job = {"state": "downloading", "progress": 0.0, "error": None}
        _jobs[video_id] = job
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_run_transcribe, args=(video_id,), daemon=True).start()
    return job


# ── word-api (maestria) ───────────────────────────────────────────────────────

def _word_api(method: str, path: str, payload: dict | None = None):
    """Chamada JSON à word-api; devolve (status, corpo decodificado ou None)."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(word_vocab.base_url() + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urlrequest.urlopen(req, timeout=word_vocab._timeout()) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urlerror.HTTPError as e:
        return e.code, None


def set_word_level(word: str, level: int, pinyin: str = "", translation: str = "") -> dict:
    """Grava o confidence_level de uma palavra; cria a palavra se não existir.

    O nível anterior vem do /search (o GET /{word} incrementaria o contador
    ``calls`` da palavra, e isto não é uma consulta de verdade).
    """
    if not word_vocab.is_real_word(word) or level not in (1, 2, 3):
        raise ValueError("palavra ou nível inválido")
    status, found = _word_api("GET", "/search?q=" + urlparse.quote(word))
    previous = next((w.get("confidence_level") for w in found or [] if w.get("word") == word), None)

    status, _ = _word_api("PATCH", "/" + urlparse.quote(word), {"confidence_level": level})
    if status == 404:
        if not pinyin or not translation:
            raise ValueError(f"{word} não está na word-api e veio sem pinyin/tradução")
        status, _ = _word_api("POST", "/", {"word": word, "pinyin": pinyin,
                                            "translation": translation, "confidence_level": level})
    if status not in (200, 201):
        hint = " (o hanzi-api já tem o PATCH /word-api/{word}?)" if status == 405 else ""
        raise RuntimeError(f"word-api respondeu HTTP {status}{hint}")
    word_vocab.mastered_words(force=True)
    return {"word": word, "level": level, "previous": previous}


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

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "JSON inválido"})
            return None
        return body

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/jobs/"):
            video_id = self.path[len("/jobs/"):]
            job = _jobs.get(video_id)
            if job is None and VIDEO_ID_RE.match(video_id) and _whisper_path(video_id).exists():
                job = start_transcribe(video_id)  # já transcrito antes: carrega do cache
            if job is None:
                self._json(404, {"error": "sem job"})
            else:
                self._json(200, {k: v for k, v in job.items() if k != "cues" or job["state"] == "done"})
        elif self.path == "/health":
            self._json(200, {"ok": True})
        elif self.path == "/mastered":
            self._json(200, {"words": sorted(word_vocab.mastered_words(force=True))})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/pairs", "/pairs/stream", "/transcribe", "/mastered"):
            self._json(404, {"error": "not found"})
            return
        body = self._read_body()
        if body is None:
            return
        if self.path == "/mastered":
            try:
                result = set_word_level(str(body.get("word") or ""), int(body.get("level", 3)),
                                        str(body.get("pinyin") or ""), str(body.get("translation") or ""))
            except (TypeError, ValueError) as e:
                self._json(400, {"error": str(e)})
                return
            except Exception as e:  # noqa: BLE001 - word-api fora do ar etc.
                self._json(502, {"error": str(e)})
                return
            self._json(200, result)
            return
        video_id = str(body.get("video_id") or "")
        if not VIDEO_ID_RE.match(video_id):
            self._json(400, {"error": "video_id inválido"})
            return
        if self.path == "/transcribe":
            job = start_transcribe(video_id)
            self._json(200, {k: v for k, v in job.items() if k != "cues"})
            return
        raw_cues = body.get("cues")
        if not isinstance(raw_cues, list):
            self._json(400, {"error": "esperado {video_id, cues:[...]}"})
            return
        if self.path == "/pairs":
            try:
                cues = build_cues(video_id, raw_cues)
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
                return
            self._json(200, {"video_id": video_id, "cues": cues})
            return

        # /pairs/stream: sem Content-Length; a conexão fecha no fim (HTTP/1.0).
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()
        self.close_connection = True
        try:
            from_t = float(body.get("from") or 0)
        except (TypeError, ValueError):
            from_t = 0.0
        cues = _normalize_cues(raw_cues)
        try:
            self._ndjson({"total": len(cues)})
            for chunk in iter_cues(video_id, cues, from_t):
                self._ndjson({"cues": chunk})
            self._ndjson({"done": True})
        except (BrokenPipeError, ConnectionResetError):
            pass  # a aba fechou/navegou: o que já foi feito ficou no cache
        except Exception as e:  # noqa: BLE001
            self._ndjson({"error": str(e)})

    def _ndjson(self, obj) -> None:
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
        self.wfile.flush()

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
