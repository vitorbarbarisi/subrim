#!/usr/bin/env python3
"""
Audio to Video - Empacota arquivos de áudio em MP4 com fundo preto estático

Usage:
  python3 audio_to_video.py                      # Processa assets/audio
  python3 audio_to_video.py assets/audio/audio09 # Processa uma pasta específica
  python3 audio_to_video.py --force              # Regera MP4s já existentes
  python3 audio_to_video.py --size 640x360 --fps 5

O script:
1. Encontra os áudios (mp3/wav/m4a/aac) dentro do diretório informado
2. Para cada um, gera um MP4 de mesmo nome ao lado do áudio
3. O vídeo é um fundo preto na menor resolução útil (128x72 @ 1fps),
   já que não há imagem — o arquivo final fica praticamente do tamanho do áudio
4. A trilha de áudio é copiada sem recodificar (mantém a qualidade original)

IDEMPOTENTE: pula áudios que já têm MP4 gerado (use --force para refazer)

Dependências:
- FFmpeg instalado no sistema
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
DEFAULT_ROOT = Path("assets/audio")
DEFAULT_SIZE = "128x72"
DEFAULT_FPS = 1


def find_audio_files(root: Path) -> List[Path]:
    """Retorna os áudios encontrados em ``root`` (ou o próprio arquivo, se for um)."""
    if root.is_file():
        return [root] if root.suffix.lower() in AUDIO_EXTENSIONS else []

    found = [p for p in sorted(root.rglob("*")) if p.suffix.lower() in AUDIO_EXTENSIONS]
    return found


def probe_duration(audio: Path) -> float:
    """Duração exata da trilha, medida pelo último pacote (pts + duration).

    O ``format=duration`` do MP3 desconta o padding gapless do LAME e fica
    alguns segundos abaixo do que realmente vai para o MP4 quando o áudio é
    copiado sem recodificar — por isso a medição é feita pelos pacotes.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(audio)],
        capture_output=True, text=True, check=True,
    )
    last = [line for line in result.stdout.splitlines() if line.strip()][-1]
    pts, dur = (float(v) if v not in ("", "N/A") else 0.0 for v in last.split(",")[:2])
    return pts + dur


def build_command(audio: Path, output: Path, duration: float, size: str, fps: int,
                  reencode_audio: bool) -> List[str]:
    """Monta o comando FFmpeg que gera o MP4 de fundo preto para ``audio``."""
    audio_args = ["-c:a", "aac", "-b:a", "192k"] if reencode_audio else ["-c:a", "copy"]

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        # -t no input do fundo preto (e não -shortest) porque o -shortest do
        # FFmpeg 8 sobra vários segundos de preto no fim, de forma inconsistente
        "-f", "lavfi",
        "-t", f"{duration:.3f}",
        "-i", f"color=c=black:s={size}:r={fps}",
        "-i", str(audio),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-preset", "ultrafast",
        "-crf", "51",
        "-g", str(max(fps * 10, 1)),
        "-pix_fmt", "yuv420p",
        *audio_args,
        "-movflags", "+faststart",
        str(output),
    ]


def human_size(num_bytes: int) -> str:
    """Formata bytes em uma unidade legível."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def convert(audio: Path, size: str, fps: int, force: bool, reencode_audio: bool) -> bool:
    """Gera o MP4 correspondente a ``audio``. Retorna True se o arquivo existe ao final."""
    output = audio.with_suffix(".mp4")

    if output.exists() and not force:
        print(f"⏭️  {audio.name} → {output.name} já existe (use --force para refazer)")
        return True

    print(f"🎬 {audio.name} → {output.name}")
    duration = probe_duration(audio)
    result = subprocess.run(build_command(audio, output, duration, size, fps, reencode_audio),
                            capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Falhou: {result.stderr.strip()}")
        return False

    print(f"✅ {output.name} ({human_size(output.stat().st_size)})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Empacota áudios em MP4 com fundo preto estático",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", nargs="?", default=str(DEFAULT_ROOT),
                        help=f"Arquivo ou diretório de áudio (padrão: {DEFAULT_ROOT})")
    parser.add_argument("--size", default=DEFAULT_SIZE,
                        help=f"Resolução do fundo preto (padrão: {DEFAULT_SIZE})")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help=f"Taxa de quadros do vídeo (padrão: {DEFAULT_FPS})")
    parser.add_argument("--force", action="store_true",
                        help="Regera MP4s que já existem")
    parser.add_argument("--reencode-audio", action="store_true",
                        help="Converte o áudio para AAC em vez de copiar a trilha original")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"❌ Caminho não encontrado: {root}")
        return 1

    audios = find_audio_files(root)
    if not audios:
        print(f"⚠️ Nenhum áudio encontrado em {root}")
        return 1

    print(f"🔎 {len(audios)} áudio(s) em {root} — fundo {args.size} @ {args.fps}fps\n")

    failures = [a for a in audios
                if not convert(a, args.size, args.fps, args.force, args.reencode_audio)]

    print(f"\n{'⚠️' if failures else '🎉'} {len(audios) - len(failures)}/{len(audios)} convertido(s)")
    for a in failures:
        print(f"   ❌ {a}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
