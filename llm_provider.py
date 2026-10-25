#!/usr/bin/env python3
"""Provedor de LLM do subrim: DeepSeek (API) ou modelo local (Ollama).

Todas as chamadas de LLM do pipeline (pares palavra/pinyin/tradução, tradução
para zht e para pt) passam por ``chat()``. Os prompts e os parsers continuam
em quem chama; aqui fica só o transporte.

Escolha do provedor:
  - parâmetro ``provider`` ("deepseek" | "local"), quando quem chama sabe
    (o subrim_server recebe da extensão em cada pedido);
  - senão a env ``SUBRIM_LLM_PROVIDER`` (o subrim_manager injeta por queima);
  - senão "deepseek".

DeepSeek: ``DEEPSEEK_API_KEY``, ``DEEPSEEK_API_BASE``, ``DEEPSEEK_MODEL`` (como
sempre). Local: ``LOCAL_LLM_BASE`` (default http://localhost:11434) e
``LOCAL_LLM_MODEL`` (default qwen2.5:14b). O modo local usa a API nativa do
Ollama (/api/chat), não a compatível com OpenAI, porque só ela aceita
``num_ctx`` — o contexto padrão (2–4k tokens) truncaria um lote de pares.

No modo local o pinyin dos pares vem do pypinyin (``fix_pinyin``), não do
modelo: é determinístico e um modelo de 14B erra tom/leitura com frequência.

Diagnóstico rápido:  python3 llm_provider.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib import error as urlerror, request as urlrequest

PROVIDERS = ("deepseek", "local")
LABELS = {"deepseek": "DeepSeek", "local": "LLM local"}

DEFAULT_LOCAL_BASE = "http://localhost:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5:14b"
LOCAL_NUM_CTX = 8192

_PAIR_RE = re.compile(r"^([^\s(]+)\s*\(([^)]*)\)\s*:\s*(.+)$")
_warned_pypinyin = False


def active(provider: str | None = None) -> str:
    p = (provider or os.getenv("SUBRIM_LLM_PROVIDER") or "deepseek").strip().lower()
    if p not in PROVIDERS:
        raise ValueError(f"provedor de LLM desconhecido: {p!r} (use deepseek ou local)")
    return p


def local_base() -> str:
    return os.getenv("LOCAL_LLM_BASE", DEFAULT_LOCAL_BASE).rstrip("/")


def local_model() -> str:
    return os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except ValueError:
        return default


def batch_size(kind: str, provider: str | None = None) -> int:
    """Frases por chamada. ``kind``: "pairs" ou "translate".

    O local usa lotes menores: a geração é mais lenta e um lote pequeno faz a
    primeira resposta chegar logo (a extensão mostra as falas lote a lote).
    """
    if active(provider) == "local":
        return max(1, _env_int("LOCAL_LLM_PAIRS_BATCH" if kind == "pairs" else "LOCAL_LLM_TRANSLATE_BATCH", 8))
    if kind == "pairs":
        return max(1, _env_int("DEEPSEEK_PAIRS_BATCH", 20))
    return max(1, _env_int("DEEPSEEK_TRANSLATE_BATCH", 15))


def timeout(n_items: int = 1, provider: str | None = None) -> float:
    """Read-timeout (s) de uma chamada. O local gera bem mais devagar."""
    if active(provider) == "local":
        cap = float(os.getenv("LOCAL_LLM_TIMEOUT_CAP") or 600)
        return max(120.0, min(cap, 30.0 + 25.0 * max(1, n_items)))
    import processor  # import tardio: processor importa este módulo
    return processor._deepseek_timeout(n_items)


def _strip_fences(content: str) -> str:
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def chat(prompt: str, *, system: str | None = None, temperature: float = 0.2,
         max_tokens: int | None = None, timeout_sec: float | None = None,
         n_items: int = 1, json_object: bool = False, provider: str | None = None) -> str:
    """Manda ``prompt`` ao provedor e devolve o texto da resposta (sem cercas ```).

    ``json_object=True`` pede ao local saída JSON válida (format=json do
    Ollama) — só para prompts que devolvem um OBJETO. Devolve "" se o modelo
    respondeu vazio. Erros de rede/HTTP viram RuntimeError, para o
    ``processor._retry_api_call`` tentar de novo.
    """
    import processor  # import tardio: processor importa este módulo

    p = active(provider)
    if timeout_sec is None:
        timeout_sec = timeout(n_items, p)
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]

    if p == "local":
        name = "LLM local"
        url = f"{local_base()}/api/chat"
        options = {"temperature": temperature, "num_ctx": LOCAL_NUM_CTX}
        if max_tokens:
            options["num_predict"] = max_tokens
        body = {"model": local_model(), "messages": messages, "stream": False, "options": options}
        if json_object:
            body["format"] = "json"
        headers = {"Content-Type": "application/json"}
        ssl_ctx = None
    else:
        name = "DeepSeek"
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key or not api_key.strip():
            raise RuntimeError("DEEPSEEK_API_KEY não encontrada ou vazia no ambiente")
        api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
        url = f"{api_base.rstrip('/')}/chat/completions"
        body = {"model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": messages, "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = max_tokens
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        ssl_ctx = processor._get_ssl_context()

    req = urlrequest.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout_sec, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        processor._log_deepseek(p, prompt, raw)
        obj = json.loads(raw)
    except urlerror.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError(f"Erro de autenticação com {name}. Verifique sua API key.")
        if exc.code == 404 and p == "local":
            raise RuntimeError(f"Modelo {local_model()} não encontrado no Ollama. Rode: ollama pull {local_model()}")
        if exc.code == 429:
            raise RuntimeError(f"Limite de taxa da API {name} excedido. Aguarde alguns minutos.")
        if exc.code >= 500:
            raise RuntimeError(f"Erro no servidor {name} (HTTP {exc.code}). Tente novamente mais tarde.")
        raise RuntimeError(f"Falha na chamada ao {name}: HTTP {exc.code}")
    except TimeoutError:
        raise RuntimeError(f"Timeout na chamada ao {name} ({timeout_sec:.0f}s).")
    except (urlerror.URLError, OSError, ValueError) as exc:
        if p == "local" and isinstance(exc, urlerror.URLError):
            raise RuntimeError(f"LLM local fora do ar em {local_base()} (rode: ollama serve): {exc.reason}")
        raise RuntimeError(f"Falha na chamada ao {name}: {exc}")

    if p == "local":
        content = (obj.get("message") or {}).get("content")
    else:
        content = (obj.get("choices") or [{}])[0].get("message", {}).get("content")
    return _strip_fences(content) if content else ""


def fix_pinyin(pairs: list[str], provider: str | None = None) -> list[str]:
    """No modo local, troca o pinyin de cada "palavra (pinyin): tradução" pelo
    do pypinyin (com tons, sílabas separadas por espaço). DeepSeek: intocado."""
    global _warned_pypinyin
    if active(provider) != "local":
        return pairs
    try:
        from pypinyin import Style, pinyin
    except ImportError:
        if not _warned_pypinyin:
            _warned_pypinyin = True
            print("⚠️  pypinyin não instalado: usando o pinyin do modelo local "
                  "(pip install pypinyin)", file=sys.stderr)
        return pairs
    out = []
    for item in pairs:
        m = _PAIR_RE.match(item.strip())
        if not m:
            out.append(item)
            continue
        word, _py, tr = m.groups()
        if not _CJK_RE.search(word):
            out.append(f"{word} ({word}): {tr.strip()}")  # "Kindle (Kindle)", como a DeepSeek faz
            continue
        # O dicionário de palavras do pypinyin é em simplificado: com o
        # tradicional ele não acha a palavra e lê caractere a caractere
        # (睡覺 → shuì jué, 銀行 → yín xíng). Simplificado acerta (jiào, háng).
        py = " ".join(s[0] for s in pinyin(_to_simplified(word), style=Style.TONE, errors="ignore")
                      if s and s[0])
        out.append(f"{word} ({py}): {tr.strip()}" if py else item)
    return out


_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_t2s = None


def _to_simplified(text: str) -> str:
    global _t2s
    if _t2s is None:
        try:
            import opencc
            _t2s = opencc.OpenCC("t2s").convert
        except ImportError:
            _t2s = lambda s: s  # noqa: E731 - sem OpenCC, pypinyin no tradicional mesmo
    return _t2s(text)


def status(provider: str) -> dict:
    """{ok, detail} — o provedor está pronto para uso?"""
    p = active(provider)
    if p == "deepseek":
        # O manager não carrega o .env (os scripts do pipeline carregam ao
        # importar o processor) — sem isto a chave pareceria ausente.
        import processor
        processor.load_dotenv()
        ok = bool((os.getenv("DEEPSEEK_API_KEY") or "").strip())
        return {"ok": ok, "detail": "chave configurada" if ok else "sem DEEPSEEK_API_KEY no .env"}
    try:
        with urlrequest.urlopen(f"{local_base()}/api/tags", timeout=3) as resp:
            names = {m.get("name") for m in json.loads(resp.read()).get("models", [])}
    except Exception:  # noqa: BLE001
        return {"ok": False, "detail": "Ollama fora do ar (ollama serve)"}
    model = local_model()
    if model in names or f"{model}:latest" in names:
        return {"ok": True, "detail": f"Ollama no ar · {model}"}
    return {"ok": False, "detail": f"{model} não baixado (ollama pull {model})"}


if __name__ == "__main__":
    import processor  # noqa: F401 - carrega o .env
    for prov in PROVIDERS:
        st = status(prov)
        print(f"{prov:9s} {'ok ' if st['ok'] else 'NÃO'}  {st['detail']}")
