#!/usr/bin/env python3
"""Banco de traduções do warehouse, agrupadas por pontuação — o jogo 4.

No jogo 4 a imagem mostra só o mandarim e o jogador escolhe a tradução entre
cinco. As quatro erradas saem da coluna 5 dos ``*_base.txt``, e o critério é a
PONTUAÇÃO: uma opção com a mesma sequência de vírgulas e pontos parece do mesmo
tipo de frase, então descartar as erradas exige de fato ler o chinês.

A assinatura sai SEMPRE do português, nunca do chinês. Medindo os 209 bases, a
pontuação das duas colunas só coincide em 78,9% das linhas — a legenda foi
re-segmentada na tradução, e um `？` no fim do chinês vira ponto final em
português com frequência. Tirar a assinatura do chinês daria alvo errado em uma
frase a cada cinco.

O botão mostra o texto LIMPO: sem o `[NOME]` do falante, sem `<i>` e sem `♪`. A
tarja do falante é ruído para quem está escolhendo uma tradução, e às vezes
denuncia a resposta — a certa vem do mesmo episódio que a imagem, então um nome
que combina com a cena já elimina as outras quatro. É também sobre o texto limpo
que a assinatura é calculada, então o colchete não conta como pontuação.
"""

import random
import re
import unicodedata

from wordgrid import PT_COL, iter_base_rows

# Marcas que contam para a assinatura. Colchetes, aspas, parênteses e travessão
# ficam de fora: eles dizem quem fala ou que há música, não como a frase é
# construída.
_SIGNIFICANT = ".,?!;:"

# Punctuação CJK que vazou para a coluna portuguesa (~50 linhas no warehouse).
_FULLWIDTH = {"，": ",", "。": ".", "？": "?", "！": "!", "、": ",",
              "：": ":", "；": ";", "…": "..."}

_TAG_RE = re.compile(r"\[[^\]]*\]")        # [BRUNO], [RISO], [SILÊNCIO]
_HTML_RE = re.compile(r"<[^>]*>")          # <i>…</i>
_ARROW_RE = re.compile(r">+")              # ">> Fulano" / "A vida. >>Inteira."
_SPACE_RE = re.compile(r"\s+")
_LEFTOVER_RE = re.compile(r"[\[\]<>]")     # marcação que sobrou depois da limpeza

# Acima disso é artefato: o warehouse guarda algumas respostas de LLM inteiras
# ("Desculpe, mas a frase … parece estar incompleta"), que como opção de múltipla
# escolha se denunciam pelo tamanho antes de serem lidas.
MAX_LEN = 140


def clean_pt(text: str) -> str:
    """Tira a marcação da legenda e colapsa espaço. Não mexe na pontuação.

    Sai tudo que marca QUEM fala ou o que se ouve, e não o que é dito:
    ``[NOME]``, ``[RISO]``, o itálico ``<i>``, o ``♪`` da música e o ``>>`` de
    troca de falante. É ruído para quem escolhe uma tradução, e pior: aparece em
    umas opções e não em outras, o que dá para usar como pista sem ler nada.

    O ``>>`` precisa de regra própria — não tem ``<``, então o padrão de HTML
    não o alcança.
    """
    if not text:
        return ""
    out = _TAG_RE.sub(" ", text)
    out = _HTML_RE.sub(" ", out)
    out = _ARROW_RE.sub(" ", out)
    out = out.replace("♪", " ").replace("♫", " ")
    return _SPACE_RE.sub(" ", out).strip()


def punct_signature(text: str) -> str:
    """Sequência ordenada da pontuação significativa de ``text``."""
    out = []
    for ch in clean_pt(text):
        ch = _FULLWIDTH.get(ch, ch)
        for c in ch:                      # "…" vira três pontos
            if c in _SIGNIFICANT:
                out.append(c)
    return "".join(out)


def _is_caps(text: str) -> bool:
    """True se as letras do texto são todas maiúsculas.

    As novelas do warehouse são caixa-alta e os filmes são caixa mista. Sem esta
    checagem, uma opção em caixa mista no meio de quatro em maiúsculas se
    identifica sem ser lida.
    """
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _usable(text: str) -> bool:
    """A tradução serve como opção? (nem vazia, nem só música/tarja, nem enorme)"""
    cleaned = clean_pt(text)
    if not cleaned or cleaned.upper() == "N/A":
        return False
    if len(cleaned) > MAX_LEN:
        return False
    # Colchete sobrando = tarja partida entre dois cartões de legenda
    # ("LAURINDA] ÓTIMA, MAS…", "[LUCAS ELE TÁ LÁ?"). São 16 linhas em 167 mil e
    # não dá para reconstruir o par que falta, então saem do pool inteiras — o
    # que importa é que nenhum botão mostre um colchete solto.
    if _LEFTOVER_RE.search(cleaned):
        return False
    # Precisa ter ao menos uma letra: sobra "-" ou "..." em algumas linhas.
    return any(unicodedata.category(c).startswith("L") for c in cleaned)


class Bank:
    """``assinatura -> traduções``, para sortear as opções erradas."""

    def __init__(self, buckets: dict):
        self.buckets = buckets

    def __bool__(self) -> bool:
        return bool(self.buckets)

    def __len__(self) -> int:
        return sum(len(v) for v in self.buckets.values())

    @classmethod
    def load(cls, warehouse=None) -> "Bank":
        """Varre os bases e indexa as traduções LIMPAS pela assinatura."""
        buckets: dict = {}
        seen: set = set()
        for _asset, cols in iter_base_rows(warehouse):
            original = (cols[PT_COL] or "").strip()
            if not _usable(original):
                continue
            cleaned = clean_pt(original)
            # Dedupe pelo texto LIMPO: 7,1% das linhas repetem a tradução de
            # outra dentro do mesmo episódio (cartões de legenda partidos), e
            # sem isto a mesma opção errada apareceria duas vezes no grid.
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            buckets.setdefault(punct_signature(original), []).append(cleaned)
        return cls(buckets)

    def options(self, correct: str, rng: random.Random, k: int = 5):
        """As ``k`` opções do jogo 4, já limpas e embaralhadas, ou ``None``.

        ``correct`` entra como está no base (com a tarja do falante); o que sai
        é o texto limpo, inclusive o da opção certa — quem chama deve comparar
        com ``clean_pt(correct)``, não com o original.

        Devolve ``None`` quando o balde da assinatura não tem candidatos
        suficientes — a frase então cai para o jogo 1.
        """
        correct = (correct or "").strip()
        if not _usable(correct):
            return None
        pool = self.buckets.get(punct_signature(correct))
        if not pool:
            return None

        correct = clean_pt(correct)
        mine = correct.casefold()
        caps = _is_caps(correct)
        size = len(correct)
        candidates = [t for t in pool if t.casefold() != mine]
        if len(candidates) < k - 1:
            return None
        rng.shuffle(candidates)

        # Três peneiras, da mais exigente à mais frouxa. Cada uma existe só para
        # não entregar a resposta: sem a de caixa, a única opção em caixa mista é
        # a certa; sem a de tamanho, a mais comprida é a certa.
        def pick(pred):
            for t in candidates:
                if len(chosen) >= k - 1:
                    return
                if t in chosen:
                    continue
                if pred(t):
                    chosen.append(t)

        chosen: list = []
        pick(lambda t: _is_caps(t) == caps and 0.5 * size <= len(t) <= 1.5 * size)
        pick(lambda t: _is_caps(t) == caps)
        pick(lambda t: True)
        if len(chosen) < k - 1:
            return None

        out = chosen + [correct]
        rng.shuffle(out)
        return out
