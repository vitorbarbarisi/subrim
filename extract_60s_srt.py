#!/usr/bin/env python3
"""
Extract first 60 seconds of SRT subtitles
"""

import re
from pathlib import Path

def time_to_seconds(time_str):
    """Convert SRT time format to seconds"""
    # Format: 00:00:26,880
    parts = time_str.replace(',', '.').split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds

def seconds_to_time(seconds):
    """Convert seconds to SRT time format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace('.', ',')

def extract_first_60s_srt(srt_file, output_file):
    """Extract first 60 seconds from SRT file"""
    
    with open(srt_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split into subtitle blocks
    blocks = re.split(r'\n\s*\n', content.strip())
    
    output_blocks = []
    subtitle_num = 1
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
            
        # Parse subtitle number, timing, and text
        try:
            timing_line = lines[1]
            # Extract start and end times
            match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', timing_line)
            if not match:
                continue
                
            start_time = match.group(1)
            end_time = match.group(2)
            
            start_seconds = time_to_seconds(start_time)
            end_seconds = time_to_seconds(end_time)
            
            # Only include subtitles that start within first 60 seconds
            if start_seconds < 60.0:
                # If subtitle extends beyond 60s, truncate it
                if end_seconds > 60.0:
                    end_seconds = 60.0
                    end_time = seconds_to_time(end_seconds)
                
                # Get subtitle text
                text_lines = lines[2:]
                text = '\n'.join(text_lines)
                
                # Create new subtitle block
                new_block = f"{subtitle_num}\n{start_time} --> {end_time}\n{text}"
                output_blocks.append(new_block)
                subtitle_num += 1
            else:
                # Stop processing once we go beyond 60 seconds
                break
                
        except Exception as e:
            print(f"Error processing block: {e}")
            continue
    
    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(output_blocks))
        if output_blocks:
            f.write('\n')
    
    print(f"Extracted {len(output_blocks)} subtitles from first 60 seconds")
    return len(output_blocks)

if __name__ == "__main__":
    srt_input = "/Users/vitor.barbarisi/dev/subrim/assets/onibus152/Capítulo de 25⧸03⧸2025 [13458287].pt-BR.srt"
    srt_output = "/Users/vitor.barbarisi/dev/subrim/assets/test/test_60s.srt"
    
    extract_first_60s_srt(srt_input, srt_output)
