#!/usr/bin/env python3
"""
Add seconds to SRT subtitle timestamps

Usage: python3 add_seconds_to_srt.py <srt_file> <seconds_to_add>

Example: python3 add_seconds_to_srt.py subtitle.srt 3
"""

import sys
import re
from datetime import datetime, timedelta


def parse_srt_time(time_str):
    """Parse SRT timestamp to datetime object."""
    # SRT format: HH:MM:SS,mmm
    time_str = time_str.strip()
    hours, minutes, seconds_ms = time_str.split(':')
    seconds, milliseconds = seconds_ms.split(',')

    # Create time object
    return datetime.strptime(f"{hours}:{minutes}:{seconds},{milliseconds}", "%H:%M:%S,%f")


def format_srt_time(dt):
    """Format datetime object to SRT timestamp."""
    return dt.strftime("%H:%M:%S,%f")[:-3]  # Remove microseconds, keep milliseconds


def add_seconds_to_srt(input_file, output_file, seconds_to_add):
    """Add seconds to all timestamps in SRT file."""
    print(f"📝 Processando arquivo: {input_file}")
    print(f"⏱️  Adicionando {seconds_to_add} segundos a todos os timestamps...")

    modified_count = 0

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split content into lines
    lines = content.split('\n')

    # Process each line
    for i, line in enumerate(lines):
        # Check if line contains timestamp (contains -->)
        if '-->' in line:
            # Split timestamps
            start_time, end_time = line.split('-->')

            # Parse and add seconds
            start_dt = parse_srt_time(start_time)
            end_dt = parse_srt_time(end_time)

            # Add seconds
            start_dt += timedelta(seconds=seconds_to_add)
            end_dt += timedelta(seconds=seconds_to_add)

            # Format back to SRT
            new_start = format_srt_time(start_dt)
            new_end = format_srt_time(end_dt)

            # Update line
            lines[i] = f"{new_start} --> {new_end}"
            modified_count += 1

    # Write modified content
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print("✅ Processamento concluído!")
    print(f"📊 Total de timestamps modificados: {modified_count}")
    print(f"💾 Arquivo salvo como: {output_file}")


def main():
    if len(sys.argv) != 3:
        print("Uso: python3 add_seconds_to_srt.py <arquivo_srt> <segundos>")
        print("Exemplo: python3 add_seconds_to_srt.py subtitle.srt 3")
        sys.exit(1)

    input_file = sys.argv[1]
    seconds_to_add = float(sys.argv[2])
    output_file = input_file.replace('.srt', f'_mais_{int(seconds_to_add)}s.srt')

    add_seconds_to_srt(input_file, output_file, seconds_to_add)


if __name__ == "__main__":
    main()
