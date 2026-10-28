"""Endpoints ``/mgr/*`` do subrim_server: o backend do Subrim Manager (client).

  GET  /mgr/ping              → {ok, host, repo}
  GET  /mgr/file?p=<caminho>  → bytes do arquivo (com Range, para vídeo)
  POST /mgr/call   {fn, args, kwargs}  → NDJSON: {"cb"}… {"ka"}… {"ok"|"err"}
  POST /mgr/fs     {op, path, args}    → {"ok": resultado}
  POST /mgr/proc   {argv, env, label}  → {"id"}
  POST /mgr/proc/<id>/stream {from}    → NDJSON: {"line"}… {"exit"}
  POST /mgr/proc/<id>/stop | /forget
  POST /mgr/procs                      → {"procs": [...]}

Caminhos viajam relativos à raiz do repo (ver subrim_remote). Só valem
caminhos dentro do repo ou dos pontos de montagem de HD externo (``/Volumes``
no macOS; ``/mnt``, ``/media/<usuário>`` no Linux/WSL — os de expurgo), e só
módulos/scripts do próprio repo podem ser chamados.
"""

from __future__ import annotations

import importlib
import json
import mimetypes
import os
import posixpath
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import subrim_remote as sr

REPO = Path(__file__).absolute().parent
# Com o repo atrás de um symlink, há módulos que resolvem o caminho e outros não.
ROOTS = tuple(dict.fromkeys((REPO, REPO.resolve())))
# Pontos de montagem de HD externo (expurgo/restauro): /Volumes ou /mnt, /media…
def _mounts():
    import manager_core
    return tuple(manager_core.mount_roots())

# Módulos cujas funções públicas o client pode chamar.
CALLABLE_MODULES = {"manager_core", "collection_builder", "periods_base",
                    "get_drive_token"}


# ── Caminhos ──────────────────────────────────────────────────────────────────

def to_path(s: str) -> Path:
    """String do client → Path deste lado, recusando o que sai do repo/HDs."""
    norm = posixpath.normpath(s)
    p = Path(norm) if posixpath.isabs(norm) else REPO / norm
    p = Path(os.path.normpath(p))
    for root in (*ROOTS, *_mounts()):
        if p == root or root in p.parents:
            return p
    raise PermissionError(f"caminho fora do repositório: {s}")


def from_path(obj):
    if isinstance(obj, Path):
        p = Path(os.path.normpath(obj if obj.is_absolute() else Path.cwd() / obj))
        for root in ROOTS:
            try:
                return p.relative_to(root).as_posix() or "."
            except ValueError:
                continue
        return str(p)
    return None


def enc(obj):
    return sr.encode(obj, from_path)


def dec(obj):
    return sr.decode(obj, to_path)


# ── /mgr/call ─────────────────────────────────────────────────────────────────

def resolve_fn(name: str):
    mod, _, attr = str(name).partition(".")
    if mod not in CALLABLE_MODULES or not attr or attr.startswith("_") or "." in attr:
        raise PermissionError(f"função não permitida: {name}")
    fn = getattr(importlib.import_module(mod), attr, None)
    if not callable(fn):
        raise AttributeError(f"{name} não existe")
    return fn


def call_events(body: dict):
    fn = resolve_fn(body.get("fn"))
    stream = sr.CallbackStream(enc)

    def arg(v):
        if isinstance(v, dict) and set(v) == {"__cb__"}:
            return stream.make_callback(int(v["__cb__"]))
        return dec(v)

    args = [arg(a) for a in body.get("args") or []]
    kwargs = {str(k): arg(v) for k, v in (body.get("kwargs") or {}).items()}
    return stream.run(fn, args, kwargs)


# ── /mgr/fs ───────────────────────────────────────────────────────────────────

def _stat(p: Path) -> dict:
    st = p.stat()
    return {"st_size": st.st_size, "st_mtime": st.st_mtime}


def _unlink(p: Path, missing_ok=False):
    p.unlink(missing_ok=bool(missing_ok))


def _mkdir(p: Path, parents=False, exist_ok=False):
    p.mkdir(parents=bool(parents), exist_ok=bool(exist_ok))


FS_OPS = {
    "exists":     lambda p: p.exists(),
    "is_dir":     lambda p: p.is_dir(),
    "is_file":    lambda p: p.is_file(),
    "glob":       lambda p, pat: sorted(p.glob(pat)),
    "rglob":      lambda p, pat: sorted(p.rglob(pat)),
    "iterdir":    lambda p: sorted(p.iterdir()),
    "read_text":  lambda p: p.read_text(encoding="utf-8"),
    "write_text": lambda p, text: [p.write_text(text, encoding="utf-8")] and None,
    "stat":       _stat,
    "unlink":     _unlink,
    "mkdir":      _mkdir,
}


def fs(body: dict):
    op = FS_OPS.get(body.get("op"))
    if op is None:
        raise PermissionError(f"operação inválida: {body.get('op')}")
    return enc(op(to_path(str(body.get("path") or ".")), *dec(body.get("args") or [])))


# ── Processos ─────────────────────────────────────────────────────────────────

MAX_LINES = 50_000      # log guardado por processo (o começo é descartado)
MAX_FINISHED = 40       # processos encerrados lembrados para o client reler


class Proc:
    _next = 0
    _lock = threading.Lock()

    def __init__(self, argv: list, env: dict, label: str):
        with Proc._lock:
            Proc._next += 1
            self.id = Proc._next
        self.label = label
        self.argv = argv
        self.started = time.time()
        self.lines: list = []
        self.dropped = 0          # linhas descartadas do começo (MAX_LINES)
        self.returncode = None
        self.cond = threading.Condition()
        self.popen = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, cwd=str(REPO), env=env)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.popen.stdout:
            line = raw.rstrip("\n")
            with self.cond:
                self.lines.append(line)
                if len(self.lines) > MAX_LINES:
                    cut = len(self.lines) - MAX_LINES
                    del self.lines[:cut]
                    self.dropped += cut
                self.cond.notify_all()
        self.popen.wait()
        with self.cond:
            self.returncode = self.popen.returncode
            self.cond.notify_all()

    def running(self) -> bool:
        return self.returncode is None

    def info(self) -> dict:
        return {"id": self.id, "label": self.label, "running": self.running(),
                "returncode": self.returncode, "started": self.started,
                "lines": self.dropped + len(self.lines)}

    def events(self, offset: int):
        """Linhas a partir de ``offset`` (absoluto) até o processo acabar."""
        pos = max(int(offset), 0)
        while True:
            with self.cond:
                while (pos >= self.dropped + len(self.lines) and self.returncode is None):
                    if not self.cond.wait(timeout=sr.CallbackStream.KEEPALIVE):
                        break
                start = max(pos, self.dropped)
                novas = self.lines[start - self.dropped:]
                rc = self.returncode
            if start > pos:
                yield {"line": f"… ({start - pos} linha(s) antigas descartadas)"}
            for line in novas:
                yield {"line": line}
            pos = start + len(novas)
            if rc is not None and pos >= self.dropped + len(self.lines):
                yield {"exit": rc}
                return
            if not novas:
                yield {"ka": 1}


_procs: dict[int, Proc] = {}
_procs_lock = threading.Lock()

# Variáveis que o client pode definir no ambiente do processo (estilo da queima,
# LLM, debug). O resto vem do ambiente do servidor (.env, PATH, chaves).
ENV_KEYS = {"BURN_PAUSE_RATE", "BURN_BOX_OPAQUE", "BURN_TOP_TRANSLATION", "BURN_MULTILINE",
            "EXTRACT_AUDIO", "DRIVE_UPLOAD", "SUBRIM_LLM_PROVIDER", "DEEPSEEK_DEBUG"}


def _argv(raw: list) -> list:
    """Troca os marcadores de Python e valida que o script é do repo."""
    import manager_core
    pythons = {sr.PY: sys.executable,
               sr.WHISPER_PY: str(manager_core.whisper_python()),
               sr.SCRAPER_PY: manager_core.scraper_python()}
    if len(raw) < 2 or raw[0] not in pythons:
        raise PermissionError("comando não permitido (esperado: <python> <script do repo> ...)")
    script = to_path(str(raw[1]))
    if script.suffix != ".py" or not script.is_file() or not any(r in script.parents for r in ROOTS):
        raise PermissionError(f"script inválido: {raw[1]}")
    out = [pythons[raw[0]], str(script)]
    for a in raw[2:]:
        out.append(str(to_path(a["__p__"])) if isinstance(a, dict) and "__p__" in a else str(a))
    return out


def proc_start(body: dict) -> dict:
    argv = _argv(list(body.get("argv") or []))
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    for k, v in (body.get("env") or {}).items():
        if k not in ENV_KEYS:
            continue
        if v is None:
            env.pop(k, None)
        else:
            env[k] = str(v)
    p = Proc(argv, env, str(body.get("label") or Path(argv[1]).name))
    with _procs_lock:
        _procs[p.id] = p
        done = sorted((q for q in _procs.values() if not q.running()), key=lambda q: q.id)
        for q in done[:max(0, len(done) - MAX_FINISHED)]:
            _procs.pop(q.id, None)
    print(f"[mgr] ▶ #{p.id} {p.label}: {' '.join(argv[1:])}", file=sys.stderr)
    return {"id": p.id}


def get_proc(pid: str) -> Proc:
    try:
        p = _procs.get(int(pid))
    except ValueError:
        p = None
    if p is None:
        raise LookupError(f"processo #{pid} desconhecido no servidor")
    return p


def proc_stop(pid: str) -> dict:
    p = get_proc(pid)
    if p.running():
        p.popen.terminate()
    return {"ok": True}


def proc_forget(pid: str) -> dict:
    with _procs_lock:
        p = _procs.get(int(pid))
        if p is not None and not p.running():
            _procs.pop(p.id, None)
    return {"ok": True}


def procs() -> dict:
    with _procs_lock:
        return {"procs": [p.info() for p in sorted(_procs.values(), key=lambda q: q.id)]}


# ── Roteamento (chamado pelo Handler do subrim_server) ────────────────────────

def ping() -> dict:
    return {"ok": True, "host": socket.gethostname(), "repo": str(REPO)}


def handle_get(h) -> bool:
    """GET /mgr/*. Devolve False se o caminho não é deste módulo."""
    path, _, query = h.path.partition("?")
    if path == "/mgr/ping":
        h._json(200, ping())
        return True
    if path == "/mgr/file":
        from urllib.parse import parse_qs
        try:
            p = to_path(parse_qs(query).get("p", [""])[0])
        except PermissionError as e:
            h._json(403, {"error": str(e)})
            return True
        if not p.is_file():
            h._json(404, {"error": f"arquivo não encontrado: {p.name}"})
            return True
        _send_file(h, p)
        return True
    return False


def _send_file(h, p: Path) -> None:
    size = p.stat().st_size
    start, end = 0, size - 1
    rng = h.headers.get("Range", "")
    partial = rng.startswith("bytes=")
    if partial:
        a, _, b = rng[6:].split(",")[0].partition("-")
        try:
            if a:
                start = int(a)
                end = int(b) if b else end
            else:                       # "bytes=-500": os últimos 500
                start = max(0, size - int(b))
        except ValueError:
            partial = False
            start, end = 0, size - 1
        end = min(end, size - 1)
        if start > end:
            h.send_response(416)
            h.send_header("Content-Range", f"bytes */{size}")
            h.end_headers()
            return
    h.send_response(206 if partial else 200)
    h.send_header("Content-Type", mimetypes.guess_type(p.name)[0] or "application/octet-stream")
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Content-Length", str(end - start + 1))
    if partial:
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    h.end_headers()
    try:
        with open(p, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                h.wfile.write(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass


def handle_post(h, body: dict) -> bool:
    """POST /mgr/*. Devolve False se o caminho não é deste módulo."""
    path = h.path
    if not path.startswith("/mgr/"):
        return False
    try:
        if path == "/mgr/call":
            _stream(h, call_events(body))
        elif path == "/mgr/fs":
            h._json(200, {"ok": fs(body)})
        elif path == "/mgr/proc":
            h._json(200, proc_start(body))
        elif path == "/mgr/procs":
            h._json(200, procs())
        elif path.startswith("/mgr/proc/"):
            pid, _, action = path[len("/mgr/proc/"):].partition("/")
            if action == "stream":
                _stream(h, get_proc(pid).events(body.get("from") or 0))
            elif action == "stop":
                h._json(200, proc_stop(pid))
            elif action == "forget":
                h._json(200, proc_forget(pid))
            else:
                h._json(404, {"error": "not found"})
        else:
            h._json(404, {"error": "not found"})
    except LookupError as e:
        h._json(404, {"error": str(e)})
    except PermissionError as e:
        h._json(403, {"error": str(e)})
    except FileNotFoundError as e:
        h._json(404, {"error": f"arquivo não encontrado: {e.filename or e}"})
    except Exception as e:  # noqa: BLE001 - erro vira mensagem no client
        h._json(500, {"error": f"{type(e).__name__}: {e}"})
    return True


def _stream(h, events) -> None:
    """NDJSON sem Content-Length; a conexão fecha no fim (HTTP/1.0)."""
    h.send_response(200)
    h.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    h.end_headers()
    h.close_connection = True
    try:
        for msg in events:
            h.wfile.write(json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n")
            h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass   # o client fechou: a função/processo segue no servidor

