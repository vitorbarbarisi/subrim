#!/usr/bin/env python3
"""Transcreve um asset em assets/<nome>: 1 mp4 solto = no lugar, senão 1 pasta por vídeo.

Usage: python3 transcribe_asset.py <asset_name> [--model MODEL] [--language LANGUAGE]

Varre assets/<asset_name>/ **recursivamente** por arquivos .mp4 — cobre tanto
uma pasta com vídeos soltos quanto uma pasta com subpastas (ex.: uma por
canal, no caso do youtube_monitor). Downloads incompletos do yt-dlp (que
terminam em .part) nunca batem com o glob "*.mp4" e são ignorados sozinhos.

Se só existir um único mp4 e ele já estiver direto dentro de
assets/<asset_name>/ (sem subpasta), transcreve no lugar — é o caso comum de
"baixei um episódio, já é um asset". Em qualquer outro caso (vários vídeos,
ou um único vídeo enterrado numa subpasta), cada vídeo é promovido a um asset
próprio: uma pasta-irmã em assets/ com o nome do arquivo (sem extensão), o
mp4 movido pra lá, e a transcrição roda nessa pasta nova — só assim o vídeo
fica visível para o resto do pipeline (video_burner.py etc. só enxergam
assets/<nome>/ de primeiro nível).
"""

import argparse
import shutil
import sys
from pathlib import Path

import transcribe_video


def organize_and_transcribe(asset_name: str, model: str = "medium", language: str = "zh") -> bool:
    assets_dir = Path("assets") / asset_name
    if not assets_dir.exists():
        print(f"❌ Diretório não encontrado: {assets_dir}")
        return False

    videos = sorted(assets_dir.rglob("*.mp4"))
    if not videos:
        print(f"❌ Nenhum arquivo MP4 encontrado em {assets_dir}")
        return False

    if len(videos) == 1 and videos[0].parent == assets_dir:
        return transcribe_video.transcribe_video(asset_name, model, language)

    print(f"📦 {len(videos)} vídeo(s) encontrado(s) em {assets_dir} — organizando em pastas individuais...")
    ok = True
    for video in videos:
        target_dir = Path("assets") / video.stem
        if target_dir.exists():
            print(f"⚠️  Pulei '{video.name}': já existe assets/{video.stem}/")
            ok = False
            continue
        target_dir.mkdir(parents=True)
        shutil.move(str(video), str(target_dir / video.name))
        print(f"📁 assets/{video.stem}/ criado, vídeo movido.")
        if not transcribe_video.transcribe_video(video.stem, model, language):
            ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_name", help="Nome do diretório em assets/")
    parser.add_argument("--model", default="medium",
                         choices=["tiny", "base", "small", "medium", "large"],
                         help="Modelo Whisper a usar (padrão: medium)")
    parser.add_argument("--language", default="zh",
                         help="Código de idioma para o Whisper (padrão: zh)")
    args = parser.parse_args()

    ok = organize_and_transcribe(args.asset_name, args.model, args.language)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
