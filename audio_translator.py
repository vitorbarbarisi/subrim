#!/usr/bin/env python3
"""
Audio Translator - Gera áudio em chinês a partir de legendas VTT/SRT

Usage: python3 audio_translator.py <directory_name>
Example: python3 audio_translator.py tale_fishermen

O script:
1. Encontra arquivos VTT ou SRT com legendas em chinês no diretório assets/<directory_name>
2. Gera arquivos de áudio MP3 para cada linha de legenda usando edge-tts
3. Cria um arquivo de áudio completo sincronizado com o timing original
4. Opcionalmente, pode gerar áudio com traduções em português também

Dependências necessárias:
pip install edge-tts

Vozes disponíveis para chinês:
- zh-CN-XiaoxiaoNeural (chinês simplificado, feminina)
- zh-CN-YunxiNeural (chinês simplificado, masculina)
- zh-TW-HsiaoyuNeural (chinês tradicional, feminina)
- zh-TW-YunJheNeural (chinês tradicional, masculina)
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
DEFAULT_CHINESE_VOICE = "zh-TW-HsiaoyuNeural"  # Chinês tradicional, feminina
DEFAULT_PORTUGUESE_VOICE = "pt-BR-FranciscaNeural"  # Português brasileiro, feminina
TEMP_DIR = Path("temp_audio")

def parse_vtt_file(vtt_path: Path) -> List[Tuple[float, float, str]]:
    """
    Parse VTT file and extract timing and text.
    
    Returns:
        List of tuples (start_time, end_time, text)
    """
    subtitles = []
    
    with open(vtt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove WEBVTT header
    content = content.replace('WEBVTT\n\n', '')
    
    # Split by double newlines to get subtitle blocks
    blocks = content.split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
            
        # First line should be timing
        timing_line = lines[0]
        if '-->' not in timing_line:
            continue
            
        # Parse timing
        timing_parts = timing_line.split(' --> ')
        if len(timing_parts) != 2:
            continue
            
        start_time = parse_time_to_seconds(timing_parts[0].strip())
        end_time = parse_time_to_seconds(timing_parts[1].strip())
        
        # Rest of the lines are the text
        text = ' '.join(lines[1:]).strip()
        
        if text:
            subtitles.append((start_time, end_time, text))
    
    return subtitles

def parse_srt_file(srt_path: Path) -> List[Tuple[float, float, str]]:
    """
    Parse SRT file and extract timing and text.
    
    Returns:
        List of tuples (start_time, end_time, text)
    """
    subtitles = []
    
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by double newlines to get subtitle blocks
    blocks = content.split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
            
        # First line is index, second is timing, rest is text
        timing_line = lines[1]
        if '-->' not in timing_line:
            continue
            
        # Parse timing (SRT format: 00:00:00,000 --> 00:00:02,600)
        timing_parts = timing_line.split(' --> ')
        if len(timing_parts) != 2:
            continue
            
        start_time = parse_srt_time_to_seconds(timing_parts[0].strip())
        end_time = parse_srt_time_to_seconds(timing_parts[1].strip())
        
        # Rest of the lines are the text
        text = ' '.join(lines[2:]).strip()
        
        if text:
            subtitles.append((start_time, end_time, text))
    
    return subtitles

def parse_time_to_seconds(time_str: str) -> float:
    """Parse VTT time format (00:02.600) to seconds."""
    # Remove any extra characters
    time_str = time_str.strip()
    
    # Handle format like "00:02.600"
    if ':' in time_str and '.' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
    
    # Handle format like "2.600"
    try:
        return float(time_str)
    except ValueError:
        return 0.0

def parse_srt_time_to_seconds(time_str: str) -> float:
    """Parse SRT time format (00:00:02,600) to seconds."""
    # Remove any extra characters
    time_str = time_str.strip()
    
    # Replace comma with dot for decimal
    time_str = time_str.replace(',', '.')
    
    # Handle format like "00:00:02.600"
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
    
    # Handle format like "2.600"
    try:
        return float(time_str)
    except ValueError:
        return 0.0

async def generate_audio_for_text(text: str, voice: str, output_path: Path) -> bool:
    """
    Generate audio file for a single text using edge-tts.
    
    Args:
        text: Text to convert to speech
        voice: Voice identifier (e.g., "zh-TW-HsiaoyuNeural")
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

def merge_audio_segments_ffmpeg(subtitles: List[Tuple[float, float, str]], 
                               audio_files: List[Path], 
                               output_path: Path) -> bool:
    """
    Merge individual audio files into a single synchronized audio file using ffmpeg.
    
    Args:
        subtitles: List of (start_time, end_time, text) tuples
        audio_files: List of paths to individual audio files
        output_path: Path to save the merged audio file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create temp directory if it doesn't exist
        TEMP_DIR.mkdir(exist_ok=True)
        
        # Calculate total duration
        total_duration = max([end_time for _, end_time, _ in subtitles]) if subtitles else 0
        
        # Create a base silence file
        silence_file = TEMP_DIR / "silence.wav"
        if not create_silence_ffmpeg(total_duration, silence_file):
            return False
        
        # Create filter complex for ffmpeg
        filter_parts = []
        input_files = [str(silence_file)]
        
        for i, ((start_time, end_time, text), audio_file) in enumerate(zip(subtitles, audio_files)):
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

async def generate_audio_translation(directory_name: str, 
                                   chinese_voice: str = DEFAULT_CHINESE_VOICE,
                                   portuguese_voice: Optional[str] = None,
                                   generate_portuguese: bool = False) -> bool:
    """
    Generate audio translation for a directory.
    
    Args:
        directory_name: Name of directory in assets/
        chinese_voice: Voice for Chinese text
        portuguese_voice: Voice for Portuguese text (if generate_portuguese=True)
        generate_portuguese: Whether to also generate Portuguese audio
        
    Returns:
        True if successful, False otherwise
    """
    assets_dir = Path("assets") / directory_name
    if not assets_dir.exists():
        print(f"❌ Diretório não encontrado: {assets_dir}")
        return False
    
    # Find subtitle files
    vtt_files = list(assets_dir.glob("*.vtt"))
    srt_files = list(assets_dir.glob("*.srt"))
    
    subtitle_file = None
    subtitles = []
    
    # Prefer VTT files, then SRT files
    if vtt_files:
        subtitle_file = vtt_files[0]
        print(f"📄 Processando arquivo VTT: {subtitle_file.name}")
        subtitles = parse_vtt_file(subtitle_file)
    elif srt_files:
        subtitle_file = srt_files[0]
        print(f"📄 Processando arquivo SRT: {subtitle_file.name}")
        subtitles = parse_srt_file(subtitle_file)
    else:
        print("❌ Nenhum arquivo VTT ou SRT encontrado")
        return False
    
    if not subtitles:
        print("❌ Nenhuma legenda encontrada no arquivo")
        return False
    
    print(f"📊 {len(subtitles)} legendas encontradas")
    
    # Create temp directory
    TEMP_DIR.mkdir(exist_ok=True)
    
    # Generate Chinese audio
    print(f"🎤 Gerando áudio em chinês com voz: {chinese_voice}")
    chinese_audio_files = []
    
    for i, (start_time, end_time, text) in enumerate(subtitles):
        audio_file = TEMP_DIR / f"chinese_{i:04d}.mp3"
        
        print(f"   [{i+1:3d}/{len(subtitles)}] {text[:50]}{'...' if len(text) > 50 else ''}")
        
        success = await generate_audio_for_text(text, chinese_voice, audio_file)
        if success:
            chinese_audio_files.append(audio_file)
        else:
            # Create silence if generation failed
            silence_file = TEMP_DIR / f"silence_{i:04d}.wav"
            if create_silence_ffmpeg(end_time - start_time, silence_file):
                # Convert to mp3
                convert_cmd = [
                    'ffmpeg', '-i', str(silence_file), '-y', str(audio_file)
                ]
                subprocess.run(convert_cmd, capture_output=True)
                chinese_audio_files.append(audio_file)
            else:
                chinese_audio_files.append(audio_file)
    
    # Merge Chinese audio
    chinese_output = assets_dir / f"{subtitle_file.stem}_chinese_audio.mp3"
    success = merge_audio_segments_ffmpeg(subtitles, chinese_audio_files, chinese_output)
    
    if not success:
        print("❌ Falha ao gerar áudio em chinês")
        return False
    
    # Generate Portuguese audio if requested
    if generate_portuguese and portuguese_voice:
        print(f"🎤 Gerando áudio em português com voz: {portuguese_voice}")
        
        # For Portuguese, we need to find translation files
        # This would require integration with the existing translation system
        print("⚠️  Geração de áudio em português ainda não implementada")
        print("   (requer integração com sistema de tradução existente)")
    
    # Cleanup temp files
    try:
        import shutil
        shutil.rmtree(TEMP_DIR)
        print("🧹 Arquivos temporários removidos")
    except:
        pass
    
    print(f"✅ Tradução em áudio concluída!")
    print(f"   📁 Arquivo gerado: {chinese_output}")
    print(f"   ⏱️  Duração total: {max([end for _, end, _ in subtitles]):.2f}s")
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Gerar tradução em áudio a partir de legendas")
    parser.add_argument("directory", help="Nome do diretório em assets/")
    parser.add_argument("--chinese-voice", default=DEFAULT_CHINESE_VOICE,
                       help=f"Voz para chinês (padrão: {DEFAULT_CHINESE_VOICE})")
    parser.add_argument("--portuguese-voice", default=DEFAULT_PORTUGUESE_VOICE,
                       help=f"Voz para português (padrão: {DEFAULT_PORTUGUESE_VOICE})")
    parser.add_argument("--generate-portuguese", action="store_true",
                       help="Também gerar áudio em português")
    
    args = parser.parse_args()
    
    # Check if edge-tts is installed
    try:
        import edge_tts
    except ImportError:
        print("❌ edge-tts não está instalado. Execute:")
        print("   pip install edge-tts pydub")
        return 1
    
    # Run the async function
    success = asyncio.run(generate_audio_translation(
        args.directory,
        args.chinese_voice,
        args.portuguese_voice,
        args.generate_portuguese
    ))
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
