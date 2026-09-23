#!/usr/bin/env python3
"""Léxico, segmentação e distratores para os jogos 2, 3 e 6 do ditado.

O jogo 2 precisa da frase INTEIRA quebrada em palavras com pinyin — um botão
por palavra, mais dois botões errados por palavra. A coluna 4 do ``*_base.txt``
não serve para isso: ela lista só as palavras que ensinam algo, e medindo os 209
bases do warehouse apenas 6,8% das frases têm os pares cobrindo a frase toda.

Também não há ``jieba`` nem ``pypinyin`` instalados, e um bundle roda offline no
celular — então a segmentação tem de acontecer AQUI, na hora de empacotar, com
stdlib.

A saída é o léxico ``palavra -> pinyin`` mais um casamento guloso do maior
prefixo. Não é análise linguística: é boa o bastante porque os botões e o
verificador saem da MESMA segmentação, então ela é correta por construção. Na
prática 99,8% das frases fecham com pinyin em todos os tokens.

Distratores variam nas LETRAS, nunca só no acento: se a certa é ``jiǎn zhí``,
``jiān zhí`` está proibido — vale ``jiān chí``, ``miǎn zhí``. Ver ``distractors``.

O jogo 6 usa a MESMA coluna 4 que não serve ao jogo 2, e pelo mesmo motivo: ela
lista só as palavras que a legenda ensina. Onde o jogo 2 precisa da frase toda,
o 6 precisa de uma palavra só — e quer justamente a que vale a pena esconder.
Ver ``Masks``.
"""

import random
import re
import sys
import unicodedata
from pathlib import Path

# A raiz do repo entra no path aqui, e não em quem importa: assim o módulo pode
# ser importado de dentro de dictation/ (onde o make_bundle roda) sem que cada
# ponto de entrada tenha de saber onde mora o word_vocab.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import word_vocab  # noqa: E402

# Coluna 4 do base: '["最多 (zuì duō): no máximo", "半 (bàn): meia"]'.
# Regex local, e não `video_screenshoter_r36s.parse_pinyin_translations`, porque
# importar aquele módulo arrastaria cv2 + PIL para dentro de dictation/ — que o
# README promete manter sem dependência de runtime.
_PAIR_RE = re.compile(r'"([^"\s(]+)\s*\(([^)]+)\):\s*([^"]*)"')

_CJK_ONLY_RE = re.compile(r"[^一-鿿㐀-䶿豈-﫿]")

PAIRS_COL = 4
PT_COL = 5
ZHT_COL = 3


def warehouse_dir(warehouse: Path = None) -> Path:
    """Pasta do warehouse — por padrão a irmã de ``dictation/``."""
    if warehouse is None:
        warehouse = Path(__file__).resolve().parent.parent / "warehouse"
    return warehouse


def iter_base_rows(warehouse: Path = None, include_periods: bool = False):
    """Percorre todos os ``*_base.txt``, devolvendo ``(asset, colunas)``.

    Uma linha só é devolvida se tiver as 6 colunas do contrato
    (``index begin end zht pares pt``). Mora aqui, e não em cada consumidor,
    porque o ditado já tem três módulos lendo os mesmos 209 arquivos — o
    léxico dos jogos 2/5, o banco de traduções do jogo 4 e as máscaras do 6.

    ``include_periods`` acrescenta os ``*_periods.txt``, que têm o mesmo
    formato de 6 colunas e os seus próprios pares. Uma coleção pode ter sido
    construída a partir deles (ver ``collection_builder.active_base_for``), e
    28 mil frases só existem lá. Fica desligado por padrão porque ao léxico e
    ao banco de traduções essas linhas quase só repetem o que o base já tem —
    quem precisa da frase EXATA da coleção é a ``Masks``.
    """
    warehouse = warehouse_dir(warehouse)
    if not warehouse.is_dir():
        return
    padroes = ["*_base.txt"] + (["*_periods.txt"] if include_periods else [])
    for padrao in padroes:
        sufixo = padrao[1:-len(".txt")]        # "_base" / "_periods"
        for base in sorted(warehouse.glob(padrao)):
            asset = (base.stem[:-len(sufixo)]
                     if base.stem.endswith(sufixo) else base.stem)
            try:
                text = base.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                cols = line.split("\t")
                if len(cols) > PT_COL:
                    yield asset, cols

# ── Pinyin ──────────────────────────────────────────────────────────────────
# Os quatro tons combinantes. O trema do "ü" (U+0308) NÃO entra aqui: ele faz
# parte da letra, e removê-lo transformaria lǚ em lu.
_TONES = "̄́̌̀"

# Iniciais, as de duas letras primeiro — senão "zh" casaria como "z" + "h".
_INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g",
             "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")

# Pares que o ouvido confunde. Servem para MUTAR uma sílaba mantendo-a
# plausível: trocar por algo aleatório não engana ninguém.
_NEIGHBOR_INITIAL = {
    "n": "l", "l": "n", "zh": "z", "z": "zh", "ch": "c", "c": "ch",
    "sh": "s", "s": "sh", "j": "q", "q": "j", "x": "j", "b": "p", "p": "b",
    "d": "t", "t": "d", "g": "k", "k": "g", "f": "h", "h": "f",
    "m": "n", "r": "l", "y": "w", "w": "y", "": "y",
}
# Finais do mandarim. Fecham a estrutura da sílaba junto com _INITIALS, e é essa
# estrutura que separa pinyin de qualquer outra sequência de letras — a word-api
# tem entradas com inglês no campo pinyin ("暗示" → "suggest") e com sílabas
# grudadas ("孩子們" → "háizi men"), que passariam por um teste só de alfabeto.
# "ue" está aqui porque depois de j/q/x/y o "ü" se escreve "u" (jué, xué, yuè).
_FINALS = frozenset((
    "a", "o", "e", "ai", "ei", "ao", "ou", "an", "en", "ang", "eng", "ong", "er",
    "i", "ia", "ie", "iao", "iu", "ian", "in", "iang", "ing", "iong",
    "u", "ua", "uo", "uai", "ui", "uan", "un", "uang", "ueng",
    "v", "ve", "ue", "van", "vn",
    "iou", "uei", "uen", "io",          # grafias antigas que aparecem nos bases
))

_NEIGHBOR_FINAL = {
    "an": "ang", "ang": "an", "en": "eng", "eng": "en", "in": "ing",
    "ing": "in", "ian": "iang", "iang": "ian", "uan": "uang", "uang": "uan",
    "ai": "ei", "ei": "ai", "ao": "ou", "ou": "ao", "a": "ia", "ia": "a",
    "o": "uo", "uo": "o", "e": "ei", "i": "ie", "ie": "i", "u": "ou",
    "ong": "eng", "uai": "ui", "ui": "uai", "un": "ong", "ua": "uo",
    "ve": "ue", "er": "e", "iu": "iao", "iao": "iu",
}


def strip_tone(syl: str) -> tuple:
    """``("jiǎn")`` → ``("jian", "\\u030c")``. Devolve (sílaba sem tom, marca)."""
    mark = ""
    kept = []
    for ch in unicodedata.normalize("NFD", syl):
        if ch in _TONES:
            if not mark:
                mark = ch
        else:
            kept.append(ch)
    return unicodedata.normalize("NFC", "".join(kept)), mark


def apply_tone(syl: str, mark: str) -> str:
    """Recoloca a marca de tom na vogal certa (regra do pinyin: a > o > e > última)."""
    if not mark:
        return syl
    chars = list(unicodedata.normalize("NFD", syl))
    vowels = [i for i, ch in enumerate(chars) if ch in "aoeiu"]
    if not vowels:
        return syl
    pos = vowels[-1]
    for want in "aoe":
        hit = [i for i in vowels if chars[i] == want]
        if hit:
            pos = hit[0]
            break
    # Depois da vogal pode vir o trema do "ü"; o tom entra DEPOIS dele, senão a
    # sequência não compõe (ǚ é u + trema + caron, nessa ordem).
    ins = pos + 1
    while ins < len(chars) and unicodedata.combining(chars[ins]):
        ins += 1
    chars.insert(ins, mark)
    return unicodedata.normalize("NFC", "".join(chars))


def ascii_pinyin(pinyin: str) -> str:
    """Pinyin reduzido a letras ASCII, sem tom e sem espaços (``ü`` vira ``v``).

    É a forma canônica usada nas comparações: é ela que define "mesma grafia".
    """
    plain, _ = strip_tone(pinyin)
    plain = plain.replace("ü", "v").replace("Ü", "v")
    return "".join(c for c in unicodedata.normalize("NFD", plain)
                   if "a" <= c.lower() <= "z").lower()


def split_syllable(plain: str) -> tuple:
    """``"jian"`` → ``("j", "ian")``. Espera a sílaba já em ASCII sem tom."""
    for ini in _INITIALS:
        if plain.startswith(ini) and len(plain) > len(ini):
            return ini, plain[len(ini):]
    return "", plain


def mutate_syllable(syl: str, rng: random.Random, valid: set = None) -> list:
    """Variantes da sílaba com as LETRAS trocadas, preservando o tom.

    ``valid`` é o conjunto de sílabas (ASCII, sem tom) que existem de fato; as
    tabelas de vizinhos são cegas à fonotática do mandarim e sozinhas produzem
    coisas como ``fao`` ou ``yie``, que um leitor de pinyin descarta de cara.
    Com o filtro ligado a lista pode sair vazia — quem chama tenta outra sílaba,
    e só relaxa o filtro depois de esgotar todas.
    """
    plain, mark = strip_tone(syl)
    key = ascii_pinyin(plain)
    ini, fin = split_syllable(key)
    out = []
    if fin in _NEIGHBOR_FINAL:
        out.append(ini + _NEIGHBOR_FINAL[fin])
    if ini in _NEIGHBOR_INITIAL:
        out.append(_NEIGHBOR_INITIAL[ini] + fin)
    if ini and not out:
        out.append(fin)                      # último recurso: cai a inicial

    out = [v for v in out if v != key]
    if valid is not None:
        out = [v for v in out if v in valid]
    rng.shuffle(out)
    # De volta para "ü": as tabelas trabalham em ASCII, mas o botão mostra
    # pinyin de verdade — e "lv" não é pinyin.
    return [apply_tone(v.replace("v", "ü"), mark) for v in out]


def is_pinyin_syllable(key: str) -> bool:
    """True se ``key`` (ASCII, sem tom) tem estrutura de sílaba do mandarim."""
    if not key:
        return False
    return split_syllable(key)[1] in _FINALS


def is_clean_pinyin(pinyin: str) -> bool:
    """True se ``pinyin`` é uma sequência de sílabas separadas por espaço.

    Não basta olhar o alfabeto. Os bases trazem entradas malformadas
    (``shén……shén me``) e a word-api chega a guardar a TRADUÇÃO no campo pinyin
    (``暗示`` → ``suggest``) ou o pinyin sem os espaços (``孩子們`` →
    ``háizi men``). Como o rótulo do botão é o pinyin cru, qualquer uma dessas
    vira uma opção obviamente falsa e entrega o jogo — daí a checagem ser
    estrutural, sílaba por sílaba.
    """
    plain, _ = strip_tone(pinyin)
    if not plain.strip():
        return False
    for syl in plain.split(" "):
        if not syl:
            return False                      # espaço duplo
        for ch in syl:
            if not (("a" <= ch.lower() <= "z") or ch in "üÜ"):
                return False
        if not is_pinyin_syllable(ascii_pinyin(syl)):
            return False
    return True


def clean_chinese_only(text: str) -> str:
    """Só ideogramas, igual ao ``collection_builder.clean_chinese_only``."""
    return _CJK_ONLY_RE.sub("", text or "")


def parse_pairs(cell: str) -> list:
    """Coluna 4 do base → lista de ``(palavra, pinyin, tradução)``.

    Exigir o ``): …"`` inteiro, e não só o ``(pinyin)``, é o que descarta as
    ~460 entradas malformadas do warehouse: pontuação catalogada como palavra
    (``"？ (?: ponto de interrogação)"``, onde o ``?`` vinha como o termo),
    parêntese que não fecha (``"起來 (qǐ lái: indica início de ação)"``) e
    anotação no meio do nome (``"出  (repetição) (chū): sair"``).
    """
    return [(w, p.strip(), t.strip()) for w, p, t in _PAIR_RE.findall(cell or "")]


# ── Léxico ──────────────────────────────────────────────────────────────────
class Lexicon:
    """``palavra -> pinyin``, com segmentação e geração de distratores."""

    def __init__(self, words: dict):
        self.words = words
        self.maxlen = max((len(w) for w in words), default=0)
        # Índice por nº de sílabas: o distrator sempre mantém o tamanho da
        # palavra certa, então só candidatos com o mesmo nº interessam.
        self._by_n = {}
        # Todas as sílabas atestadas, para a síntese não inventar fonotática.
        self.syllables = set()
        for word, pinyin in words.items():
            syls = pinyin.split()
            keys = tuple(ascii_pinyin(s) for s in syls)
            # Um hanzi, uma sílaba: quando não bate, o pinyin veio sem os
            # espaços (安妮塔 → "ānǐtǎ") ou é erhua/latim. A palavra continua
            # servindo para SEGMENTAR, mas fica fora do pool de distratores —
            # como distrator ela viraria um rótulo comprido e obviamente falso.
            if len(clean_chinese_only(word)) != len(syls):
                continue
            self.syllables.update(k for k in keys if k)
            if not 1 <= len(syls) <= 4:
                continue
            self._by_n.setdefault(len(syls), []).append((word, pinyin, keys))

    def __bool__(self) -> bool:
        return bool(self.words)

    def __len__(self) -> int:
        return len(self.words)

    # ── Carga ───────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, warehouse: Path = None) -> "Lexicon":
        """word-api primeiro; o warehouse preenche o que faltar.

        A API é a fonte canônica, mas ``word_vocab`` falha aberta (devolve vazio
        se ela estiver fora do ar) — e sem léxico não há jogo 2 nenhum. Varrer os
        bases custa ~1s e cobre o mesmo vocabulário, então vale como rede.
        """
        words = {}
        for word, (pinyin, _tr) in (word_vocab.vocabulary() or {}).items():
            word = (word or "").strip()
            pinyin = (pinyin or "").strip()
            # Chave só de ideogramas: a frase chega aqui passada por
            # clean_chinese_only, então qualquer chave com latim ou pontuação
            # jamais casaria. A word-api guarda notas dentro do campo da
            # palavra ("的  (neste caso, usado para…)"), e sem este filtro elas
            # entram como termos de 50 caracteres — peso morto que ainda por
            # cima faz a segmentação tentar fatias desse tamanho.
            if word and word == clean_chinese_only(word) and is_clean_pinyin(pinyin):
                words[word] = pinyin

        for word, pinyin in cls._scan_warehouse(warehouse).items():
            words.setdefault(word, pinyin)

        return cls(words)

    @staticmethod
    def _scan_warehouse(warehouse: Path = None) -> dict:
        """``palavra -> pinyin mais frequente`` agregando todos os ``*_base.txt``."""
        tally = {}
        for _asset, cols in iter_base_rows(warehouse):
            for word, pinyin, _tr in parse_pairs(cols[PAIRS_COL]):
                word = clean_chinese_only(word)   # já garante a chave CJK
                if not word or not is_clean_pinyin(pinyin):
                    continue
                counts = tally.setdefault(word, {})
                counts[pinyin] = counts.get(pinyin, 0) + 1

        return {w: max(c.items(), key=lambda kv: kv[1])[0] for w, c in tally.items()}

    # ── Segmentação ─────────────────────────────────────────────────────────
    def segment(self, sentence: str) -> list:
        """Maior prefixo guloso. Caractere sem entrada vira token de 1 char."""
        out = []
        i = 0
        while i < len(sentence):
            for size in range(min(self.maxlen, len(sentence) - i), 0, -1):
                if sentence[i:i + size] in self.words:
                    out.append(sentence[i:i + size])
                    i += size
                    break
            else:
                out.append(sentence[i])
                i += 1
        return out

    # ── Distratores ─────────────────────────────────────────────────────────
    def distractors(self, word: str, rng: random.Random, banned: set,
                    k: int = 2) -> list:
        """Até ``k`` rótulos de pinyin parecidos, com as LETRAS alteradas.

        ``banned`` são as grafias SEM TOM já faladas para a frase — as das
        palavras certas e as dos distratores já escolhidos. É modificado no
        lugar.

        Bloquear por grafia sem tom, e não pelo rótulo cru, é o que faz a regra
        valer no escopo da frase toda: ``jiān zhí`` cai como distrator de
        ``jiǎn zhí``, e ``shǐ`` também cai se ``shí`` estiver em QUALQUER outra
        palavra da frase — senão sobrariam dois botões diferindo só no acento,
        que é exatamente o que não se quer pedir para o jogador distinguir.
        """
        pinyin = self.words.get(word)
        if not pinyin:
            return []
        syls = pinyin.split()
        keys = tuple(ascii_pinyin(s) for s in syls)
        out = []

        def take(label: str) -> None:
            label = label.lower()
            key = ascii_pinyin(label)
            if key in banned:
                return
            banned.add(key)
            out.append(label)

        # 1) Palavras reais: exatamente UMA sílaba difere, e ela ainda
        #    compartilha inicial ou final — senão o distrator fica longe demais
        #    ("de" contra "è" não confunde ninguém).
        pool = []
        for other, other_pinyin, other_keys in self._by_n.get(len(syls), ()):
            if other == word or other_keys == keys:
                continue
            diff = [i for i in range(len(keys)) if keys[i] != other_keys[i]]
            if len(diff) != 1:
                continue
            mine = split_syllable(keys[diff[0]])
            theirs = split_syllable(other_keys[diff[0]])
            if mine[0] != theirs[0] and mine[1] != theirs[1]:
                continue
            pool.append(other_pinyin)
        rng.shuffle(pool)
        for candidate in pool:
            if len(out) >= k:
                break
            take(candidate)

        # 2) Síntese: muta uma sílaba do próprio pinyin correto. O botão só
        #    mostra pinyin, então não precisa ser palavra real para enganar.
        # Duas passadas: primeiro só sílabas atestadas, em todas as posições;
        # só depois de esgotá-las é que vale um rótulo foneticamente estranho —
        # melhor isso que uma opção a menos.
        order = list(range(len(syls)))
        rng.shuffle(order)
        for valid in (self.syllables, None):
            if len(out) >= k:
                break
            for i in order:
                for variant in mutate_syllable(syls[i], rng, valid):
                    if len(out) >= k:
                        break
                    take(" ".join(syls[:i] + [variant] + syls[i + 1:]))
                if len(out) >= k:
                    break

        return out

    # ── Jogo 2 ──────────────────────────────────────────────────────────────
    def word_game(self, sentence: str, rng: random.Random):
        """``{"words": [...], "opts": [...]}`` ou ``None`` se a frase não servir.

        ``opts`` já vai embaralhado, com ``w`` só nas opções certas — o
        distrator não tem hanzi nenhum para revelar.

        Uma opção certa por OCORRÊNCIA (cada posição precisa do seu botão, e
        botões iguais são intercambiáveis), mas os 2 distratores saem por
        palavra DISTINTA: numa frase como 這放開放開放開… as três ocorrências
        renderiam seis variações quase idênticas de 放開, afogando o grid.
        """
        words = self.segment(sentence)
        if len(words) < 2:
            return None
        labels = [self.words.get(w, "").lower() for w in words]
        if not all(labels):
            return None                       # sem pinyin não dá para rotular

        banned = {ascii_pinyin(label) for label in labels}
        opts = [{"p": label, "w": word} for word, label in zip(words, labels)]
        for word in dict.fromkeys(words):     # distintas, na ordem da frase
            for wrong in self.distractors(word, rng, banned):
                opts.append({"p": wrong})

        rng.shuffle(opts)
        return {"words": words, "opts": opts}


# ── Jogo 3 ──────────────────────────────────────────────────────────────────
def char_game(sentence: str, rng: random.Random):
    """Caracteres da frase, embaralhados. ``None`` se não houver o que montar."""
    if len(sentence) < 2:
        return None
    chars = list(sentence)
    rng.shuffle(chars)
    # Um embaralhamento que devolve a ordem original entrega o jogo de graça.
    if len(set(chars)) > 1:
        for _ in range(8):
            if chars != list(sentence):
                break
            rng.shuffle(chars)
    return chars


# ── Jogo 6 ──────────────────────────────────────────────────────────────────
MASK = "*"


class Masks:
    """``frase limpa -> palavra a ocultar``, agregando todos os bases.

    No jogo 6 a imagem mostra só a tradução e o campo traz a frase em mandarim
    com uma palavra trocada por ``*``. Qual palavra não sai do léxico dos jogos
    2/3/5, e sim dos pares da PRÓPRIA legenda: o léxico tem pinyin e tradução
    para ``我`` também, então ele esconderia ``我`` em vez de ``失去``. A coluna 4
    lista só o que aquela legenda se propôs a ensinar, que é exatamente o
    critério de "palavra que vale a pena esconder".

    A chave é ``clean_chinese_only(zht)``, que é o que o ``collection_builder``
    grava em ``sentence`` no ``index.json`` — então a busca é por igualdade, sem
    depender do nome do arquivo nem do número da linha (que um base regravado
    ou uma coleção de períodos deslocariam).

    As palavras DOMINADAS ficam de fora. O base preserva pinyin e tradução de
    tudo, inclusive do que já se sabe — em ``因為她失去了兒子`` os cinco pares
    estão lá, e sem o filtro o escolhido seria ``因為``, que é a primeira e é
    dominada. Esconder uma palavra que já se sabe não ensina nada: quem importa
    ali é ``失去``, a única que ainda tem o que ensinar. É o mesmo critério do
    ``word_vocab.count_learnable``.

    O preço são 8 pontos de cobertura (89,5% → 81,5%), quase todos em frases
    onde TODA palavra ensinada já é dominada — e essas não tinham mesmo o que
    perguntar. O outro preço é a word-api: com ela fora do ar o filtro não
    aplica nada e volta-se a esconder palavra sabida. Falha aberta, como o resto
    do repo, mas o ``make_bundle`` avisa em vez de deixar passar calado.
    """

    def __init__(self, choices: dict, mastered: frozenset = frozenset()):
        self.choices = choices
        # Quantas dominadas o filtro chegou a conhecer. Zero, com a word-api no
        # ar e alguma palavra marcada, significa que ela não respondeu.
        self.mastered = mastered

    def __bool__(self) -> bool:
        return bool(self.choices)

    def __len__(self) -> int:
        return len(self.choices)

    @classmethod
    def load(cls, warehouse: Path = None, mastered: frozenset = None) -> "Masks":
        """Varre ``*_base.txt`` e ``*_periods.txt`` escolhendo uma palavra por frase.

        ``mastered`` default é ``word_vocab.mastered_words()``; passar um
        conjunto explícito serve para testar sem depender da API.
        """
        if mastered is None:
            mastered = word_vocab.mastered_words()
        tally = {}
        for _asset, cols in iter_base_rows(warehouse, include_periods=True):
            sentence = clean_chinese_only(cols[ZHT_COL])
            if len(sentence) < 2:
                continue                      # um caractere só: nada a esconder
            best = None
            for word, pinyin, translation in parse_pairs(cols[PAIRS_COL]):
                if not (pinyin and translation):
                    continue
                # Dominada não ensina nada escondida: em 因為她失去了兒子 os
                # cinco pares valem, mas quatro já se sabem e só 失去 pergunta
                # alguma coisa.
                if word in mastered:
                    continue
                at = sentence.find(word)
                # A palavra do tamanho da frase deixaria o campo com um ``*`` só,
                # e produzir a frase inteira sem nenhum mandarim na tela é mais
                # duro que qualquer outro jogo. Fora tokens que a limpeza do
                # `sentence` comeu (pontuação, latim): não há o que mascarar.
                if at < 0 or len(word) >= len(sentence):
                    continue
                if best is None or at < best[0]:
                    best = (at, word)
            if best:
                counts = tally.setdefault(sentence, {})
                counts[best[1]] = counts.get(best[1], 0) + 1

        # 0,5% das frases aparecem em duas linhas com escolhas diferentes. A mais
        # frequente vence, como no `_scan_warehouse`: a varredura é ordenada, e
        # com isso reempacotar a mesma coleção devolve o mesmo bundle.
        return cls({s: max(c.items(), key=lambda kv: kv[1])[0] for s, c in tally.items()},
                   mastered)

    def mask(self, sentence: str):
        """``("我不想*你，我愛你。", "失去")`` ou ``None`` se a frase não servir.

        Um ``*`` só para a palavra inteira, mesmo com 2+ caracteres: o número de
        asteriscos entregaria o tamanho da resposta.
        """
        word = self.choices.get(sentence)
        if not word:
            return None
        at = sentence.find(word)
        if at < 0:
            return None
        return sentence[:at] + MASK + sentence[at + len(word):], word
