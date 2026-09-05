#!/usr/bin/env python3
"""Empacota uma coleção em .html autocontidos, para abrir no celular.

    python3 dictation/make_bundle.py warehouse/collections/0_r36s

Gera quantos arquivos forem necessários para cobrir TODAS as entradas do
``index.json``, em blocos de ``--per-file`` (padrão 150), dentro de
``dictation/``:

    dictation/0_r36s_ditado_01.html
    dictation/0_r36s_ditado_02.html
    ...

Por que existe: o Chrome do Android abre um arquivo local via ``content://``, que
é um identificador OPACO de um documento — não um caminho dentro de uma pasta.
Nenhum caminho relativo (``source/x.png``) resolve a partir dali, então a página
+ pasta de imagens simplesmente não funciona nesse cenário. Embutindo tudo em
cada arquivo, não sobra nenhuma referência externa: funciona em ``content://``,
``file://``, servido por HTTP, e offline.

Os bundles reaproveitam ``dictation/index.html`` como template — a lógica do app
não é duplicada aqui. A única coisa injetada é ``window.__DICTATION__``.

Custo: base64 infla ~33%, então o script re-encoda para JPEG (padrão q88, ~6x
menor que o PNG e visualmente equivalente nas legendas). ``--png`` mantém os
bytes originais.

O progresso (done) fica no localStorage, com chave derivada dos nomes dos
arquivos de CADA bundle — então cada arquivo controla o seu próprio bloco, e o
"Exportar" de um bundle traz só as entradas dele.

Os três jogos (digitar / montar por pinyin / montar por caractere) se alternam a
cada frase, então um bloco de 150 sai 50/50/50. O que os jogos 2 e 3 precisam —
segmentação, pinyin, distratores, embaralhamento — é resolvido AQUI e viaja
embutido: a página não tem rede quando roda no celular. Ver ``wordgrid.py``.
"""

import argparse
import base64
import io
import json
import random
import sys
from pathlib import Path

import wordgrid

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "index.html"
MARKER = "<!-- DICTATION_DATA:"

N_GAMES = 3

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


def assign_games(items: list, lex, games: bool = True) -> list:
    """Alterna 1, 2, 3 pelos itens e anexa o que cada jogo precisa.

    A distribuição usa a posição na lista JÁ FILTRADA (as entradas sem imagem
    saíram antes), que é o que garante o 50/50/50 num bloco de 150.

    Um item que não dá para montar — frase de um caractere só, ou com um
    caractere fora do léxico — é REBAIXADO para o jogo 1 em vez de sumir.
    ``games=False`` rebaixa todos. Devolve a contagem por jogo.
    """
    counts = [0] * N_GAMES
    for i, item in enumerate(items):
        game = (i % N_GAMES) + 1 if games else 1
        # Semente pelo nome do arquivo: reempacotar a mesma coleção devolve
        # exatamente o mesmo bundle, o que torna diffs e bugs reproduzíveis.
        rng = random.Random(item["source"])
        sentence = item["sentence"]

        if game == 2 and lex:
            built = lex.word_game(sentence, rng)
            if built:
                item["words"] = built["words"]
                item["opts"] = built["opts"]
            else:
                game = 1
        elif game == 3:
            chars = wordgrid.char_game(sentence, rng)
            if chars:
                item["chars"] = chars
            else:
                game = 1
        elif game != 1:
            game = 1                          # jogo 2 sem léxico

        item["game"] = game
        counts[game - 1] += 1
    return counts


def write_bundle(chunk: list, folder: Path, out: Path, template: str,
                 quality: int, keep_png: bool, lex, games: bool = True) -> tuple:
    """Grava um bundle. Devolve (n_imagens, bytes, faltando, contagem_por_jogo)."""
    items = []
    faltando = []
    for i, e in enumerate(chunk, 1):
        src = e.get("source") or ""
        img_path = folder / src
        if not img_path.exists():
            faltando.append(src)
            continue
        items.append({
            "index": e.get("index", i),
            "source": src,
            "sentence": e.get("sentence", ""),
            "done": bool(e.get("done", False)),
            "img": encode_image(img_path, quality, keep_png),
        })

    if not items:
        return (0, 0, faltando, [0] * N_GAMES)

    counts = assign_games(items, lex, games)

    # json.dumps produz JS válido. Escapa "<" para nenhum conteúdo poder fechar
    # a tag <script> por acidente.
    payload = json.dumps(items, ensure_ascii=False).replace("<", "\\u003c")
    injected = f"<script>window.__DICTATION__={payload};</script>"

    before, _, rest = template.partition(MARKER)
    _, _, after = rest.partition("-->")
    out.write_text(before + injected + after, encoding="utf-8")
    return (len(items), out.stat().st_size, faltando, counts)


def build(folder: Path, out_dir: Path, per_file: int, quality: int,
          keep_png: bool, max_files: int, no_games: bool = False) -> int:
    index_json = folder / "index.json"
    if not index_json.exists():
        print(f"❌ {index_json} não encontrado.", file=sys.stderr)
        print("   A coleção precisa ter sido salva com a versão que gera o índice.",
              file=sys.stderr)
        return 1
    if not TEMPLATE.exists():
        print(f"❌ template ausente: {TEMPLATE}", file=sys.stderr)
        return 1
    if per_file < 1:
        print("❌ --per-file precisa ser >= 1.", file=sys.stderr)
        return 1

    template = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in template:
        print(f"❌ marcador {MARKER!r} não achado em {TEMPLATE.name}.", file=sys.stderr)
        return 1

    entries = json.loads(index_json.read_text(encoding="utf-8"))
    if not entries:
        print(f"❌ {index_json} está vazio.", file=sys.stderr)
        return 1

    chunks = [entries[i:i + per_file] for i in range(0, len(entries), per_file)]
    # Largura do número vem do total, não do recorte: assim os nomes não mudam
    # se você reexecutar com --max-files.
    width = max(2, len(str(len(chunks))))
    total_chunks = len(chunks)
    if max_files > 0:
        chunks = chunks[:max_files]

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"📖 {index_json} — {len(entries)} entradas")
    print(f"   {total_chunks} arquivo(s) de até {per_file} imagens → {out_dir}/")
    if len(chunks) < total_chunks:
        print(f"   ⚠️  --max-files {max_files}: gerando só os {len(chunks)} primeiros")

    # Uma carga só para a execução inteira: a word-api é uma chamada de rede e a
    # varredura do warehouse lê 200+ arquivos.
    lex = None
    if no_games:
        print("   --no-games: tudo sai como jogo 1 (digitar)")
    else:
        lex = wordgrid.Lexicon.load()
        if lex:
            print(f"   léxico: {len(lex)} palavras (jogos 1, 2 e 3)")
        else:
            print("   ⚠️  léxico vazio: sem word-api e sem warehouse, o jogo 2 "
                  "não tem como ser montado — essas frases saem como jogo 1")

    escritos, total_bytes, faltando_geral = 0, 0, []
    for n, chunk in enumerate(chunks, 1):
        out = out_dir / f"{folder.name}_ditado_{n:0{width}d}.html"
        n_img, size, faltando, jogos = write_bundle(chunk, folder, out, template,
                                                    quality, keep_png, lex,
                                                    not no_games)
        faltando_geral += faltando
        if not n_img:
            print(f"   [{n}/{len(chunks)}] {out.name}: nenhuma imagem encontrada — pulado")
            continue
        escritos += 1
        total_bytes += size
        mb = size / (1024 * 1024)
        flag = "  ⚠️  grande" if mb > WARN_MB else ""
        print(f"   [{n}/{len(chunks)}] {out.name}  {n_img} imagens, {mb:.1f} MB{flag}")
        if not no_games:
            # Rebaixadas = as que iriam para o jogo 2 ou 3, não deram, e por
            # isso engordaram o jogo 1 acima do terço que lhe cabia.
            rebaixadas = jogos[0] - -(-n_img // N_GAMES)
            extra = f", {rebaixadas} rebaixada(s)" if rebaixadas else ""
            print(f"        jogos {jogos[0]}/{jogos[1]}/{jogos[2]}{extra}")

    if faltando_geral:
        print(f"\n⚠️  {len(faltando_geral)} imagem(ns) do índice não existem na pasta "
              f"e ficaram fora: {faltando_geral[:5]}")
    if not escritos:
        print("❌ nada foi gerado.", file=sys.stderr)
        return 1

    print(f"\n✅ {escritos} arquivo(s) em {out_dir}/ "
          f"({total_bytes / (1024 * 1024):.1f} MB no total)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Empacota uma coleção em .html autocontidos (blocos de --per-file).")
    p.add_argument("folder", help="pasta da coleção (a que contém index.json)")
    p.add_argument("--out-dir", default=str(HERE),
                   help="onde gravar os .html (padrão: a própria pasta dictation/)")
    p.add_argument("--per-file", type=int, default=150,
                   help="imagens por arquivo (padrão: 150)")
    p.add_argument("--max-files", type=int, default=0,
                   help="gera no máximo N arquivos; 0 = todos (padrão: 0)")
    p.add_argument("--quality", type=int, default=88,
                   help="qualidade do JPEG, 1-95 (padrão: 88)")
    p.add_argument("--png", action="store_true",
                   help="embute o PNG original em vez de re-encodar (bem maior)")
    p.add_argument("--no-games", action="store_true",
                   help="gera tudo como jogo 1 (digitar), sem os grids de botões")
    a = p.parse_args()

    folder = Path(a.folder)
    if not folder.is_dir():
        print(f"❌ pasta não encontrada: {folder}", file=sys.stderr)
        return 1
    return build(folder, Path(a.out_dir), a.per_file, a.quality, a.png,
                 a.max_files, a.no_games)


if __name__ == "__main__":
    sys.exit(main())
