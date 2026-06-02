#!/usr/bin/env python3
"""Busca por palavra no warehouse e geração de coleções de frames legendados.

Varre todos os ``*_base.txt`` do warehouse procurando frases cujo array de
palavras contenha a palavra em mandarim buscada. Para cada frase encontrada
extrai o frame do vídeo original na minutagem correspondente e queima a legenda
rica (chinês + pinyin + tradução), reaproveitando o renderizador do
``video_screenshoter_r36s``.

A coleção é salva em ``warehouse/collections/<palavra>/`` com duas resoluções:
``original/`` (resolução do vídeo) e ``r36s/`` (640x480, legenda maior).
"""

import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional

import cv2

from video_screenshoter_r36s import add_subtitles_to_frame, parse_pinyin_translations

REPO = Path(__file__).parent
WAREHOUSE = REPO / "warehouse"
COLLECTIONS = WAREHOUSE / "collections"


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


def search(word: str) -> List[dict]:
    """Varre o warehouse e retorna as frases cujo array de palavras contém ``word``.

    Match exato: a palavra precisa ser uma das entradas (hanzi) do array, não
    apenas uma substring.
    """
    word = word.strip()
    results: List[dict] = []
    if not word or not WAREHOUSE.exists():
        return results

    for base_file in sorted(WAREHOUSE.glob("*_base.txt")):
        video_path = _find_video(base_file)
        if not video_path:
            continue
        asset = base_file.stem.replace("_base", "")

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
                    })
        except Exception as e:  # noqa: BLE001 - varredura tolerante a arquivos ruins
            print(f"⚠️  Erro ao ler {base_file.name}: {e}", flush=True)

    return results


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

        ts = _corrected_timestamp(timestamp_seconds)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * ts))
        ret, frame = cap.read()
        if not ret:
            print(f"❌ Falha ao capturar frame em {ts:.3f}s de {video_path}", flush=True)
            return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), frame)
        return True
    finally:
        cap.release()


def render_preview(match: dict, mode: str = "r36s"):
    """Gera uma imagem PIL já legendada de uma frase (para preview na GUI).

    ``mode`` = ``"r36s"`` (640x480) ou ``"original"`` (resolução do vídeo).
    Retorna um ``PIL.Image.Image`` ou ``None`` em caso de erro.
    """
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        tmp_png = Path(tmp) / "frame.png"
        if not extract_frame(match["video_path"], match["avg_time"], tmp_png):
            return None
        add_subtitles_to_frame(
            tmp_png, match["chinese"], match["translations_json"], match["portuguese"],
            resize=(mode == "r36s"),
        )
        with Image.open(tmp_png) as img:
            return img.copy()


def save_collection(word: str, matches: List[dict],
                    progress_cb: Optional[Callable[[int, int, str], None]] = None) -> Path:
    """Persiste a coleção em ``warehouse/collections/<word>_<pinyin>/`` nas 2 resoluções.

    A pasta recebe o pinyin (sem acento) como sufixo (ex.: ``當_dang``).
    Cada frase vira uma imagem em ``original/`` e outra em ``r36s/``.
    Retorna o diretório da coleção.
    """
    out_dir = COLLECTIONS / collection_folder_name(word, matches)
    orig_dir = out_dir / "original"
    r36s_dir = out_dir / "r36s"
    orig_dir.mkdir(parents=True, exist_ok=True)
    r36s_dir.mkdir(parents=True, exist_ok=True)

    total = len(matches)
    for i, match in enumerate(matches, 1):
        name = f"{i:03d}_{match['asset']}_line{match['line_num']:04d}.png"
        orig_path = orig_dir / name
        r36s_path = r36s_dir / name

        if not extract_frame(match["video_path"], match["avg_time"], orig_path):
            if progress_cb:
                progress_cb(i, total, f"⚠️  Falha ao extrair frame de {match['asset']} (linha {match['line_num']})")
            continue

        # Reaproveita o mesmo frame para as duas resoluções
        shutil.copy(orig_path, r36s_path)
        add_subtitles_to_frame(orig_path, match["chinese"], match["translations_json"],
                               match["portuguese"], resize=False)
        add_subtitles_to_frame(r36s_path, match["chinese"], match["translations_json"],
                               match["portuguese"], resize=True)

        if progress_cb:
            progress_cb(i, total, f"✓ {name}")

    return out_dir
