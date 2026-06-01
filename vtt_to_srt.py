#!/usr/bin/env python3
"""
VTT to SRT Converter - Converte arquivos .en.vtt para .en.srt

Usage: python3 vtt_to_srt.py <directory_name> [--file vtt_file]
Example: python3 vtt_to_srt.py roseki01-1
Example: python3 vtt_to_srt.py --file assets/roseki01-1/video.en.vtt

O script:
1. Encontra arquivos .en.vtt no diretório assets/<directory_name>
2. Converte cada arquivo VTT para formato SRT
3. Gera arquivo .en.srt no mesmo diretório
"""

import sys
import argparse
import re
from pathlib import Path
from typing import List, Tuple

def convert_vtt_time_to_srt(vtt_time: str) -> str:
    """
    Convert VTT time format to SRT time format.
    
    VTT formats:
    - 00:02:05.873 (HH:MM:SS.mmm)
    - 00:02.600 (MM:SS.mmm)
    - 2.600 (SS.mmm)
    
    SRT format: HH:MM:SS,mmm
    """
    # Remove any extra characters and whitespace
    vtt_time = vtt_time.strip()
    
    # Handle format like "00:02:05.873" (HH:MM:SS.mmm)
    if vtt_time.count(':') == 2 and '.' in vtt_time:
        parts = vtt_time.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_parts = parts[2].split('.')
            seconds = int(seconds_parts[0])
            milliseconds = int(seconds_parts[1][:3].ljust(3, '0'))  # Ensure 3 digits
            
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
    
    # Handle format like "00:02.600" (MM:SS.mmm)
    if vtt_time.count(':') == 1 and '.' in vtt_time:
        parts = vtt_time.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds_parts = parts[1].split('.')
            seconds = int(seconds_parts[0])
            milliseconds = int(seconds_parts[1][:3].ljust(3, '0'))  # Ensure 3 digits
            
            # Convert minutes to hours and minutes
            hours = minutes // 60
            minutes = minutes % 60
            
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
    
    # Handle format like "2.600" (SS.mmm)
    if '.' in vtt_time and ':' not in vtt_time:
        try:
            seconds_parts = vtt_time.split('.')
            total_seconds = float(vtt_time)
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)
            milliseconds = int((total_seconds - int(total_seconds)) * 1000)
            
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
        except ValueError:
            pass
    
    # Default fallback
    return "00:00:00,000"

def parse_vtt_content(content: str) -> List[Tuple[str, str, str]]:
    """
    Parse VTT content and extract subtitle entries.
    
    Returns:
        List of tuples (start_time, end_time, text)
    """
    subtitles = []
    
    # Remove WEBVTT header and metadata
    lines = content.split('\n')
    content_lines = []
    skip_next = False
    
    for i, line in enumerate(lines):
        # Skip WEBVTT header
        if line.strip() == 'WEBVTT':
            skip_next = True
            continue
        
        # Skip metadata lines (Kind:, Language:, etc.)
        if skip_next and (line.strip() == '' or ':' in line):
            if line.strip() == '':
                skip_next = False
            continue
        
        skip_next = False
        content_lines.append(line)
    
    # Join and split by double newlines
    content = '\n'.join(content_lines)
    blocks = content.split('\n\n')
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        lines = block.split('\n')
        if len(lines) < 2:
            continue
        
        # First line should be timing
        timing_line = lines[0].strip()
        if '-->' not in timing_line:
            # Might be a cue identifier, skip it
            if len(lines) > 1 and '-->' in lines[1]:
                timing_line = lines[1].strip()
                text_lines = lines[2:]
            else:
                continue
        else:
            text_lines = lines[1:]
        
        # Parse timing
        timing_parts = timing_line.split(' --> ')
        if len(timing_parts) != 2:
            continue
        
        start_time = convert_vtt_time_to_srt(timing_parts[0].strip())
        end_time = convert_vtt_time_to_srt(timing_parts[1].strip())
        
        # Rest of the lines are the text
        text = '\n'.join(text_lines).strip()
        
        # Remove HTML tags if present
        text = re.sub(r'<[^>]+>', '', text)
        
        if text:
            subtitles.append((start_time, end_time, text))
    
    return subtitles

def convert_vtt_to_srt(vtt_path: Path, srt_path: Path) -> bool:
    """
    Convert VTT file to SRT format.
    
    Args:
        vtt_path: Path to input VTT file
        srt_path: Path to output SRT file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(vtt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse VTT content
        subtitles = parse_vtt_content(content)
        
        if not subtitles:
            print(f"⚠️  Nenhuma legenda encontrada em {vtt_path.name}")
            return False
        
        # Write SRT file
        srt_content = []
        for i, (start_time, end_time, text) in enumerate(subtitles, 1):
            srt_content.append(f"{i}")
            srt_content.append(f"{start_time} --> {end_time}")
            srt_content.append(text)
            srt_content.append("")  # Empty line
        
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        print(f"✅ Convertido: {vtt_path.name} → {srt_path.name}")
        print(f"   {len(subtitles)} legendas convertidas")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao converter {vtt_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return False

def convert_directory(directory_name: str) -> bool:
    """
    Convert all .en.vtt files in a directory to .en.srt.
    
    Args:
        directory_name: Name of directory in assets/
        
    Returns:
        True if successful, False otherwise
    """
    assets_dir = Path("assets") / directory_name
    if not assets_dir.exists():
        print(f"❌ Diretório não encontrado: {assets_dir}")
        return False
    
    # Find all .en.vtt files
    vtt_files = list(assets_dir.glob("*.en.vtt"))
    
    if not vtt_files:
        print(f"❌ Nenhum arquivo .en.vtt encontrado em {assets_dir}")
        return False
    
    success_count = 0
    for vtt_file in vtt_files:
        # Generate output filename: replace .en.vtt with .en.srt
        srt_file = vtt_file.with_suffix('.srt').with_name(
            vtt_file.stem.replace('.en', '') + '.en.srt'
        )
        
        # If the replacement didn't work as expected, try simpler approach
        if srt_file == vtt_file:
            srt_file = vtt_file.parent / f"{vtt_file.stem}.srt"
        
        # Ensure .en.srt extension
        if not srt_file.name.endswith('.en.srt'):
            base_name = vtt_file.stem.replace('.en', '')
            srt_file = vtt_file.parent / f"{base_name}.en.srt"
        
        if convert_vtt_to_srt(vtt_file, srt_file):
            success_count += 1
    
    print(f"\n✅ Conversão concluída: {success_count}/{len(vtt_files)} arquivos convertidos")
    return success_count > 0

def convert_single_file(vtt_file_path: str) -> bool:
    """
    Convert a single VTT file to SRT.
    
    Args:
        vtt_file_path: Path to VTT file
        
    Returns:
        True if successful, False otherwise
    """
    vtt_path = Path(vtt_file_path)
    
    if not vtt_path.exists():
        print(f"❌ Arquivo não encontrado: {vtt_path}")
        return False
    
    # Generate output filename
    if vtt_path.name.endswith('.en.vtt'):
        srt_path = vtt_path.with_name(vtt_path.stem.replace('.en', '') + '.en.srt')
    else:
        srt_path = vtt_path.with_suffix('.srt')
    
    return convert_vtt_to_srt(vtt_path, srt_path)

def main():
    parser = argparse.ArgumentParser(description="Converter arquivos VTT para SRT")
    parser.add_argument("directory", nargs='?', help="Nome do diretório em assets/")
    parser.add_argument("--file", help="Caminho para um arquivo VTT específico")
    
    args = parser.parse_args()
    
    if args.file:
        # Convert single file
        success = convert_single_file(args.file)
        return 0 if success else 1
    elif args.directory:
        # Convert directory
        success = convert_directory(args.directory)
        return 0 if success else 1
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())

