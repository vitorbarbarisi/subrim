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

import os
import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional

import cv2

import word_vocab
from video_screenshoter_r36s import add_subtitles_to_frame, parse_pinyin_translations

REPO = Path(__file__).parent
WAREHOUSE = REPO / "warehouse"
COLLECTIONS = WAREHOUSE / "collections"
# Cache de frames de um episódio "arquivado" (mp4 trocado por 1 frame/legenda).
# Estrutura: warehouse/frames/<asset>/line{NNNN}.jpg — chaveado por line_num,
# que é estável e mapeia 1-para-1 com a linha do *_base.txt.
FRAMES = WAREHOUSE / "frames"


def _frames_dir(asset: str) -> Path:
    return FRAMES / asset


def _cached_frame_path(asset: str, line_num: int) -> Path:
    return _frames_dir(asset) / f"line{line_num:04d}.jpg"


def has_frame_cache(asset: str) -> bool:
    """True se o episódio tem cache de frames (foi arquivado)."""
    d = _frames_dir(asset)
    return d.is_dir() and next(d.glob("line*.jpg"), None) is not None


def frame_cache_count(asset: str) -> int:
    """Quantidade de frames no cache do episódio (0 se não houver)."""
    d = _frames_dir(asset)
    if not d.is_dir():
        return 0
    return sum(1 for _ in d.glob("line*.jpg"))


def pinyin_to_ascii(pinyin: str) -> str:
    """Converte um pinyin com tons em letras simples sem acento (ex.: 'dāng' → 'dang').

    Remove marcas de tom (acentos), trata ü→u, descarta dígitos de tom e espaços.
    """
    if not pinyin:
        return ""
    decomposed = unicodedata.normalize("NFD", pinyin)
    no_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]", "", no_accents.lower())


def collection_folder_name(word: str, matches: List[dict]) -> str:
    """Nome da pasta da coleção: ``<palavra>_<pinyin_sem_acento>`` (ex.: ``當_dang``).

    O sufixo é o pinyin (sem acento) mais frequente entre as frases encontradas.
    Se nenhum pinyin estiver disponível, usa apenas a palavra.
    """
    safe_word = word.strip().replace("/", "_").replace("\\", "_")
    suffixes = [pinyin_to_ascii(m.get("pinyin", "")) for m in matches]
    suffixes = [s for s in suffixes if s]
    if not suffixes:
        return safe_word
    most_common = Counter(suffixes).most_common(1)[0][0]
    return f"{safe_word}_{most_common}"


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


def base_path_for(asset: str) -> Path:
    """Caminho do base do asset no warehouse."""
    return WAREHOUSE / f"{asset}_base.txt"


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


def set_notes(asset: str, notes: Dict[int, Optional[int]]) -> int:
    """Grava notas no base do asset. ``notes`` = ``{line_num: nota|None}``.

    Aplica TODAS as edições numa única reescrita e devolve quantas linhas
    mudaram. ``None`` remove a nota da linha.

    Invariante crítica: contagem de linhas, ordem e terminadores saem idênticos.
    ``line_num`` é o índice FÍSICO da linha e é a única chave do cache de frames
    (``warehouse/frames/<asset>/lineNNNN.jpg``); alterá-la remapearia em silêncio
    os frames dos episódios cujo mp4 já foi apagado. Por isso o trabalho é feito
    em bytes, substituindo apenas o elemento alvo da lista de linhas — as demais
    linhas nunca são decodificadas nem reconstruídas.

    A troca final é atômica (``os.replace``), então uma busca lendo em paralelo
    enxerga o arquivo antigo ou o novo, nunca um pela metade.
    """
    path = base_path_for(asset)
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


def _asset_source(base_file: Path):
    """Fonte utilizável de frames para o episódio do ``*_base.txt``.

    Retorna ``("video", Path)`` se há o mp4 original, ``("frames", Path)`` se
    o episódio foi arquivado (só cache de frames), ou ``(None, None)`` se não
    há nenhuma fonte (a busca precisa ignorar esse episódio).
    """
    video = _find_video(base_file)
    if video is not None:
        return "video", video
    asset = base_file.stem.replace("_base", "")
    if has_frame_cache(asset):
        return "frames", _frames_dir(asset)
    return None, None


def search(word: str, log_cb: Optional[Callable[[str], None]] = None) -> List[dict]:
    """Varre o warehouse e retorna as frases cujo array de palavras contém ``word``.

    Match exato: a palavra precisa ser uma das entradas (hanzi) do array, não
    apenas uma substring.

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
    if not word or not WAREHOUSE.exists():
        return results

    skipped_no_src: List[str] = []     # base sem vídeo E sem cache → não dá pra extrair frame
    scanned_no_match: List[str] = []   # base varrida, mas a palavra não aparece nela
    bases_with_match = 0

    for base_file in sorted(WAREHOUSE.glob("*_base.txt")):
        asset = base_file.stem.replace("_base", "")
        kind, src = _asset_source(base_file)
        if kind is None:
            skipped_no_src.append(asset)
            continue
        # Arquivado (frames-only): não há mp4; o frame vem do cache por line_num.
        video_path = str(src) if kind == "video" else ""

        hits_before = len(results)
        try:
            with open(base_file, "r", encoding="utf-8") as f:
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
                        "nota": parse_nota(cols[NOTA_COL]) if len(cols) > NOTA_COL else None,
                    })
        except Exception as e:  # noqa: BLE001 - varredura tolerante a arquivos ruins
            _log(f"⚠️  Erro ao ler {base_file.name}: {e}")
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


def _scan_bases(log_cb: Optional[Callable[[str], None]] = None):
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

    if not WAREHOUSE.exists():
        return

    skipped_no_src: List[str] = []
    for base_file in sorted(WAREHOUSE.glob("*_base.txt")):
        asset = base_file.stem.replace("_base", "")
        kind, src = _asset_source(base_file)
        if kind is None:
            skipped_no_src.append(asset)
            continue
        video_path = str(src) if kind == "video" else ""

        try:
            with open(base_file, "r", encoding="utf-8") as f:
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
                        "nota": parse_nota(cols[NOTA_COL]) if len(cols) > NOTA_COL else None,
                    }
        except Exception as e:  # noqa: BLE001
            _log(f"⚠️  Erro ao ler {base_file.name}: {e}")

    if skipped_no_src:
        _log(f"⚠️  {len(skipped_no_src)} base(s) ignorada(s) por falta de vídeo e de cache de frames.")


def search_comprehensible(log_cb: Optional[Callable[[str], None]] = None,
                          max_unknown: int = 1) -> List[dict]:
    """Busca frases com no máximo ``max_unknown`` palavras desconhecidas.

    "Desconhecida" = o base tem pinyin E tradução para a palavra E ela ainda não
    é dominada na word-api (``confidence_level != 3``). Palavras nuas (só o
    caractere) e dominadas contam como conhecidas — nos dois casos não há ajuda
    a ser exibida no render.

    O campo ``word`` de cada match indica o nº de desconhecidas da frase
    (ex.: "0" ou "1") e é usado na coluna Palavra da GUI.
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
    for rec in _scan_bases(log_cb=log_cb):
        pairs = parse_pinyin_translations(rec["translations_json"])
        n_unknown = word_vocab.count_learnable(pairs, mastered)
        if n_unknown > max_unknown:
            continue
        rec["pinyin"] = ""
        rec["word"] = str(n_unknown)   # "0" ou "1"
        results.append(rec)

    _log(f"✓ i+1: {len(results)} frase(s) com ≤{max_unknown} palavra(s) desconhecida(s).")
    return results


def search_all(log_cb: Optional[Callable[[str], None]] = None) -> List[dict]:
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
    for rec in _scan_bases(log_cb=log_cb):
        rec["pinyin"] = ""
        rec["word"] = "1"
        results.append(rec)

    n_assets = len({r["asset"] for r in results})
    _log(f"✓ todas: {len(results)} frase(s) disponíveis em {n_assets} asset(s).")
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


def _render_frame_to(match: dict, out_path: Path) -> bool:
    """Materializa o frame da frase em ``out_path`` (sem legenda).

    Usa o mp4 original quando disponível; senão cai no cache de frames do
    episódio arquivado (``warehouse/frames/<asset>/lineNNNN.jpg``). É o único
    ponto por onde preview e coleção obtêm o frame — mantém busca, visualização
    e salvamento consistentes esteja o episódio arquivado ou não.
    """
    video_path = match.get("video_path") or ""
    if video_path and Path(video_path).exists():
        return extract_frame(video_path, match["avg_time"], out_path)

    # Fallback: episódio arquivado — frame já extraído, indexado por line_num.
    cached = _cached_frame_path(match["asset"], match["line_num"])
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


def archive_asset(asset: str, jpeg_quality: int = 90,
                  progress_cb: Optional[Callable[[int, int, str], None]] = None) -> dict:
    """Extrai 1 frame por legenda do episódio para o cache (``warehouse/frames/<asset>/``).

    Percorre TODAS as linhas do ``*_base.txt`` (não só as de uma palavra), pois a
    busca pode encontrar qualquer palavra. Cada frame é salvo como
    ``line{NNNN}.jpg`` no mesmo timestamp (``avg_time``) que o preview/coleção
    usariam ao vivo — logo o frame do cache é idêntico ao que o mp4 produziria.

    NÃO apaga o mp4: devolve estatísticas para o chamador decidir a remoção
    conforme a tolerância a frames perdidos.

    Retorna ``{"total", "ok", "failed", "dropped": [line_num], "dir"}``.
    """
    base_file = WAREHOUSE / f"{asset}_base.txt"
    if not base_file.exists():
        raise FileNotFoundError(f"base não encontrado: {base_file}")

    video = _find_video(base_file)
    if video is None:
        raise FileNotFoundError(f"vídeo original ausente para '{asset}' — nada a arquivar")

    # Lê todas as linhas com timestamps válidos.
    lines: List[tuple] = []  # (line_num, avg_time)
    with open(base_file, "r", encoding="utf-8") as f:
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

    out_dir = _frames_dir(asset)
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
            out_path = _cached_frame_path(asset, line_num)
            cv2.imwrite(str(out_path), frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
            ok += 1
            if progress_cb and (i % 25 == 0 or i == total):
                progress_cb(i, total, f"{i}/{total} frames")
    finally:
        cap.release()

    return {"total": total, "ok": ok, "failed": len(dropped),
            "dropped": dropped, "dir": out_dir}


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


def save_collection(word: str, matches: List[dict], mode: str = "r36s",
                    progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Path:
    """Persiste a coleção em ``warehouse/collections/<chave>_<mode>/``.

    ``mode`` é ``"original"`` (resolução do vídeo) ou ``"r36s"`` (640x480, legenda
    maior) — um só por chamada. A chave é ``collection_folder_name`` (ex.:
    ``當_dang``), então a pasta fica ``當_dang_r36s``.

    O formato vai no NOME da pasta, e não numa subpasta ``original/``/``r36s/``
    fixa: subpasta com nome fixo colide quando duas coleções são copiadas para o
    mesmo destino.

    A ordem de ``matches`` é preservada no prefixo numérico do arquivo — é a
    ordem da tabela da GUI. Não reordenar aqui.

    Retorna o diretório da coleção.
    """
    if mode not in SAVE_MODES:
        raise ValueError(f"mode inválido: {mode!r} (esperado um de {SAVE_MODES})")

    out_dir = COLLECTIONS / f"{collection_folder_name(word, matches)}_{mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(matches)
    for i, match in enumerate(matches, 1):
        name = f"{i:03d}_{match['asset']}_line{match['line_num']:04d}.png"
        out_path = out_dir / name

        if not _render_frame_to(match, out_path):
            if progress_cb:
                progress_cb(i, total, f"⚠️  Falha ao extrair frame de {match['asset']} (linha {match['line_num']})")
            continue

        add_subtitles_to_frame(out_path, match["chinese"], match["translations_json"],
                               match["portuguese"], resize=(mode == "r36s"))

        if progress_cb:
            progress_cb(i, total, f"✓ {name}")

    return out_dir
