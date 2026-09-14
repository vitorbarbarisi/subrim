#!/usr/bin/env python3
"""Gera o ``*_base.txt`` de um texto em chinês tradicional já traduzido.

Uso: ``python3 text_pipeline.py <stem> [--force]``   (ex.: ``sutra1``)

Lê ``assets/text/<stem>.txt`` e escreve ``warehouse/text/<stem>_base.txt``. É o
equivalente, para o modo Texto, do que o ``processor.py`` faz para o modo Vídeo —
mas MUITO mais curto, porque o texto já vem traduzido: só falta o array de pares
palavra a palavra, que continua vindo da LLM.

Formato do base — o MESMO do modo Vídeo, de propósito::

    {n}\\t0.000s\\t0.000s\\t{chinês}\\t{array de pares}\\t{português}

Os timestamps são fixos em ``0.000s``: não existe minutagem num texto. Mantê-los
na linha é o que permite que ``collection_builder`` (busca, i+1, notas) e a aba
Warehouse do ``subrim_manager`` leiam os dois corpora com o mesmo código — a
única coisa que muda de verdade é de onde sai a imagem.

Diferença funcional em relação ao pipeline de vídeo: o registro do vocabulário na
word-api vai com ``text=true``, então a API contabiliza em ``calls_text`` que a
palavra foi vista num texto, e não numa legenda.

O script é idempotente: rodar de novo só processa as frases que ainda não estão
no base. ``--force`` recomeça do zero.
"""

import argparse
import re
import sys
from pathlib import Path

from processor import (
    _call_deepseek_pairs,
    _call_deepseek_pairs_batch,
    _retry_api_call,
    _sanitize_tsv_field,
    load_dotenv,
)
from sanitize_base import (
    check_word_api_health,
    extract_pairs_from_translation,
    process_word_api_integration,
)

REPO = Path(__file__).resolve().parent
TEXTS = REPO / "assets" / "text"
TEXT_WAREHOUSE = REPO / "warehouse" / "text"

# Timestamps de um texto: não existem. O par fixo mantém a linha com as 6 colunas
# que todo leitor do base espera (ver docstring do módulo).
NO_TIME = "0.000s"

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

# Linhas que são só ornamento editorial do txt e nunca viram frase.
_SEPARATORS = {"⸻", "—", "―", "---", "***"}


def has_chinese(line: str) -> bool:
    return bool(_CJK.search(line))


def parse_txt(txt_path: Path) -> list:
    """Extrai ``[(chinês, português)]`` do txt.

    Contrato do arquivo: linha em chinês, quebra de linha, tradução em
    português. A leitura é tolerante ao que os textos reais trazem:

    - linhas vazias e separadores (``⸻``) são ignorados;
    - a tradução de uma frase é a próxima linha não vazia SEM chinês;
    - se a próxima linha não vazia também tiver chinês, a frase fica sem
      português. É o caso do cabeçalho do ``sutra1.txt``, em que duas linhas
      chinesas precedem uma única tradução — sem esta regra a primeira roubaria
      a tradução da segunda.
    """
    lines = [ln.strip() for ln in txt_path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and ln not in _SEPARATORS]

    out = []
    for i, line in enumerate(lines):
        if not has_chinese(line):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        pt = "" if (not nxt or has_chinese(nxt)) else nxt
        out.append((line, pt))
    return out


def existing_sentences(base_path: Path) -> set:
    """Frases chinesas já gravadas no base (coluna 4), para retomar de onde parou."""
    if not base_path.exists():
        return set()
    done = set()
    for line in base_path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 6:
            done.add(cols[3])
    return done


def next_index(base_path: Path) -> int:
    """Próximo valor da coluna 0 (o contador do base)."""
    if not base_path.exists():
        return 1
    last = 0
    for line in base_path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if cols and cols[0].isdigit():
            last = max(last, int(cols[0]))
    return last + 1


def fetch_pairs(sentences: list) -> dict:
    """``{frase: array de pares}`` — em lote, com fallback 1-a-1.

    Espelha o ``_fetch_batch`` do ``processor.py``: o ganho vem do lote (menos
    round-trips, prompt compartilhado), e a frase que o lote não cobriu é
    resolvida sozinha em vez de derrubar o lote inteiro.
    """
    got = {}
    if not sentences:
        return got
    try:
        got = _retry_api_call(_call_deepseek_pairs_batch, sentences)
    except Exception as e:  # noqa: BLE001 - o fallback abaixo resolve frase a frase
        print(f"⚠️  Lote falhou ({e}); resolvendo frase a frase…", flush=True)
        got = {}
    for s in sentences:
        if s not in got:
            got[s] = _retry_api_call(_call_deepseek_pairs, s)
    return got


def register_vocabulary(pairs_str: str) -> None:
    """Registra as palavras da frase na word-api marcando a origem como texto."""
    if not pairs_str or pairs_str in ("[]", "N/A"):
        return
    pairs = extract_pairs_from_translation(pairs_str)
    if pairs:
        process_word_api_integration(pairs, text=True)


def build(stem: str, force: bool = False, batch_size: int = 20) -> int:
    txt_path = TEXTS / f"{stem}.txt"
    if not txt_path.exists():
        print(f"❌ Texto não encontrado: {txt_path}", file=sys.stderr)
        return 1

    TEXT_WAREHOUSE.mkdir(parents=True, exist_ok=True)
    base_path = TEXT_WAREHOUSE / f"{stem}_base.txt"

    if force and base_path.exists():
        base_path.unlink()
        print(f"🗑️  Base anterior removida: {base_path.name}")

    print(f"📖 Lendo {txt_path.relative_to(REPO)}")
    entries = parse_txt(txt_path)
    print(f"🔤 {len(entries)} frase(s) em chinês encontrada(s)")
    if not entries:
        print("❌ Nenhuma linha com caracteres chineses no txt", file=sys.stderr)
        return 1

    done = existing_sentences(base_path)
    pending = [(zh, pt) for zh, pt in entries if zh not in done]
    if done:
        print(f"↩️  {len(done)} frase(s) já no base; {len(pending)} pendente(s)")
    if not pending:
        print("✅ Nada a fazer — o base já está completo.")
        return 0

    # A ausência da API não é fatal: o base (o produto do script) sai igual. Só o
    # registro do vocabulário é pulado, e o aviso diz isso na cara.
    api_ok = check_word_api_health()
    if not api_ok:
        print("⚠️  Word-api indisponível — o base será gerado, mas nenhuma "
              "palavra será registrada com text=true.")

    index = next_index(base_path)
    written = 0
    with base_path.open("a", encoding="utf-8") as fh:
        for start in range(0, len(pending), batch_size):
            group = pending[start:start + batch_size]

            unique, seen = [], set()
            for zh, _pt in group:
                if zh not in seen:
                    seen.add(zh)
                    unique.append(zh)

            print(f"🤖 Pares para {len(unique)} frase(s) "
                  f"({start + 1}–{start + len(group)} de {len(pending)})…", flush=True)
            pairs_by_sentence = fetch_pairs(unique)

            for zh, pt in group:
                pairs_str = pairs_by_sentence.get(zh, "[]")
                fh.write(
                    f"{index}\t{NO_TIME}\t{NO_TIME}\t{_sanitize_tsv_field(zh)}\t"
                    f"{_sanitize_tsv_field(pairs_str)}\t{_sanitize_tsv_field(pt)}\n"
                )
                index += 1
                written += 1
                if api_ok:
                    register_vocabulary(pairs_str)
            fh.flush()   # cada grupo persistido antes do próximo (resume barato)

    print(f"\n✅ {written} frase(s) gravada(s) em "
          f"{base_path.relative_to(REPO)}")
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Gera o base.txt de um texto de assets/text/ no warehouse/text/.")
    parser.add_argument("stem", help="Nome do txt sem extensão (ex.: sutra1)")
    parser.add_argument("--force", action="store_true",
                        help="Recomeça do zero, descartando o base existente")
    parser.add_argument("--batch", type=int, default=20,
                        help="Frases por chamada em lote da LLM (padrão: 20)")
    args = parser.parse_args()

    print("📝 Text Pipeline — base.txt a partir de texto")
    print("=" * 60)
    return build(args.stem, force=args.force, batch_size=max(1, args.batch))


if __name__ == "__main__":
    sys.exit(main())
