#!/usr/bin/env python3
"""
VTT to SRT Converter - Converte arquivos VTT para SRT

Usage: python3 vtt_to_srt_converter.py <vtt_file_path> <output_srt_path>
Example: python3 vtt_to_srt_converter.py input.vtt output.srt

Converte arquivo VTT para formato SRT padrão.
"""

import sys
import re
from pathlib import Path

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
        
        # Remove WEBVTT header
        content = content.replace('WEBVTT\n\n', '')
        
        # Split by double newlines to get subtitle blocks
        blocks = content.split('\n\n')
        
        srt_content = []
        subtitle_index = 1
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 2:
                continue
                
            # First line should be timing
            timing_line = lines[0]
            if '-->' not in timing_line:
                continue
                
            # Convert VTT timing to SRT timing
            timing_parts = timing_line.split(' --> ')
            if len(timing_parts) != 2:
                continue
                
            start_time = convert_vtt_time_to_srt(timing_parts[0].strip())
            end_time = convert_vtt_time_to_srt(timing_parts[1].strip())
            
            # Rest of the lines are the text
            text = ' '.join(lines[1:]).strip()
            
            if text:
                srt_content.append(f"{subtitle_index}")
                srt_content.append(f"{start_time} --> {end_time}")
                srt_content.append(text)
                srt_content.append("")  # Empty line
                subtitle_index += 1
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        print(f"✅ Convertido: {vtt_path.name} → {srt_path.name}")
        print(f"   {subtitle_index - 1} legendas convertidas")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao converter: {e}")
        return False

def convert_vtt_time_to_srt(vtt_time: str) -> str:
    """
    Convert VTT time format to SRT time format.
    
    VTT: 00:02.600
    SRT: 00:00:02,600
    """
    # Remove any extra characters
    vtt_time = vtt_time.strip()
    
    # Handle format like "00:02.600"
    if ':' in vtt_time and '.' in vtt_time:
        parts = vtt_time.split(':')
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            
            # Convert to SRT format: HH:MM:SS,mmm
            hours = minutes // 60
            minutes = minutes % 60
            
            # Format seconds with milliseconds
            seconds_int = int(seconds)
            milliseconds = int((seconds - seconds_int) * 1000)
            
            return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{milliseconds:03d}"
    
    # Handle format like "2.600"
    try:
        seconds = float(vtt_time)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds_int = int(seconds % 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{milliseconds:03d}"
    except ValueError:
        return "00:00:00,000"

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 vtt_to_srt_converter.py <vtt_file_path> <output_srt_path>")
        return 1
    
    vtt_path = Path(sys.argv[1])
    srt_path = Path(sys.argv[2])
    
    if not vtt_path.exists():
        print(f"❌ Arquivo VTT não encontrado: {vtt_path}")
        return 1
    
    success = convert_vtt_to_srt(vtt_path, srt_path)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
