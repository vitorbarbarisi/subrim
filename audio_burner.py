#!/usr/bin/env python3
"""
Audio Burner - Combina áudio original em mandarim com áudio em português alternadamente

Usage: python3 audio_burner.py <directory_name>
Example: python3 audio_burner.py tale_fishermen

O script:
1. Encontra arquivos *_base.txt no diretório assets/<directory_name>
2. Localiza o áudio original em mandarim (geralmente *.mp3)
3. Localiza os chunks em português gerados pelo audio_translator_pt.py
4. Cria recortes (chunks) no MP3 em zht baseado nos timestamps do base.txt
5. Mescla os chunks alternadamente: português -> mandarim -> português -> mandarim...

Dependências necessárias:
- FFmpeg instalado no sistema
- Arquivo base.txt com colunas: begin | end | zht | pares | trad
- Áudio original em mandarim
- Chunks em português gerados pelo audio_translator_pt.py
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
import tempfile
import shutil

def find_audio_files(directory: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Encontra os arquivos de áudio necessários no diretório.
    
    Returns:
        (mandarin_audio, portuguese_chunks_dir) - Caminhos para o áudio mandarim e diretório de chunks português
    """
    # Procurar áudio original em mandarim
    mandarin_patterns = ["*.mp3", "*.wav", "*.m4a", "*.aac"]
    mandarin_audio = None
    
    for pattern in mandarin_patterns:
        files = list(directory.glob(pattern))
        # Filtrar arquivos que não são de português
        files = [f for f in files if "portuguese" not in f.name.lower() and "portugues" not in f.name.lower()]
        if files:
            mandarin_audio = files[0]
            break
    
    # Procurar diretório de chunks em português
    portuguese_chunks_dirs = list(directory.glob("*_portuguese_chunks"))
    portuguese_chunks_dir = portuguese_chunks_dirs[0] if portuguese_chunks_dirs else None
    
    return mandarin_audio, portuguese_chunks_dir

def parse_base_file(base_file: Path) -> List[dict]:
    """
    Parse do arquivo base.txt para extrair informações de timing e texto.
    
    Returns:
        Lista de dicionários com informações de cada linha
    """
    subtitles = []
    
    try:
        with open(base_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('\t')
            if len(parts) < 6:
                print(f"⚠️ Linha {line_num} tem formato inválido: {line}")
                continue
            
            # Extrair informações
            begin_time = parts[1].strip()
            end_time = parts[2].strip()
            zht_text = parts[3].strip()
            pairs = parts[4].strip()
            trad_text = parts[5].strip()
            
            # Converter tempos para segundos
            try:
                begin_seconds = float(begin_time.replace('s', ''))
                end_seconds = float(end_time.replace('s', ''))
            except ValueError:
                print(f"⚠️ Linha {line_num} tem tempo inválido: {begin_time} -> {end_time}")
                continue
            
            subtitles.append({
                'line_num': line_num,
                'begin_seconds': begin_seconds,
                'end_seconds': end_seconds,
                'zht_text': zht_text,
                'trad_text': trad_text,
                'duration': end_seconds - begin_seconds
            })
        
        print(f"📊 {len(subtitles)} linhas de legenda processadas")
        return subtitles
        
    except Exception as e:
        print(f"❌ Erro ao processar arquivo base: {e}")
        return []

def create_mandarin_chunks(subtitles: List[dict], mandarin_audio: Path, temp_dir: Path) -> List[Path]:
    """
    Cria chunks do áudio mandarim baseado nos timestamps do base.txt.
    Verifica se os chunks já existem antes de criá-los (idempotente).
    
    Returns:
        Lista de caminhos para os chunks de mandarim criados
    """
    chunks = []
    existing_chunks = 0
    new_chunks = 0
    
    print(f"🎵 Verificando {len(subtitles)} chunks de mandarim...")
    
    for i, subtitle in enumerate(subtitles):
        # Nome do arquivo de chunk
        chunk_name = f"mandarin_{i:04d}.mp3"
        chunk_path = temp_dir / chunk_name
        
        # Verificar se o chunk já existe
        if chunk_path.exists():
            chunks.append(chunk_path)
            existing_chunks += 1
            if (i + 1) % 50 == 0:
                print(f"   [{i+1:3d}/{len(subtitles)}] Chunks verificados...")
            continue
        
        # Extrair chunk do áudio mandarim
        start_time = subtitle['begin_seconds']
        duration = subtitle['duration']
        
        try:
            cmd = [
                'ffmpeg', '-y',  # -y para sobrescrever arquivos existentes
                '-i', str(mandarin_audio),
                '-ss', str(start_time),
                '-t', str(duration),
                '-c', 'copy',  # Copiar sem re-encoding para velocidade
                str(chunk_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"⚠️ Erro ao criar chunk mandarim {i+1}: {result.stderr}")
                continue
            
            chunks.append(chunk_path)
            new_chunks += 1
            
            if (i + 1) % 50 == 0:
                print(f"   [{i+1:3d}/{len(subtitles)}] Chunks processados...")
                
        except Exception as e:
            print(f"❌ Erro ao processar chunk mandarim {i+1}: {e}")
            continue
    
    if existing_chunks > 0:
        print(f"✅ {existing_chunks} chunks de mandarim já existiam")
    if new_chunks > 0:
        print(f"✅ {new_chunks} chunks de mandarim criados")
    print(f"📊 Total: {len(chunks)} chunks de mandarim disponíveis")
    return chunks

def load_portuguese_chunks(portuguese_chunks_dir: Path, num_subtitles: int) -> List[Path]:
    """
    Carrega os chunks em português do diretório preservado.
    Verifica se os chunks existem antes de carregá-los (idempotente).
    
    Returns:
        Lista de caminhos para os chunks de português
    """
    chunks = []
    existing_chunks = 0
    missing_chunks = 0
    
    print(f"📁 Verificando {num_subtitles} chunks de português...")
    
    for i in range(num_subtitles):
        chunk_file = portuguese_chunks_dir / f"portuguese_{i:04d}.mp3"
        if chunk_file.exists():
            chunks.append(chunk_file)
            existing_chunks += 1
        else:
            print(f"⚠️ Chunk português {i:04d} não encontrado")
            missing_chunks += 1
            # Criar chunk de silêncio como fallback
            silence_file = portuguese_chunks_dir / f"silence_{i:04d}.mp3"
            try:
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', 'anullsrc=duration=1',
                    '-c:a', 'libmp3lame',
                    str(silence_file)
                ]
                subprocess.run(cmd, capture_output=True)
                chunks.append(silence_file)
            except:
                chunks.append(None)
    
    if existing_chunks > 0:
        print(f"✅ {existing_chunks} chunks de português encontrados")
    if missing_chunks > 0:
        print(f"⚠️ {missing_chunks} chunks de português em falta (usando silêncio)")
    print(f"📊 Total: {len([c for c in chunks if c])} chunks de português disponíveis")
    return chunks

def merge_alternating_audio(mandarin_chunks: List[Path], portuguese_chunks: List[Path], output_path: Path) -> bool:
    """
    Mescla os chunks alternadamente: português -> mandarim -> mandarim(0.5x) -> português -> mandarim -> mandarim(0.5x)...
    Verifica se o arquivo de saída já existe (idempotente).
    
    Returns:
        True se bem-sucedido, False caso contrário
    """
    if not mandarin_chunks or not portuguese_chunks:
        print("❌ Nenhum chunk para mesclar")
        return False
    
    # Verificar se o arquivo de saída já existe
    if output_path.exists():
        print(f"📁 Arquivo de saída já existe: {output_path.name}")
        print(f"   Tamanho: {output_path.stat().st_size / (1024*1024):.1f} MB")
        print(f"   Modificado: {output_path.stat().st_mtime}")
        
        # Verificar se o arquivo tem tamanho razoável (mais que 1MB)
        if output_path.stat().st_size > 1024 * 1024:
            print(f"✅ Arquivo de saída já existe e parece válido")
            return True
        else:
            print(f"⚠️ Arquivo de saída existe mas é muito pequeno, recriando...")
    
    print(f"🔗 Mesclando chunks alternadamente...")
    
    try:
        # Usar abordagem de mesclagem mais robusta
        temp_dir = output_path.parent / "temp_merge"
        temp_dir.mkdir(exist_ok=True)
        
        # Criar lista de arquivos para mesclar (português primeiro, depois mandarim)
        merge_files = []
        
        for i in range(len(mandarin_chunks)):
            # Adicionar chunk português primeiro
            if i < len(portuguese_chunks) and portuguese_chunks[i]:
                merge_files.append(portuguese_chunks[i])
            
            # Adicionar chunk mandarim normal
            if i < len(mandarin_chunks) and mandarin_chunks[i]:
                merge_files.append(mandarin_chunks[i])
            
            # Adicionar chunk mandarim em velocidade 0.5x
            if i < len(mandarin_chunks) and mandarin_chunks[i]:
                # Criar versão em velocidade 0.5x
                slow_mandarin_file = temp_dir / f"mandarin_slow_{i:04d}.wav"
                cmd = [
                    'ffmpeg', '-y',
                    '-i', str(mandarin_chunks[i]),
                    '-filter:a', 'atempo=0.5',
                    '-ar', '44100',
                    '-ac', '2',
                    str(slow_mandarin_file)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    merge_files.append(slow_mandarin_file)
        
        # Converter todos os chunks para WAV primeiro para garantir compatibilidade
        wav_files = []
        for i, chunk in enumerate(merge_files):
            if chunk and chunk.exists():
                wav_file = temp_dir / f"chunk_{i:04d}.wav"
                cmd = [
                    'ffmpeg', '-y',
                    '-i', str(chunk),
                    '-ar', '44100',
                    '-ac', '2',
                    str(wav_file)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    wav_files.append(wav_file)
        
        if not wav_files:
            print("❌ Nenhum chunk WAV válido criado")
            return False
        
        # Criar arquivo de lista para FFmpeg com arquivos WAV
        list_file = temp_dir / "merge_list.txt"
        with open(list_file, 'w', encoding='utf-8') as f:
            for wav_file in wav_files:
                # Aspa simples no nome (ex.: "China's") fecharia a string do concat
                # demuxer; o escape dele é '\''.
                path = str(wav_file.absolute()).replace("'", "'\\''")
                f.write(f"file '{path}'\n")
        
        # Comando FFmpeg para mesclar WAVs e converter para MP3
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-ar', '44100',
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Erro ao mesclar áudios: {result.stderr}")
            # Limpar diretório temporário
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        
        # Limpar diretório temporário
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        print(f"✅ Áudio alternado salvo: {output_path.name}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao mesclar áudios: {e}")
        return False

def get_audio_duration(audio_file: Path) -> float:
    """
    Obtém a duração de um arquivo de áudio em segundos.
    """
    try:
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'csv=p=0',
            str(audio_file)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return float(result.stdout.strip())
        else:
            print(f"⚠️ Não foi possível obter duração de {audio_file.name}")
            return 0.0
    except Exception as e:
        print(f"⚠️ Erro ao obter duração: {e}")
        return 0.0

def main(directory_name: str) -> int:
    """
    Função principal do script.
    """
    print(f"🎬 Audio Burner - Combinando áudio mandarim e português alternadamente")
    print(f"📁 Diretório: {directory_name}")
    
    # Verificar se FFmpeg está disponível
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ FFmpeg não encontrado. Instale FFmpeg para continuar.")
        return 1
    
    # Construir caminho do diretório
    assets_dir = Path("assets") / directory_name
    if not assets_dir.exists():
        print(f"❌ Diretório não encontrado: {assets_dir}")
        return 1
    
    # Encontrar arquivo base
    base_files = list(assets_dir.glob("*_base.txt"))
    if not base_files:
        print(f"❌ Nenhum arquivo *_base.txt encontrado em {assets_dir}")
        return 1
    
    base_file = base_files[0]
    print(f"📄 Processando arquivo base: {base_file.name}")
    
    # Encontrar arquivos de áudio
    mandarin_audio, portuguese_chunks_dir = find_audio_files(assets_dir)
    
    if not mandarin_audio:
        print(f"❌ Áudio original em mandarim não encontrado")
        return 1
    
    if not portuguese_chunks_dir:
        print(f"❌ Diretório de chunks em português não encontrado")
        print(f"   Execute primeiro: python3 audio_translator_pt.py {directory_name}")
        return 1
    
    print(f"🎵 Áudio mandarim: {mandarin_audio.name}")
    print(f"📁 Chunks português: {portuguese_chunks_dir.name}")
    
    # Verificar duração do áudio mandarim
    mandarin_duration = get_audio_duration(mandarin_audio)
    print(f"⏱️ Duração mandarim: {mandarin_duration:.1f}s")
    
    # Parse do arquivo base
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("❌ Nenhuma legenda válida encontrada")
        return 1
    
    # Carregar chunks em português
    portuguese_chunks = load_portuguese_chunks(portuguese_chunks_dir, len(subtitles))
    
    # Criar diretório persistente para chunks mandarim
    mandarin_chunks_dir = assets_dir / f"{base_file.stem}_mandarin_chunks"
    mandarin_chunks_dir.mkdir(exist_ok=True)
    
    # Criar chunks de mandarim
    mandarin_chunks = create_mandarin_chunks(subtitles, mandarin_audio, mandarin_chunks_dir)
    if not mandarin_chunks:
        print("❌ Nenhum chunk de mandarim criado")
        return 1
    
    # Definir arquivo de saída
    output_file = assets_dir / f"{base_file.stem}_alternating_audio.mp3"
    
    # Mesclar chunks alternadamente
    if merge_alternating_audio(mandarin_chunks, portuguese_chunks, output_file):
        print(f"✅ Áudio alternado gerado com sucesso!")
        print(f"📁 Arquivo: {output_file.name}")
        
        # Mostrar estatísticas
        total_duration = sum(s['duration'] for s in subtitles)
        print(f"📊 Estatísticas:")
        print(f"   • Total de segmentos: {len(subtitles)}")
        print(f"   • Chunks mandarim: {len(mandarin_chunks)}")
        print(f"   • Chunks português: {len([c for c in portuguese_chunks if c])}")
        print(f"   • Duração total estimada: {total_duration:.1f}s")
        print(f"   • Padrão: Português -> Mandarim -> Mandarim(0.5x) -> Português -> Mandarim -> Mandarim(0.5x)...")
        print(f"   • Chunks mandarim preservados em: {mandarin_chunks_dir.name}")
        
        return 0
    else:
        print("❌ Falha ao mesclar áudios")
        return 1

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 audio_burner.py <directory_name>")
        print("Example: python3 audio_burner.py tale_fishermen")
        sys.exit(1)
    
    directory_name = sys.argv[1]
    sys.exit(main(directory_name))