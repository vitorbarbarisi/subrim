#!/usr/bin/env python3
"""
Split Subtitle Processor
Divide legendas de arquivo base completo em chunks baseados em vídeos já existentes

Usage: python3 split_subtitle.py <directory_name>
Example: python3 split_subtitle.py mulher6

O script:
1. Assume que os chunks de vídeo já existem na pasta _sub
2. Lê o arquivo base original completo (do diretório assets/<directory_name>)
3. Para cada chunk de vídeo encontrado, cria arquivo base correspondente
4. Não processa vídeos, apenas divide as legendas por chunk

Pré-requisitos:
- Pasta _sub deve existir com chunks de vídeo (*_chunk_*.mp4)
- Arquivo base completo deve existir em assets/<directory_name>/
- Vídeos devem estar nomeados como: <nome>_chunk_XXX.mp4
"""

import sys
import argparse
import shutil
import subprocess
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple
from decimal import Decimal, ROUND_HALF_UP


def find_base_file(directory: Path) -> Path:
    """Find the base.txt file in the directory."""
    base_files = list(directory.glob("*_base.txt"))
    if not base_files:
        raise FileNotFoundError(f"Nenhum arquivo *_base.txt encontrado em {directory}")
    return base_files[0]


def find_video_chunks(sub_dir: Path) -> List[Path]:
    """Find all video chunks in the _sub directory."""
    chunks = []
    for chunk_file in sub_dir.glob("*_chunk_*.mp4"):
        if "_processed" not in chunk_file.name and "_temp" not in chunk_file.name:
            chunks.append(chunk_file)

    # Sort by chunk number
    def get_chunk_number(chunk_path: Path) -> int:
        match = re.search(r'_chunk_(\d+)', chunk_path.name)
        return int(match.group(1)) if match else 999

    chunks.sort(key=get_chunk_number)
    return chunks


def get_video_duration(video_path: Path) -> float:
    """Get video duration using ffprobe."""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        str(video_path)
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        import json
        data = json.loads(result.stdout)

        # Get duration from format or video stream
        duration = float(data.get('format', {}).get('duration', 0))
        if duration == 0:
            # Try to get from video stream
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    duration = float(stream.get('duration', 0))
                    break

        return duration
    except Exception as e:
        print(f"   ❌ Erro ao obter duração do vídeo {video_path.name}: {e}")
        return 0.0


def parse_base_file(base_file_path: Path) -> Dict[float, Tuple[str, str, str, str, float]]:
    """
    Parse the base.txt file and return a mapping of begin_time -> (chinese subtitle, translations, translations_json, portuguese, duration).

    Returns:
        Dict mapping begin_time (as float seconds) to tuple of (chinese_text, translations_text, translations_json, portuguese_text, duration)
    """
    subtitles = {}

    try:
        with open(base_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                parts = line.split('\t')
                if len(parts) < 6:  # Need at least: index, begin, end, chinese, pairs, portuguese
                    print(f"   ⚠️  Linha {line_num} mal formatada, pulando: {line[:50]}...")
                    continue

                try:
                    index = int(parts[0])
                    begin_time_str = parts[1]
                    end_time_str = parts[2]
                    chinese_text = parts[3]
                    translations_json = parts[4] if len(parts) > 4 else ""
                    portuguese_text = parts[5] if len(parts) > 5 else ""

                    # Convert begin time to float
                    if begin_time_str.endswith('s'):
                        begin_time = float(begin_time_str[:-1])
                    else:
                        begin_time = float(begin_time_str)

                    # Calculate duration
                    if end_time_str.endswith('s'):
                        end_time = float(end_time_str[:-1])
                    else:
                        end_time = float(end_time_str)
                    duration = end_time - begin_time

                    subtitles[begin_time] = (chinese_text, "", translations_json, portuguese_text, duration)

                except (ValueError, IndexError) as e:
                    print(f"   ⚠️  Erro na linha {line_num}: {e}")
                    continue

    except Exception as e:
        print(f"   ❌ Erro ao ler arquivo base: {e}")
        return {}

    return subtitles


def create_video_chunks(subtitles: Dict[float, Tuple[str, str, str, str, float]], video_duration: float) -> List[Dict]:
    """
    Create chunks of approximately 30 seconds based on subtitles.

    Args:
        subtitles: Dict of begin_time -> (chinese, translations, json, portuguese, duration)
        video_duration: Total video duration in seconds

    Returns:
        List of chunk dictionaries with start_time, end_time, and subtitles
    """
    if not subtitles:
        return []

    # Sort subtitles by begin time
    sorted_times = sorted(subtitles.keys())
    chunks = []

    chunk_duration = 30.0  # Target chunk duration in seconds
    current_start = 0.0

    while current_start < video_duration:
        current_end = min(current_start + chunk_duration, video_duration)

        # Find subtitles that belong to this chunk
        chunk_subtitles = []
        for begin_time in sorted_times:
            if begin_time >= current_start and begin_time < current_end:
                chinese, translations, json_trans, portuguese, duration = subtitles[begin_time]
                chunk_subtitles.append({
                    'begin_time': begin_time,
                    'end_time': begin_time + duration,
                    'chinese': chinese,
                    'translations': translations,
                    'translations_json': json_trans,
                    'portuguese': portuguese,
                    'duration': duration
                })

        if chunk_subtitles:  # Only create chunk if it has subtitles
            chunks.append({
                'start_time': current_start,
                'end_time': current_end,
                'subtitles': chunk_subtitles
            })

        current_start = current_end

    return chunks


def create_chunk_base_file(base_path: Path, subtitles: List[Dict], chunk_start_time: float) -> None:
    """
    Create a base.txt file for a specific chunk.

    Args:
        base_path: Path to the output base file
        subtitles: List of subtitle dictionaries for this chunk
        chunk_start_time: Start time of the chunk (to adjust timestamps)
    """
    try:
        with open(base_path, 'w', encoding='utf-8') as f:
            for i, subtitle in enumerate(subtitles, 1):
                # Adjust timestamps relative to chunk start
                adjusted_begin = subtitle['begin_time'] - chunk_start_time
                adjusted_end = subtitle['end_time'] - chunk_start_time

                # Ensure timestamps don't go negative
                adjusted_begin = max(0, adjusted_begin)
                adjusted_end = max(adjusted_begin + 0.1, adjusted_end)  # Minimum 0.1s duration

                line = (
                    f"{i}\t{adjusted_begin:.3f}s\t{adjusted_end:.3f}s\t"
                    f"{subtitle['chinese']}\t{subtitle['translations_json']}\t"
                    f"{subtitle['portuguese']}"
                )
                f.write(line + "\n")

    except Exception as e:
        print(f"   ❌ Erro ao criar arquivo base {base_path.name}: {e}")


def split_subtitles(directory_name: str) -> None:
    """
    Split subtitles from base file into chunks based on existing video chunks.

    Args:
        directory_name: Name of the directory inside assets/
    """
    print("🎬 Iniciando split de legendas...")
    print(f"   📁 Diretório: {directory_name}")

    # Define paths
    assets_dir = Path("assets")
    source_dir = assets_dir / directory_name
    sub_dir = assets_dir / f"{directory_name}_sub"

    # Check if directories exist
    if not source_dir.exists():
        print(f"   ❌ Diretório assets/{directory_name} não encontrado")
        return

    if not sub_dir.exists():
        print(f"   ❌ Pasta {directory_name}_sub não encontrada")
        print("   💡 Execute primeiro: python3 split_video.py {directory_name}")
        return

    # Find base file
    try:
        base_file = find_base_file(source_dir)
        print(f"   📄 Arquivo base encontrado: {base_file.name}")
    except FileNotFoundError as e:
        print(f"   ❌ {e}")
        return

    # Find video chunks
    video_chunks = find_video_chunks(sub_dir)
    if not video_chunks:
        print("   ❌ Nenhum chunk de vídeo encontrado na pasta _sub")
        print("   💡 Execute primeiro: python3 split_video.py {directory_name}")
        return

    print(f"   🎬 Encontrados {len(video_chunks)} chunks de vídeo")

    # Parse base file
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("   ❌ Não foi possível ler o arquivo base")
        return

    print(f"   📝 Total de legendas no arquivo base: {len(subtitles)}")

    # Sort subtitles by time
    sorted_subtitles = sorted(subtitles.items())

    # Process each video chunk
    for i, video_chunk in enumerate(video_chunks, 1):
        print(f"\n   🔄 Processando chunk {i:03d}/{len(video_chunks):03d}")
        print(f"   📁 Vídeo: {video_chunk.name}")

        # Get video duration
        video_duration = get_video_duration(video_chunk)
        if video_duration <= 0:
            print(f"   ⚠️  Não foi possível obter duração do vídeo {video_chunk.name}, pulando...")
            continue

        print(f"   ⏱️  Duração: {video_duration:.1f}s")

        # Calculate time offset for this chunk (based on chunk number)
        # Assuming each chunk is approximately 30 seconds
        chunk_start_time = (i - 1) * 30.0
        chunk_end_time = chunk_start_time + video_duration

        print(f"   📊 Tempo relativo: {chunk_start_time:.1f}s - {chunk_end_time:.1f}s")

        # Find subtitles that belong to this chunk
        chunk_subtitles = []
        for begin_time, (chinese, translations, json_trans, portuguese, duration) in sorted_subtitles:
            if chunk_start_time <= begin_time < chunk_end_time:
                # Adjust timestamp relative to chunk start
                adjusted_begin = begin_time - chunk_start_time
                adjusted_end = adjusted_begin + duration

                chunk_subtitles.append({
                    'begin_time': adjusted_begin,
                    'end_time': adjusted_end,
                    'chinese': chinese,
                    'translations': translations,
                    'translations_json': json_trans,
                    'portuguese': portuguese,
                    'duration': duration
                })

        print(f"   📝 Legendas encontradas: {len(chunk_subtitles)}")

        # Create base file for this chunk
        base_filename = f"{directory_name}_chromecast_chunk_{i:03d}_base.txt"
        chunk_base_path = sub_dir / base_filename

        if chunk_subtitles:
            create_chunk_base_file(chunk_base_path, chunk_subtitles, chunk_start_time)
            print(f"   ✅ Arquivo base criado: {chunk_base_path.name}")
        else:
            # Create empty base file if no subtitles found
            create_chunk_base_file(chunk_base_path, [], chunk_start_time)
            print(f"   📄 Arquivo base vazio criado: {chunk_base_path.name}")

    print(f"\n🎉 Split de legendas concluído! Processados {len(video_chunks)} chunks.")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Divide legendas de arquivo base em chunks baseados em vídeos já existentes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 split_subtitle.py mulher6     # Processa mulher6
  python3 split_subtitle.py onibus132   # Processa onibus132

Pré-requisitos:
- Pasta _sub deve existir com chunks (*_chunk_*.mp4)
- Arquivo base completo deve existir em assets/<nome>/
        """
    )

    parser.add_argument(
        "directory",
        help="Nome do diretório dentro de assets/ (ex: mulher6)"
    )

    args = parser.parse_args()

    try:
        split_subtitles(args.directory)
    except KeyboardInterrupt:
        print("\n⚠️  Interrompido pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
