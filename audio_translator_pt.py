#!/usr/bin/env python3
"""
Audio Translator PT-BR - Gera áudio em português brasileiro a partir de arquivos base.txt

Usage: python3 audio_translator_pt.py <directory_name>
Example: python3 audio_translator_pt.py tale_fishermen

O script:
1. Encontra arquivos *_base.txt no diretório assets/<directory_name>
2. Gera arquivos de áudio MP3 para cada linha de tradução em português usando edge-tts
3. Cria um arquivo de áudio completo sincronizado com o timing original
4. Usa voz brasileira para melhor qualidade de pronúncia

Dependências necessárias:
pip install edge-tts

Vozes disponíveis para português brasileiro:
- pt-BR-FranciscaNeural (feminina, recomendada)
- pt-BR-AntonioNeural (masculina)
- pt-BR-DanielNeural (masculina)
- pt-BR-ElzaNeural (feminina)
- pt-BR-FabioNeural (masculina)
- pt-BR-GiovannaNeural (feminina)
- pt-BR-HumbertoNeural (masculina)
- pt-BR-JulioNeural (masculina)
- pt-BR-LeilaNeural (feminina)
- pt-BR-LeticiaNeural (feminina)
- pt-BR-ManuelaNeural (feminina)
- pt-BR-NicolauNeural (masculina)
- pt-BR-ValerioNeural (masculina)
- pt-BR-YaraNeural (feminina)
"""

import sys
import argparse
import asyncio
import edge_tts
import re
from pathlib import Path
from typing import List, Tuple, Optional
import subprocess
import tempfile
import os
import json

# Configurações padrão
DEFAULT_PORTUGUESE_VOICE = "pt-BR-FranciscaNeural"  # Português brasileiro, feminina
TEMP_DIR = Path("temp_audio_pt")

def parse_base_file(base_file_path: Path) -> List[Tuple[float, float, str, str]]:
    """
    Parse base file and extract timing and Portuguese text.
    
    Returns:
        List of tuples (start_time, end_time, chinese_text, portuguese_text)
    """
    subtitles = []
    
    with open(base_file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
                
            # Split by tabs
            parts = line.split('\t')
            if len(parts) < 6:
                print(f"⚠️  Linha {line_num} com formato inválido: {line[:50]}...")
                continue
            
            try:
                # Parse timing
                start_time_str = parts[1].strip()
                end_time_str = parts[2].strip()
                
                # Convert timing to seconds
                start_time = parse_time_to_seconds(start_time_str)
                end_time = parse_time_to_seconds(end_time_str)
                
                # Get Chinese and Portuguese text
                chinese_text = parts[3].strip()
                portuguese_text = parts[5].strip()  # Portuguese is in the 6th column
                
                # Skip if Portuguese text is empty or N/A
                if not portuguese_text or portuguese_text == 'N/A':
                    continue
                
                subtitles.append((start_time, end_time, chinese_text, portuguese_text))
                
            except (ValueError, IndexError) as e:
                print(f"⚠️  Erro ao processar linha {line_num}: {e}")
                continue
    
    return subtitles

def parse_time_to_seconds(time_str: str) -> float:
    """Parse time format to seconds."""
    # Remove 's' suffix if present
    time_str = time_str.rstrip('s')
    
    try:
        return float(time_str)
    except ValueError:
        return 0.0

async def generate_audio_for_text(text: str, voice: str, output_path: Path) -> bool:
    """
    Generate audio file for a single text using edge-tts.
    
    Args:
        text: Text to convert to speech
        voice: Voice identifier (e.g., "pt-BR-FranciscaNeural")
        output_path: Path to save the audio file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Clean text for TTS
        clean_text = clean_text_for_tts(text)
        if not clean_text:
            return False
            
        # Generate audio using edge-tts
        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(str(output_path))
        
        return True
    except Exception as e:
        print(f"Erro ao gerar áudio para '{text[:50]}...': {e}")
        return False

def clean_text_for_tts(text: str) -> str:
    """
    Clean text for TTS processing.
    
    Args:
        text: Original text
        
    Returns:
        Cleaned text suitable for TTS
    """
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove special characters that might cause issues
    text = re.sub(r'[♪♫♬♭♮♯]', '', text)
    
    # Remove brackets and parentheses content
    text = re.sub(r'[【】\[\]()（）]', '', text)
    
    # Remove ellipsis
    text = text.replace('…', '')
    
    # Remove Chinese characters (keep only Portuguese)
    text = re.sub(r'[\u4e00-\u9fff]+', '', text)
    
    return text.strip()

def create_silence_ffmpeg(duration_seconds: float, output_path: Path) -> bool:
    """Create silence audio file using ffmpeg."""
    try:
        cmd = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', f'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-t', str(duration_seconds),
            '-y',
            str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Erro ao criar silêncio: {e}")
        return False

def merge_audio_segments_ffmpeg(subtitles: List[Tuple[float, float, str, str]], 
                               audio_files: List[Path], 
                               output_path: Path) -> bool:
    """
    Merge individual audio files into a single synchronized audio file using ffmpeg.
    
    Args:
        subtitles: List of (start_time, end_time, chinese_text, portuguese_text) tuples
        audio_files: List of paths to individual audio files
        output_path: Path to save the merged audio file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create temp directory if it doesn't exist
        TEMP_DIR.mkdir(exist_ok=True)
        
        # Calculate total duration
        total_duration = max([end_time for _, end_time, _, _ in subtitles]) if subtitles else 0
        
        # Create a base silence file
        silence_file = TEMP_DIR / "silence.wav"
        if not create_silence_ffmpeg(total_duration, silence_file):
            return False
        
        # Create filter complex for ffmpeg
        filter_parts = []
        input_files = [str(silence_file)]
        
        for i, ((start_time, end_time, chinese_text, portuguese_text), audio_file) in enumerate(zip(subtitles, audio_files)):
            if not audio_file.exists():
                print(f"Arquivo de áudio não encontrado: {audio_file}")
                continue
                
            input_files.append(str(audio_file))
            input_index = len(input_files) - 1
            
            # Add delay and overlay
            filter_parts.append(f"[{input_index}]adelay={int(start_time * 1000)}|{int(start_time * 1000)}[delayed{i}]")
            if i == 0:
                filter_parts.append(f"[0][delayed{i}]amix=inputs=2[mixed{i}]")
            else:
                filter_parts.append(f"[mixed{i-1}][delayed{i}]amix=inputs=2[mixed{i}]")
        
        if not filter_parts:
            print("Nenhum arquivo de áudio válido encontrado")
            return False
        
        # Final output
        final_output = f"[mixed{len(filter_parts)//2 - 1}]"
        filter_complex = ";".join(filter_parts)
        
        # Build ffmpeg command
        cmd = ['ffmpeg']
        for input_file in input_files:
            cmd.extend(['-i', input_file])
        
        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', final_output,
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-y',
            str(output_path)
        ])
        
        print(f"🎵 Mesclando {len(audio_files)} segmentos de áudio...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Erro no ffmpeg: {result.stderr}")
            return False
        
        print(f"✅ Áudio completo gerado: {output_path}")
        return True
        
    except Exception as e:
        print(f"Erro ao mesclar áudio: {e}")
        return False

async def generate_portuguese_audio_translation(directory_name: str, 
                                              portuguese_voice: str = DEFAULT_PORTUGUESE_VOICE) -> bool:
    """
    Generate Portuguese audio translation for a directory.
    
    Args:
        directory_name: Name of directory in assets/
        portuguese_voice: Voice for Portuguese text
        
    Returns:
        True if successful, False otherwise
    """
    assets_dir = Path("assets") / directory_name
    if not assets_dir.exists():
        print(f"❌ Diretório não encontrado: {assets_dir}")
        return False
    
    # Find base file
    base_files = list(assets_dir.glob("*_base.txt"))
    if not base_files:
        print(f"❌ Nenhum arquivo *_base.txt encontrado em {assets_dir}")
        return False
    
    base_file = base_files[0]
    print(f"📄 Processando arquivo base: {base_file.name}")
    
    # Parse base file
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("❌ Nenhuma tradução em português encontrada no arquivo base")
        return False
    
    print(f"📊 {len(subtitles)} traduções em português encontradas")
    
    # Create temp directory
    TEMP_DIR.mkdir(exist_ok=True)
    
    # Generate Portuguese audio
    print(f"🎤 Gerando áudio em português com voz: {portuguese_voice}")
    portuguese_audio_files = []
    
    for i, (start_time, end_time, chinese_text, portuguese_text) in enumerate(subtitles):
        audio_file = TEMP_DIR / f"portuguese_{i:04d}.mp3"
        
        print(f"   [{i+1:3d}/{len(subtitles)}] {portuguese_text[:50]}{'...' if len(portuguese_text) > 50 else ''}")
        
        success = await generate_audio_for_text(portuguese_text, portuguese_voice, audio_file)
        if success:
            portuguese_audio_files.append(audio_file)
        else:
            # Create silence if generation failed
            silence_file = TEMP_DIR / f"silence_{i:04d}.wav"
            if create_silence_ffmpeg(end_time - start_time, silence_file):
                # Convert to mp3
                convert_cmd = [
                    'ffmpeg', '-i', str(silence_file), '-y', str(audio_file)
                ]
                subprocess.run(convert_cmd, capture_output=True)
                portuguese_audio_files.append(audio_file)
            else:
                portuguese_audio_files.append(audio_file)
    
    # Merge Portuguese audio
    portuguese_output = assets_dir / f"{base_file.stem}_portuguese_audio.mp3"
    success = merge_audio_segments_ffmpeg(subtitles, portuguese_audio_files, portuguese_output)
    
    if not success:
        print("❌ Falha ao gerar áudio em português")
        return False
    
    # Preserve temp files in a permanent directory for audio_burner
    temp_preserve_dir = assets_dir / f"{base_file.stem}_portuguese_chunks"
    temp_preserve_dir.mkdir(exist_ok=True)
    
    # Copy temp files to preserve directory
    for i, temp_file in enumerate(portuguese_audio_files):
        preserve_file = temp_preserve_dir / f"portuguese_{i:04d}.mp3"
        if temp_file.exists():
            import shutil
            shutil.copy2(temp_file, preserve_file)
    
    print(f"📁 Chunks em português preservados em: {temp_preserve_dir.name}")
    
    # Cleanup original temp files
    try:
        import shutil
        shutil.rmtree(TEMP_DIR)
        print("🧹 Arquivos temporários originais removidos")
    except:
        pass
    
    print(f"✅ Tradução em áudio em português concluída!")
    print(f"   📁 Arquivo gerado: {portuguese_output}")
    print(f"   ⏱️  Duração total: {max([end for _, end, _, _ in subtitles]):.2f}s")
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Gerar tradução em áudio em português brasileiro")
    parser.add_argument("directory", help="Nome do diretório em assets/")
    parser.add_argument("--portuguese-voice", default=DEFAULT_PORTUGUESE_VOICE,
                       help=f"Voz para português (padrão: {DEFAULT_PORTUGUESE_VOICE})")
    
    args = parser.parse_args()
    
    # Check if edge-tts is installed
    try:
        import edge_tts
    except ImportError:
        print("❌ edge-tts não está instalado. Execute:")
        print("   pip install edge-tts")
        return 1
    
    # Run the async function
    success = asyncio.run(generate_portuguese_audio_translation(
        args.directory,
        args.portuguese_voice
    ))
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
