#!/usr/bin/env python3
"""Maestria de vocabulário da word-api, consultada em lote.

O ``*_base.txt`` preserva SEMPRE pinyin e tradução de todas as palavras. Quais
delas aparecem COM ajuda (pinyin + tradução) é decidido na hora de RENDERIZAR,
aqui, consultando a word-api. Assim marcar uma palavra como dominada passa a
valer retroativamente em tudo — queima do pipeline e aba Coleções — sem
reescrever nenhum base.

Antes o filtro ficava no ``sanitize_base.py``, que regravava a entrada como
hanzi nu (``"當"`` em vez de ``"當 (dāng): quando"``). Isso perdia pinyin e
tradução no arquivo, de forma irreversível, e congelava a decisão no dia em que
o sanitize rodou.

Uma única chamada ``GET /word-api/search?q=`` devolve o vocabulário inteiro
(~34k palavras em ~0,6s), do qual só interessa o conjunto de palavras dominadas
(``confidence_level == 3``). Esse conjunto é pequeno (centenas de palavras),
picklável e barato de passar para processos worker — o que garante que todos os
chunks de uma queima apliquem exatamente a mesma maestria.

Configuração por ambiente:
  ``WORD_API_BASE_URL``  (default ``http://localhost:7998/word-api``)
  ``WORD_API_TIMEOUT``   (default ``30`` segundos)

Se a API estiver fora do ar o módulo falha ABERTO: devolve conjunto vazio (nada
é escondido, o base volta a ser a única fonte) e avisa uma única vez. Render e
pipeline nunca são bloqueados por indisponibilidade da API.

Diagnóstico rápido:  python3 word_vocab.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://localhost:7998/word-api"
MASTERED_LEVEL = 3   # confidence_level que significa "dominada"

_mastered: frozenset | None = None   # cache de processo
_warned = False                      # aviso de API fora do ar sai só uma vez


def base_url() -> str:
    """URL base da word-api (``WORD_API_BASE_URL`` ou o default local)."""
    return os.getenv("WORD_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> float:
    raw = os.getenv("WORD_API_TIMEOUT")
    if not raw or not raw.strip():
        return 30.0
    try:
        return float(raw)
    except ValueError:
        return 30.0


def _warn_once(msg: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        print(msg, file=sys.stderr, flush=True)


def _fetch_mastered() -> frozenset:
    """``GET /search?q=`` → conjunto de palavras com ``confidence_level == 3``.

    A query vazia devolve o vocabulário completo. Levanta exceção em erro de
    rede/HTTP/JSON — quem chama decide o que fazer (ver ``mastered_words``).
    """
    url = f"{base_url()}/search?" + urllib.parse.urlencode({"q": ""})
    with urllib.request.urlopen(url, timeout=_timeout()) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    if not isinstance(payload, list):
        raise ValueError(f"resposta inesperada de {url}: {type(payload).__name__}")

    out: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        word = (item.get("word") or "").strip()
        if not word:
            continue
        try:
            level = int(item.get("confidence_level"))
        except (TypeError, ValueError):
            continue   # nível ilegível → trata como não dominada (falha aberta)
        if level == MASTERED_LEVEL:
            out.add(word)
    return frozenset(out)


def mastered_words(force: bool = False) -> frozenset:
    """Conjunto de palavras dominadas, memoizado no processo.

    ``force=True`` refaz a chamada. Falha ABERTA: em qualquer erro mantém o
    cache anterior (ou conjunto vazio) e avisa uma única vez.
    """
    global _mastered
    if _mastered is not None and not force:
        return _mastered
    try:
        _mastered = _fetch_mastered()
    except Exception as e:  # noqa: BLE001 - render jamais deve quebrar pela API
        _warn_once(f"⚠️  word-api indisponível ({base_url()}): {e}\n"
                   "   Nenhuma palavra será tratada como dominada "
                   "(toda a ajuda do base será exibida).")
        if _mastered is None:
            _mastered = frozenset()
    return _mastered


def reload_mastered() -> int:
    """Recarrega o vocabulário e devolve o total de dominadas (botão da GUI)."""
    global _warned
    _warned = False   # permite avisar de novo se a API caiu desde a última carga
    return len(mastered_words(force=True))


def set_mastered(words) -> None:
    """Prima o cache deste processo com um conjunto já carregado.

    Serve para processos worker (``ProcessPoolExecutor(initializer=...)``):
    o processo pai carrega uma vez e todos os workers renderizam com EXATAMENTE
    a mesma maestria, mesmo que a API caia no meio da queima — o que evita
    chunks do mesmo vídeo saindo com critérios diferentes.
    """
    global _mastered
    _mastered = frozenset(words or ())


def is_mastered(word: str, mastered: frozenset | None = None) -> bool:
    """True se a palavra é dominada (não deve receber pinyin/tradução)."""
    if mastered is None:
        mastered = mastered_words()
    return word in mastered


def display_pairs(pairs, mastered: frozenset | None = None) -> list:
    """Zera pinyin/tradução das palavras dominadas, preservando a tokenização.

    ``pairs`` é a lista de tuplas ``(hanzi, pinyin, tradução)`` devolvida por
    ``parse_pinyin_translations``. A palavra CONTINUA na lista: ela ainda
    delimita o token dentro da frase (evitando que um termo de vários
    caracteres seja quebrado) e segue sendo desenhada como hanzi — apenas perde
    a ajuda.

    Deve ser aplicado ANTES do cálculo de largura das colunas, porque os dois
    renderizadores dimensionam cada palavra com ``max(..., pinyin_width, ...)``.
    """
    if mastered is None:
        mastered = mastered_words()
    if not mastered:
        return list(pairs)
    return [(w, "", "") if w in mastered else (w, py, tr) for w, py, tr in pairs]


def count_learnable(pairs, mastered: frozenset | None = None) -> int:
    """Nº de palavras da frase que ainda ensinam algo (usado pela busca i+1).

    Aprendível = o base tem pinyin E tradução para ela E ela não é dominada.
    O primeiro termo preserva o comportamento das bases antigas, em que a
    entrada nua já significava "não há ajuda a dar".
    """
    if mastered is None:
        mastered = mastered_words()
    return sum(1 for w, py, tr in pairs
               if py.strip() and tr.strip() and w not in mastered)


def is_known(word: str, has_pinyin: bool, has_translation: bool,
             mastered: frozenset | None = None) -> bool:
    """Contraparte de ``count_learnable`` para uma palavra só (coluna Conhecida)."""
    if mastered is None:
        mastered = mastered_words()
    return (not has_pinyin) or (not has_translation) or (word in mastered)


if __name__ == "__main__":
    words = mastered_words()
    print(f"word-api: {base_url()}")
    print(f"palavras dominadas (confidence_level == {MASTERED_LEVEL}): {len(words)}")
    if words:
        sample = sorted(words)[:20]
        print("amostra:", " ".join(sample))
