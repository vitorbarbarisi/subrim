"""Ponte entre o Subrim Manager (client) e o subrim_server.py (servidor na rede).

O manager não guarda mais vídeos, bases nem coleções: tudo mora no clone do
repositório na máquina servidor, e este módulo leva até lá cada operação.

- ``RemotePath`` imita o pedaço da API do ``pathlib.Path`` que o manager usa.
  O caminho é relativo à raiz do repo no servidor (ou absoluto, para os HDs em
  os HDs externos); cada ``exists``/``glob``/``read_text``… é uma chamada HTTP.
  Não tem ``__fspath__`` de propósito: um ``open()`` local num RemotePath falha
  na hora em vez de ler (ou criar) arquivo nesta máquina.
- ``RemoteModule("collection_builder").search(...)`` roda a função no servidor.
  Argumentos chamáveis (``log_cb``, ``progress_cb``) viram callbacks: o servidor
  os devolve como eventos NDJSON e eles rodam aqui, na thread de quem chamou.
- ``CLIENT.proc_*`` lança e acompanha os scripts do pipeline no servidor. O
  processo pertence ao servidor: fechar o manager não o interrompe.

Os dois lados usam ``encode``/``decode`` (JSON com marcadores para caminhos,
conjuntos, tuplas, bytes e imagens). Só stdlib — o client não instala nada.
"""

from __future__ import annotations

import base64
import io
import json
import posixpath
import queue
import threading
import time
from types import SimpleNamespace
from urllib import error as urlerror, parse as urlparse, request as urlrequest

DEFAULT_PORT = 7997
PING_INTERVAL = 3.0       # segundos entre pings do monitor de conexão
CONNECT_TIMEOUT = 4.0     # chamadas curtas (fs, listas)
STREAM_TIMEOUT = 120.0    # silêncio máximo num stream (o servidor manda keepalive)

# Marcadores de comando no argv de um processo remoto, trocados no servidor
# pelo Python certo de lá (o sys.executable daqui não existe na outra máquina).
PY = "{python}"
WHISPER_PY = "{whisper_python}"
SCRAPER_PY = "{scraper_python}"


class RemoteError(RuntimeError):
    """Erro devolvido pelo servidor (a mensagem é a da exceção de lá)."""


class Disconnected(RemoteError):
    """Sem servidor configurado ou inacessível."""


# ── Codificação ───────────────────────────────────────────────────────────────

def encode(obj, path_to_str):
    """Objeto Python → estrutura JSON. ``path_to_str(obj)`` devolve a string do
    caminho se ``obj`` for um caminho deste lado, senão ``None``."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    p = path_to_str(obj)
    if p is not None:
        return {"__p__": p}
    if isinstance(obj, dict):
        if all(isinstance(k, str) for k in obj):
            return {k: encode(v, path_to_str) for k, v in obj.items()}
        return {"__map__": [[encode(k, path_to_str), encode(v, path_to_str)]
                            for k, v in obj.items()]}
    if isinstance(obj, list):
        return [encode(v, path_to_str) for v in obj]
    if isinstance(obj, tuple):
        return {"__tup__": [encode(v, path_to_str) for v in obj]}
    if isinstance(obj, (set, frozenset)):
        return {"__set__": [encode(v, path_to_str) for v in obj]}
    if isinstance(obj, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(obj)).decode("ascii")}
    if hasattr(obj, "save") and hasattr(obj, "mode") and hasattr(obj, "size"):
        return {"__img__": _image_to_b64(obj)}          # PIL.Image
    if hasattr(obj, "item") and callable(obj.item):   # escalar numpy
        return obj.item()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"não serializável para o servidor: {type(obj).__name__}")


def decode(obj, make_path):
    """Inverso de ``encode``; ``make_path(str)`` cria o caminho deste lado."""
    if isinstance(obj, list):
        return [decode(v, make_path) for v in obj]
    if not isinstance(obj, dict):
        return obj
    if len(obj) == 1:
        (k, v), = obj.items()
        if k == "__p__":
            return make_path(v)
        if k == "__tup__":
            return tuple(decode(x, make_path) for x in v)
        if k == "__set__":
            return {decode(x, make_path) for x in v}
        if k == "__map__":
            return {decode(a, make_path): decode(b, make_path) for a, b in v}
        if k == "__b64__":
            return base64.b64decode(v)
        if k == "__img__":
            return _image_from_b64(v)
    return {k: decode(v, make_path) for k, v in obj.items()}


def _image_to_b64(img) -> str:
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.save(buf, format="PNG")
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _image_from_b64(data: str):
    from PIL import Image   # só quem recebe imagem precisa do Pillow
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    img.load()
    return img


# ── Caminho remoto ────────────────────────────────────────────────────────────

class RemotePath:
    """Caminho no servidor: relativo à raiz do repo (``"."`` = a raiz) ou absoluto."""

    __slots__ = ("_s",)

    def __init__(self, *parts):
        segs = [p._s if isinstance(p, RemotePath) else str(p) for p in parts] or ["."]
        self._s = posixpath.normpath(posixpath.join(*segs))

    # Pura manipulação de string (sem rede)
    def __str__(self):
        return self._s

    def __repr__(self):
        return f"RemotePath({self._s!r})"

    def __eq__(self, other):
        return isinstance(other, RemotePath) and other._s == self._s

    def __hash__(self):
        return hash(("RemotePath", self._s))

    def __lt__(self, other):
        return self._s < other._s

    def __truediv__(self, other):
        return RemotePath(self._s, other)

    @property
    def name(self) -> str:
        return "" if self._s in (".", "/") else posixpath.basename(self._s)

    @property
    def suffix(self) -> str:
        n = self.name
        i = n.rfind(".")
        return n[i:] if 0 < i < len(n) - 1 else ""

    @property
    def stem(self) -> str:
        n, s = self.name, self.suffix
        return n[: -len(s)] if s else n

    @property
    def parent(self) -> "RemotePath":
        d = posixpath.dirname(self._s)
        return RemotePath(d or ".")

    def with_name(self, name: str) -> "RemotePath":
        return self.parent / name

    def with_suffix(self, suffix: str) -> "RemotePath":
        return self.parent / (self.stem + suffix)

    def relative_to(self, other) -> "RemotePath":
        rel = posixpath.relpath(self._s, str(other))
        if rel.startswith(".."):
            raise ValueError(f"{self._s} não está dentro de {other}")
        return RemotePath(rel)

    def resolve(self) -> "RemotePath":
        return self

    # Operações no servidor
    def _fs(self, op, *args):
        return CLIENT.fs(op, self, *args)

    def exists(self) -> bool:
        return self._fs("exists")

    def is_dir(self) -> bool:
        return self._fs("is_dir")

    def is_file(self) -> bool:
        return self._fs("is_file")

    def glob(self, pattern: str):
        return iter(self._fs("glob", pattern))

    def rglob(self, pattern: str):
        return iter(self._fs("rglob", pattern))

    def iterdir(self):
        return iter(self._fs("iterdir"))

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._fs("read_text")

    def read_bytes(self) -> bytes:
        return CLIENT.fetch(self)

    def write_text(self, text: str, encoding: str = "utf-8") -> None:
        self._fs("write_text", text)

    def stat(self):
        return SimpleNamespace(**self._fs("stat"))

    def unlink(self, missing_ok: bool = False) -> None:
        self._fs("unlink", missing_ok)

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self._fs("mkdir", parents, exist_ok)


def _client_path_str(obj):
    if isinstance(obj, RemotePath):
        return str(obj)
    # Um pathlib.Path local nunca deve viajar: seria um caminho DESTA máquina.
    if type(obj).__module__ == "pathlib":
        raise TypeError(f"caminho local enviado ao servidor: {obj}")
    return None


# ── Client HTTP ───────────────────────────────────────────────────────────────

def parse_host(text: str):
    """``"192.168.0.10"`` / ``"192.168.0.10:7997"`` → URL base, ou None."""
    text = (text or "").strip()
    if not text:
        return None
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.strip("/")
    host, _, port = text.partition(":")
    if not host or (port and not port.isdigit()):
        return None
    return f"http://{host}:{port or DEFAULT_PORT}"


class Client:
    def __init__(self):
        self.base = None
        self.connected = False
        self._state = None        # último estado avisado (None = ainda não testado)
        self.info: dict = {}
        self._listeners = []
        self._wake = threading.Event()
        self._monitor = None

    # Conexão
    def set_host(self, text: str) -> bool:
        """Aponta para outro servidor. False se o texto não é um endereço válido."""
        base = parse_host(text)
        self.base = base
        self.connected, self.info, self._state = False, {}, None
        if base is None:
            self._set_connected(False, {})   # nada a testar: avisa já
        self._wake.set()
        return base is not None

    def on_change(self, fn):
        """``fn(connected: bool, info: dict)`` a cada mudança de estado (na thread
        do monitor — quem mexe em UI deve repassar para a thread dela)."""
        self._listeners.append(fn)

    def start_monitor(self):
        if self._monitor is None:
            self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor.start()

    def _monitor_loop(self):
        while True:
            base = self.base
            ok, info = False, {}
            if base:
                try:
                    info = self._get_json("/mgr/ping", timeout=CONNECT_TIMEOUT)
                    ok = bool(info.get("ok"))
                except Exception:   # noqa: BLE001 - qualquer falha = desconectado
                    ok = False
            if base == self.base:   # o host não mudou durante o ping
                self._set_connected(ok, info)
            self._wake.wait(PING_INTERVAL)
            self._wake.clear()

    def _set_connected(self, ok: bool, info: dict):
        changed = ok != self._state
        self.connected, self.info, self._state = ok, info, ok
        if changed:
            for fn in self._listeners:
                try:
                    fn(ok, info)
                except Exception:   # noqa: BLE001
                    pass

    def _need(self):
        if not self.base:
            raise Disconnected("Servidor não configurado: informe o IP no topo da janela.")
        if not self.connected:
            raise Disconnected(f"Servidor inacessível ({self.base}).")
        return self.base

    def url(self, path: str, **query) -> str:
        base = self._need()
        q = f"?{urlparse.urlencode(query)}" if query else ""
        return f"{base}{path}{q}"

    # HTTP
    def _get_json(self, path: str, timeout: float = CONNECT_TIMEOUT):
        with urlrequest.urlopen(f"{self.base}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _open(self, path: str, payload, timeout: float):
        req = urlrequest.Request(
            self.url(path), data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            return urlrequest.urlopen(req, timeout=timeout)
        except urlerror.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", str(e))
            except Exception:   # noqa: BLE001
                msg = str(e)
            raise RemoteError(msg) from None
        except (urlerror.URLError, OSError) as e:
            self._wake.set()   # o monitor confere já, sem esperar o intervalo
            raise Disconnected(f"Sem resposta do servidor ({self.base}): {e}") from None

    def _post_json(self, path: str, payload, timeout: float = CONNECT_TIMEOUT):
        with self._open(path, payload, timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # Chamadas de função
    def call(self, fn: str, *args, **kwargs):
        """Roda ``modulo.funcao(*args, **kwargs)`` no servidor e devolve o resultado."""
        callbacks = []

        def enc(v):
            if callable(v) and not isinstance(v, type):
                callbacks.append(v)
                return {"__cb__": len(callbacks) - 1}
            return encode(v, _client_path_str)

        payload = {"fn": fn, "args": [enc(a) for a in args],
                   "kwargs": {k: enc(v) for k, v in kwargs.items()}}
        with self._open("/mgr/call", payload, STREAM_TIMEOUT) as r:
            for raw in r:
                if not raw.strip():
                    continue
                msg = json.loads(raw.decode("utf-8"))
                if "cb" in msg:
                    callbacks[msg["cb"]](*decode(msg["args"], RemotePath))
                elif "ok" in msg:
                    return decode(msg["ok"], RemotePath)
                elif "err" in msg:
                    raise RemoteError(msg["err"])
        raise Disconnected(f"O servidor encerrou a chamada {fn} sem resposta.")

    def fs(self, op: str, path: RemotePath, *args):
        res = self._post_json("/mgr/fs", {"op": op, "path": str(path),
                                          "args": [encode(a, _client_path_str) for a in args]})
        return decode(res["ok"], RemotePath)

    def fetch(self, path: RemotePath) -> bytes:
        """Conteúdo de um arquivo do servidor (para clipes de áudio e afins)."""
        try:
            with urlrequest.urlopen(self.file_url(path), timeout=STREAM_TIMEOUT) as r:
                return r.read()
        except urlerror.HTTPError as e:
            raise RemoteError(f"{path}: HTTP {e.code}") from None
        except (urlerror.URLError, OSError) as e:
            raise Disconnected(f"Sem resposta do servidor ({self.base}): {e}") from None

    def file_url(self, path: RemotePath) -> str:
        """URL que serve o arquivo (com Range: vídeo abre em streaming no navegador)."""
        return self.url("/mgr/file", p=str(path))

    # Processos
    def proc_start(self, argv: list, env: dict, label: str) -> int:
        res = self._post_json("/mgr/proc", {
            "argv": [encode(a, _client_path_str) if not isinstance(a, str) else a
                     for a in argv],
            "env": env, "label": label})
        return res["id"]

    def proc_stream(self, pid: int, offset: int = 0):
        """Gera ``("line", texto)`` e, no fim, ``("exit", código)``."""
        with self._open(f"/mgr/proc/{pid}/stream", {"from": offset}, STREAM_TIMEOUT) as r:
            for raw in r:
                if not raw.strip():
                    continue
                msg = json.loads(raw.decode("utf-8"))
                if "line" in msg:
                    yield "line", msg["line"]
                elif "exit" in msg:
                    yield "exit", msg["exit"]
                    return
        raise Disconnected("Stream do processo interrompido.")

    def proc_stop(self, pid: int) -> None:
        self._post_json(f"/mgr/proc/{pid}/stop", {})

    def proc_forget(self, pid: int) -> None:
        self._post_json(f"/mgr/proc/{pid}/forget", {})

    def procs(self) -> list:
        return self._post_json("/mgr/procs", {})["procs"]


CLIENT = Client()


class RemoteModule:
    """``RemoteModule("periods_base").generate(bf)`` → chamada no servidor."""

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr: str):
        if attr.startswith("_"):
            raise AttributeError(attr)
        fn = f"{self._name}.{attr}"
        return lambda *a, **k: CLIENT.call(fn, *a, **k)


class RemoteProc:
    """Processo no servidor com a cara do ``subprocess.Popen`` que o _launch usava.

    ``for line in proc.stdout`` lê o log em streaming; reconecta sozinho se a
    rede cair no meio (o servidor guarda o log), até o processo acabar.
    """

    def __init__(self, pid: int, offset: int = 0):
        self.pid = pid
        self.returncode = None
        self._offset = offset

    @property
    def stdout(self):
        while self.returncode is None:
            try:
                for kind, val in CLIENT.proc_stream(self.pid, self._offset):
                    if kind == "line":
                        self._offset += 1
                        yield val + "\n"
                    else:
                        self.returncode = val
            except RemoteError as e:
                if "desconhecido" in str(e):   # servidor reiniciou: o processo se perdeu
                    self.returncode = -1
                    yield f"❌ {e}\n"
                    return
                time.sleep(PING_INTERVAL)      # rede caiu: tenta de novo do ponto onde parou

    def poll(self):
        return self.returncode

    def wait(self):
        for _ in self.stdout:
            pass
        return self.returncode

    def terminate(self):
        try:
            CLIENT.proc_stop(self.pid)
        except RemoteError:
            pass


# ── Lado do servidor ──────────────────────────────────────────────────────────

class CallbackStream:
    """Servidor: roda ``fn`` numa thread e emite NDJSON (callbacks, keepalive, resultado)."""

    KEEPALIVE = 10.0

    def __init__(self, encode_out):
        self._q: queue.Queue = queue.Queue()
        self._encode = encode_out

    def make_callback(self, idx: int):
        return lambda *a: self._q.put({"cb": idx, "args": self._encode(list(a))})

    def _run(self, fn, args, kwargs):
        try:
            self._q.put({"ok": self._encode(fn(*args, **kwargs))})
        except Exception as e:   # noqa: BLE001 - o erro vai para o client
            self._q.put({"err": f"{type(e).__name__}: {e}"})

    def run(self, fn, args, kwargs):
        """Inicia ``fn`` e devolve o gerador de eventos."""
        threading.Thread(target=self._run, args=(fn, args, kwargs), daemon=True).start()
        return self._events()

    def _events(self):
        while True:
            try:
                msg = self._q.get(timeout=self.KEEPALIVE)
            except queue.Empty:
                yield {"ka": 1}
                continue
            yield msg
            if "ok" in msg or "err" in msg:
                return
