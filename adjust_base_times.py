#!/usr/bin/env python3
"""
Script para ajustar tempos de 'end' em arquivos base.txt

Funcionalidade:
- Lê arquivo base.txt de um diretório
- Ajusta tempos de end com a seguinte lógica:
  1. Adiciona 60 segundos ao tempo de end atual
  2. OU deixa o end 1ms anterior ao begin da próxima linha
  3. Escolhe o menor valor entre as duas opções

Formato suportado:
linha	start_time	end_time	texto_chinês	[traduções]	tradução_extra

Exemplo de uso:
python adjust_base_times.py assets/test/
python adjust_base_times.py assets/death_becomes_her/ --output assets/death_becomes_her_adjusted/
"""

import argparse
import re
from pathlib import Path
import shutil


def parse_time_string(time_str):
    """
    Parse time string format like '72.943s' to float seconds
    
    Args:
        time_str (str): Time in format 'XX.XXXs'
    
    Returns:
        float: Time in seconds
    """
    if time_str.endswith('s'):
        return float(time_str[:-1])
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def format_time_string(seconds):
    """
    Format float seconds back to string format 'XX.XXXs'
    
    Args:
        seconds (float): Time in seconds
    
    Returns:
        str: Formatted time string
    """
    return f"{seconds:.3f}s"


def parse_base_line(line):
    """
    Parse a single line from base.txt
    
    Args:
        line (str): Line from base.txt
    
    Returns:
        dict: Parsed line data with keys: line_num, start_time, end_time, rest
        None: If line cannot be parsed
    """
    line = line.strip()
    if not line:
        return None
    
    # Split by tabs
    parts = line.split('\t')
    if len(parts) < 3:
        return None
    
    try:
        line_num = parts[0]
        start_time = parse_time_string(parts[1])
        end_time = parse_time_string(parts[2])
        rest = '\t'.join(parts[3:])  # Join remaining parts
        
        return {
            'line_num': line_num,
            'start_time': start_time,
            'end_time': end_time,
            'rest': rest
        }
    except (ValueError, IndexError) as e:
        print(f"Warning: Could not parse line: {line[:50]}... - Error: {e}")
        return None


def adjust_end_times(parsed_lines):
    """
    Adjust end times according to the logic:
    - Add 60 seconds to current end time
    - OR set to 1ms before next line's start time
    - Choose the smaller value
    
    Args:
        parsed_lines (list): List of parsed line dictionaries
    
    Returns:
        list: List of adjusted parsed lines
    """
    adjusted_lines = []
    
    for i, line_data in enumerate(parsed_lines):
        if line_data is None:
            adjusted_lines.append(line_data)
            continue
        
        # Copy the original data
        adjusted_line = line_data.copy()
        current_end = line_data['end_time']
        
        # Option 2: 1ms before next line's start (if there is a next line)
        if i + 1 < len(parsed_lines) and parsed_lines[i + 1] is not None:
            next_start = parsed_lines[i + 1]['start_time']
            option2_end = next_start - 0.001  # 1ms before next start
            # Option 1: no máximo +60s de exibição
            option1_end = current_end + 60.0
            new_end_time = min(option1_end, option2_end)
        else:
            # Última linha (sem próxima): estende +60s sobre o START, não sobre o
            # end atual — assim reprocessar o mesmo base é IDEMPOTENTE (não cresce
            # +60 a cada passada).
            new_end_time = line_data['start_time'] + 60.0
        
        # Ensure the new end time is not before the current start time
        if new_end_time <= line_data['start_time']:
            new_end_time = line_data['start_time'] + 0.001  # At least 1ms duration
        
        adjusted_line['end_time'] = new_end_time
        adjusted_lines.append(adjusted_line)
    
    return adjusted_lines


def write_adjusted_base_file(adjusted_lines, output_path):
    """
    Write the adjusted lines back to a base.txt file
    
    Args:
        adjusted_lines (list): List of adjusted parsed lines
        output_path (Path): Output file path
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for line_data in adjusted_lines:
            if line_data is None:
                f.write('\n')
                continue
            
            # Format the line back to original format
            formatted_line = (
                f"{line_data['line_num']}\t"
                f"{format_time_string(line_data['start_time'])}\t"
                f"{format_time_string(line_data['end_time'])}\t"
                f"{line_data['rest']}\n"
            )
            f.write(formatted_line)


def find_base_txt_file(directory):
    """
    Find base.txt file in the directory
    
    Args:
        directory (Path): Directory to search
    
    Returns:
        Path: Path to base.txt file, or None if not found
    """
    # Look for common base.txt variations
    possible_names = [
        'base.txt',
        'test_sub_zht_secs_base.txt',
        '*_base.txt'
    ]
    
    for pattern in possible_names:
        if '*' in pattern:
            matches = list(directory.glob(pattern))
            if matches:
                return matches[0]  # Return first match
        else:
            base_file = directory / pattern
            if base_file.exists():
                return base_file
    
    return None


def process_directory(input_dir, output_dir=None, backup=True):
    """
    Process base.txt file in a directory
    
    Args:
        input_dir (Path): Input directory containing base.txt
        output_dir (Path): Output directory (default: same as input)
        backup (bool): Whether to create backup of original file
    
    Returns:
        bool: Success status
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"❌ Input directory not found: {input_path}")
        return False
    
    # Find base.txt file
    base_file = find_base_txt_file(input_path)
    if not base_file:
        print(f"❌ No base.txt file found in: {input_path}")
        print("   Looked for: base.txt, *_base.txt")
        return False
    
    print(f"📄 Found base file: {base_file.name}")
    
    # Determine output directory and file
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        output_file = output_path / base_file.name
    else:
        output_file = base_file
    
    # Create backup if needed
    if backup and output_file == base_file:
        backup_file = base_file.with_suffix('.bak')
        shutil.copy2(base_file, backup_file)
        print(f"💾 Backup created: {backup_file.name}")
    
    # Read and parse the file
    print(f"📖 Reading file: {base_file}")
    
    try:
        with open(base_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        print("❌ Error reading file. Trying different encodings...")
        try:
            with open(base_file, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(base_file, 'r', encoding='latin-1') as f:
                lines = f.readlines()
    
    # Parse all lines
    parsed_lines = []
    for line in lines:
        parsed_line = parse_base_line(line)
        parsed_lines.append(parsed_line)
    
    valid_lines = [line for line in parsed_lines if line is not None]
    print(f"📊 Parsed {len(valid_lines)} valid subtitle entries")
    
    if not valid_lines:
        print("❌ No valid subtitle entries found")
        return False
    
    # Adjust end times
    print("⏱️  Adjusting end times...")
    adjusted_lines = adjust_end_times(parsed_lines)
    
    # Show some examples of adjustments
    print("\n📋 Sample adjustments:")
    for i, (original, adjusted) in enumerate(zip(parsed_lines[:3], adjusted_lines[:3])):
        if original and adjusted:
            old_end = original['end_time']
            new_end = adjusted['end_time']
            diff = new_end - old_end
            print(f"   Line {original['line_num']}: {format_time_string(old_end)} → {format_time_string(new_end)} (+{diff:.3f}s)")
    
    # Write adjusted file
    print(f"💾 Writing adjusted file: {output_file}")
    write_adjusted_base_file(adjusted_lines, output_file)
    
    print(f"✅ Successfully adjusted {len(valid_lines)} subtitle entries!")
    print(f"📁 Output saved to: {output_file}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Adjust end times in base.txt subtitle files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 adjust_base_times.py test
  python3 adjust_base_times.py death_becomes_her
  python3 adjust_base_times.py test --no-backup

Logic for adjusting end times:
  1. Calculate: current_end + 60 seconds
  2. Calculate: next_line_start - 1ms (if next line exists)  
  3. Use the smaller of the two values
  4. Ensure end time is always after start time
  
Note: Script automatically looks for base.txt files in assets/{folder_name}/
        """)
    
    parser.add_argument('folder_name', 
                       help='Folder name inside assets/ directory (e.g., "test", "death_becomes_her")')
    parser.add_argument('--no-backup', action='store_true',
                       help='Skip creating backup of original file')
    
    args = parser.parse_args()
    
    print("🎬 Base.txt Time Adjuster")
    print("=" * 50)
    
    # Construct the full path to assets/{folder_name}
    assets_dir = Path('assets') / args.folder_name
    
    if not assets_dir.exists():
        print(f"❌ Assets directory not found: {assets_dir}")
        print(f"   Make sure the folder 'assets/{args.folder_name}' exists")
        return 1
    
    success = process_directory(
        input_dir=assets_dir,
        output_dir=None,  # Modify original file
        backup=not args.no_backup
    )
    
    if success:
        print("\n🎉 Time adjustment completed successfully!")
    else:
        print("\n❌ Time adjustment failed!")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
