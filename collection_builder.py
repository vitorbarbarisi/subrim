#!/usr/bin/env python3
"""Busca por palavra no warehouse e geração de coleções de frames legendados.

Varre todos os ``*_base.txt`` do warehouse procurando frases cujo array de
palavras contenha a palavra em mandarim buscada. Para cada frase encontrada
extrai o frame do vídeo original na minutagem correspondente e queima a legenda
rica (chinês + pinyin + tradução), reaproveitando o renderizador do
``video_screenshoter_r36s``.

A coleção é salva em ``warehouse/collections/<chave>_<formato>/``, num formato só
por vez: ``original`` (resolução do vídeo) ou ``r36s`` (640x480, legenda maior).
"""

import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional

import cv2

import periods_base
import word_vocab
from video_screenshoter_r36s import add_subtitles_to_frame, parse_pinyin_translations

REPO = Path(__file__).parent
WAREHOUSE = REPO / "warehouse"
COLLECTIONS = WAREHOUSE / "collections"
# Escopo "texto": bases gerados pelo text_pipeline.py a partir de assets/text/.
# Subpasta própria (e não um sufixo no nome) porque os dois corpora nunca devem
# se misturar numa busca — o modo Vídeo varre WAREHOUSE, o modo Texto varre só
# aqui, e nenhum dos dois precisa saber que o outro existe.
TEXT_WAREHOUSE = WAREHOUSE / "text"
TEXT_COLLECTIONS = TEXT_WAREHOUSE / "collections"
# Cache de frames de um episódio "arquivado" (mp4 trocado por 1 frame/legenda).
# Estrutura: warehouse/frames/<asset>/line{NNNN}.jpg — chaveado por line_num,
# que é estável e mapeia 1-para-1 com a linha do *_base.txt.
FRAMES = WAREHOUSE / "frames"
# Cache dos episódios arquivados PELOS PERÍODOS (ver periods_base.py). Diretório
# separado, e não um sufixo dentro de frames/<asset>/, porque a chave do cache é
# o número da linha e as duas segmentações numeram diferente: misturá-las
# devolveria a imagem errada para todo mundo, em silêncio.
FRAMES_PERIODS = WAREHOUSE / "frames_periods"


def warehouse_dir(text: bool = False) -> Path:
    """Diretório varrido pelas buscas: warehouse/ (vídeo) ou warehouse/text/."""
    return TEXT_WAREHOUSE if text else WAREHOUSE


def _frames_dir(asset: str, periods: bool = False) -> Path:
    return (FRAMES_PERIODS if periods else FRAMES) / asset


def _cached_frame_path(asset: str, line_num: int, periods: bool = False) -> Path:
    return _frames_dir(asset, periods) / f"line{line_num:04d}.jpg"


def has_frame_cache(asset: str, periods: Optional[bool] = None) -> bool:
    """True se o episódio tem cache de frames (foi arquivado).

    ``periods=None`` aceita qualquer um dos dois caches; ``True``/``False``
    perguntam por um só.
    """
    kinds = (True, False) if periods is None else (periods,)
    for kind in kinds:
        d = _frames_dir(asset, kind)
        if d.is_dir() and next(d.glob("line*.jpg"), None) is not None:
            return True
    return False


def frame_cache_count(asset: str, periods: Optional[bool] = None) -> int:
    """Quantidade de frames no cache do episódio (0 se não houver)."""
    kinds = (True, False) if periods is None else (periods,)
    total = 0
    for kind in kinds:
        d = _frames_dir(asset, kind)
        if d.is_dir():
            total += sum(1 for _ in d.glob("line*.jpg"))
    return total


def pinyin_to_ascii(pinyin: str) -> str:
    """Converte um pinyin com tons em letras simples sem acento (ex.: 'dāng' → 'dang').

    Remove marcas de tom (acentos), trata ü→u, descarta dígitos de tom e espaços.
    """
    if not pinyin:
        return ""
    decomposed = unicodedata.normalize("NFD", pinyin)
    no_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]", "", no_accents.lower())


# Só ideogramas CJK. Os ranges são os mesmos que subrim_manager._count_chars usa:
# U+4E00–9FFF (CJK Unified), U+3400–4DBF (Extensão A), U+F900–FAFF (Compatibilidade).
#
# Escapes explícitos DE PROPÓSITO: o _count_chars escreve esse range com literais,
# e o "豈" dele é o ideograma de COMPATIBILIDADE U+F900, não o 豈 comum U+8C48.
# Copiar aquela linha à mão normaliza o caractere e quebra o range em silêncio.
CJK_ONLY_RE = re.compile(r"[^一-鿿㐀-䶿豈-﫿]")


def clean_chinese_only(text: str) -> str:
    """Mantém só os ideogramas CJK da frase.

    Descarta pontuação (``，。？！…「」、·``), espaço, ``♪``, latim, dígitos,
    cirílico, kana, hangul e o ``U+FFFD`` de mojibake que existe em algumas bases.

    Ex.: ``"有什麼作用？"`` → ``"有什麼作用"``;
    ``"\\&&♪ -矛盾 \\&&♪ -別這樣"`` → ``"矛盾別這樣"``.
    """
    return CJK_ONLY_RE.sub("", text or "")


def has_clean_sentence(match: dict) -> bool:
    """True se a frase do match sobra depois da limpeza.

    Frase que zera (legenda só com ``♪`` ou pontuação) não vira imagem nem
    entrada no índice — não há nada a ler nela.
    """
    return bool(clean_chinese_only(match.get("chinese", "")))


def dedupe_sentences(matches: List[dict]) -> tuple:
    """Remove frases repetidas, preservando a ordem. → ``(mantidas, n_removidas)``.

    Compara só os ideogramas (``clean_chinese_only``), então ``"我沒有。"`` e
    ``"我沒有..."`` são a mesma frase — é a mesma noção de frase que o app de
    ditado usa. Sobrevive a PRIMEIRA ocorrência da ordem recebida.

    Frase cuja normalização é vazia — legenda só com ``♪``, pontuação ou mojibake
    — NUNCA deduplica: são milhares no corpus e colidiriam todas num único balde,
    sumindo de uma vez.
    """
    vistos, out = set(), []
    for m in matches:
        key = clean_chinese_only(m.get("chinese", ""))
        if key:
            if key in vistos:
                continue
            vistos.add(key)
        out.append(m)
    return out, len(matches) - len(out)


def collection_folder_name(label: str, matches: List[dict]) -> str:
    """Nome da pasta da coleção: ``<busca>`` ou ``<palavra>_<pinyin_sem_acento>``.

    A coleção inteira vai para UMA pasta, nomeada pelo texto da busca que a
    produziu. Quando esse texto é um termo simples, o sufixo é o pinyin (sem
    acento) mais frequente entre as frases — o ``當_dang`` de sempre.
    """
    safe = label.strip().replace("/", "_").replace("\\", "_")
    # Busca com vírgula (ou) ou traço (e) reúne termos diferentes: o "pinyin mais
    # frequente" seria o de um termo só, escolhido por acaso. Sem sufixo, então.
    if "," in safe or "-" in safe:
        return safe
    suffixes = [pinyin_to_ascii(m.get("pinyin", "")) for m in matches]
    suffixes = [s for s in suffixes if s]
    if not suffixes:
        return safe
    most_common = Counter(suffixes).most_common(1)[0][0]
    return f"{safe}_{most_common}"


# ── Nota (coluna 6 do base, opcional) ───────────────────────────────────────────
# O base tem 6 colunas (0=index 1=begin 2=end 3=zht 4=pares 5=pt). A nota é uma
# 7ª coluna gravada APENAS nas linhas que têm nota — linha sem nota continua com
# 6 colunas. Isso evita um campo vazio no fim, que metade dos leitores do repo
# não enxerga (fazem .strip() antes do split) e que vários escritores apagariam.
NOTA_MIN = 0
NOTA_MAX = 10
NOTA_DEFAULT = 5
NOTA_COL = 6


def parse_nota(raw: str) -> Optional[int]:
    """Nota da coluna 6 como int em 0..10, ou ``None`` se ausente/inválida."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if NOTA_MIN <= value <= NOTA_MAX:
        return value
    return None


def clamp_nota(value: int) -> int:
    """Limita a nota à faixa válida."""
    return max(NOTA_MIN, min(NOTA_MAX, int(value)))


def base_path_for(asset: str, text: bool = False) -> Path:
    """Caminho do base do asset no warehouse (ou no warehouse de textos)."""
    return warehouse_dir(text) / f"{asset}_base.txt"


def periods_path_for(asset: str, text: bool = False) -> Path:
    """Caminho do arquivo de períodos do asset (ver ``periods_base.py``)."""
    return warehouse_dir(text) / f"{asset}{periods_base.PERIODS_SUFFIX}"


def active_base_for(base_file: Path):
    """Arquivo que a busca deve LER para esse episódio, e se ele é o de períodos.

    O ``*_base.txt`` continua intacto no disco; quem manda é o ``*_periods.txt``
    quando ele existe, porque é dele que saem os frames desde que o
    arquivamento passou a usar períodos.

    A exceção é o episódio arquivado ANTES disso: os frames dele estão
    numerados pela segmentação da legenda, então ler os períodos devolveria a
    imagem de outra frase. Nesse caso o base antigo segue valendo — gerar o
    arquivo de períodos para um episódio já arquivado não muda nada e não
    quebra nada.

    Devolve ``(Path, is_periods)``.
    """
    asset = base_file.stem.replace("_base", "")
    periods = base_file.with_name(f"{asset}{periods_base.PERIODS_SUFFIX}")
    if not periods.exists():
        return base_file, False
    if has_frame_cache(asset, periods=False) and not has_frame_cache(asset, periods=True):
        return base_file, False
    return periods, True


def active_base_path(asset: str, text: bool = False) -> Path:
    """``active_base_for`` a partir do nome do asset (usado pela gravação de notas)."""
    return active_base_for(base_path_for(asset, text=text))[0]


def _split_terminator(line: bytes):
    """Separa a linha do seu terminador, preservando qual terminador era."""
    for term in (b"\r\n", b"\n", b"\r"):
        if line.endswith(term):
            return line[:-len(term)], term
    return line, b""


def _backup_once(path: Path) -> None:
    """Cópia pristina antes da PRIMEIRA escrita neste base.

    O warehouse não está no git e 155 dos 165 episódios já tiveram o mp4
    apagado, então não há de onde reconstruir. Um .bak por arquivo é barato e é
    a única rede de segurança.
    """
    bak = path.with_suffix(".bak")   # amor100_base.txt → amor100_base.bak
    if bak.exists():
        return
    try:
        shutil.copy2(path, bak)
    except Exception as e:  # noqa: BLE001 - backup é best-effort, não bloqueia
        print(f"⚠️  não foi possível criar backup {bak.name}: {e}", flush=True)


def set_notes(asset: str, notes: Dict[int, Optional[int]], text: bool = False) -> int:
    """Grava notas no base do asset. ``notes`` = ``{line_num: nota|None}``.

    Aplica TODAS as edições numa única reescrita e devolve quantas linhas
    mudaram. ``None`` remove a nota da linha.

    Escreve no arquivo que a BUSCA leu (``active_base_path``): num episódio já
    arquivado por períodos a nota pertence ao período, e ``line_num`` só faz
    sentido no ``*_periods.txt``. As notas do base antigo continuam lá, e o
    gerador de períodos as carrega para o período (a maior das linhas que ele
    junta) — mas daí em diante os dois arquivos anotam separado.

    Invariante crítica: contagem de linhas, ordem e terminadores saem idênticos.
    ``line_num`` é o índice FÍSICO da linha e é a única chave do cache de frames
    (``warehouse/frames/<asset>/lineNNNN.jpg``); alterá-la remapearia em silêncio
    os frames dos episódios cujo mp4 já foi apagado. Por isso o trabalho é feito
    em bytes, substituindo apenas o elemento alvo da lista de linhas — as demais
    linhas nunca são decodificadas nem reconstruídas.

    A troca final é atômica (``os.replace``), então uma busca lendo em paralelo
    enxerga o arquivo antigo ou o novo, nunca um pela metade.
    """
    path = active_base_path(asset, text=text)
    if not notes or not path.exists():
        return 0

    # bytes.splitlines só quebra em \r, \n e \r\n — ao contrário de str, que
    # também quebraria em \v, \f,  … e mudaria a contagem de linhas.
    lines = path.read_bytes().splitlines(keepends=True)
    total = len(lines)
    changed = 0

    for line_num, nota in notes.items():
        if not (1 <= line_num <= total):
            print(f"⚠️  nota ignorada: linha {line_num} fora de {path.name} "
                  f"({total} linhas)", flush=True)
            continue

        original = lines[line_num - 1]
        body, term = _split_terminator(original)
        cols = body.split(b"\t")
        if len(cols) < 6:
            print(f"⚠️  nota ignorada: linha {line_num} de {path.name} tem "
                  f"{len(cols)} coluna(s)", flush=True)
            continue

        if nota is None:
            if len(cols) <= NOTA_COL:
                continue                      # já não tinha nota
            cols = cols[:NOTA_COL]            # remove a coluna
        else:
            value = str(clamp_nota(nota)).encode("ascii")
            if len(cols) > NOTA_COL:
                if cols[NOTA_COL] == value:
                    continue                  # nada a fazer
                cols[NOTA_COL] = value
            else:
                cols = cols + [b""] * (NOTA_COL - len(cols)) + [value]

        new_line = b"\t".join(cols) + term
        if new_line != original:
            lines[line_num - 1] = new_line
            changed += 1

    if not changed:
        return 0

    _backup_once(path)

    # O temp fica no mesmo diretório (os.replace exige mesmo filesystem) e o
    # nome NÃO casa com o glob "*_base.txt" das buscas.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(b"".join(lines))
    os.replace(tmp, path)
    return changed


def _corrected_timestamp(timestamp_seconds: float) -> float:
    """Aplica a correção de margem de erro de timestamp (vide word_fetcher)."""
    if timestamp_seconds > 250:
        margin = int(round(0.001749577141105422 * timestamp_seconds + 0.18668641727612567))
        return timestamp_seconds + margin
    return timestamp_seconds


# Sufixos de vídeos já processados (com legenda queimada) — nunca são a fonte.
_PROCESSED_SUFFIXES = ("_chromecast", "_merged", "_processed", "_chunk")


def _find_video(base_file: Path) -> Optional[Path]:
    """Encontra o vídeo ORIGINAL (sem legenda) correspondente ao ``*_base.txt``.

    Convenção do warehouse: o vídeo original tem o mesmo prefixo do base
    (ex.: ``clone40.mp4`` para ``clone40_base.txt``). Artefatos processados
    (``*_merged.mp4`` etc.) são ignorados, pois já têm legenda queimada.
    """
    prefix = base_file.stem.replace("_base", "")

    exact = base_file.parent / f"{prefix}.mp4"
    if exact.exists():
        return exact

    for cand in sorted(base_file.parent.glob(f"{prefix}*.mp4")):
        if not any(s in cand.name for s in _PROCESSED_SUFFIXES):
            return cand
    return None


def _asset_source(base_file: Path, periods: bool = False):
    """Fonte utilizável de frames para o episódio do ``*_base.txt``.

    Retorna ``("video", Path)`` se há o mp4 original, ``("frames", Path)`` se
    o episódio foi arquivado (só cache de frames), ou ``(None, None)`` se não
    há nenhuma fonte (a busca precisa ignorar esse episódio).

    ``periods`` diz qual dos dois caches responde por este episódio — o da
    segmentação da legenda ou o dos períodos.
    """
    video = _find_video(base_file)
    if video is not None:
        return "video", video
    asset = base_file.stem.replace("_base", "")
    if has_frame_cache(asset, periods=periods):
        return "frames", _frames_dir(asset, periods)
    return None, None


def search(word: str, log_cb: Optional[Callable[[str], None]] = None,
           text: bool = False) -> List[dict]:
    """Varre o warehouse e retorna as frases cujo array de palavras contém ``word``.

    Match exato: a palavra precisa ser uma das entradas (hanzi) do array, não
    apenas uma substring.

    ``text=True`` varre ``warehouse/text/`` em vez de ``warehouse/``. Nesse
    escopo não há vídeo nem cache de frames a resolver — a imagem é desenhada do
    zero (ver ``_render_frame_to``) —, então nenhuma base é descartada por falta
    de fonte.

    ``log_cb`` (opcional) recebe mensagens de diagnóstico: bases ignoradas por
    falta de vídeo e bases varridas que não contêm a palavra. Sem callback, as
    mensagens vão para o stdout.
    """
    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)
        else:
            print(msg, flush=True)

    word = word.strip()
    results: List[dict] = []
    root = warehouse_dir(text)
    if not word or not root.exists():
        return results

    skipped_no_src: List[str] = []     # base sem vídeo E sem cache → não dá pra extrair frame
    scanned_no_match: List[str] = []   # base varrida, mas a palavra não aparece nela
    bases_with_match = 0

    for base_file in sorted(root.glob("*_base.txt")):
        asset = base_file.stem.replace("_base", "")
        active, is_periods = active_base_for(base_file)
        if text:
            video_path = ""
        else:
            kind, src = _asset_source(base_file, periods=is_periods)
            if kind is None:
                skipped_no_src.append(asset)
                continue
            # Arquivado (frames-only): não há mp4; o frame vem do cache por line_num.
            video_path = str(src) if kind == "video" else ""

        hits_before = len(results)
        try:
            with open(active, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.rstrip("\n")
                    cols = line.split("\t")
                    if len(cols) < 6:
                        continue

                    word_array = cols[4]
                    pairs = parse_pinyin_translations(word_array)
                    matched = next((p for p in pairs if p[0] == word), None)
                    if matched is None:
                        continue

                    try:
                        begin = float(cols[1].replace("s", ""))
                        end = float(cols[2].replace("s", ""))
                    except ValueError:
                        continue

                    results.append({
                        "asset": asset,
                        "video_path": str(video_path),
                        "line_num": line_num,
                        "begin": begin,
                        "end": end,
                        "avg_time": (begin + end) / 2,
                        "chinese": cols[3],
                        "translations_json": word_array,
                        "portuguese": cols[5],
                        "pinyin": matched[1],
                        "word": word,
                        "text": text,
                        "periods": is_periods,
                        "nota": parse_nota(cols[NOTA_COL]) if len(cols) > NOTA_COL else None,
                    })
        except Exception as e:  # noqa: BLE001 - varredura tolerante a arquivos ruins
            _log(f"⚠️  Erro ao ler {active.name}: {e}")
            continue

        if len(results) > hits_before:
            bases_with_match += 1
        else:
            scanned_no_match.append(asset)

    # ── Diagnóstico ─────────────────────────────────────────────────────────
    if skipped_no_src:
        _log(f"⚠️  {len(skipped_no_src)} base(s) IGNORADA(s) por falta de vídeo e de cache de frames: "
             + ", ".join(skipped_no_src))
    if scanned_no_match:
        _log(f"🔎 {len(scanned_no_match)} base(s) varrida(s) SEM '{word}': "
             + ", ".join(scanned_no_match))
    _log(f"✓ '{word}': {len(results)} ocorrência(s) em {bases_with_match} base(s) com fonte.")

    return results


def _scan_bases(log_cb: Optional[Callable[[str], None]] = None, text: bool = False):
    """Gera um registro por linha válida de cada ``*_base.txt`` com fonte utilizável.

    Centraliza o contrato de leitura do base (colunas, timestamps, resolução da
    fonte de frames) compartilhado pelas buscas que varrem TODO o warehouse.
    Cada registro traz apenas os campos comuns; o chamador acrescenta ``word`` e
    ``pinyin`` conforme o modo de busca.

    Consuma o gerador até o fim: o aviso de bases sem fonte sai no encerramento.
    """
    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)
        else:
            print(msg, flush=True)

    root = warehouse_dir(text)
    if not root.exists():
        return

    skipped_no_src: List[str] = []
    for base_file in sorted(root.glob("*_base.txt")):
        asset = base_file.stem.replace("_base", "")
        active, is_periods = active_base_for(base_file)
        if text:
            # Escopo texto: a imagem é desenhada do zero, então não há fonte a
            # resolver e nenhuma base é descartada.
            video_path = ""
        else:
            kind, src = _asset_source(base_file, periods=is_periods)
            if kind is None:
                skipped_no_src.append(asset)
                continue
            video_path = str(src) if kind == "video" else ""

        try:
            with open(active, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    cols = line.rstrip("\r\n").split("\t")
                    if len(cols) < 6:
                        continue
                    try:
                        begin = float(cols[1].replace("s", ""))
                        end   = float(cols[2].replace("s", ""))
                    except ValueError:
                        continue

                    yield {
                        "asset":             asset,
                        "video_path":        video_path,
                        "line_num":          line_num,
                        "begin":             begin,
                        "end":               end,
                        "avg_time":          (begin + end) / 2,
                        "chinese":           cols[3],
                        "translations_json": cols[4],
                        "portuguese":        cols[5],
                        "text":              text,
                        "periods":           is_periods,
                        "nota": parse_nota(cols[NOTA_COL]) if len(cols) > NOTA_COL else None,
                    }
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️  Erro ao ler {active.name}: {e}")

    if skipped_no_src:
        _log(f"⚠️  {len(skipped_no_src)} base(s) ignorada(s) por falta de vídeo e de cache de frames.")


def search_comprehensible(log_cb: Optional[Callable[[str], None]] = None,
                          max_unknown: int = 1, text: bool = False) -> List[dict]:
    """Busca frases com no máximo ``max_unknown`` palavras desconhecidas.

    "Desconhecida" = o base tem pinyin E tradução para a palavra E ela ainda não
    é dominada na word-api (``confidence_level != 3``). Palavras nuas (só o
    caractere) e dominadas contam como conhecidas — nos dois casos não há ajuda
    a ser exibida no render.

    ``word`` recebe ``"0"`` em todos os matches — o termo que ativa o modo, como
    em ``search_all``. É o que agrupa a coleção ao salvar, então o modo inteiro
    vira UMA pasta ``0_<formato>``. O nº de desconhecidas da frase vai em
    ``n_unknown`` (0 ou 1), usado só para o resumo na GUI.
    """
    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)
        else:
            print(msg, flush=True)

    # Uma carga só para a varredura inteira (são ~130k linhas).
    mastered = word_vocab.mastered_words()
    _log(f"📚 {len(mastered)} palavra(s) dominada(s) contam como conhecidas.")

    results: List[dict] = []
    for rec in _scan_bases(log_cb=log_cb, text=text):
        pairs = parse_pinyin_translations(rec["translations_json"])
        n_unknown = word_vocab.count_learnable(pairs, mastered)
        if n_unknown > max_unknown:
            continue
        rec["pinyin"] = ""
        rec["n_unknown"] = n_unknown   # 0 ou 1 — só para o resumo na GUI
        rec["word"] = "0"              # termo da busca: agrupa tudo numa pasta só
        results.append(rec)

    _log(f"✓ i+1: {len(results)} frase(s) com ≤{max_unknown} palavra(s) desconhecida(s).")
    return results


def search_all(log_cb: Optional[Callable[[str], None]] = None,
               text: bool = False) -> List[dict]:
    """Retorna TODAS as frases das bases com fonte utilizável (sem filtrar por palavra).

    Modo especial da GUI (busca ``"1"``): mostra tudo o que está disponível para
    virar imagem. O filtro de assets é aplicado pelo chamador.

    Não faz parsing de pinyin — desnecessário aqui, e evita o custo de percorrer
    o array de palavras de cada frase.

    O campo ``word`` recebe ``"1"`` (o termo que ativa o modo), usado na coluna
    Palavra e no agrupamento ao salvar a coleção.
    """
    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)
        else:
            print(msg, flush=True)

    results: List[dict] = []
    for rec in _scan_bases(log_cb=log_cb, text=text):
        rec["pinyin"] = ""
        rec["word"] = "1"
        results.append(rec)

    n_assets = len({r["asset"] for r in results})
    _log(f"✓ todas: {len(results)} frase(s) disponíveis em {n_assets} asset(s).")
    return results


def search_terms(terms: List[str],
                 log_cb: Optional[Callable[[str], None]] = None,
                 max_unknown: int = 1, text: bool = False) -> List[dict]:
    """Frases que satisfazem TODOS os ``terms`` — a busca concatenada por traço.

    Cada termo é ``"0"`` (regra i+1: ≤ ``max_unknown`` palavras desconhecidas),
    ``"1"`` (curinga, não filtra nada) ou uma palavra — match exato numa entrada
    do array de palavras, igual ao ``search()``.

    Uma varredura só do warehouse avalia todos os termos por linha, e cada frase
    entra UMA vez — ao contrário da vírgula, que concatena uma cópia por termo.

    ``word`` recebe o termo inteiro (``"放-結束"``), porque é ele que agrupa a
    coleção ao salvar: o grupo vira uma pasta só. ``pinyin`` sai da primeira
    palavra do grupo, que é o que dá o sufixo do nome da pasta.
    """
    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)
        else:
            print(msg, flush=True)

    label = "-".join(terms)
    words = [t for t in terms if t not in ("0", "1")]
    needs_i1 = "0" in terms

    # Uma carga só para a varredura inteira (são ~130k linhas), como no i+1.
    mastered = word_vocab.mastered_words() if needs_i1 else None
    if needs_i1:
        _log(f"📚 {len(mastered)} palavra(s) dominada(s) contam como conhecidas.")

    results: List[dict] = []
    for rec in _scan_bases(log_cb=log_cb, text=text):
        found = {}
        if words or needs_i1:
            pairs = parse_pinyin_translations(rec["translations_json"])
            if needs_i1:
                n_unknown = word_vocab.count_learnable(pairs, mastered)
                if n_unknown > max_unknown:
                    continue
                rec["n_unknown"] = n_unknown
            found = {w: py for w, py, _ in pairs}

        if not all(w in found for w in words):
            continue

        rec["word"] = label
        rec["pinyin"] = found[words[0]] if words else ""
        results.append(rec)

    _log(f"✓ '{label}': {len(results)} frase(s) com todos os termos.")
    return results


def _grab_at(cap, fps: float, timestamp_seconds: float, total_frames: int = 0):
    """Lê o frame no timestamp (já corrigido), robusto contra o fim do vídeo.

    A correção de margem (``_corrected_timestamp``) empurra a última legenda
    alguns segundos à frente, o que pode cair ALÉM do fim do vídeo e fazer
    ``cap.read()`` falhar. Aqui o alvo é limitado ao último frame conhecido e,
    se mesmo assim não decodificar, recua até achar o último frame legível.
    Retorna o frame (ndarray) ou ``None``.
    """
    ts = _corrected_timestamp(timestamp_seconds)
    target = int(fps * ts)
    if total_frames and total_frames > 0:
        target = min(target, total_frames - 1)
    target = max(0, target)
    # Recua no máximo ~1s de frames procurando o último frame decodificável.
    lowest = max(0, target - int(round(fps)) - 1)
    for probe in range(target, lowest - 1, -1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, probe)
        ret, frame = cap.read()
        if ret:
            return frame
    return None


def extract_frame(video_path: str, timestamp_seconds: float, out_path: Path) -> bool:
    """Extrai o frame do vídeo na minutagem indicada e salva como PNG (sem legenda)."""
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            print(f"❌ Não foi possível abrir o vídeo: {video_path}", flush=True)
            return False

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps:
            print(f"❌ FPS inválido para o vídeo: {video_path}", flush=True)
            return False

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame = _grab_at(cap, fps, timestamp_seconds, total_frames)
        if frame is None:
            print(f"❌ Falha ao capturar frame em ~{timestamp_seconds:.3f}s de {video_path}", flush=True)
            return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), frame)
        return True
    finally:
        cap.release()


# Tela do R36S. A imagem de uma frase de texto já nasce nessa proporção, então o
# letterbox do add_subtitles_to_frame vira no-op no modo r36s e a legenda cai no
# mesmo lugar que cairia sobre um frame de vídeo.
_TEXT_CANVAS = (640, 480)


def _render_frame_to(match: dict, out_path: Path) -> bool:
    """Materializa o frame da frase em ``out_path`` (sem legenda).

    Usa o mp4 original quando disponível; senão cai no cache de frames do
    episódio arquivado (``warehouse/frames/<asset>/lineNNNN.jpg``). É o único
    ponto por onde preview e coleção obtêm o frame — mantém busca, visualização
    e salvamento consistentes esteja o episódio arquivado ou não.

    Frase vinda de um texto (``match["text"]``) não tem vídeo nenhum: a "cena" é
    uma tela preta, sobre a qual o mesmo ``add_subtitles_to_frame`` desenha a
    legenda. Assim a coleção de texto sai com o layout idêntico ao das coleções
    de vídeo — só sem a foto atrás.
    """
    if match.get("text"):
        from PIL import Image

        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", _TEXT_CANVAS, "black").save(out_path)
        return True

    video_path = match.get("video_path") or ""
    if video_path and Path(video_path).exists():
        return extract_frame(video_path, match["avg_time"], out_path)

    # Fallback: episódio arquivado — frame já extraído, indexado por line_num.
    cached = _cached_frame_path(match["asset"], match["line_num"],
                                bool(match.get("periods")))
    if cached.exists():
        img = cv2.imread(str(cached))
        if img is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_path), img)
            return True
        print(f"❌ Cache de frame ilegível: {cached}", flush=True)
    else:
        print(f"❌ Sem vídeo nem cache para {match.get('asset')} "
              f"(linha {match.get('line_num')})", flush=True)
    return False


def derive_periods_cache(asset: str, progress_cb: Optional[Callable[[int, int, str], None]] = None,
                         force: bool = False) -> dict:
    """Monta ``frames_periods/<asset>/`` a partir do ``frames/<asset>/`` já existente.

    Arquivar por período normalmente re-extrai o frame do mp4 no timestamp do
    período inteiro — mas o vídeo original só sobrou em 6 dos 215 episódios. O
    atalho é que um período é um AGRUPAMENTO de legendas consecutivas, então o
    frame dele já está no cache antigo: basta escolher, entre as legendas do
    grupo, aquela cujo instante fica mais perto do meio do período.

    Em 75% dos casos o período é uma legenda só e o frame é EXATAMENTE o que a
    re-extração daria. Nos 22% que agrupam, o erro de tempo fica em 0,9s na
    mediana (1,7s no p90) — dentro do mesmo plano, quase sempre.

    A numeração é o ponto delicado: tanto ``archive_asset`` quanto
    ``_scan_bases`` nomeiam e leem o frame pela POSIÇÃO da linha no arquivo
    (``enumerate(f, 1)``), não pela coluna 0. Então a origem é
    ``line{row.line_num}`` no base e o destino é ``line{posição do período}`` no
    arquivo de períodos. Confundir as duas daria a imagem de outra frase, sem
    erro nenhum aparecendo.

    Usa hardlink: são ~120 mil jpgs, e copiá-los dobraria o warehouse à toa.

    Retorna ``{"total", "exact", "approx", "missing", "dir", "skipped"}``.
    """
    base_file = WAREHOUSE / f"{asset}_base.txt"
    periods_file = periods_path_for(asset)
    out_dir = _frames_dir(asset, periods=True)

    vazio = {"total": 0, "exact": 0, "approx": 0, "missing": 0,
             "dir": out_dir, "skipped": ""}
    if not base_file.exists() or not periods_file.exists():
        return dict(vazio, skipped="sem base ou sem arquivo de períodos")
    if not has_frame_cache(asset, periods=False):
        return dict(vazio, skipped="sem frames/ de onde derivar")
    if has_frame_cache(asset, periods=True) and not force:
        # O cache extraído do vídeo é a verdade; não trocar por derivado.
        return dict(vazio, skipped="frames_periods/ já existe")

    grupos = periods_base.build_groups(base_file)
    arquivo = [l for l in periods_file.read_text(encoding="utf-8").splitlines()]
    if len(grupos) != len(arquivo):
        return dict(vazio, skipped=f"períodos no disco ({len(arquivo)}) não batem "
                                   f"com os recalculados ({len(grupos)})")
    # Confere o alinhamento posição a posição pelo começo do período: se o
    # agrupamento no disco for outro, o frame iria para a frase errada.
    for pos, (g, linha) in enumerate(zip(grupos, arquivo), 1):
        cols = linha.split("\t")
        if len(cols) < 3 or cols[1] != g.rows[0].begin:
            return dict(vazio, skipped=f"período {pos} do disco não corresponde ao recalculado")

    origem_dir = _frames_dir(asset, periods=False)
    disponiveis = {int(f.stem[4:]) for f in origem_dir.glob("line*.jpg")}
    out_dir.mkdir(parents=True, exist_ok=True)

    exact = approx = missing = 0
    for pos, g in enumerate(grupos, 1):
        rows = g.rows
        alvo = (rows[0].begin_s + rows[-1].end_s) / 2
        candidatos = [r for r in rows if r.line_num in disponiveis]
        if not candidatos:
            missing += 1
            continue
        melhor = min(candidatos, key=lambda r: abs((r.begin_s + r.end_s) / 2 - alvo))
        src = _cached_frame_path(asset, melhor.line_num, periods=False)
        dst = _cached_frame_path(asset, pos, periods=True)
        if dst.exists():
            dst.unlink()
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)        # sistemas de arquivo sem hardlink
        if len(rows) == 1:
            exact += 1
        else:
            approx += 1
        if progress_cb and (pos % 200 == 0 or pos == len(grupos)):
            progress_cb(pos, len(grupos), f"{pos}/{len(grupos)}")

    return {"total": len(grupos), "exact": exact, "approx": approx,
            "missing": missing, "dir": out_dir, "skipped": ""}


def archive_asset(asset: str, jpeg_quality: int = 90,
                  progress_cb: Optional[Callable[[int, int, str], None]] = None,
                  periods: bool = True) -> dict:
    """Extrai 1 frame por FRASE do episódio para o cache e devolve estatísticas.

    A frase é o período inteiro: antes de extrair, o ``*_periods.txt`` é gerado
    (se ainda não existir) e é ELE que define as linhas, indo o cache para
    ``warehouse/frames_periods/<asset>/``. Assim o cartão da coleção mostra o
    período completo em vez do pedaço que coube na legenda. ``periods=False``
    volta ao comportamento antigo (uma imagem por legenda, em
    ``warehouse/frames/<asset>/``).

    Percorre TODAS as linhas do arquivo (não só as de uma palavra), pois a busca
    pode encontrar qualquer palavra. Cada frame é salvo como ``line{NNNN}.jpg``
    no mesmo timestamp (``avg_time``) que o preview/coleção usariam ao vivo —
    logo o frame do cache é idêntico ao que o mp4 produziria.

    NÃO apaga o mp4: devolve estatísticas para o chamador decidir a remoção
    conforme a tolerância a frames perdidos.

    Retorna ``{"total", "ok", "failed", "dropped": [line_num], "dir", "periods",
    "source"}``.
    """
    base_file = WAREHOUSE / f"{asset}_base.txt"
    if not base_file.exists():
        raise FileNotFoundError(f"base não encontrado: {base_file}")

    video = _find_video(base_file)
    if video is None:
        raise FileNotFoundError(f"vídeo original ausente para '{asset}' — nada a arquivar")

    source_file = base_file
    if periods:
        # force=False: um arquivo de períodos já existente (gerado no clean-up ou
        # ajustado à mão) é o que vale — refazer mudaria a numeração das linhas
        # debaixo de um cache que talvez já exista.
        res = periods_base.generate(base_file, force=False)
        source_file = Path(res["path"])
        if progress_cb and not res.get("skipped"):
            progress_cb(0, 0, f"📐 períodos gerados: {res['source_lines']} legenda(s) → "
                              f"{res['groups']} período(s) [{res['criterio']}]")

    # Lê todas as linhas com timestamps válidos.
    lines: List[tuple] = []  # (line_num, avg_time)
    with open(source_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 6:
                continue
            try:
                begin = float(cols[1].replace("s", ""))
                end = float(cols[2].replace("s", ""))
            except ValueError:
                continue
            lines.append((line_num, (begin + end) / 2))

    out_dir = _frames_dir(asset, periods)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(lines)
    ok = 0
    dropped: List[int] = []   # line_nums que não puderam ser extraídos
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"não foi possível abrir o vídeo: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps:
            raise RuntimeError(f"FPS inválido para o vídeo: {video}")
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        for i, (line_num, avg_time) in enumerate(lines, 1):
            frame = _grab_at(cap, fps, avg_time, total_frames)
            if frame is None:
                dropped.append(line_num)
                if progress_cb:
                    progress_cb(i, total, f"⚠️  sem frame legível para a linha {line_num} (~{avg_time:.1f}s)")
                continue
            out_path = _cached_frame_path(asset, line_num, periods)
            cv2.imwrite(str(out_path), frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
            ok += 1
            if progress_cb and (i % 25 == 0 or i == total):
                progress_cb(i, total, f"{i}/{total} frames")
    finally:
        cap.release()

    return {"total": total, "ok": ok, "failed": len(dropped),
            "dropped": dropped, "dir": out_dir, "periods": periods,
            "source": source_file}


def render_preview(match: dict, mode: str = "r36s"):
    """Gera uma imagem PIL já legendada de uma frase (para preview na GUI).

    ``mode`` = ``"r36s"`` (640x480) ou ``"original"`` (resolução do vídeo).
    Retorna um ``PIL.Image.Image`` ou ``None`` em caso de erro.
    """
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        tmp_png = Path(tmp) / "frame.png"
        if not _render_frame_to(match, tmp_png):
            return None
        add_subtitles_to_frame(
            tmp_png, match["chinese"], match["translations_json"], match["portuguese"],
            resize=(mode == "r36s"),
        )
        with Image.open(tmp_png) as img:
            return img.copy()


SAVE_MODES = ("original", "r36s")


# Subpastas das variantes de legenda usadas pelos jogos 3 e 4 do ditado.
# Subpasta, e não sufixo no nome (``001_..._pt.png``), porque o visor do R36S
# varre todo ``*.png`` da pasta: com sufixo as variantes entrariam no slideshow
# intercaladas com as imagens de verdade.
VARIANT_DIRS = {"pt": "so_traducao", "zh": "so_mandarim"}


def save_collection(label: str, matches: List[dict], mode: str = "r36s",
                    progress_cb: Optional[Callable[[int, int, str], None]] = None,
                    text: bool = False, variants: bool = False) -> Path:
    """Persiste a coleção INTEIRA em ``warehouse/collections/<chave>_<mode>/``.

    Uma chamada, uma pasta: ``label`` é o texto da busca que produziu a coleção, e
    todas as frases vão juntas — não há mais uma pasta por termo.

    ``mode`` é ``"original"`` (resolução do vídeo) ou ``"r36s"`` (640x480, legenda
    maior) — um só por chamada. A chave é ``collection_folder_name`` (ex.:
    ``當_dang``), então a pasta fica ``當_dang_r36s``.

    Invariante da pasta: uma frase, uma imagem — ver ``dedupe_sentences`` abaixo.

    O formato vai no NOME da pasta, e não numa subpasta ``original/``/``r36s/``
    fixa: subpasta com nome fixo colide quando duas coleções são copiadas para o
    mesmo destino.

    A ordem de ``matches`` é preservada no prefixo numérico do arquivo — é a
    ordem da tabela da GUI. Não reordenar aqui.

    Junto das imagens grava um ``index.json`` para a aplicação JS que roda no
    celular: uma lista de ``{index, source, sentence, portuguese, done}``, onde
    ``sentence`` é a frase limpa (só ideogramas) e ``done`` começa sempre
    ``false``.

    ``variants=True`` grava mais duas imagens por frase, em ``so_traducao/`` e
    ``so_mandarim/``, com o mesmo nome de arquivo. São as que escondem metade da
    legenda: sem elas os jogos 3 e 4 do ditado mostrariam a própria resposta.
    Custam duas queimadas de legenda a mais por frase — não um segundo seek de
    vídeo, que é a parte cara e continua acontecendo uma vez só.

    Frases que zeram na limpeza (legenda só com ``♪`` ou pontuação) não geram
    imagem nem entrada.

    Retorna o diretório da coleção.
    """
    if mode not in SAVE_MODES:
        raise ValueError(f"mode inválido: {mode!r} (esperado um de {SAVE_MODES})")

    # Coleção de texto vai para warehouse/text/collections/: o nome da pasta é o
    # termo buscado, que colidiria com a coleção homônima do modo Vídeo.
    root = TEXT_COLLECTIONS if text else COLLECTIONS
    out_dir = root / f"{collection_folder_name(label, matches)}_{mode}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if variants:
        for sub in VARIANT_DIRS.values():
            (out_dir / sub).mkdir(exist_ok=True)

    # Filtra ANTES de numerar, para o prefixo (001_, 002_…) ficar contíguo.
    usable = [m for m in matches if has_clean_sentence(m)]
    # A busca por vírgula devolve a mesma frase uma vez por termo, e agora a
    # coleção inteira cai numa pasta só — sem isto o ditado repetiria o cartão.
    # Aqui, e não só na GUI, porque a garantia é da função e não de quem chama.
    usable, n_repetidas = dedupe_sentences(usable)
    if n_repetidas and progress_cb:
        progress_cb(0, len(usable), f"↺ {n_repetidas} frase(s) repetida(s) ignorada(s)")

    entries: List[dict] = []
    total = len(usable)
    for i, match in enumerate(usable, 1):
        name = f"{i:03d}_{match['asset']}_line{match['line_num']:04d}.png"
        out_path = out_dir / name

        if not _render_frame_to(match, out_path):
            if progress_cb:
                progress_cb(i, total, f"⚠️  Falha ao extrair frame de {match['asset']} (linha {match['line_num']})")
            continue

        # As cópias saem do frame CRU e ANTES da primeira queimada:
        # add_subtitles_to_frame grava por cima do arquivo, então depois dela o
        # frame limpo não existe mais e só um novo seek no vídeo o traria de
        # volta — que é justamente o custo que se quer pagar uma vez só.
        variant_paths = {}
        if variants:
            for key, sub in VARIANT_DIRS.items():
                variant_paths[key] = out_dir / sub / name
                shutil.copyfile(out_path, variant_paths[key])

        burn = (mode == "r36s")
        # Sem base_chinese_font_size: o render escolhe a fonte pelo conteúdo, o
        # que importa aqui porque a frase de um período inteiro é bem maior que
        # a de uma legenda (ver _auto_chinese_font_size).
        add_subtitles_to_frame(out_path, match["chinese"], match["translations_json"],
                               match["portuguese"], resize=burn)
        for key, vpath in variant_paths.items():
            add_subtitles_to_frame(vpath, match["chinese"], match["translations_json"],
                                   match["portuguese"], resize=burn, variant=key)

        # Só entra no índice o que virou imagem de fato.
        entry = {
            "index": i,
            "source": name,
            "sentence": clean_chinese_only(match["chinese"]),
            # Gravado sempre, mesmo sem as variantes: não custa nada e é o que o
            # jogo 4 usa como resposta certa.
            "portuguese": (match.get("portuguese") or "").strip(),
            "done": False,
        }
        for key, sub in VARIANT_DIRS.items():
            if key in variant_paths:
                entry[f"source_{key}"] = f"{sub}/{name}"
        entries.append(entry)

        # Um aviso por FRASE, não por imagem: com as variantes o log triplicaria
        # sem dizer nada de novo.
        if progress_cb:
            progress_cb(i, total, f"✓ {name}")

    # ensure_ascii=False: sem isso o chinês vira \uXXXX no arquivo.
    (out_dir / "index.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    return out_dir


# ── CLI ─────────────────────────────────────────────────────────────────────────
def _cli(argv=None) -> int:
    """``python3 collection_builder.py derivar-periodos [asset...|--all]``."""
    import argparse

    p = argparse.ArgumentParser(
        description="Utilitários do acervo de coleções.")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("derivar-periodos",
                       help="monta frames_periods/ a partir do frames/ existente")
    d.add_argument("assets", nargs="*", help="nome do asset; vazio exige --all")
    d.add_argument("--all", action="store_true", help="todos os assets do warehouse")
    d.add_argument("--force", action="store_true",
                   help="refaz mesmo se frames_periods/ já existir "
                        "(sobrescreve o cache extraído do vídeo)")
    a = p.parse_args(argv)

    alvos = (sorted(x.stem.replace("_base", "") for x in WAREHOUSE.glob("*_base.txt"))
             if a.all else a.assets)
    if not alvos:
        p.error("informe um asset ou use --all")

    tot = {"total": 0, "exact": 0, "approx": 0, "missing": 0}
    pulados = []
    for asset in alvos:
        r = derive_periods_cache(asset, force=a.force)
        if r["skipped"]:
            pulados.append((asset, r["skipped"]))
            continue
        for k in tot:
            tot[k] += r[k]
        print(f"✓ {asset}: {r['total']} período(s) — {r['exact']} exato(s), "
              f"{r['approx']} aproximado(s), {r['missing']} sem frame")

    if pulados:
        print(f"\n↷ {len(pulados)} pulado(s):")
        motivos = {}
        for asset, m in pulados:
            motivos.setdefault(m, []).append(asset)
        for m, assets in sorted(motivos.items(), key=lambda kv: -len(kv[1])):
            amostra = ", ".join(assets[:4]) + ("…" if len(assets) > 4 else "")
            print(f"   {len(assets):3d}  {m}  ({amostra})")

    print(f"\nΣ {tot['total']} período(s): {tot['exact']} exato(s), "
          f"{tot['approx']} aproximado(s), {tot['missing']} sem frame")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
