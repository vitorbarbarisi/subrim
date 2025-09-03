#!/usr/bin/env python3
"""
Merge Chunks - Junta todos os chunks de vídeo em um único arquivo

Usage: python3 merge_chunks.py <directory_name>
Example: python3 merge_chunks.py onibus132

O script:
1. Encontra todos os chunks na pasta <directory_name>_sub
2. Cria uma lista de concatenação para FFmpeg
3. Junta todos os chunks em um vídeo _merged.mp4
4. Mantém todos os arquivos originais
"""

import sys
import argparse
import subprocess
import os
from pathlib import Path
from typing import List


def find_chunk_files(directory: Path) -> List[Path]:
    """
    Encontra todos os arquivos de chunk (MP4) no diretório,
    ordenados numericamente.
    """
    chunk_files = []

    # Procurar por arquivos que contenham "chunk" no nome
    for file_path in directory.glob("*chunk*.mp4"):
        chunk_files.append(file_path)

    # Ordenar por nome (chunk_001, chunk_002, etc.)
    chunk_files.sort(key=lambda x: x.name)

    return chunk_files


def create_concat_list(chunk_files: List[Path], list_file: Path) -> bool:
    """
    Cria arquivo de lista para concatenação FFmpeg.
    """
    try:
        with open(list_file, 'w', encoding='utf-8') as f:
            for chunk_file in chunk_files:
                # Escrever caminho absoluto para evitar problemas
                f.write(f"file '{chunk_file.absolute()}'\n")

        print(f"📄 Lista de concatenação criada: {list_file}")
        print(f"📊 Total de chunks para mergear: {len(chunk_files)}")

        # Mostrar preview dos primeiros chunks
        for i, chunk in enumerate(chunk_files[:5], 1):
            print(f"   {i:2d}. {chunk.name}")

        if len(chunk_files) > 5:
            print(f"   ... e mais {len(chunk_files) - 5} chunks")

        return True

    except Exception as e:
        print(f"❌ Erro ao criar lista de concatenação: {e}")
        return False


def merge_chunks(chunk_files: List[Path], output_file: Path) -> bool:
    """
    Junta todos os chunks usando FFmpeg concat.
    """
    if not chunk_files:
        print("❌ Nenhum chunk encontrado para mergear")
        return False

    print("\n🎬 Iniciando merge dos chunks...")
    print(f"📁 Arquivo de saída: {output_file.name}")
    print(f"📊 Total de chunks: {len(chunk_files)}")

    # Criar arquivo de lista temporário
    list_file = output_file.parent / "concat_list.txt"

    try:
        # Criar lista de concatenação
        if not create_concat_list(chunk_files, list_file):
            return False

        # Comando FFmpeg para concatenação
        cmd = [
            'ffmpeg',
            '-f', 'concat',           # Usar modo concat
            '-safe', '0',             # Permitir caminhos absolutos
            '-i', str(list_file),     # Arquivo de lista
            '-c', 'copy',             # Copiar streams sem re-encoding
            '-y',                     # Sobrescrever se existir
            str(output_file)
        ]

        print("\n🔄 Executando FFmpeg concat...")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Limpar arquivo de lista
        try:
            list_file.unlink()
            print("🧹 Arquivo de lista temporário removido")
        except:
            pass

        if result.returncode == 0:
            print("✅ Merge concluído com sucesso!")

            # Mostrar informações do arquivo resultante
            if output_file.exists():
                size_mb = output_file.stat().st_size / (1024 * 1024)
                print(".1f")
                # Verificar duração aproximada (opcional)
                try:
                    duration_cmd = [
                        'ffprobe',
                        '-v', 'quiet',
                        '-print_format', 'json',
                        '-show_format',
                        str(output_file)
                    ]
                    duration_result = subprocess.run(duration_cmd, capture_output=True, text=True, check=False)
                    if duration_result.returncode == 0:
                        import json
                        data = json.loads(duration_result.stdout)
                        duration = float(data.get('format', {}).get('duration', 0))
                        if duration > 0:
                            minutes = int(duration // 60)
                            seconds = duration % 60
                            print(".1f")
                except:
                    pass

            return True
        else:
            print("❌ Erro no FFmpeg concat")
            print(f"📄 STDERR: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Erro durante o merge: {e}")
        # Limpar arquivo de lista em caso de erro
        try:
            if list_file.exists():
                list_file.unlink()
        except:
            pass
        return False


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Junta todos os chunks de vídeo em um único arquivo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 merge_chunks.py onibus132    # Junta chunks em onibus132_sub/

Funcionamento:
  1. Encontra todos os chunks na pasta <directory_name>_sub
  2. Cria lista de concatenação para FFmpeg
  3. Junta todos os chunks em _merged.mp4
  4. Mantém todos os arquivos originais

Requisitos:
  - FFmpeg deve estar instalado
  - Chunks devem estar na pasta _sub
  - Arquivos devem seguir padrão: *chunk*.mp4
        """
    )

    parser.add_argument('directory', help='Nome do diretório (sem _sub)')

    args = parser.parse_args()

    # Construct paths
    source_dir = Path('assets') / f"{args.directory}_sub"
    output_file = source_dir / f"{args.directory}_chromecast_merged.mp4"

    print("🎬 Merge Chunks - Junta chunks em vídeo único")
    print("=" * 50)
    print(f"📁 Diretório fonte: {source_dir}")
    print(f"📁 Arquivo destino: {output_file.name}")

    # Check FFmpeg availability
    if not check_ffmpeg():
        print("❌ Erro: FFmpeg não encontrado!")
        print("   Instale FFmpeg:")
        print("   macOS: brew install ffmpeg")
        print("   Ubuntu: sudo apt install ffmpeg")
        return 1

    # Check if source directory exists
    if not source_dir.exists():
        print(f"❌ Erro: Diretório {source_dir} não encontrado")
        return 1

    try:
        # Find chunk files
        print("\n🔍 Procurando chunks...")
        chunk_files = find_chunk_files(source_dir)

        if not chunk_files:
            print(f"❌ Nenhum arquivo de chunk encontrado em {source_dir}")
            print("   Certifique-se de que os arquivos seguem o padrão: *chunk*.mp4")
            return 1

        print(f"✅ Encontrados {len(chunk_files)} chunks")

        # Check if output file already exists
        if output_file.exists():
            print(f"⚠️  Arquivo {output_file.name} já existe")
            response = input("   Deseja sobrescrever? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print("❌ Operação cancelada pelo usuário")
                return 0

        # Merge chunks
        if merge_chunks(chunk_files, output_file):
            print("\n🎉 Merge concluído!")
            print(f"📁 Arquivo final: {output_file}")
            print("💡 Arquivos originais mantidos intactos")
            return 0
        else:
            print("❌ Falha no merge")
            return 1

    except KeyboardInterrupt:
        print("\n❌ Operação interrompida pelo usuário")
        return 1
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
