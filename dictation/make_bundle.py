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

Os cinco jogos se alternam a cada frase, então um bloco de 150 sai 30 de cada.
Tudo que eles precisam — segmentação, pinyin, distratores, traduções erradas,
decomposições, embaralhamento — é resolvido AQUI e viaja embutido: a página não
tem rede quando roda no celular. Ver ``wordgrid.py``, ``translations.py`` e
``hanzi_decomp.py``.

Cada jogo embute a imagem que NÃO mostra a sua resposta: o jogo 3 usa a variante
``so_traducao/`` e o jogo 4 a ``so_mandarim/``, gravadas pelo "salvar coleção".
Continua sendo uma imagem por frase — o tamanho do bundle não muda.
"""

import argparse
import base64
import io
import json
import random
import sys
from pathlib import Path

import hanzi_decomp
import translations
import wordgrid

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "index.html"
MARKER = "<!-- DICTATION_DATA:"

# Qual variante de imagem cada jogo embute. Ausente = a imagem completa.
GAME_IMAGE = {3: "source_pt", 4: "source_zh"}

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


class Deps:
    """O que os jogos precisam, carregado uma vez por execução.

    Também decide QUAIS jogos esta coleção suporta. Uma coleção salva sem as
    variantes de imagem não tem como jogar 3 nem 4; alternar 1..5 assim mandaria
    60% das frases para o jogo 1. O rodízio passa a ser só sobre os jogos
    possíveis — 1, 2 e 5 nesse caso — e a saída diz o motivo.
    """

    def __init__(self, entries: list, folder: Path, enabled: bool = True):
        self.lex = None
        self.bank = None
        self.decomps = {}
        self.comps = {}
        self.games = [1]
        self.notas = []
        if not enabled:
            return

        self.lex = wordgrid.Lexicon.load()
        if self.lex:
            self.games.append(2)
        else:
            self.notas.append("sem léxico: o jogo 2 sai de cena")

        if any((e.get("source_pt") and (folder / e["source_pt"]).exists())
               for e in entries):
            self.games.append(3)
        else:
            self.notas.append("sem so_traducao/: o jogo 3 sai de cena")

        tem_pt = any((e.get("portuguese") or "").strip() for e in entries)
        self.bank = translations.Bank.load() if tem_pt else None
        if tem_pt and self.bank and any(
                (e.get("source_zh") and (folder / e["source_zh"]).exists())
                for e in entries):
            self.games.append(4)
        else:
            self.notas.append("sem so_mandarim/ ou sem traduções: o jogo 4 sai de cena")

        # Buscar TODOS os caracteres de uma vez: só depois de saber se alguma
        # decomposição existe é que dá para decidir se o jogo 5 vale a pena. Sem
        # nenhuma ele viraria o jogo 3 com a imagem que mostra a resposta.
        chars = {c for e in entries for c in (e.get("sentence") or "")}
        if chars:
            self.decomps = hanzi_decomp.decompositions(sorted(chars))
        # O jogo 5 precisa dos componentes separados, não do campo inteiro.
        self.comps = {c: hanzi_decomp.split_components(d)
                      for c, d in self.decomps.items()}
        if any(self.comps.values()):
            self.games.append(5)
        else:
            self.notas.append("nenhuma decomposição: o jogo 5 sai de cena")

    def describe(self) -> str:
        return "jogos disponíveis: " + "/".join(str(g) for g in self.games)


def assign_games(items: list, deps: Deps) -> list:
    """Alterna os jogos disponíveis pelos itens e anexa o que cada um precisa.

    A distribuição usa a posição na lista JÁ FILTRADA (as entradas sem imagem
    saíram antes), que é o que garante o 30/30/30/30/30 num bloco de 150.

    Um item que não dá para montar — frase de um caractere só, sem tradução com
    pontuação parecida, sem pinyin para alguma palavra — é REBAIXADO para o
    jogo 1 em vez de sumir. Devolve a contagem por jogo (índice 0 = jogo 1).
    """
    counts = [0] * 5
    ciclo = deps.games
    ultimas = []          # onde a certa do jogo 4 caiu nas duas últimas vezes
    for i, item in enumerate(items):
        game = ciclo[i % len(ciclo)]
        # Semente pelo nome do arquivo: reempacotar a mesma coleção devolve
        # exatamente o mesmo bundle, o que torna diffs e bugs reproduzíveis.
        rng = random.Random(item["source"])
        sentence = item["sentence"]

        if game == 2:
            built = deps.lex.word_game(sentence, rng) if deps.lex else None
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
        elif game == 4:
            options = (deps.bank.options(item.get("portuguese", ""), rng)
                       if deps.bank else None)
            if options:
                # A certa também vai limpa: é assim que ela aparece no botão, e
                # é por igualdade de texto que a página confere o clique.
                answer = translations.clean_pt(item["portuguese"])
                onde = options.index(answer)
                # O sorteio é uniforme e independente — medido —, mas o acaso
                # produz corridas: chegou a cinco frases seguidas com a certa na
                # mesma posição, e aí o jogo PARECE viciado mesmo sorteando
                # direito. Duas seguidas é o limite. A regra dispara em ~4% dos
                # itens (1/5 × 1/5), então quase não mexe na distribuição.
                #
                # Mora aqui, e não no `translations.options`: a regra é sobre a
                # SEQUÊNCIA, e lá só se enxerga uma frase por vez. Entre dois
                # jogos 4 passam sempre quatro frases de outros jogos, então o
                # histórico é dos jogos 4, não dos itens vizinhos.
                if len(ultimas) == 2 and ultimas[0] == ultimas[1] == onde:
                    # Troca, nunca remove e reinsere: é o que garante que as
                    # cinco opções continuem lá, sem duplicar nem perder uma.
                    novo = rng.choice([j for j in range(len(options)) if j != onde])
                    options[onde], options[novo] = options[novo], options[onde]
                    onde = novo
                ultimas = (ultimas + [onde])[-2:]
                item["options"] = options
                item["answer"] = answer
            else:
                game = 1          # rebaixada: não houve posição para lembrar
        elif game == 5:
            # Um botão por COMPONENTE. `needs` guarda, na ordem da frase, quais
            # componentes cada caractere pede; `comps` é a lista embaralhada de
            # botões. O multiconjunto dos dois é o MESMO — nada sobra e nada
            # falta —, e é isso que garante que a frase fecha mesmo quando dois
            # caracteres pedem o mesmo radical.
            needs, botoes = [], []
            for ch in sentence:
                partes = deps.comps.get(ch) or []
                if partes:
                    needs.append([c for c, _g in partes])
                    botoes += partes
                else:
                    # Sem decomposição utilizável: o caractere inteiro vira um
                    # botão só, como pedido.
                    needs.append([ch])
                    botoes.append((ch, ""))
            decompostos = sum(1 for n, ch in zip(needs, sentence) if n != [ch])
            if len(sentence) >= 2 and decompostos:
                rng.shuffle(botoes)
                item["needs"] = needs
                item["comps"] = [{"c": c, "g": g} if g else {"c": c}
                                 for c, g in botoes]
            else:
                # Nenhum caractere decompõe: seriam todos botões inteiros, o
                # jogo viraria o 3 — só que com a imagem que mostra a resposta.
                game = 1

        item["game"] = game
        counts[game - 1] += 1
    return counts


def write_bundle(chunk: list, folder: Path, out: Path, template: str,
                 quality: int, keep_png: bool, deps: Deps) -> tuple:
    """Grava um bundle. Devolve (n_imagens, bytes, faltando, contagem_por_jogo)."""
    items = []
    faltando = []
    for i, e in enumerate(chunk, 1):
        src = e.get("source") or ""
        if not (folder / src).exists():
            faltando.append(src)
            continue
        items.append({
            "index": e.get("index", i),
            "source": src,
            "sentence": e.get("sentence", ""),
            "portuguese": (e.get("portuguese") or "").strip(),
            "done": bool(e.get("done", False)),
            # Os caminhos das variantes ficam guardados fora do payload: servem
            # para escolher a imagem e não têm por que viajar até o celular.
            "_src": {k: e.get(v) for k, v in GAME_IMAGE.items() if e.get(v)},
        })

    if not items:
        return (0, 0, faltando, [0] * 5)

    # Os jogos são atribuídos ANTES de codificar: cada jogo embute uma imagem
    # diferente, e codificar tudo para depois escolher desperdiçaria o base64.
    counts = assign_games(items, deps)

    for item in items:
        variante = item.pop("_src").get(item["game"])
        caminho = folder / variante if variante else folder / item["source"]
        if not caminho.exists():
            # A variante sumiu do disco entre o índice e agora: joga o jogo 1
            # com a imagem completa, em vez de gerar um item sem imagem.
            counts[item["game"] - 1] -= 1
            item["game"] = 1
            counts[0] += 1
            caminho = folder / item["source"]
        item["img"] = encode_image(caminho, quality, keep_png)
        # Serviu para montar as opções do jogo 4 e não tem leitor na página: o
        # que ela compara é `answer`, já limpo.
        del item["portuguese"]

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

    # Uma carga só para a execução inteira: são duas varreduras de 200+ arquivos
    # e uma consulta por caractere na hanzi-api.
    if no_games:
        print("   --no-games: tudo sai como jogo 1 (digitar)")
    deps = Deps(entries, folder, enabled=not no_games)
    if not no_games:
        print(f"   {deps.describe()}")
        if deps.lex:
            print(f"   léxico: {len(deps.lex)} palavras"
                  + (f", traduções: {len(deps.bank)}" if deps.bank else "")
                  + (f", decomposições: {sum(1 for v in deps.comps.values() if v)}"
                     f"/{len(deps.comps)} caracteres" if deps.comps else ""))
        for nota in deps.notas:
            print(f"   ⚠️  {nota}")

    escritos, total_bytes, faltando_geral = 0, 0, []
    for n, chunk in enumerate(chunks, 1):
        out = out_dir / f"{folder.name}_ditado_{n:0{width}d}.html"
        n_img, size, faltando, jogos = write_bundle(chunk, folder, out, template,
                                                    quality, keep_png, deps)
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
            # Rebaixadas = as que iriam para outro jogo, não deram, e por isso
            # engordaram o jogo 1 acima da fatia que lhe cabia no rodízio.
            por_jogo = -(-n_img // len(deps.games))
            rebaixadas = jogos[0] - (por_jogo if 1 in deps.games else 0)
            extra = f", {rebaixadas} rebaixada(s)" if rebaixadas > 0 else ""
            print("        jogos " + "/".join(str(x) for x in jogos) + extra)

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
