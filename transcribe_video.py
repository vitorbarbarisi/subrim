#!/usr/bin/env python3
"""
Video Transcriber - Transcreve vídeo usando Whisper e gera arquivo SRT

Usage: python3 transcribe_video.py <directory_name> [--model MODEL] [--language LANGUAGE]
Example: python3 transcribe_video.py roseki01-1 --model medium --language zh

O script:
1. Encontra arquivo de vídeo MP4 no diretório assets/<directory_name>
2. Extrai o áudio do vídeo
3. Transcreve o áudio usando Whisper
4. Gera arquivo SRT com sufixo -zht (para mandarim)

Dependências necessárias:
pip install openai-whisper

Modelos disponíveis:
- tiny: Mais rápido, menor precisão
- base: Balanceado
- small: Boa qualidade
- medium: Alta qualidade (recomendado para mandarim)
- large: Melhor qualidade, mais lento
"""

import sys
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

def extract_audio_from_video(video_path: Path, audio_output: Path) -> bool:
    """
    Extract audio from video file using ffmpeg.
    
    Args:
        video_path: Path to input video file
        audio_output: Path to save extracted audio file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"🎵 Extraindo áudio do vídeo...")
        cmd = [
            'ffmpeg',
            '-i', str(video_path),
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '16000',  # 16kHz sample rate (Whisper works well with this)
            '-ac', '1',  # Mono
            '-y',  # Overwrite output file
            str(audio_output)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Erro ao extrair áudio: {result.stderr}")
            return False
        
        print(f"✅ Áudio extraído: {audio_output}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao extrair áudio: {e}")
        return False

def parse_srt_to_segments(srt_path: Path) -> list:
    """
    Parse SRT file and convert to segments format.
    
    Args:
        srt_path: Path to SRT file
        
    Returns:
        List of segments with 'start', 'end', and 'text' keys
    """
    segments = []
    
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by double newlines
    blocks = content.split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        
        # Second line should be timing
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
            segments.append({
                'start': start_time,
                'end': end_time,
                'text': text
            })
    
    return segments

def parse_srt_time_to_seconds(time_str: str) -> float:
    """Parse SRT time format (00:00:02,600) to seconds."""
    time_str = time_str.strip().replace(',', '.')
    
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    
    try:
        return float(time_str)
    except ValueError:
        return 0.0

def format_timestamp(seconds: float) -> str:
    """
    Format seconds to SRT timestamp format (HH:MM:SS,mmm).
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

# Global flag to print warning only once
_opencc_warning_printed = False

def convert_simplified_to_traditional(text: str) -> str:
    """
    Convert simplified Chinese characters to traditional Chinese characters using OpenCC.
    """
    global _opencc_warning_printed
    try:
        import opencc
        converter = opencc.OpenCC('s2t')  # simplified to traditional
        return converter.convert(text)
    except ImportError:
        if not _opencc_warning_printed:
            print("⚠️ OpenCC não disponível, usando conversão básica")
            print("   Para conversão completa, instale: pip install opencc-python-reimplemented")
            _opencc_warning_printed = True
        # Fallback to basic conversion if OpenCC is not available
        # Common simplified to traditional conversions
        conversions = {
            "组": "組", "什么": "什麼", "不会": "不會", "样": "樣", "湾": "灣",
            "来": "來", "这": "這", "个": "個", "说": "說", "还": "還",
            "过": "過", "时": "時", "为": "為", "发": "發", "现": "現",
            "对": "對", "应": "應", "经": "經", "没": "沒", "会": "會",
            "年": "年", "几": "幾"
        }
        result = text
        for simplified, traditional in conversions.items():
            result = result.replace(simplified, traditional)
        return result

def write_srt_file(segments: list, output_path: Path) -> bool:
    """
    Write transcription segments to SRT file.
    
    Args:
        segments: List of segments with 'start', 'end', and 'text' keys
        output_path: Path to save SRT file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, 1):
                start_time = format_timestamp(segment['start'])
                end_time = format_timestamp(segment['end'])
                text = segment['text'].strip()
                
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{text}\n")
                f.write("\n")
        
        print(f"✅ Arquivo SRT gerado: {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao escrever arquivo SRT: {e}")
        return False

def transcribe_video(directory_name: str, 
                    model_name: str = "medium",
                    language: Optional[str] = "zh") -> bool:
    """
    Transcribe video using Whisper.
    
    Args:
        directory_name: Name of directory in assets/
        model_name: Whisper model to use (tiny, base, small, medium, large)
        language: Language code (zh for Chinese, None for auto-detect)
        
    Returns:
        True if successful, False otherwise
    """
    assets_dir = Path("assets") / directory_name
    if not assets_dir.exists():
        print(f"❌ Diretório não encontrado: {assets_dir}")
        return False
    
    # Find video file
    video_files = list(assets_dir.glob("*.mp4"))
    if not video_files:
        print(f"❌ Nenhum arquivo MP4 encontrado em {assets_dir}")
        return False
    
    video_file = video_files[0]
    print(f"📹 Vídeo encontrado: {video_file.name}")
    
    # Create temp directory for audio
    temp_dir = Path(tempfile.mkdtemp())
    audio_file = temp_dir / "audio.wav"
    
    # Extract audio
    if not extract_audio_from_video(video_file, audio_file):
        return False
    
    # Try to use Whisper via CLI first, then fallback to Python API
    whisper_cli_available = False
    try:
        result = subprocess.run(['whisper', '--version'], capture_output=True, text=True)
        whisper_cli_available = (result.returncode == 0)
    except:
        pass
    
    segments = []
    
    if whisper_cli_available:
        # Use Whisper CLI
        print(f"🤖 Usando Whisper CLI com modelo: {model_name}")
        print(f"🎤 Transcrevendo áudio em mandarim...")
        print("   (Isso pode levar alguns minutos dependendo do tamanho do vídeo)")
        
        try:
            # Convert audio to format whisper CLI can use
            audio_for_whisper = temp_dir / "audio_for_whisper.wav"
            cmd_convert = [
                'ffmpeg', '-i', str(audio_file),
                '-ar', '16000', '-ac', '1',
                '-y', str(audio_for_whisper)
            ]
            subprocess.run(cmd_convert, check=True, capture_output=True)
            
            # Run whisper CLI
            output_srt_temp = temp_dir / "output.srt"
            cmd_whisper = [
                'whisper',
                str(audio_for_whisper),
                '--model', model_name,
                '--language', language if language else 'auto',
                '--output_format', 'srt',
                '--output_dir', str(temp_dir)
            ]
            
            result = subprocess.run(cmd_whisper, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"⚠️  Erro ao usar Whisper CLI: {result.stderr}")
                whisper_cli_available = False
            else:
                # Parse SRT file generated by whisper
                srt_file = temp_dir / f"{audio_for_whisper.stem}.srt"
                if srt_file.exists():
                    segments = parse_srt_to_segments(srt_file)
                    print(f"✅ {len(segments)} segmentos transcritos via CLI")
                else:
                    whisper_cli_available = False
        
        except Exception as e:
            print(f"⚠️  Erro ao usar Whisper CLI: {e}")
            whisper_cli_available = False
    
    if not whisper_cli_available:
        # Fallback to Python API
        print(f"🤖 Carregando modelo Whisper via Python API: {model_name}")
        try:
            import whisper
            model = whisper.load_model(model_name)
        except Exception as e:
            print(f"❌ Erro ao carregar modelo Whisper: {e}")
            print("   Certifique-se de que o whisper está instalado:")
            print("   pip install openai-whisper")
            print("   OU instale o whisper CLI:")
            print("   pip install openai-whisper")
            return False
        
        # Transcribe audio
        print(f"🎤 Transcrevendo áudio em mandarim...")
        print("   (Isso pode levar alguns minutos dependendo do tamanho do vídeo)")
        
        try:
            if language:
                result = model.transcribe(str(audio_file), language=language)
            else:
                result = model.transcribe(str(audio_file))
            
            segments = result.get("segments", [])
            
            if not segments:
                print("❌ Nenhum segmento transcrito encontrado")
                return False
            
            print(f"✅ {len(segments)} segmentos transcritos")
            
        except Exception as e:
            print(f"❌ Erro ao transcrever áudio: {e}")
            return False
    
    # Convert simplified Chinese to traditional Chinese
    print("🔄 Convertendo chinês simplificado para tradicional...")
    for segment in segments:
        if 'text' in segment:
            segment['text'] = convert_simplified_to_traditional(segment['text'])
    
    # Generate output filename
    video_stem = video_file.stem
    output_srt = assets_dir / f"{video_stem}.zht.srt"
    
    # Write SRT file
    if not write_srt_file(segments, output_srt):
        return False
    
    # Cleanup temp files
    try:
        import shutil
        shutil.rmtree(temp_dir)
        print("🧹 Arquivos temporários removidos")
    except:
        pass
    
    print(f"✅ Transcrição concluída!")
    print(f"   📁 Arquivo gerado: {output_srt.name}")
    print(f"   📊 Total de segmentos: {len(segments)}")
    
    # Show some statistics
    total_duration = max([seg['end'] for seg in segments]) if segments else 0
    print(f"   ⏱️  Duração total: {total_duration:.2f}s ({total_duration/60:.2f} minutos)")
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Transcrever vídeo usando Whisper")
    parser.add_argument("directory", help="Nome do diretório em assets/")
    parser.add_argument("--model", default="medium",
                       choices=["tiny", "base", "small", "medium", "large"],
                       help="Modelo Whisper a usar (padrão: medium)")
    parser.add_argument("--language", default="zh",
                       help="Código de idioma (zh para chinês, None para auto-detectar)")
    
    args = parser.parse_args()
    
    # Check if whisper is available (CLI or Python)
    whisper_available = False
    
    # Check CLI
    try:
        result = subprocess.run(['whisper', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            whisper_available = True
            print("✅ Whisper CLI encontrado")
    except:
        pass
    
    # Check Python API
    if not whisper_available:
        try:
            import whisper
            whisper_available = True
            print("✅ Whisper Python API encontrado")
        except ImportError:
            pass
    
    if not whisper_available:
        print("❌ Whisper não está instalado. Execute:")
        print("   pip install openai-whisper")
        print("   (Nota: Python 3.14 pode ter problemas. Use Python 3.13 ou anterior)")
        return 1
    
    # Run transcription
    success = transcribe_video(
        args.directory,
        args.model,
        args.language if args.language.lower() != "none" else None
    )
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

