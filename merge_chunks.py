#!/usr/bin/env python3
"""
Merge Chunks with Validation - Valida chunks processados e executa merge

Este script:
1. Varre a pasta *_sub correspondente ao parâmetro passado
2. Verifica se existem arquivos *_processed.mp4 na ordem sequencial (001, 002, etc.)
3. Se algum chunk não tiver seu respectivo _processed.mp4, copia o original e adiciona _processed no nome
4. Imprime na tela todos os arquivos processados encontrados/criados
5. Executa o merge de todos os arquivos _processed.mp4

Usage: python3 merge_chunks.py <directory_name>
Example: python3 merge_chunks.py mulher13
"""

import sys
import argparse
import subprocess
import os
import shutil
import re
from pathlib import Path
from typing import List, Tuple, Dict
import glob


def find_original_chunks(directory: Path) -> Dict[int, Path]:
    """
    Encontra todos os chunks originais no diretório e retorna um dicionário
    mapeando número do chunk -> caminho do arquivo.
    """
    chunk_dict = {}
    
    # Procurar por arquivos que seguem o padrão *_chunk_XXX.mp4 (não _processed)
    pattern = "*_chunk_*.mp4"
    for file_path in directory.glob(pattern):
        # Excluir arquivos _processed.mp4
        if "_processed.mp4" in file_path.name:
            continue
            
        # Extrair número do chunk
        match = re.search(r'_chunk_(\d+)\.mp4$', file_path.name)
        if match:
            chunk_number = int(match.group(1))
            chunk_dict[chunk_number] = file_path
    
    return chunk_dict


def find_processed_chunks(directory: Path) -> Dict[int, Path]:
    """
    Encontra todos os chunks processados no diretório e retorna um dicionário
    mapeando número do chunk -> caminho do arquivo.
    """
    processed_dict = {}
    
    # Procurar por arquivos que terminam com _processed.mp4
    pattern = "*_processed.mp4"
    for file_path in directory.glob(pattern):
        # Extrair número do chunk
        match = re.search(r'_chunk_(\d+)_processed\.mp4$', file_path.name)
        if match:
            chunk_number = int(match.group(1))
            processed_dict[chunk_number] = file_path
    
    return processed_dict


def validate_and_create_missing_processed(directory: Path) -> Tuple[Dict[int, Path], List[Path]]:
    """
    Valida chunks e cria arquivos _processed.mp4 faltantes.
    Retorna (dicionário_de_processados, lista_de_arquivos_criados).
    """
    print(f"🔍 Varrendo pasta: {directory.name}")
    
    original_chunks = find_original_chunks(directory)
    processed_chunks = find_processed_chunks(directory)
    
    print(f"📊 Chunks originais encontrados: {len(original_chunks)}")
    print(f"📊 Chunks processados existentes: {len(processed_chunks)}")
    
    if not original_chunks:
        print("❌ Nenhum chunk original encontrado!")
        return processed_chunks, []
    
    # Determinar sequência esperada
    min_chunk = min(original_chunks.keys())
    max_chunk = max(original_chunks.keys())
    
    print(f"📈 Validando sequência de {min_chunk:03d} até {max_chunk:03d}...")
    
    created_files = []
    missing_count = 0
    
    # Verificar cada chunk na sequência
    for chunk_num in range(min_chunk, max_chunk + 1):
        if chunk_num not in processed_chunks:
            if chunk_num in original_chunks:
                # Chunk original existe, mas não tem versão processada
                original_file = original_chunks[chunk_num]
                
                # Criar nome do arquivo processado
                processed_name = original_file.name.replace('.mp4', '_processed.mp4')
                processed_path = directory / processed_name
                
                try:
                    print(f"📋 Criando: {chunk_num:03d} - {original_file.name} -> {processed_name}")
                    shutil.copy2(original_file, processed_path)
                    
                    # Adicionar ao dicionário de processados e à lista de criados
                    processed_chunks[chunk_num] = processed_path
                    created_files.append(processed_path)
                    
                except Exception as e:
                    print(f"❌ Erro ao copiar chunk {chunk_num:03d}: {e}")
            else:
                print(f"⚠️  Chunk {chunk_num:03d} não encontrado (nem original nem processado)")
                missing_count += 1
    
    # Resumo da validação
    if created_files:
        print(f"✅ Criados {len(created_files)} arquivos _processed.mp4")
    else:
        print("✅ Todos os chunks já possuem versão processada")
    
    if missing_count > 0:
        print(f"⚠️  {missing_count} chunks estão faltando completamente")
    
    return processed_chunks, created_files


def display_processed_files_list(processed_chunks: Dict[int, Path]) -> List[Path]:
    """
    Exibe lista completa de arquivos processados em ordem.
    Retorna lista ordenada de arquivos para o merge.
    """
    if not processed_chunks:
        print("\n❌ Nenhum arquivo processado disponível")
        return []
    
    print(f"\n📋 LISTA COMPLETA DE ARQUIVOS PROCESSADOS:")
    print("=" * 70)
    
    # Ordenar por número do chunk
    sorted_chunks = sorted(processed_chunks.items())
    file_list = []
    
    for i, (chunk_num, file_path) in enumerate(sorted_chunks, 1):
        print(f"  {i:3d}. [{chunk_num:03d}] {file_path.name}")
        file_list.append(file_path)
    
    print(f"\n📊 Total de arquivos processados prontos para merge: {len(file_list)}")
    
    return file_list


def create_concat_list(chunk_files: List[Path], list_file: Path) -> bool:
    """
    Cria arquivo de lista para concatenação FFmpeg.
    """
    try:
        with open(list_file, 'w', encoding='utf-8') as f:
            for chunk_file in chunk_files:
                # Escrever caminho absoluto para evitar problemas
                f.write(f"file '{chunk_file.absolute()}'\n")

        print(f"📄 Lista de concatenação criada: {list_file.name}")
        return True

    except Exception as e:
        print(f"❌ Erro ao criar lista de concatenação: {e}")
        return False


def merge_processed_chunks(chunk_files: List[Path], output_file: Path) -> bool:
    """
    Executa o merge de todos os chunks processados usando FFmpeg.
    """
    if not chunk_files:
        print("❌ Nenhum arquivo processado encontrado para mergear")
        return False

    print(f"\n🎬 EXECUTANDO MERGE DOS ARQUIVOS PROCESSADOS")
    print("=" * 60)
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

        print(f"\n🔄 Executando FFmpeg concat...")
        print(f"💡 Comando: {' '.join(cmd[:6])} ... {output_file.name}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Limpar arquivo de lista temporário
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
                print(f"📁 Tamanho do arquivo final: {size_mb:.1f} MB")
                
                # Verificar duração (opcional)
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
                            print(f"⏱️  Duração: {minutes}m {seconds:.1f}s")
                except:
                    pass

            return True
        else:
            print("❌ Erro no FFmpeg concat")
            if result.stderr:
                print(f"📄 Detalhes do erro: {result.stderr}")
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
    """Verifica se FFmpeg está disponível."""
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Valida chunks processados e executa merge da pasta especificada",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Funcionamento detalhado:
  1. Varre a pasta <directory_name>_sub
  2. Verifica se existem arquivos *_processed.mp4 na ordem sequencial
  3. Cria arquivos _processed faltantes copiando os originais
  4. Imprime lista completa de arquivos processados
  5. Executa merge usando FFmpeg

Exemplos:
  python3 merge_chunks.py mulher13     # Processa pasta mulher13_sub/
  python3 merge_chunks.py onibus152    # Processa pasta onibus152_sub/

Requisitos:
  - FFmpeg deve estar instalado
  - Pasta <directory_name>_sub deve existir no diretório assets
  - Chunks devem seguir padrão: *_chunk_XXX.mp4
        """
    )

    parser.add_argument('directory', help='Nome do diretório (sem _sub)')

    args = parser.parse_args()

    # Construir caminhos
    source_dir = Path('assets') / f"{args.directory}_sub"
    output_file = source_dir / f"{args.directory}_chromecast_merged.mp4"

    print("🎬 Merge Chunks com Validação")
    print("=" * 60)
    print(f"📂 Pasta alvo: {source_dir}")
    print(f"📁 Arquivo destino: {output_file.name}")

    # Verificar disponibilidade do FFmpeg
    if not check_ffmpeg():
        print("\n❌ Erro: FFmpeg não encontrado!")
        print("   Instale FFmpeg:")
        print("   • macOS: brew install ffmpeg")
        print("   • Ubuntu: sudo apt install ffmpeg")
        print("   • Windows: baixe de https://ffmpeg.org/")
        return 1

    # Verificar se o diretório fonte existe
    if not source_dir.exists():
        print(f"\n❌ Erro: Diretório {source_dir} não encontrado")
        print(f"   Certifique-se de que a pasta {args.directory}_sub existe no diretório assets")
        return 1

    try:
        print(f"\n🚀 INICIANDO PROCESSAMENTO...")
        
        # Etapa 1: Validar e criar arquivos processados faltantes
        print(f"\n📋 ETAPA 1: Validação de chunks processados")
        processed_chunks, created_files = validate_and_create_missing_processed(source_dir)

        if not processed_chunks:
            print("❌ Nenhum chunk processado disponível")
            return 1

        # Etapa 2: Exibir lista completa de arquivos processados
        print(f"\n📋 ETAPA 2: Lista de arquivos para merge")
        final_file_list = display_processed_files_list(processed_chunks)

        if not final_file_list:
            print("❌ Nenhum arquivo disponível para merge")
            return 1

        # Verificar se arquivo de saída já existe
        if output_file.exists():
            print(f"\n⚠️  Arquivo {output_file.name} já existe")
            response = input("   Deseja sobrescrever? (y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                print("❌ Operação cancelada pelo usuário")
                return 0

        # Etapa 3: Executar merge
        print(f"\n📋 ETAPA 3: Merge final")
        if merge_processed_chunks(final_file_list, output_file):
            print(f"\n🎉 PROCESSO CONCLUÍDO COM SUCESSO!")
            print(f"📊 Resumo:")
            print(f"   • Arquivos _processed criados: {len(created_files)}")
            print(f"   • Total de chunks unidos: {len(final_file_list)}")
            print(f"   • Arquivo final: {output_file}")
            return 0
        else:
            print("❌ Falha no merge")
            return 1

    except KeyboardInterrupt:
        print("\n❌ Operação interrompida pelo usuário")
        return 1
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())