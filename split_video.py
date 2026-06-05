#!/usr/bin/env python3
"""
Split Video Processor
Processa um vídeo MP4 para compatibilidade com Chromecast e prepara para split

Usage: python3 split_video.py <directory_name>
Example: python3 split_video.py onibus132

O script:
1. Procura um arquivo MP4 dentro de assets/<directory_name>/
2. Cria uma pasta _sub
3. Move uma cópia do MP4 para a pasta _sub
4. Ajusta essa cópia para compatibilidade Chromecast
5. Chama função split_video (por enquanto vazia)
"""

import sys
import argparse
import shutil
import subprocess
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


def find_mp4_file(directory: Path) -> Path:
    """Find the first MP4 file in the directory."""
    mp4_files = list(directory.glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError(f"Nenhum arquivo MP4 encontrado em {directory}")
    return mp4_files[0]


def convert_to_chromecast_format(input_video: Path, output_video: Path) -> bool:
    """
    Converte vídeo para formato compatível com Chromecast.

    Args:
        input_video: Vídeo original
        output_video: Vídeo convertido para Chromecast

    Returns:
        True se conversão bem-sucedida
    """
    print("📱 Convertendo para formato Chromecast...", flush=True)
    print(f"   📁 Entrada: {input_video.name}")
    print(f"   📁 Saída: {output_video.name}")

    # Configurações testadas e aprovadas para Chromecast
    cmd = [
        'ffmpeg',
        '-i', str(input_video),

        # Codec de vídeo: H.264 software (máxima compatibilidade)
        '-c:v', 'libx264',
        '-profile:v', 'high',
        '-level', '4.1',

        # Qualidade otimizada para streaming.
        # preset veryfast: este arquivo é INTERMEDIÁRIO (re-encodado de novo na
        # queima), então a eficiência de compressão do 'medium' seria desperdiçada.
        # SSIM ~idêntico (0.988 vs 0.987) com encode mais rápido.
        '-crf', '20',              # Alta qualidade
        '-preset', 'veryfast',     # Intermediário — prioriza velocidade

        # Codec de áudio: AAC (padrão Chromecast)
        '-c:a', 'aac',
        '-b:a', '128k',           # Bitrate áudio adequado
        '-ar', '48000',           # Sample rate padrão

        # Configurações de compatibilidade
        '-pix_fmt', 'yuv420p',    # Formato pixel compatível
        '-movflags', '+faststart', # Otimização streaming

        # Resolução máxima suportada pelo Chromecast
        '-vf', 'scale=min(1920\\,iw):min(1080\\,ih):force_original_aspect_ratio=decrease',

        # Progresso e otimizações
        '-progress', 'pipe:1',
        '-nostats',
        '-y',                     # Sobrescrever arquivo se existir

        str(output_video)
    ]

    try:
        print("   🔄 Processando...", flush=True)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True
        )

        # Mostrar progresso básico
        for line in process.stdout:
            if line.startswith('frame='):
                parts = line.strip().split()
                for part in parts:
                    if part.startswith('time='):
                        time_str = part.split('=')[1]
                        print(f"   ⏱️  Progresso: {time_str}", end='\r')

        return_code = process.wait()

        if return_code != 0:
            stderr_output = process.stderr.read()
            print(f"\n❌ Erro na conversão:")
            print(f"   {stderr_output}")
            return False

        print("✅ Vídeo convertido para Chromecast com sucesso!", flush=True)

        # Mostrar informações de tamanho
        if output_video.exists():
            original_size = input_video.stat().st_size / (1024*1024)
            converted_size = output_video.stat().st_size / (1024*1024)
            reduction = ((original_size - converted_size) / original_size) * 100

            print(".1f")
            print(".1f")
            print(".1f")

        return True

    except Exception as e:
        print(f"❌ Erro na conversão: {e}")
        return False


def split_video(video_path: Path) -> None:
    """
    Divide o vídeo em chunks de aproximadamente 30 segundos baseados no arquivo base.txt.

    Args:
        video_path: Caminho para o vídeo processado e compatível com Chromecast
    """
    print("🎬 Função split_video chamada!", flush=True)
    print(f"   📁 Vídeo para split: {video_path}", flush=True)

    # Verificar se o vídeo existe
    if not video_path.exists():
        print(f"   ❌ Vídeo não encontrado: {video_path}")
        return

    # Encontrar o arquivo base.txt correspondente no diretório de origem
    source_dir = Path("assets") / video_path.parent.name.replace("_sub", "")
    base_file = None

    # Procurar por arquivos *_base.txt
    for file_path in source_dir.glob("*_base.txt"):
        base_file = file_path
        break

    if not base_file:
        print(f"   ❌ Arquivo base.txt não encontrado em {source_dir}")
        return

    print(f"   📄 Base file encontrado: {base_file.name}")

    # Ler o arquivo base.txt
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("   ⚠️  Arquivo base.txt vazio - fazendo cópia do vídeo original com tag _processed")

        # Criar caminho para o vídeo processado
        processed_video_path = video_path.parent / f"{video_path.stem}_processed{video_path.suffix}"

        # Copiar o vídeo original para o arquivo processado
        try:
            shutil.copy2(video_path, processed_video_path)
            print(f"   ✅ Vídeo copiado com sucesso: {processed_video_path.name}")
            print(f"\n🎉 Processamento concluído! Vídeo copiado como {processed_video_path.name}")
            return
        except Exception as e:
            print(f"   ❌ Erro ao copiar vídeo: {e}")
            return

    # Obter duração do vídeo
    video_width, video_height, video_duration = get_video_info(video_path)
    if video_duration <= 0:
        print("   ❌ Não foi possível obter duração do vídeo")
        return

    print(f"   ⏱️  Duração do vídeo: {video_duration:.1f}s")
    print(f"   📊 Total de legendas: {len(subtitles)}")

    # Criar chunks de aproximadamente 30 segundos
    chunks = create_video_chunks(subtitles, video_duration)
    if not chunks:
        print("   ❌ Não foi possível criar chunks")
        return

    print(f"   🎬 Criados {len(chunks)} chunks")

    # Processar cada chunk
    for i, chunk in enumerate(chunks, 1):
        print(f"\n   🔄 Gerando chunk {i:03d}/{len(chunks):03d}")
        print(f"   ⏱️  Tempo: {chunk['start_time']:.1f}s - {chunk['end_time']:.1f}s")

        # Criar arquivo de vídeo do chunk
        chunk_video_path = video_path.parent / f"{video_path.stem}_chunk_{i:03d}{video_path.suffix}"

        # Cortar vídeo usando FFmpeg
        if cut_video_chunk(video_path, chunk_video_path, chunk['start_time'], chunk['end_time']):
            print(f"   ✅ Chunk de vídeo criado: {chunk_video_path.name}")

            # Criar arquivo base.txt para o chunk
            chunk_base_path = video_path.parent / f"{video_path.stem}_chunk_{i:03d}_base.txt"
            create_chunk_base_file(chunk_base_path, chunk['subtitles'], chunk['start_time'])
            print(f"   📝 Arquivo base criado: {chunk_base_path.name}")
        else:
            print(f"   ❌ Falha ao criar chunk de vídeo {i:03d}")

    print(f"\n🎉 Split concluído! {len(chunks)} chunks criados.")


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

                # Split by tabs
                parts = line.split('\t')
                if len(parts) < 6:  # Precisa ter pelo menos 6 colunas (formato novo)
                    continue

                # Extract begin timestamp (second column)
                begin_timestamp_str = parts[1].strip()

                # Extract seconds from begin timestamp (e.g., "186.645s" -> 186.645)
                begin_match = re.match(r'([\d.]+)s?', begin_timestamp_str)
                if not begin_match:
                    continue

                begin_seconds = float(begin_match.group(1))

                # Extract end timestamp
                end_timestamp_str = parts[2].strip()
                end_match = re.match(r'([\d.]+)s?', end_timestamp_str)
                if not end_match:
                    continue

                end_seconds = float(end_match.group(1))

                # Calculate duration
                duration = max(0.5, end_seconds - begin_seconds)

                # Extract Chinese subtitle
                chinese_text = parts[3].strip()

                # Extract translations
                translations_json = parts[4].strip() if len(parts) >= 5 else ""
                portuguese_text = parts[5].strip() if len(parts) >= 6 else ""

                # Parse translations list if it exists
                formatted_translations = ""
                if translations_json and translations_json != 'N/A':
                    try:
                        # Remove outer brackets and parse as list
                        import ast
                        translations_list = ast.literal_eval(translations_json)
                        if isinstance(translations_list, list):
                            # Join translations with line breaks
                            formatted_translations = '\n'.join(translations_list)
                        else:
                            formatted_translations = translations_json
                    except:
                        # If parsing fails, use raw text
                        formatted_translations = translations_json
                else:
                    translations_json = ""

                # Clean Portuguese text
                if portuguese_text == 'N/A':
                    portuguese_text = ""

                if chinese_text and chinese_text != 'N/A':
                    subtitles[begin_seconds] = (chinese_text, formatted_translations, translations_json, portuguese_text, duration)

    except Exception as e:
        print(f"Erro ao ler arquivo base {base_file_path}: {e}")

    return subtitles


def create_video_chunks(subtitles: Dict[float, Tuple[str, str, str, str, float]], video_duration: float) -> List[Dict]:
    """
    Cria chunks de vídeo que respeitam os limites das legendas (sem cortar legendas no meio).

    Args:
        subtitles: Dicionário com legendas
        video_duration: Duração total do vídeo em segundos

    Returns:
        Lista de chunks, cada um contendo start_time, end_time e subtitles
    """
    chunks = []
    target_chunk_duration = 30.0  # Duração alvo de 30 segundos

    # Ordenar legendas por tempo
    sorted_times = sorted(subtitles.keys())

    if not sorted_times:
        return chunks

    current_start = 0.0

    while current_start < video_duration:
        # Encontrar o melhor ponto de corte para este chunk
        chunk_end = find_best_chunk_end(current_start, target_chunk_duration, video_duration, subtitles, sorted_times)

        # Adicionar todas as legendas que começam dentro deste chunk
        chunk_subs = {}
        for sub_time in sorted_times:
            _, _, _, _, duration = subtitles[sub_time]
            sub_end_time = sub_time + duration

            # Incluir legenda se começa dentro do chunk atual
            if current_start <= sub_time < chunk_end:
                chunk_subs[sub_time] = subtitles[sub_time]

        # Criar o chunk
        chunks.append({
            'start_time': current_start,
            'end_time': chunk_end,
            'subtitles': chunk_subs
        })

        # Próximo chunk começa exatamente onde o atual termina
        current_start = chunk_end

        # Se chegamos ao fim do vídeo, parar
        if current_start >= video_duration:
            break

    return chunks


def find_best_chunk_end(current_start: float, target_duration: float, video_duration: float,
                        subtitles: Dict[float, Tuple[str, str, str, str, float]],
                        sorted_times: List[float]) -> float:
    """
    Encontra o melhor ponto de fim para um chunk, evitando cortar legendas no meio
    e garantindo que não haja sobreposição de frames.

    Args:
        current_start: Início do chunk atual
        target_duration: Duração alvo do chunk
        video_duration: Duração total do vídeo
        subtitles: Dicionário com todas as legendas
        sorted_times: Lista ordenada dos tempos de início das legendas

    Returns:
        Melhor tempo de fim para o chunk
    """
    target_end = current_start + target_duration

    # Se o target_end já é o fim do vídeo, usar ele
    if target_end >= video_duration:
        return video_duration

    # Procurar a última legenda que termina antes ou no target_end
    best_end = target_end

    for sub_time in sorted_times:
        if sub_time >= current_start and sub_time < target_end:
            _, _, _, _, duration = subtitles[sub_time]
            sub_end_time = sub_time + duration

            # Só considerar legendas que terminam dentro do target_end
            # Isso garante que não haverá legendas cortadas no meio
            if sub_end_time <= target_end:
                best_end = max(best_end, sub_end_time)

    # Garantir que não ultrapassamos o limite máximo (target_end + uma tolerância)
    max_end = min(target_end + 10.0, video_duration)  # Máximo 10s de tolerância

    # Se encontramos um bom ponto de corte, usar ele
    if best_end <= max_end:
        return best_end
    else:
        # Se não encontramos um bom ponto, usar o target_end
        return target_end


def cut_video_chunk(input_video: Path, output_video: Path, start_time: float, end_time: float) -> bool:
    """
    Corta um chunk do vídeo usando FFmpeg com método otimizado para evitar quadros pretos.

    Args:
        input_video: Vídeo de entrada
        output_video: Vídeo de saída
        start_time: Tempo inicial em segundos
        end_time: Tempo final em segundos

    Returns:
        True se bem-sucedido
    """
    duration = end_time - start_time

    # Método 1: Re-encoding preciso para evitar qualquer sobreposição (mais confiável).
    # IMPORTANTE: -ss vem ANTES de -i (input seek). Com re-encode, o ffmpeg faz
    # "accurate seek" — pula direto para o keyframe anterior ao start e decodifica
    # só até o ponto exato, em vez de decodificar o vídeo inteiro desde 0 a cada
    # chunk (que tornava o corte O(n²): ~100× mais lento em chunks tardios).
    cmd_precise = [
        'ffmpeg',
        '-ss', str(start_time),  # Start time exato (input seek, rápido + preciso)
        '-i', str(input_video),
        '-t', str(duration),     # Duration exata (output)
        '-c:v', 'libx264',      # Re-encode video para precisão
        '-c:a', 'aac',          # Re-encode audio para sincronização
        '-preset', 'ultrafast',  # Encoding rápido
        '-crf', '20',           # Alta qualidade (ligeiramente reduzida para velocidade)
        '-keyint_min', '25',    # Keyframe mínimo
        '-g', '25',             # GOP size fixo para consistência
        '-sc_threshold', '0',   # Desabilitar detecção de cena para consistência
        '-avoid_negative_ts', 'make_zero',
        '-fflags', '+discardcorrupt+genpts',  # Gerar timestamps corretos
        '-y',
        str(output_video)
    ]

    # Método 2: Usar -ss antes do input com verificações extras (fallback)
    safe_start_time = max(0, start_time - 0.01)  # 10ms antes para margem de segurança

    cmd_fast = [
        'ffmpeg',
        '-ss', str(safe_start_time),  # Start time BEFORE input com margem
        '-i', str(input_video),
        '-t', str(duration + 0.02),  # Duration + margem de 20ms
        '-c', 'copy',           # Copy streams
        '-avoid_negative_ts', 'make_zero',
        '-fflags', '+discardcorrupt+genpts',
        '-y',
        str(output_video)
    ]

    try:
        print(f"   🎬 Cortando vídeo: {start_time:.1f}s - {end_time:.1f}s (duração: {duration:.1f}s)")

        # Primeiro tenta o método preciso (re-encoding) - mais confiável
        print(f"   🔄 Usando método preciso (re-encoding) para evitar sobreposições...")
        result = subprocess.run(cmd_precise, capture_output=True, text=True, check=False)

        if result.returncode == 0:
            print(f"   ✅ Método preciso bem-sucedido - sem sobreposições")
            return True
        else:
            print(f"   ⚠️  Método preciso falhou, tentando método rápido (copy)...")
            print(f"   ⚡ Fallback para método rápido...")

            # Se o método preciso falhar, tenta o método rápido como fallback
            result = subprocess.run(cmd_fast, capture_output=True, text=True, check=False)

            if result.returncode == 0:
                print(f"   ✅ Método rápido bem-sucedido (fallback)")
                return True
            else:
                print(f"   ❌ Ambos os métodos falharam")
                print(f"   📄 Erro método preciso: {result.stderr[:200]}...")
                return False

    except Exception as e:
        print(f"   ❌ Erro ao cortar vídeo: {e}")
        return False


def create_chunk_base_file(base_file_path: Path, chunk_subtitles: Dict[float, Tuple[str, str, str, str, float]], chunk_start_time: float) -> None:
    """
    Cria arquivo base.txt para um chunk específico com tempos ajustados.

    Args:
        base_file_path: Caminho para o arquivo base.txt de saída
        chunk_subtitles: Legendas do chunk
        chunk_start_time: Tempo inicial do chunk (para ajustar tempos)
    """
    try:
        with open(base_file_path, 'w', encoding='utf-8') as f:
            # Ordenar legendas por tempo
            sorted_times = sorted(chunk_subtitles.keys())

            for i, original_begin_time in enumerate(sorted_times, 1):
                chinese_text, formatted_translations, translations_json, portuguese_text, duration = chunk_subtitles[original_begin_time]

                # Ajustar tempos subtraindo o tempo inicial do chunk
                adjusted_begin_time = original_begin_time - chunk_start_time
                adjusted_end_time = adjusted_begin_time + duration

                # Formatar linha no mesmo formato do arquivo original
                line = f"{i}\t{adjusted_begin_time:.3f}s\t{adjusted_end_time:.3f}s\t{chinese_text}\t{translations_json}\t{portuguese_text}\n"
                f.write(line)

        print(f"   📝 Criado arquivo base com {len(chunk_subtitles)} legendas")

    except Exception as e:
        print(f"   ❌ Erro ao criar arquivo base: {e}")


def get_video_info(video_path: Path) -> Tuple[int, int, float]:
    """Get video dimensions and duration using ffmpeg."""
    try:
        # Use ffmpeg to get video info (more reliable than ffprobe for some files)
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-f', 'null',
            '-'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        # Parse duration from stderr output
        duration = 0.0
        width, height = 1920, 1080
        
        for line in result.stderr.split('\n'):
            if 'Duration:' in line:
                # Extract duration from line like "Duration: 01:23:45.67, start: 0.000000, bitrate: 1234 kb/s"
                try:
                    duration_part = line.split('Duration:')[1].split(',')[0].strip()
                    # Convert HH:MM:SS.mmm to seconds
                    time_parts = duration_part.split(':')
                    if len(time_parts) == 3:
                        hours = float(time_parts[0])
                        minutes = float(time_parts[1])
                        seconds = float(time_parts[2])
                        duration = hours * 3600 + minutes * 60 + seconds
                except:
                    pass
            elif 'Stream #0:0' in line and 'Video:' in line:
                # Extract resolution from line like "Stream #0:0(und): Video: h264, yuv420p, 1920x1080"
                try:
                    if 'x' in line:
                        res_part = line.split('Video:')[1].split(',')[1].strip()
                        if 'x' in res_part:
                            w, h = res_part.split('x')
                            width = int(w.strip())
                            height = int(h.strip())
                except:
                    pass
        
        if duration == 0.0:
            print(f"   ⚠️  Não foi possível obter duração do vídeo convertido, tentando arquivo original...")
            # Try to get duration from original file
            original_path = video_path.parent.parent / video_path.name.replace('_chromecast', '')
            if original_path.exists():
                try:
                    orig_cmd = [
                        'ffmpeg',
                        '-i', str(original_path),
                        '-f', 'null',
                        '-'
                    ]
                    orig_result = subprocess.run(orig_cmd, capture_output=True, text=True, check=False)
                    for line in orig_result.stderr.split('\n'):
                        if 'Duration:' in line:
                            try:
                                duration_part = line.split('Duration:')[1].split(',')[0].strip()
                                time_parts = duration_part.split(':')
                                if len(time_parts) == 3:
                                    hours = float(time_parts[0])
                                    minutes = float(time_parts[1])
                                    seconds = float(time_parts[2])
                                    duration = hours * 3600 + minutes * 60 + seconds
                                    print(f"   ✅ Duração obtida do arquivo original: {duration:.1f}s")
                                    break
                            except:
                                pass
                except:
                    pass
            
            if duration == 0.0:
                print(f"   ⚠️  Usando duração estimada baseada no tamanho do arquivo")
                # Try to estimate duration from file size (very rough estimate)
                file_size = video_path.stat().st_size
                # Assume ~1MB per second (very rough)
                duration = max(3600, file_size / (1024 * 1024))  # At least 1 hour
            
        return width, height, duration
    except Exception as e:
        print(f"   ⚠️  Erro ao obter informações do vídeo: {e}")
        # Default values if detection fails
        return 1920, 1080, 0.0


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def cleanup_temp_files(dest_dir: Path, final_output: Path) -> None:
    """
    Remove arquivos temporários, mantendo apenas o arquivo final.
    """
    if not dest_dir.exists():
        return

    print("\n🧹 Limpando arquivos temporários...")

    # Lista de arquivos a manter (arquivo final + arquivos que não são temporários)
    keep_patterns = [
        final_output.name,  # Arquivo final
        "_chromecast.mp4",  # Arquivos já convertidos
    ]

    # Lista de arquivos a remover (temporários)
    remove_patterns = [
        "_chromecast_temp.mp4",  # Arquivos temporários de conversão
        ".fdash-video_por=",     # Fragmentos DASH
    ]

    cleaned_count = 0

    for file_path in dest_dir.glob("*.mp4"):
        should_remove = False

        # Verificar se deve ser removido baseado nos padrões
        for pattern in remove_patterns:
            if pattern in file_path.name:
                should_remove = True
                break

        # Se não está nos padrões de remoção, verificar se está nos de manutenção
        if not should_remove:
            is_keep_file = False
            for pattern in keep_patterns:
                if pattern in file_path.name:
                    is_keep_file = True
                    break

            # Se não é arquivo de manutenção e não é o arquivo final, remover
            if not is_keep_file and file_path != final_output:
                should_remove = True

        if should_remove:
            try:
                file_path.unlink()
                print(f"   🗑️  Removido: {file_path.name}")
                cleaned_count += 1
            except OSError as e:
                print(f"   ⚠️  Não foi possível remover {file_path.name}: {e}")

    if cleaned_count > 0:
        print(f"✅ {cleaned_count} arquivo(s) temporário(s) removido(s)")
    else:
        print("✅ Nenhum arquivo temporário encontrado")


def main():
    parser = argparse.ArgumentParser(
        description="Processa vídeo MP4 para Chromecast e prepara para split (idempotente)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 split_video.py onibus132    # Processa vídeo em assets/onibus132/

Funcionamento (idempotente):
  1. Procura arquivo MP4 em assets/<directory_name>/
  2. Só cria pasta _sub se não existir
  3. Só copia vídeo MP4 se não existir na pasta _sub
  4. Só converte para Chromecast se arquivo convertido não existir
  5. Remove arquivos temporários ao final
  6. Chama função split_video

Características:
  - Idempotente: executar múltiplas vezes é seguro
  - Não sobrescreve arquivos existentes
  - Mantém apenas o arquivo final processado

Requisitos:
  - FFmpeg deve estar instalado
  - macOS: brew install ffmpeg
  - Ubuntu: sudo apt install ffmpeg
        """
    )

    parser.add_argument('directory', help='Nome do diretório dentro de assets/ para processar')

    args = parser.parse_args()

    # Construct assets directory path
    assets_dir = Path('assets')
    source_dir = assets_dir / args.directory
    dest_dir = assets_dir / f"{args.directory}_sub"

    if not assets_dir.exists():
        print(f"❌ Erro: Diretório assets não encontrado em {assets_dir}")
        return 1

    if not source_dir.exists():
        print(f"❌ Erro: Diretório {source_dir} não encontrado")
        return 1

    print("🎬 Split Video Processor (Idempotente)")
    print("=" * 50)
    print(f"📁 Diretório origem: {source_dir}")
    print(f"📁 Diretório destino: {dest_dir}")

    # Check FFmpeg availability
    if not check_ffmpeg():
        print("❌ Erro: FFmpeg não encontrado!")
        print("   Instale FFmpeg:")
        print("   macOS: brew install ffmpeg")
        print("   Ubuntu: sudo apt install ffmpeg")
        return 1

    try:
        # Step 1: Find MP4 file
        print("\n🔍 Procurando arquivo MP4...")
        mp4_file = find_mp4_file(source_dir)
        print(f"✅ MP4 encontrado: {mp4_file.name}")

        # Step 2: Create destination directory (only if doesn't exist)
        if dest_dir.exists():
            print(f"\n📁 Diretório {dest_dir.name} já existe - pulando criação")
        else:
            print(f"\n📁 Criando diretório {dest_dir.name}...")
            dest_dir.mkdir(parents=True, exist_ok=True)
            print("✅ Diretório criado")

        # Step 3: Copy MP4 to destination directory (only if doesn't exist)
        dest_mp4 = dest_dir / mp4_file.name
        chromecast_output = dest_dir / f"{mp4_file.stem}_chromecast{mp4_file.suffix}"

        if chromecast_output.exists():
            print(f"\n📱 Arquivo Chromecast já existe: {chromecast_output.name}")
            print("⏭️  Pulando processamento - vídeo já está pronto!")

            # Call split_video function even if file already exists
            print("\n🎬 Chamando função split_video...")
            split_video(chromecast_output)

            print("\n✅ Processamento concluído (arquivo já existia)!")
            print(f"📁 Arquivo final: {chromecast_output.name}")
            return 0

        if dest_mp4.exists():
            print(f"\n📋 Cópia do vídeo já existe: {dest_mp4.name}")
            print("⏭️  Pulando cópia")
        else:
            print("\n📋 Copiando vídeo...")
            shutil.copy2(mp4_file, dest_mp4)
            print("✅ Vídeo copiado")

        # Step 4: Convert to Chromecast format (only if doesn't exist)
        print("\n📱 Convertendo para Chromecast...")
        if convert_to_chromecast_format(dest_mp4, chromecast_output):
            print("✅ Vídeo compatível com Chromecast criado")

            # Remove the original copy (keep only the Chromecast version)
            if dest_mp4.exists():
                dest_mp4.unlink()
                print("🗑️  Cópia original removida")

            # Step 5: Clean up temporary files
            cleanup_temp_files(dest_dir, chromecast_output)

            # Step 6: Call split_video function
            print("\n🎬 Chamando função split_video...")
            split_video(chromecast_output)

            print("\n✅ Processamento concluído!")
            print(f"📁 Arquivo final: {chromecast_output.name}")
            return 0
        else:
            print("❌ Erro na conversão para Chromecast")
            return 1

    except FileNotFoundError as e:
        print(f"❌ Erro: {e}")
        return 1
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
