#!/usr/bin/env python3
"""Decomposição dos caracteres, da hanzi-api, com cache em disco — o jogo 5.

No jogo 5 cada botão mostra a decomposição de um caractere
(``日 (sol/tempo) + 寺 (templo/instituição)``) e o jogador monta a frase por
elas. O dado vem do campo ``decomposition`` da hanzi-api.

Ao contrário da word-api, a hanzi-api **não tem ``/search``**: só
``GET /hanzi-api/{caractere}``, um por vez. E cada GET dispara um
``increment_count`` do lado do servidor — o contador que diz quantas vezes você
encontrou aquele caractere estudando. Empacotar uma coleção grande tocaria ~4200
caracteres e inflaria esse contador com algo que não é estudo.

Daí o cache em disco: um caractere é consultado uma vez na vida e reempacotar
não toca mais na API. O cache guarda TAMBÉM os 404 (como string vazia), senão os
milhares de caracteres que ainda não estão no banco seriam re-consultados a cada
execução.

O campo é preenchido por LLM de forma assíncrona, então string vazia é resposta
legítima e frequente: dos caracteres que aparecem no warehouse, 19% têm
decomposição — mas são os frequentes, então cobrem 78% das ocorrências. Quem
chama decide o fallback (o jogo mostra o caractere puro).

Configuração por ambiente:
  ``HANZI_API_BASE_URL``  (default ``http://localhost:7998/hanzi-api/hanzi``)
  ``HANZI_API_TIMEOUT``   (default ``10`` segundos)

Diagnóstico rápido:  python3 dictation/hanzi_decomp.py 學 我 的
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# O prefixo tem "hanzi" duas vezes: o app monta o router em "/hanzi-api" e o
# router monta o seu sub-router em "/hanzi". A URL completa é a que responde —
# "/hanzi-api/我" devolve 404.
DEFAULT_BASE_URL = "http://localhost:7998/hanzi-api/hanzi"
CACHE_PATH = Path(__file__).resolve().parent / ".hanzi_cache.json"

_cache: dict | None = None
_warned = False
requests_made = 0        # instrumentação: quantos GETs esta execução fez


def base_url() -> str:
    return os.getenv("HANZI_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> float:
    raw = os.getenv("HANZI_API_TIMEOUT")
    try:
        return float(raw) if raw and raw.strip() else 10.0
    except ValueError:
        return 10.0


def _warn_once(msg: str) -> None:
    global _warned
    if not _warned:
        _warned = True
        print(msg, file=sys.stderr, flush=True)


def load_cache() -> dict:
    """``caractere -> decomposição`` já conhecido. Vazio se o arquivo não abrir."""
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if CACHE_PATH.exists():
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _cache = {k: v for k, v in data.items() if isinstance(v, str)}
        except (OSError, ValueError):
            pass          # cache ruim é cache ausente, não erro
    return _cache


def save_cache() -> None:
    try:
        CACHE_PATH.write_text(
            json.dumps(load_cache(), ensure_ascii=False, indent=0, sort_keys=True),
            encoding="utf-8")
    except OSError as e:
        _warn_once(f"⚠️  não deu para gravar {CACHE_PATH.name}: {e}")


def sanitize(char: str, decomposition: str) -> str:
    """Devolve a decomposição utilizável, ou "" quando ela entrega a resposta.

    O campo é escrito por LLM e 9% das linhas começam pelo PRÓPRIO caractere,
    em dois formatos:

        離 = 亠 (teto) + 凶 (perigo) + 禸 (rastro)   → dá para salvar: corta o "X ="
        又 (mão direita) — caracter pictográfico…    → não dá: é um pictograma,
                                                        não tem componentes

    No jogo 5 o botão mostra a decomposição e o jogador adivinha o caractere;
    um rótulo que já contém o caractere é a resposta impressa no botão. O
    segundo caso vira "" e cai no fallback (o caractere puro), que é o mesmo que
    ele já dizia — só que sem a descrição que o denuncia.
    """
    decomposition = (decomposition or "").strip()
    if not decomposition:
        return ""
    # "X = componentes" → fica só o lado direito.
    if decomposition.startswith(char):
        resto = decomposition[len(char):].lstrip()
        if resto.startswith("="):
            decomposition = resto[1:].strip()
    # Sem "+" não há decomposição: é o caractere descrito por extenso.
    if "+" not in decomposition or char in decomposition:
        return ""
    return decomposition


def _fetch(char: str) -> str:
    """``GET /{char}`` → decomposição. 404 devolve "". Levanta em erro de rede."""
    global requests_made
    url = f"{base_url()}/{urllib.parse.quote(char)}"
    requests_made += 1
    try:
        with urllib.request.urlopen(url, timeout=_timeout()) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""     # caractere ainda não cadastrado — resposta, não falha
        raise
    if not isinstance(payload, dict):
        return ""
    return (payload.get("decomposition") or "").strip()


def decompositions(chars, retry_empty: bool = False) -> dict:
    """``{caractere: decomposição}`` para ``chars``. "" = sem decomposição.

    Falha ABERTA, como o ``word_vocab``: se a API cair no meio, o que já veio é
    devolvido e o resto sai como "". Um bundle sempre é gerado; o jogo 5 apenas
    mostra mais caracteres puros.

    ``retry_empty=True`` re-consulta os que estão em cache como vazios — o
    enriquecimento é assíncrono, então um caractere sem decomposição hoje pode
    ter uma semana que vem.
    """
    cache = load_cache()
    faltam = [c for c in dict.fromkeys(chars)
              if c not in cache or (retry_empty and not cache[c])]

    novos = 0
    for char in faltam:
        try:
            cache[char] = _fetch(char)
            novos += 1
        except Exception as e:  # noqa: BLE001 - o bundle nunca deve quebrar pela API
            _warn_once(f"⚠️  hanzi-api indisponível ({base_url()}): {e}\n"
                       "   Os caracteres sem decomposição em cache aparecerão "
                       "inteiros no jogo 5.")
            break
    if novos:
        save_cache()

    # Guarda-se o campo CRU no cache e limpa-se na leitura: se a regra de
    # limpeza mudar, não é preciso re-consultar 4 mil caracteres.
    return {c: sanitize(c, cache.get(c, "")) for c in chars}


if __name__ == "__main__":
    alvos = sys.argv[1:] or list("學我的時半")
    print(f"hanzi-api: {base_url()}")
    print(f"cache: {CACHE_PATH} ({len(load_cache())} caracteres)")
    for char, decomp in decompositions(alvos).items():
        print(f"  {char}  {decomp or '(sem decomposição)'}")
    print(f"requisições nesta execução: {requests_made}")
