#!/usr/bin/env python3
"""Empacota uma coleção num ÚNICO .html autocontido, para abrir no celular.

    python3 dictation/make_bundle.py warehouse/collections/0_r36s
    python3 dictation/make_bundle.py <pasta> --start 200 --count 80 --out ditado.html

Por que existe: o Chrome do Android abre um arquivo local via ``content://``, que
é um identificador OPACO de um documento — não um caminho dentro de uma pasta.
Nenhum caminho relativo (``source/x.png``) resolve a partir dali, então a página
+ pasta de imagens simplesmente não funciona nesse cenário. Embutindo tudo num
arquivo só, não sobra nenhuma referência externa: funciona em ``content://``,
``file://``, servido por HTTP, e offline.

O bundle reaproveita ``dictation/index.html`` como template — a lógica do app
não é duplicada aqui. A única coisa injetada é ``window.__DICTATION__``.

Custo: base64 infla ~33%, então o script re-encoda para JPEG (padrão q88, ~6x
menor que o PNG e visualmente equivalente nas legendas). ``--png`` mantém os
bytes originais.

O progresso (done) continua no localStorage do navegador, e a chave é uma
impressão digital dos nomes dos arquivos — então o progresso é compartilhado
entre o bundle e a mesma coleção aberta pela pasta.
"""

import argparse
import base64
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "index.html"
MARKER = "<!-- DICTATION_DATA:"

# Acima disso o Chrome do Android começa a engasgar para abrir o arquivo.
WARN_MB = 60


def encode_image(path: Path, quality: int, keep_png: bool) -> str:
    """Devolve a imagem como data URI. JPEG re-encodado, ou PNG original."""
    if keep_png:
        raw = path.read_bytes()
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")

    from PIL import Image  # só é necessário no modo JPEG
    with Image.open(path) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build(folder: Path, out: Path, start: int, count: int,
          quality: int, keep_png: bool) -> int:
    index_json = folder / "index.json"
    if not index_json.exists():
        print(f"❌ {index_json} não encontrado.", file=sys.stderr)
        print("   A coleção precisa ter sido salva com a versão que gera o índice.",
              file=sys.stderr)
        return 1
    if not TEMPLATE.exists():
        print(f"❌ template ausente: {TEMPLATE}", file=sys.stderr)
        return 1

    entries = json.loads(index_json.read_text(encoding="utf-8"))
    total = len(entries)

    # start é 1-based para casar com o campo "index" que o usuário vê.
    lo = max(0, start - 1)
    chunk = entries[lo:lo + count] if count > 0 else entries[lo:]
    if not chunk:
        print(f"❌ faixa vazia: --start {start} --count {count} de {total} entradas.",
              file=sys.stderr)
        return 1

    print(f"📖 {index_json} — {total} entradas; empacotando {len(chunk)} "
          f"(de #{chunk[0].get('index')} a #{chunk[-1].get('index')})")
    if len(chunk) < total:
        print(f"   ⚠️  {total - len(chunk)} entrada(s) fora do bundle "
              f"(use --start/--count para outra faixa)")

    out_items = []
    faltando = []
    for i, e in enumerate(chunk, 1):
        src = e.get("source") or ""
        img_path = folder / src
        if not img_path.exists():
            faltando.append(src)
            continue
        out_items.append({
            "index": e.get("index", i),
            "source": src,
            "sentence": e.get("sentence", ""),
            "done": bool(e.get("done", False)),
            "img": encode_image(img_path, quality, keep_png),
        })
        if i % 25 == 0 or i == len(chunk):
            print(f"   [{i}/{len(chunk)}] {src}")

    if faltando:
        print(f"   ⚠️  {len(faltando)} imagem(ns) do índice não existem na pasta "
              f"e ficaram fora: {faltando[:5]}")
    if not out_items:
        print("❌ nenhuma imagem encontrada — nada a empacotar.", file=sys.stderr)
        return 1

    # json.dumps produz JS válido. Escapa "<" para nenhum conteúdo poder fechar
    # a tag <script> por acidente.
    payload = json.dumps(out_items, ensure_ascii=False).replace("<", "\\u003c")
    injected = f"<script>window.__DICTATION__={payload};</script>"

    html = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in html:
        print(f"❌ marcador {MARKER!r} não achado em {TEMPLATE.name}.", file=sys.stderr)
        return 1
    # Substitui o comentário-marcador (que se estende até o fim da linha dele).
    before, _, rest = html.partition(MARKER)
    _, _, after = rest.partition("-->")
    html = before + injected + after

    out.write_text(html, encoding="utf-8")
    mb = out.stat().st_size / (1024 * 1024)
    print(f"\n✅ {out}  ({mb:.1f} MB, {len(out_items)} imagens)")
    if mb > WARN_MB:
        print(f"   ⚠️  acima de {WARN_MB} MB — o Chrome do Android pode demorar ou "
              f"falhar ao abrir. Reduza com --count.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Empacota uma coleção num único .html autocontido.")
    p.add_argument("folder", help="pasta da coleção (a que contém index.json)")
    p.add_argument("--out", help="arquivo de saída (padrão: <pasta>_ditado.html)")
    p.add_argument("--start", type=int, default=1,
                   help="primeira entrada, 1-based (padrão: 1)")
    p.add_argument("--count", type=int, default=150,
                   help="quantas entradas empacotar; 0 = todas (padrão: 150)")
    p.add_argument("--quality", type=int, default=88,
                   help="qualidade do JPEG, 1-95 (padrão: 88)")
    p.add_argument("--png", action="store_true",
                   help="embute o PNG original em vez de re-encodar (bem maior)")
    a = p.parse_args()

    folder = Path(a.folder)
    if not folder.is_dir():
        print(f"❌ pasta não encontrada: {folder}", file=sys.stderr)
        return 1
    out = Path(a.out) if a.out else folder.parent / f"{folder.name}_ditado.html"
    return build(folder, out, a.start, a.count, a.quality, a.png)


if __name__ == "__main__":
    sys.exit(main())
