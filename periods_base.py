#!/usr/bin/env python3
"""Reagrupa um ``*_base.txt`` por períodos completos → ``*_periods.txt``.

O base nasce com a segmentação da LEGENDA do vídeo: os cortes são de exibição
(cabe na tela, dura 2s), não de sentido. Quase todo período acaba partido no
meio, e a coleção herda o corte — o cartão mostra "…PROMETO QUE QUANDO A SUA
NASCER, EU FICO COM ELA O" e o resto some no cartão seguinte.

Este módulo gera um SEGUNDO arquivo, com o mesmo contrato de colunas do base,
onde cada linha é um período inteiro: as linhas consecutivas do base são
agrupadas até a frase terminar, e o grupo vira uma linha só (tempo do começo da
primeira ao fim da última, textos concatenados, arrays de palavras unidos).

O base NÃO é tocado — o ``*_periods.txt`` é um arquivo novo ao lado dele.

Onde o corte acontece
---------------------
Um grupo fecha quando:

* a frase termina (ver ``--criterio``);
* a próxima linha abre com etiqueta de locutor/efeito (``[JOYCE]``, ``[RISO]``)
  — troca de quem fala sempre começa período novo, mesmo sem pontuação;
* a linha é SÓ uma etiqueta (``[SILÊNCIO]``) — vale por si;
* algum limite de segurança estoura (``--max-linhas``/``--max-hanzi``/``--max-dur``).
  Sem eles, uma sequência sem pontuação nenhuma (música, vocalize) engoliria o
  episódio inteiro num grupo só.

Por que ``--criterio ambos`` é o padrão
---------------------------------------
As duas colunas de texto erram, mas erram em direções opostas:

* o ZHT é a fonte dos tempos e é segmentado mais fino que o PT, então o
  tradutor às vezes fecha um ``？`` no meio do período, no ponto do corte;
* o PT vem de uma legenda de cues mais longos, então a MESMA frase PT se repete
  em fragmentos ZHT consecutivos — cada linha parece terminada, e sozinho ele
  nunca juntaria nada.

Exigir os dois (``ambos``) faz um cobrir o buraco do outro. ``zht`` e ``pt``
existem para comparar o resultado.

Uso:
    python3 periods_base.py amor100              # warehouse/amor100_periods.txt
    python3 periods_base.py --all                # todo o warehouse
    python3 periods_base.py amor100 --dry-run    # só mostra como ficaria
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence

REPO = Path(__file__).resolve().parent
WAREHOUSE = REPO / "warehouse"
TEXT_WAREHOUSE = WAREHOUSE / "text"

BASE_SUFFIX = "_base.txt"
PERIODS_SUFFIX = "_periods.txt"

# Pontuação que fecha período. O usuário pediu ".", "!" e "..." — "..." já entra
# por terminar em "."; "?" e as formas de largura cheia entram porque são a
# mesma pontuação escrita no outro alfabeto (o ZHT usa 。！？, o PT usa .!?).
FINAL_PUNCT = tuple("。！？!?.…⋯")

# Aspas, parênteses e ♪ vêm DEPOIS da pontuação e não anulam o fim da frase:
# 'ELE DISSE "TCHAU."' termina tanto quanto 'ELE DISSE TCHAU.'
TRAILING_DECOR = ' 　"\'”’»）)】］]♪~'

# Etiqueta de locutor ou de efeito no COMEÇO da linha: [JOYCE], [RISO], [MÚSICA].
_TAG_AT_START = re.compile(r'^\s*[\[【][^\]】]{1,40}[\]】]')
# Linha que é só etiqueta (uma ou mais), sem fala nenhuma.
_ONLY_TAGS = re.compile(r'^\s*(?:[\[【][^\]】]{1,40}[\]】]\s*)+$')

# Itens do array de pares, do jeito que todo o repo os lê (processor.py escreve
# esse array com f-string, não com json.dumps — daí o regex e não json.loads).
_ARRAY_ITEM = re.compile(r'"([^"]*)"')

# Só ideogramas CJK — a contagem que decide se o período ainda cabe na tela.
# Escapes explícitos de propósito (mesmos ranges do collection_builder):
# escrever o range com literais normaliza o ideograma de compatibilidade
# U+F900 no comum U+8C48 e quebra o intervalo em silêncio.
_HANZI = re.compile('[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')

# Texto que o gerador do base escreve quando não houve tradução/pares.
_EMPTY_VALUES = {"", "N/A", "n/a", "[]"}

CRITERIA = ("auto", "ambos", "zht", "pt")

# Abaixo desta fração de linhas ZHT terminadas em pontuação, a coluna chinesa
# daquele base simplesmente não tem pontuação (acontece nos bases vindos de
# texto corrido). Exigir "ambos" ali nunca fecharia um período pelo sentido —
# só pelo limite de segurança —, então o "auto" passa a decidir pelo PT.
AUTO_ZHT_PUNCT_MIN = 0.15

# Limites de segurança. O de hanzi é o mais apertado de propósito: o render da
# legenda (``split_chinese_into_lines``) quebra a frase em no MÁXIMO 2 linhas e
# encolhe as palavras para caber — passando de ~40 ideogramas o cartão vira uma
# fileira ilegível, e um período gigante não serve para estudar mesmo.
DEFAULT_MAX_LINES = 6
DEFAULT_MAX_HANZI = 40
DEFAULT_MAX_SECONDS = 30.0


# ── Leitura do base ─────────────────────────────────────────────────────────────
@dataclass
class Row:
    """Uma linha do base com as colunas já separadas."""
    line_num: int
    index: str
    begin: str
    end: str
    zht: str
    pairs: str
    pt: str
    nota: Optional[str]
    begin_s: float
    end_s: float


def _seconds(value: str) -> float:
    return float(value.strip().rstrip("s"))


def read_rows(base_path: Path) -> Iterator[Row]:
    """Linhas válidas do base (as de formato quebrado são puladas, como nas buscas)."""
    with open(base_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            cols = line.rstrip("\r\n").split("\t")
            if len(cols) < 6:
                continue
            try:
                begin_s = _seconds(cols[1])
                end_s = _seconds(cols[2])
            except ValueError:
                continue
            nota = cols[6].strip() if len(cols) > 6 and cols[6].strip() else None
            yield Row(line_num=line_num, index=cols[0], begin=cols[1], end=cols[2],
                      zht=cols[3], pairs=cols[4], pt=cols[5], nota=nota,
                      begin_s=begin_s, end_s=end_s)


# ── Fim de período ──────────────────────────────────────────────────────────────
def _strip_decor(text: str) -> str:
    return (text or "").strip().rstrip(TRAILING_DECOR)


def _is_blank(text: str) -> bool:
    return _strip_decor(text).strip() in _EMPTY_VALUES


def ends_sentence(text: str) -> bool:
    """True se ``text`` termina em pontuação final (ignorando aspas/♪ no fim)."""
    stripped = _strip_decor(text)
    return bool(stripped) and stripped.endswith(FINAL_PUNCT)


def opens_with_tag(text: str) -> bool:
    """True se a linha abre com ``[LOCUTOR]``/``[EFEITO]`` — começo de fala nova."""
    return bool(_TAG_AT_START.match(text or ""))


def is_only_tag(text: str) -> bool:
    """True se a linha é só etiqueta (``[SILÊNCIO]``), sem fala."""
    return bool(_ONLY_TAGS.match(text or ""))


def resolve_criterio(rows: Sequence["Row"], criterio: str = "auto") -> str:
    """Resolve ``auto`` olhando para o arquivo; devolve os demais como vieram.

    Um base cujo ZHT não tem pontuação nenhuma (texto corrido) precisa ser
    cortado pelo PT — ver ``AUTO_ZHT_PUNCT_MIN``.
    """
    if criterio != "auto":
        return criterio
    with_text = [r for r in rows if not _is_blank(r.zht)]
    if not with_text:
        return "pt"
    ratio = sum(1 for r in with_text if ends_sentence(r.zht)) / len(with_text)
    return "ambos" if ratio >= AUTO_ZHT_PUNCT_MIN else "pt"


def _terminated(zht: str, pt: str, criterio: str) -> bool:
    """Decide se o acumulado até aqui já é um período fechado.

    Coluna vazia (ou "N/A") não segura o grupo aberto: sem texto não há
    evidência de continuação, e quem decide passa a ser a outra coluna.
    """
    zht_done = _is_blank(zht) or ends_sentence(zht)
    pt_done = _is_blank(pt) or ends_sentence(pt)
    if criterio == "zht":
        return zht_done
    if criterio == "pt":
        return pt_done
    return zht_done and pt_done


# ── Agrupamento ─────────────────────────────────────────────────────────────────
@dataclass
class Group:
    """Um período: as linhas do base que ele cobre e por que ele fechou."""
    rows: List[Row] = field(default_factory=list)
    reason: str = ""

    @property
    def hanzi(self) -> int:
        return sum(len(_HANZI.findall(r.zht)) for r in self.rows)

    @property
    def duration(self) -> float:
        return self.rows[-1].end_s - self.rows[0].begin_s


def group_rows(rows: Iterable[Row], criterio: str = "auto",
               max_lines: int = DEFAULT_MAX_LINES,
               max_hanzi: int = DEFAULT_MAX_HANZI,
               max_seconds: float = DEFAULT_MAX_SECONDS) -> List[Group]:
    """Junta as linhas do base em períodos. Preserva a ordem e não descarta nada."""
    rows = list(rows)
    criterio = resolve_criterio(rows, criterio)
    groups: List[Group] = []
    cur = Group()

    def flush(reason: str) -> None:
        nonlocal cur
        if cur.rows:
            cur.reason = reason
            groups.append(cur)
            cur = Group()

    for row in rows:
        # Fala nova começa grupo novo mesmo que a anterior tenha ficado sem ponto.
        if cur.rows and opens_with_tag(row.pt):
            flush("locutor")

        cur.rows.append(row)

        if is_only_tag(row.pt):
            flush("etiqueta")
            continue

        if _terminated(row.zht, row.pt, criterio):
            flush("pontuacao")
            continue

        if (len(cur.rows) >= max_lines or cur.hanzi >= max_hanzi
                or cur.duration >= max_seconds):
            flush("limite")

    flush("fim")
    return groups


# ── Escrita do arquivo de períodos ──────────────────────────────────────────────
def _merge_pairs(rows: Sequence[Row]) -> str:
    """Une os arrays de pares das linhas, sem repetir palavra.

    Os itens são copiados VERBATIM do base (mesma citação, mesmo espaçamento) —
    remontar o par a partir do parse arriscaria mudar o formato que
    ``parse_pinyin_translations`` espera.
    """
    items: List[str] = []
    seen = set()
    for row in rows:
        for item in _ARRAY_ITEM.findall(row.pairs or ""):
            key = item.split(" ", 1)[0].split("(", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return "[" + ", ".join(f'"{i}"' for i in items) + "]"


def _merge_pt(rows: Sequence[Row]) -> str:
    """Concatena as traduções, sem repetir a mesma frase duas vezes seguidas.

    O gerador do base repete a frase PT inteira em cada fragmento ZHT que ela
    cobre (ver ``generate_zht_base_file``); juntar sem filtrar duplicaria o
    texto dentro do próprio período.
    """
    parts: List[str] = []
    for row in rows:
        text = (row.pt or "").strip()
        if not text or text in _EMPTY_VALUES:
            continue
        if parts and parts[-1] == text:
            continue
        parts.append(text)
    return " ".join(parts)


def _merge_nota(rows: Sequence[Row]) -> Optional[str]:
    """Nota do período: a maior das linhas que o formam (None se nenhuma tinha)."""
    notas = []
    for row in rows:
        if row.nota is None:
            continue
        try:
            notas.append(int(row.nota))
        except ValueError:
            continue
    return str(max(notas)) if notas else None


def _clean_field(text: str) -> str:
    """Nenhum tab nem quebra de linha pode entrar num campo — eles são o formato."""
    return (text or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def group_to_line(group: Group) -> str:
    """Serializa um período no mesmo contrato de colunas do base.

    A coluna 0 recebe o índice da PRIMEIRA legenda do grupo (e não uma numeração
    nova): é o que permite achar no base de onde o período veio. A nota continua
    sendo uma 7ª coluna só nas linhas que têm nota.
    """
    rows = group.rows
    cols = [
        _clean_field(rows[0].index),
        _clean_field(rows[0].begin),
        _clean_field(rows[-1].end),
        _clean_field("".join(r.zht for r in rows)),
        _clean_field(_merge_pairs(rows)),
        _clean_field(_merge_pt(rows)),
    ]
    nota = _merge_nota(rows)
    if nota is not None:
        cols.append(nota)
    return "\t".join(cols)


def periods_path_for(base_path: Path) -> Path:
    """``…/amor100_base.txt`` → ``…/amor100_periods.txt``."""
    name = base_path.name
    if name.endswith(BASE_SUFFIX):
        name = name[: -len(BASE_SUFFIX)] + PERIODS_SUFFIX
    else:
        name = base_path.stem + PERIODS_SUFFIX
    return base_path.with_name(name)


def build_groups(base_path: Path, criterio: str = "auto",
                 max_lines: int = DEFAULT_MAX_LINES,
                 max_hanzi: int = DEFAULT_MAX_HANZI,
                 max_seconds: float = DEFAULT_MAX_SECONDS) -> List[Group]:
    """Períodos de um base, sem escrever nada."""
    return build_groups_with_criterio(base_path, criterio=criterio, max_lines=max_lines,
                                      max_hanzi=max_hanzi, max_seconds=max_seconds)[0]


def build_groups_with_criterio(base_path: Path, criterio: str = "auto",
                               max_lines: int = DEFAULT_MAX_LINES,
                               max_hanzi: int = DEFAULT_MAX_HANZI,
                               max_seconds: float = DEFAULT_MAX_SECONDS):
    """Como ``build_groups``, mas diz também qual critério o ``auto`` escolheu."""
    rows = list(read_rows(base_path))
    resolved = resolve_criterio(rows, criterio)
    groups = group_rows(rows, criterio=resolved, max_lines=max_lines,
                        max_hanzi=max_hanzi, max_seconds=max_seconds)
    return groups, resolved


def generate(base_path: Path, out_path: Optional[Path] = None,
             criterio: str = "auto", max_lines: int = DEFAULT_MAX_LINES,
             max_hanzi: int = DEFAULT_MAX_HANZI,
             max_seconds: float = DEFAULT_MAX_SECONDS,
             force: bool = True) -> dict:
    """Gera o ``*_periods.txt`` do base. Devolve estatísticas do agrupamento.

    A escrita é atômica (``os.replace``) e o nome temporário não casa com o
    ``*_base.txt`` das buscas — uma varredura concorrente nunca vê meio arquivo.

    ``force=False`` mantém um arquivo já existente (devolve ``{"skipped": True}``):
    é como o arquivamento evita refazer o agrupamento de quem já tem frames
    gerados a partir dele.
    """
    if criterio not in CRITERIA:
        raise ValueError(f"criterio inválido: {criterio!r} (esperado um de {CRITERIA})")
    base_path = Path(base_path)
    if not base_path.exists():
        raise FileNotFoundError(f"base não encontrado: {base_path}")

    out_path = Path(out_path) if out_path else periods_path_for(base_path)
    if out_path.exists() and not force:
        return {"skipped": True, "path": out_path}

    groups, resolved = build_groups_with_criterio(
        base_path, criterio=criterio, max_lines=max_lines,
        max_hanzi=max_hanzi, max_seconds=max_seconds)

    tmp = out_path.with_name(out_path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for group in groups:
            f.write(group_to_line(group) + "\n")
    os.replace(tmp, out_path)

    return {"skipped": False, "path": out_path, "criterio": resolved, **stats(groups)}


def stats(groups: Sequence[Group]) -> dict:
    """Resumo do agrupamento — é o que diz se o critério está se comportando."""
    by_reason: dict = {}
    for g in groups:
        by_reason[g.reason] = by_reason.get(g.reason, 0) + 1
    source_lines = sum(len(g.rows) for g in groups)
    merged = sum(1 for g in groups if len(g.rows) > 1)
    return {
        "groups": len(groups),
        "source_lines": source_lines,
        "merged": merged,
        "max_rows": max((len(g.rows) for g in groups), default=0),
        "max_hanzi": max((g.hanzi for g in groups), default=0),
        "by_reason": by_reason,
    }


def format_stats(name: str, st: dict) -> str:
    src, grp = st["source_lines"], st["groups"]
    ratio = (src / grp) if grp else 0
    reasons = ", ".join(f"{k}={v}" for k, v in sorted(st["by_reason"].items()))
    crit = f" ({st['criterio']})" if st.get("criterio") else ""
    return (f"{name}{crit}: {src} linha(s) → {grp} período(s) "
            f"({ratio:.2f} linhas/período, {st['merged']} agrupado(s), "
            f"máx {st['max_rows']} linhas / {st['max_hanzi']} hanzi) [{reasons}]")


# ── CLI ─────────────────────────────────────────────────────────────────────────
def _bases_for(args) -> List[Path]:
    root = TEXT_WAREHOUSE if args.text else WAREHOUSE
    if args.all:
        return sorted(root.glob(f"*{BASE_SUFFIX}"))
    out = []
    for asset in args.assets:
        cand = Path(asset)
        if not cand.exists():
            cand = root / f"{asset}{BASE_SUFFIX}"
        if not cand.exists():
            print(f"❌ base não encontrado para '{asset}' ({cand})", file=sys.stderr)
            continue
        out.append(cand)
    return out


def _print_sample(base_path: Path, groups: Sequence[Group], n: int) -> None:
    print(f"\n── amostra de {min(n, len(groups))} período(s) de {base_path.name} ──")
    for g in groups[:n]:
        span = f"linhas {g.rows[0].line_num}-{g.rows[-1].line_num}"
        print(f"\n  [{span} · {g.reason} · {g.duration:.1f}s]")
        print(f"  ZHT: {''.join(r.zht for r in g.rows)}")
        print(f"  PT : {_merge_pt(g.rows)}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Gera o *_periods.txt (base reagrupado por períodos completos).")
    p.add_argument("assets", nargs="*", help="nome do asset (amor100) ou caminho do base")
    p.add_argument("--all", action="store_true", help="todos os bases do warehouse")
    p.add_argument("--text", action="store_true", help="usar warehouse/text/")
    p.add_argument("--criterio", choices=CRITERIA, default="auto",
                   help="qual coluna precisa terminar em pontuação final "
                        "(padrão: auto — 'ambos', ou 'pt' se o ZHT do arquivo não for pontuado)")
    p.add_argument("--max-linhas", type=int, default=DEFAULT_MAX_LINES)
    p.add_argument("--max-hanzi", type=int, default=DEFAULT_MAX_HANZI)
    p.add_argument("--max-dur", type=float, default=DEFAULT_MAX_SECONDS)
    p.add_argument("--dry-run", action="store_true", help="não escreve nada")
    p.add_argument("--sample", type=int, default=0, help="mostra N períodos gerados")
    p.add_argument("--skip-existing", action="store_true",
                   help="não refaz quem já tem *_periods.txt")
    args = p.parse_args(argv)

    bases = _bases_for(args)
    if not bases:
        p.error("nada a fazer: informe um asset ou use --all")

    total = {"groups": 0, "source_lines": 0}
    for base_path in bases:
        groups, resolved = build_groups_with_criterio(
            base_path, criterio=args.criterio, max_lines=args.max_linhas,
            max_hanzi=args.max_hanzi, max_seconds=args.max_dur)
        st = dict(stats(groups), criterio=resolved)
        total["groups"] += st["groups"]
        total["source_lines"] += st["source_lines"]

        if args.dry_run:
            print("(dry-run) " + format_stats(base_path.name, st))
        else:
            out = periods_path_for(base_path)
            if out.exists() and args.skip_existing:
                print(f"↷ {out.name} já existe — mantido.")
            else:
                tmp = out.with_name(out.name + ".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for g in groups:
                        f.write(group_to_line(g) + "\n")
                os.replace(tmp, out)
                print("✓ " + format_stats(out.name, st))

        if args.sample:
            _print_sample(base_path, groups, args.sample)

    if len(bases) > 1:
        grp = total["groups"] or 1
        print(f"\nΣ {len(bases)} base(s): {total['source_lines']} linha(s) → "
              f"{total['groups']} período(s) ({total['source_lines'] / grp:.2f} linhas/período)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
