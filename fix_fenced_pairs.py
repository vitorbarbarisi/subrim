#!/usr/bin/env python3
"""Repara linhas de base cujo array de pares foi gravado dentro de uma cerca markdown.

Uso: ``python3 fix_fenced_pairs.py [--apply]``   (sem --apply, só simula)

O ``_call_deepseek_pairs`` do ``processor.py`` devolvia a resposta da LLM crua
quando ela vinha embrulhada em ```` ```json … ``` ````. A cerca ia para a coluna
4 do base, e nenhum leitor do repo consegue parsear aquele array — a linha perde
pinyin e tradução de TODAS as suas palavras, na queima e na aba Coleções.

A origem já está corrigida; este script conserta o que ficou gravado. A correção
é puramente a remoção da cerca: o array de dentro está íntegro.

Invariante crítica (a mesma do ``collection_builder.set_notes``): contagem de
linhas, ordem e terminadores saem IDÊNTICOS. ``line_num`` é a chave do cache de
frames dos episódios cujo mp4 já foi apagado — deslocar uma linha remapearia os
frames em silêncio. Por isso o trabalho é feito em bytes, trocando só o campo
alvo, e a gravação final é atômica.

Backup: ``<nome>.prefence.bak``, um por arquivo tocado. Sufixo próprio de
propósito — o ``.bak`` do ``set_notes`` é uma cópia anterior às notas, e
sobrescrevê-lo apagaria essa rede de segurança.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
WAREHOUSE = REPO / "warehouse"
TEXT_WAREHOUSE = WAREHOUSE / "text"

PAIRS_COL = 4
_FENCE_OPEN = re.compile(r"^```[a-zA-Z]*\s*")
_FENCE_CLOSE = re.compile(r"\s*```$")


def unfence(field: str):
    """Array limpo se ``field`` for INTEIRAMENTE uma cerca com JSON válido dentro.

    Devolve ``None`` quando não há o que consertar com segurança — inclusive no
    caso em que a LLM escreveu prosa antes da cerca (houve recusa de tradução).
    Essas linhas ficam como estão: o problema delas não é a cerca.
    """
    t = field.strip()
    if not t.startswith("```"):
        return None
    t = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", t)).strip()
    try:
        arr = json.loads(t)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
        return None
    return json.dumps(arr, ensure_ascii=False)


def _split_terminator(line: bytes):
    for term in (b"\r\n", b"\n", b"\r"):
        if line.endswith(term):
            return line[:-len(term)], term
    return line, b""


def fix_file(path: Path, apply: bool) -> tuple:
    """Retorna ``(n_corrigidas, n_ignoradas)`` para um base."""
    lines = path.read_bytes().splitlines(keepends=True)
    fixed = skipped = 0

    for i, raw in enumerate(lines):
        body, term = _split_terminator(raw)
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue
        cols = text.split("\t")
        if len(cols) <= PAIRS_COL or "```" not in cols[PAIRS_COL]:
            continue

        clean = unfence(cols[PAIRS_COL])
        if clean is None:
            skipped += 1
            print(f"    ⏭️  linha {i + 1}: cerca não isolável, mantida como está")
            continue

        cols[PAIRS_COL] = clean
        lines[i] = "\t".join(cols).encode("utf-8") + term
        fixed += 1

    if fixed and apply:
        bak = path.with_suffix(".prefence.bak")
        if not bak.exists():
            shutil.copy2(path, bak)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.writelines(lines)
            os.replace(tmp, path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    return fixed, skipped


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Remove cercas markdown do array de pares dos *_base.txt.")
    ap.add_argument("--apply", action="store_true",
                    help="Grava as correções (sem isto, apenas simula)")
    args = ap.parse_args()

    files = sorted(WAREHOUSE.glob("*_base.txt")) + sorted(TEXT_WAREHOUSE.glob("*_base.txt"))
    tot_fixed = tot_skipped = tot_files = 0

    for f in files:
        if b"```" not in f.read_bytes():
            continue
        rel = f.relative_to(REPO)
        print(f"  {rel}")
        fixed, skipped = fix_file(f, args.apply)
        if fixed:
            tot_files += 1
            print(f"    ✅ {fixed} linha(s) {'corrigida(s)' if args.apply else 'a corrigir'}")
        tot_fixed += fixed
        tot_skipped += skipped

    verbo = "corrigidas" if args.apply else "seriam corrigidas"
    print(f"\n{tot_fixed} linha(s) {verbo} em {tot_files} arquivo(s)")
    if tot_skipped:
        print(f"{tot_skipped} linha(s) mantida(s) (cerca não isolável)")
    if not args.apply:
        print("\nSimulação — nada foi gravado. Use --apply para aplicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
