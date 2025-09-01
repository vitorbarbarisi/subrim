#!/usr/bin/env python3
"""
Video Subtitle Printer - Adiciona legendas chinesas e traduções aos vídeos MP4

Usage: python3 video_subtitle_printer.py <directory_name>
Example: python3 video_subtitle_printer.py chaves001

O script lê o vídeo MP4 em assets/<directory_name>/ e o arquivo *_base.txt correspondente.
Cria uma cópia do vídeo com legendas all-in-one aplicadas diretamente (hardcoded):

- Legenda chinesa com pinyin acima e traduções em português abaixo de cada palavra
- O vídeo resultante tem as legendas permanentemente incorporadas
"""

import sys
import argparse
import shutil
import subprocess
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import re

def parse_pinyin_translations(translation_list_str: str) -> list[tuple[str, str, str]]:
    """
    Parse the translation list string to extract Chinese characters, pinyin, and Portuguese translations.
    
    Args:
        translation_list_str: String like '["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'
        
    Returns:
        List of tuples (chinese_chars, pinyin, portuguese_translation)
        Example: [("三", "sān", "três"), ("號", "hào", "número"), ("碼頭", "mǎ tóu", "cais")]
    """
    try:
        # Clean and parse the list
        translation_list_str = translation_list_str.strip()
        if not translation_list_str.startswith('[') or not translation_list_str.endswith(']'):
            return []
        
        # Remove brackets and split by quotes
        content = translation_list_str[1:-1]  # Remove [ and ]
        
        # Split by ", " but keep the quotes
        import re
        items = re.findall(r'"([^"]*)"', content)
        
        result = []
        for item in items:
            # Parse format: "三 (sān): três"
            # Extract Chinese characters, pinyin, and Portuguese translation
            match = re.match(r'^([^\s\(]+)\s*\(([^)]+)\)\s*:\s*(.+)$', item)
            if match:
                chinese_chars = match.group(1).strip()
                pinyin = match.group(2).strip()
                portuguese = match.group(3).strip()
                result.append((chinese_chars, pinyin, portuguese))
            else:
                # Fallback: try to extract just Chinese chars if format doesn't match
                chinese_match = re.match(r'^([^\s\(]+)', item)
                if chinese_match:
                    chinese_chars = chinese_match.group(1)
                    result.append((chinese_chars, "", ""))  # Empty pinyin/portuguese
        
        return result
        
    except Exception as e:
        print(f"Erro ao fazer parsing da lista de traduções com pinyin: {e}")
        return []


def parse_base_file(base_file_path: Path) -> Dict[float, Tuple[str, str, str, str, float]]:
    """
    Parse the base.txt file and return a mapping of begin_time -> (chinese subtitle, translations, translations_json, portuguese, duration).
    
    Supports both old format (5 columns) and new format (6 columns):
    - Old: index, begin_time, chinese_text, translations, portuguese
    - New: index, begin_time, end_time, chinese_text, translations, portuguese
    
    For new format, calculates duration as end_time - begin_time.
    For old format, uses default duration of 3 seconds.
    
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
                if len(parts) < 4:
                    continue
                
                # Detect format based on number of columns
                is_new_format = len(parts) >= 6
                
                # Extract begin timestamp (second column)
                begin_timestamp_str = parts[1].strip()
                
                # Extract seconds from begin timestamp (e.g., "186.645s" -> 186.645)
                begin_match = re.match(r'([\d.]+)s?', begin_timestamp_str)
                if not begin_match:
                    continue
                
                begin_seconds = float(begin_match.group(1))
                
                # Extract end timestamp and calculate duration if available
                duration = 3.0  # Default duration
                if is_new_format:
                    end_timestamp_str = parts[2].strip()
                    end_match = re.match(r'([\d.]+)s?', end_timestamp_str)
                    if end_match:
                        end_seconds = float(end_match.group(1))
                        duration = max(0.5, end_seconds - begin_seconds)  # Minimum 0.5 second duration
                
                # Extract Chinese subtitle - column position depends on format
                if is_new_format:
                    # New format: index, begin, end, chinese, translations, portuguese
                    chinese_text = parts[3].strip()
                    translations_text = parts[4].strip()
                    portuguese_text = parts[5].strip() if len(parts) >= 6 else ""
                else:
                    # Old format: index, begin, chinese, translations, portuguese
                    chinese_text = parts[2].strip()
                    translations_text = parts[3].strip()
                    portuguese_text = parts[4].strip() if len(parts) >= 5 else ""
                
                # Remove parentheses if present
                chinese_text = re.sub(r'^（(.*)）$', r'\1', chinese_text)
                
                # Keep original JSON string for translations
                translations_json = translations_text
                
                # Parse translations list if it exists
                if translations_text and translations_text != 'N/A':
                    try:
                        # Remove outer brackets and parse as list
                        import ast
                        translations_list = ast.literal_eval(translations_text)
                        if isinstance(translations_list, list):
                            # Join translations with line breaks
                            formatted_translations = '\n'.join(translations_list)
                        else:
                            formatted_translations = translations_text
                    except:
                        # If parsing fails, use raw text
                        formatted_translations = translations_text
                else:
                    formatted_translations = ""
                    translations_json = ""
                
                # Clean Portuguese text
                if portuguese_text == 'N/A':
                    portuguese_text = ""
                
                if chinese_text and chinese_text != 'N/A':
                    subtitles[begin_seconds] = (chinese_text, formatted_translations, translations_json, portuguese_text, duration)
                    
    except Exception as e:
        print(f"Erro ao ler arquivo base {base_file_path}: {e}")
    
    return subtitles


def find_base_file(directory: Path) -> Optional[Path]:
    """Find the base.txt file in the directory."""
    # Look for files ending with _base.txt
    base_files = list(directory.glob("*_base.txt"))
    if base_files:
        return base_files[0]
    
    # Look for files named base.txt
    base_file = directory / "base.txt"
    if base_file.exists():
        return base_file
    
    return None


def find_mp4_files(directory: Path) -> List[Path]:
    """Find all MP4 files in the directory, excluding files that already have subtitles or are batch files."""
    mp4_files = []
    
    for file_path in directory.glob("*.mp4"):
        # Skip files that already have subtitles (end with _sub.mp4) or are batch files (_sub_batch_X.mp4)
        if not file_path.stem.endswith('_sub') and '_batch_' not in file_path.stem:
            mp4_files.append(file_path)
    
    return sorted(mp4_files)


def create_ffmpeg_drawtext_filters(subtitles: Dict[float, Tuple[str, str, str, str, float]], video_width: int = 1920, video_height: int = 1080) -> str:
    """
    Create FFmpeg drawtext filters to render Chinese text, pinyin, and Portuguese translations directly on video.
    
    Args:
        subtitles: Dictionary mapping begin_time to subtitle data
        video_width: Video width for positioning (default 1920)
        video_height: Video height for positioning (default 1080)
        
    Returns:
        FFmpeg filter string for drawtext operations
    """
    filter_parts = []
    
    # Get appropriate font paths once for all subtitles
    chinese_font_path = get_best_chinese_font()
    latin_font_path = get_best_latin_font()
    
    print(f"   🔤 Fonte chinesa: {chinese_font_path}")
    print(f"   🔤 Fonte latina: {latin_font_path}")
    
    # Sort subtitles by time
    for begin_time in sorted(subtitles.keys()):
        chinese_text, translations_text, translations_json, portuguese_text, duration = subtitles[begin_time]
        
        # Parse translations for pinyin and word-by-word Portuguese
        word_data = parse_pinyin_translations(translations_json) if translations_json else []
        
        # Clean Chinese text
        clean_chinese = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '')
        
        # Group characters into words and build display data
        display_items = []
        remaining_text = clean_chinese
        
        while remaining_text:
            found_word = False
            
            # Try to find the longest matching word
            for chinese_word, word_pinyin, word_portuguese in sorted(word_data, key=lambda x: len(x[0]), reverse=True):
                if remaining_text.startswith(chinese_word):
                    display_items.append((chinese_word, word_pinyin, word_portuguese))
                    remaining_text = remaining_text[len(chinese_word):]
                    found_word = True
                    break
            
            if not found_word:
                # Single character with no translation
                char = remaining_text[0]
                display_items.append((char, "", ""))
                remaining_text = remaining_text[1:]
        
        # Calculate positioning for subtitle area (bottom 320px of video to accommodate multi-line Portuguese)
        chinese_y = video_height - 170  # Chinese text in middle of subtitle area
        portuguese_y = video_height - 80   # Portuguese below Chinese (more space to avoid overlap)
        pinyin_y = video_height - 230    # Pinyin above Chinese
        
        # Build text for each line with proper spacing
        chinese_parts = []
        pinyin_parts = []
        portuguese_parts = []
        
        for chinese_word, word_pinyin, word_portuguese in display_items:
            chinese_parts.append(chinese_word)
            if word_pinyin:
                pinyin_parts.append(word_pinyin)
            else:
                pinyin_parts.append(' ')  # Placeholder to maintain alignment
            
            if word_portuguese:
                # Keep full Portuguese translation (no truncation)
                portuguese_parts.append(word_portuguese)
            else:
                portuguese_parts.append('')  # Empty for words without translation
        
        # Create word-by-word aligned subtitle with pinyin centered over each Chinese word
        # Calculate total line width first to center the entire subtitle block
        total_line_width = 0
        word_widths = []
        
        # Calculate width of each word for positioning
        for chinese_word, word_pinyin, word_portuguese in display_items:
            # Use a dummy drawtext to estimate width (approximate calculation)
            # Chinese word width (64px font)
            chinese_word_width = len(chinese_word) * 45  # Approximate: 45px per Chinese character at 64px font
            
            # Pinyin width (36px font) 
            pinyin_width = len(word_pinyin) * 20 if word_pinyin else 0  # Approximate: 20px per Latin char at 36px font
            
            # Use the wider of the two for spacing
            word_width = max(chinese_word_width, pinyin_width, 80)  # Minimum 80px spacing
            word_widths.append(word_width)
            total_line_width += word_width
        
        # Calculate starting x position to center the entire line
        start_x = (video_width - total_line_width) // 2
        
        # Create time conditions - escape commas for FFmpeg enable parameter
        end_time = begin_time + duration
        time_condition = f"between(t\\,{begin_time:.3f}\\,{end_time:.3f})"
        
        # Add each word with its pinyin and Portuguese positioned individually
        current_x = start_x
        for i, (chinese_word, word_pinyin, word_portuguese) in enumerate(display_items):
            word_width = word_widths[i]
            
            # Escape text for FFmpeg
            chinese_escaped = escape_ffmpeg_text(chinese_word)
            pinyin_escaped = escape_ffmpeg_text(word_pinyin) if word_pinyin else ""
            
            # Calculate center position for this word within its allocated width
            word_center_x = current_x + word_width // 2
            
            # Chinese text (centered within word width)
            filter_parts.append(f"drawtext=text='{chinese_escaped}':x={word_center_x}-text_w/2:y={chinese_y}:fontfile='{chinese_font_path}':fontsize=64:fontcolor=white:borderw=3:bordercolor=black:enable='{time_condition}'")
            
            # Pinyin text (centered over the Chinese word)
            if pinyin_escaped:
                filter_parts.append(f"drawtext=text='{pinyin_escaped}':x={word_center_x}-text_w/2:y={pinyin_y}:fontfile='{chinese_font_path}':fontsize=36:fontcolor=#9370DB:borderw=2:bordercolor=black:enable='{time_condition}'")
            
            # Portuguese text (centered below each Chinese word, with line breaks if needed)
            if word_portuguese:
                portuguese_lines = wrap_portuguese_to_chinese_width(word_portuguese, latin_font_path, word_width)
                portuguese_line_height = 22  # Approximate line height for 20px font (reduced)
                
                for line_idx, portuguese_line in enumerate(portuguese_lines):
                    if portuguese_line.strip():  # Only add non-empty lines
                        portuguese_escaped = escape_ffmpeg_text(portuguese_line)
                        portuguese_line_y = portuguese_y + (line_idx * portuguese_line_height)
                        filter_parts.append(f"drawtext=text='{portuguese_escaped}':x={word_center_x}-text_w/2:y={portuguese_line_y}:fontfile='{latin_font_path}':fontsize=20:fontcolor=yellow:borderw=2:bordercolor=black:enable='{time_condition}'")
            
            current_x += word_width
    
    # Format for filter complex script file
    if filter_parts:
        # Start with input and chain all filters, ending with output label
        return f"[0:v]{','.join(filter_parts)}[v]"
    else:
        return "[0:v]copy[v]"  # No filters, just copy video


def wrap_portuguese_to_chinese_width(portuguese_text: str, font_path: str, max_width: int) -> List[str]:
    """
    Break Portuguese text into multiple lines to fit within the Chinese word width.
    Never breaks words in the middle - only breaks at word boundaries.
    
    Args:
        portuguese_text: Portuguese text to break
        font_path: Path to the font file
        max_width: Maximum width in pixels (width of the Chinese word)
        
    Returns:
        List of text lines that fit within max_width
    """
    if not portuguese_text:
        return []
    
    # Estimate character width for 20px font (reduced from 24px)
    char_width = 10  # Average width for Latin characters at 20px
    chars_per_line = max(3, max_width // char_width)  # Minimum 3 characters per line
    
    words = portuguese_text.split()
    if not words:
        return [portuguese_text]
    
    # If it's a single word and fits, return it
    if len(words) == 1 and len(words[0]) <= chars_per_line:
        return [words[0]]
    
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        # Check if adding this word would exceed the line limit
        word_length = len(word)
        space_length = 1 if current_line else 0  # Space before word (except first word)
        
        if current_length + space_length + word_length <= chars_per_line:
            # Word fits in current line
            current_line.append(word)
            current_length += space_length + word_length
        else:
            # Word doesn't fit, start new line
            if current_line:
                lines.append(' '.join(current_line))
                current_line = []
                current_length = 0
            
            # If single word is still too long for a line by itself, keep it whole
            # Better to have one long word than break it in the middle
            if word_length > chars_per_line:
                lines.append(word)  # Keep the word whole even if it's long
            else:
                # Start new line with this word
                current_line = [word]
                current_length = word_length
    
    # Add remaining words
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def get_best_chinese_font() -> str:
    """Find the best available Chinese font for FFmpeg."""
    # List of Chinese fonts in order of preference (verified for this system)
    chinese_fonts = [
        '/System/Library/Fonts/STHeiti Medium.ttc',     # macOS Chinese (verified available)
        '/System/Library/Fonts/STHeiti Light.ttc',      # macOS Chinese (verified available)  
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',   # Universal Unicode (verified available)
        '/Library/Fonts/Arial Unicode.ttf',             # Alternative path
        '/System/Library/Fonts/PingFang.ttc',           # macOS modern (if available)
        '/System/Library/Fonts/Hiragino Sans GB.ttc',   # macOS fallback  
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',  # Linux
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',  # Linux fallback
        'arial',  # FFmpeg's built-in fallback
    ]
    
    for font_path in chinese_fonts:
        if font_path == 'arial' or Path(font_path).exists():
            return font_path
    
    # Final fallback
    return 'arial'


def get_best_latin_font() -> str:
    """Find the best available Latin font for FFmpeg."""
    # List of Latin fonts in order of preference (verified for this system)
    latin_fonts = [
        '/System/Library/Fonts/Supplemental/Arial.ttf',  # macOS Arial (verified available)
        '/System/Library/Fonts/Helvetica.ttc',          # macOS clean
        '/System/Library/Fonts/ArialHB.ttc',            # macOS Arial
        '/System/Library/Fonts/HelveticaNeue.ttc',      # macOS modern  
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',   # Universal Unicode (verified available)
        '/Library/Fonts/Arial Unicode.ttf',             # Alternative path
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',  # Linux
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux alternative
        'arial',  # FFmpeg built-in fallback
    ]
    
    for font_path in latin_fonts:
        if font_path == 'arial' or Path(font_path).exists():
            return font_path
    
    # Final fallback
    return 'arial'


def escape_ffmpeg_text(text: str) -> str:
    """Escape text for FFmpeg drawtext filter."""
    if not text:
        return ""
    # Escape special characters for FFmpeg
    text = text.replace('\\', '\\\\')  # Backslash
    text = text.replace("'", "\\'")    # Single quote
    text = text.replace(':', '\\:')    # Colon
    text = text.replace('[', '\\[')    # Left bracket
    text = text.replace(']', '\\]')    # Right bracket
    return text


def get_video_info(video_path: Path) -> Tuple[int, int, float]:
    """Get video dimensions and duration using ffprobe."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'csv=p=0',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,duration',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        parts = result.stdout.strip().split(',')
        width = int(parts[0])
        height = int(parts[1])
        duration = float(parts[2]) if parts[2] and parts[2] != 'N/A' else 0.0
        return width, height, duration
    except:
        # Default values if detection fails
        return 1920, 1080, 0.0


def get_video_dimensions(video_path: Path) -> Tuple[int, int]:
    """Get video dimensions using ffprobe (legacy function)."""
    width, height, _ = get_video_info(video_path)
    return width, height


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def parse_ffmpeg_progress(line: str) -> Optional[float]:
    """Parse FFmpeg progress output and return current time in seconds."""
    if line.startswith('out_time_ms='):
        try:
            # out_time_ms is in microseconds, convert to seconds
            time_ms = int(line.split('=')[1])
            return time_ms / 1_000_000.0
        except:
            pass
    elif line.startswith('out_time='):
        try:
            # out_time format: HH:MM:SS.microseconds
            time_str = line.split('=')[1]
            # Parse HH:MM:SS.microseconds
            parts = time_str.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds_parts = parts[2].split('.')
                seconds = int(seconds_parts[0])
                microseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
                
                total_seconds = hours * 3600 + minutes * 60 + seconds + microseconds / 1_000_000.0
                return total_seconds
        except:
            pass
    return None


def create_filter_file(drawtext_filters: str) -> str:
    """
    Create a temporary filter file for FFmpeg to avoid 'Argument list too long' errors.
    
    Args:
        drawtext_filters: FFmpeg filter string
        
    Returns:
        Path to temporary filter file
    """
    # Create temporary file for filters
    fd, temp_path = tempfile.mkstemp(suffix='.txt', prefix='ffmpeg_filters_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            # Write the filter chain to the file
            f.write(drawtext_filters)
        return temp_path
    except Exception:
        # If writing fails, cleanup the file descriptor
        try:
            os.close(fd)
        except:
            pass
        raise


def apply_subtitles_in_batches(input_video: Path, subtitles: Dict[float, Tuple[str, str, str, str, float]], output_video: Path, video_width: int, video_height: int, video_duration: float) -> bool:
    """
    Apply subtitles to video in batches to avoid argument list limitations.
    
    Args:
        input_video: Path to input MP4 file
        subtitles: Dictionary with subtitle data
        output_video: Path to output MP4 file
        video_width: Video width
        video_height: Video height
        video_duration: Video duration in seconds
        
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"🎬 Processamento em lotes iniciado...")
        print(f"📊 Total de legendas: {len(subtitles)}")
        
        # Split subtitles into batches of manageable size
        batch_size = 100  # Process 100 subtitles at a time
        subtitle_times = sorted(subtitles.keys())
        batches = [subtitle_times[i:i + batch_size] for i in range(0, len(subtitle_times), batch_size)]
        
        print(f"📦 Dividido em {len(batches)} lotes de até {batch_size} legendas cada")
        
        # Check for existing batch files to resume processing
        existing_batches = []
        start_batch_idx = 0
        current_input = input_video
        temp_files = []
        
        print(f"🔍 Verificando lotes existentes...")
        for batch_idx in range(len(batches)):
            if batch_idx == len(batches) - 1:
                # Last batch outputs to final file
                batch_output = output_video
            else:
                # Intermediate batch outputs to temp file
                temp_suffix = f"_batch_{batch_idx}.mp4"
                batch_output = output_video.parent / (output_video.stem + temp_suffix)
            
            if batch_output.exists():
                existing_batches.append(batch_idx)
                start_batch_idx = batch_idx + 1
                current_input = batch_output  # Use this as input for next batch
                if batch_idx < len(batches) - 1:  # Don't add final output to temp_files
                    temp_files.append(batch_output)
                print(f"   ✅ Lote {batch_idx + 1} já existe: {batch_output.name}")
            else:
                break  # Stop at first missing batch
        
        if existing_batches:
            print(f"🔄 Retomando processamento a partir do lote {start_batch_idx + 1}/{len(batches)}")
            print(f"📂 Usando como entrada: {current_input.name}")
        else:
            print(f"🆕 Iniciando processamento do zero")
        
        # Check if all batches are already complete
        if start_batch_idx >= len(batches):
            print(f"✅ Todos os lotes já foram processados!")
            return True
        
        for batch_idx, batch_times in enumerate(batches):
            # Skip batches that are already completed
            if batch_idx < start_batch_idx:
                continue
                
            print(f"\n🔄 Processando lote {batch_idx + 1}/{len(batches)} ({len(batch_times)} legendas)...")
            
            # Create batch subtitles dictionary
            batch_subtitles = {time: subtitles[time] for time in batch_times}
            
            # Create drawtext filters for this batch
            batch_filters = create_ffmpeg_drawtext_filters(batch_subtitles, video_width, video_height)
            
            if not batch_filters:
                continue
            
            # Determine output file for this batch
            if batch_idx == len(batches) - 1:
                # Last batch outputs to final file
                batch_output = output_video
            else:
                # Intermediate batch outputs to temp file
                temp_suffix = f"_batch_{batch_idx}.mp4"
                batch_output = output_video.parent / (output_video.stem + temp_suffix)
                temp_files.append(batch_output)
            
            # FFmpeg command for this batch
            cmd = [
                'ffmpeg',
                '-i', str(current_input),
                '-filter_complex', batch_filters,
                '-map', '[v]',
                '-c:v', 'libx264',
                '-c:a', 'copy',
                '-crf', '18',
                '-preset', 'medium',
                '-progress', 'pipe:1',
                '-nostats',
                '-y',
                str(batch_output)
            ]
            
            print(f"   ⚙️  Aplicando {len(batch_subtitles)} legendas...")
            print(f"   📂 Saída: {batch_output.name}")
            
            # Run FFmpeg for this batch
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            last_progress = -1
            stderr_output = []
            
            # Read progress from stdout
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                    
                if line:
                    current_time = parse_ffmpeg_progress(line.strip())
                    if current_time is not None and video_duration > 0:
                        progress_percent = min(100.0, (current_time / video_duration) * 100)
                        
                        if int(progress_percent) > last_progress:
                            last_progress = int(progress_percent)
                            print(f"\r   📊 Lote {batch_idx + 1}: {last_progress:3d}% ({current_time:.1f}s/{video_duration:.1f}s)", end='', flush=True)
            
            # Read stderr
            stderr_data = process.stderr.read()
            if stderr_data:
                stderr_output.append(stderr_data)
            
            # Wait for completion
            return_code = process.wait()
            
            print()  # New line after progress
            
            if return_code == 0:
                print(f"   ✅ Lote {batch_idx + 1} concluído!")
                current_input = batch_output  # Use this output as input for next batch
            else:
                print(f"   ❌ Erro no lote {batch_idx + 1} (código: {return_code})")
                if stderr_output:
                    print(f"   STDERR: {''.join(stderr_output)}")
                return False
        
        # Clean up temporary files
        print(f"\n🧹 Limpando {len(temp_files)} arquivos temporários...")
        for temp_file in temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError:
                pass  # Ignore cleanup errors
        
        print(f"🎉 Processamento em lotes concluído com sucesso!")
        return True
        
    except Exception as e:
        print(f"❌ Erro no processamento em lotes: {e}")
        return False


def apply_subtitles_to_video(input_video: Path, subtitles: Dict[float, Tuple[str, str, str, str, float]], output_video: Path) -> bool:
    """
    Apply subtitles to video using FFmpeg drawtext filters with progress tracking.
    
    Args:
        input_video: Path to input MP4 file
        subtitles: Dictionary with subtitle data
        output_video: Path to output MP4 file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get video info for proper positioning and progress tracking
        video_width, video_height, video_duration = get_video_info(input_video)
        print(f"📐 Dimensões do vídeo: {video_width}x{video_height}")
        if video_duration > 0:
            duration_min = int(video_duration // 60)
            duration_sec = int(video_duration % 60)
            print(f"⏱️  Duração do vídeo: {duration_min}m{duration_sec:02d}s")
        
        # Create drawtext filters for subtitles
        drawtext_filters = create_ffmpeg_drawtext_filters(subtitles, video_width, video_height)
        
        if not drawtext_filters:
            print("⚠️  Nenhum filtro de legenda criado")
            return False
        
        # Check if we need to split processing for large filter chains
        filter_size = len(drawtext_filters)
        max_safe_size = 100000  # Conservative limit to avoid argument list issues
        
        if filter_size > max_safe_size:
            print(f"🔧 Filtro muito grande ({filter_size:,} chars) - usando processamento em lotes")
            return apply_subtitles_in_batches(input_video, subtitles, output_video, video_width, video_height, video_duration)
        
        print(f"🔧 Usando método direto ({filter_size:,} caracteres)")
        
        # For manageable filter chains, use direct method
        cmd = [
            'ffmpeg',
            '-i', str(input_video),
            '-filter_complex', drawtext_filters,
            '-map', '[v]',
            '-c:v', 'libx264',
            '-c:a', 'copy',
            '-crf', '18',
            '-preset', 'medium',
            '-progress', 'pipe:1',
            '-nostats',
            '-y',
            str(output_video)
        ]
        
        filter_file_path = None
        try:
            
            print(f"🎬 Aplicando legendas com FFmpeg...")
            print(f"   Entrada: {input_video.name}")
            print(f"   Saída: {output_video.name}")
            print(f"   Filtros: {len(subtitles)} legendas processadas")
            print(f"   ⏳ Processando vídeo...")
            
            # Run FFmpeg with real-time progress tracking
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            last_progress = -1
            stderr_output = []
            
            # Read progress from stdout
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                    
                if line:
                    current_time = parse_ffmpeg_progress(line.strip())
                    if current_time is not None and video_duration > 0:
                        progress_percent = min(100.0, (current_time / video_duration) * 100)
                        
                        # Update progress every 1% or more
                        if int(progress_percent) > last_progress:
                            last_progress = int(progress_percent)
                            print(f"\r   📊 Progresso: {last_progress:3d}% ({current_time:.1f}s/{video_duration:.1f}s)", end='', flush=True)
            
            # Read any remaining stderr
            stderr_data = process.stderr.read()
            if stderr_data:
                stderr_output.append(stderr_data)
            
            # Wait for process to complete
            return_code = process.wait()
            
            print()  # New line after progress
            
            if return_code == 0:
                print(f"   ✅ Legendas aplicadas com sucesso!")
                return True
            else:
                print(f"   ❌ Erro no FFmpeg (código: {return_code})")
                if stderr_output:
                    print(f"   STDERR: {''.join(stderr_output)}")
                return False
                
        finally:
            # Clean up temporary filter file
            if filter_file_path and os.path.exists(filter_file_path):
                try:
                    os.unlink(filter_file_path)
                except OSError:
                    pass  # Ignore cleanup errors
                    
    except Exception as e:
        print(f"Erro ao aplicar legendas: {e}")
        return False


def copy_videos_to_destination(source_dir: Path, dest_dir: Path) -> int:
    """
    Copy only MP4 videos from source to destination directory.
    
    Args:
        source_dir: Source directory path
        dest_dir: Destination directory path
    
    Returns:
        Number of videos copied
    """
    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all MP4 files in source directory
    mp4_files = list(source_dir.glob("*.mp4"))
    
    copied_count = 0
    for mp4_file in mp4_files:
        dest_file = dest_dir / mp4_file.name
        try:
            shutil.copy2(mp4_file, dest_file)
            copied_count += 1
        except Exception as e:
            print(f"⚠️  Erro ao copiar {mp4_file.name}: {e}")
    
    return copied_count


def process_directory(directory: Path, dry_run: bool = False, source_directory: Path = None) -> Tuple[int, int, int]:
    """
    Process all MP4 videos in the directory and add subtitles where applicable.
    
    Args:
        directory: Directory containing videos to process
        dry_run: If True, simulate operations without modifying files
        source_directory: Directory to search for base.txt file (if None, uses directory)
    
    Returns:
        (processed_count, skipped_count, error_count)
    """
    # Check FFmpeg availability
    if not dry_run and not check_ffmpeg():
        print("❌ Erro: FFmpeg não encontrado. Instale FFmpeg para continuar.")
        print("   macOS: brew install ffmpeg")
        print("   Ubuntu: sudo apt install ffmpeg")
        return 0, 0, 1
    
    # Find base file in source directory (or processing directory if not specified)
    search_dir = source_directory if source_directory else directory
    base_file = find_base_file(search_dir)
    if not base_file:
        print(f"Erro: Nenhum arquivo *_base.txt encontrado em {search_dir}")
        return 0, 0, 1
    
    print(f"📖 Usando arquivo base: {base_file.name}")
    
    # Parse subtitles
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("Erro: Nenhuma legenda encontrada no arquivo base")
        return 0, 0, 1
    
    print(f"📝 Encontradas {len(subtitles)} legendas")
    
    # Find MP4 files
    mp4_files = find_mp4_files(directory)
    if not mp4_files:
        print("Erro: Nenhum arquivo MP4 encontrado")
        return 0, 0, 1
    
    print(f"🎬 Encontrados {len(mp4_files)} vídeos MP4")
    print("-" * 60)
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    
    for mp4_file in mp4_files:
        print(f"🎬 Processando: {mp4_file.name}")
        
        # Create output filename with '_sub' suffix
        output_name = mp4_file.stem + '_sub' + mp4_file.suffix
        output_path = mp4_file.parent / output_name
        
        # Check if output file already exists
        if output_path.exists() and not dry_run:
            print(f"   ⏭️  Arquivo já existe: {output_name} - pulando processamento")
            skipped_count += 1
            continue
        
        if dry_run:
            if output_path.exists():
                print("   [DRY RUN] - Arquivo já existe - seria pulado")
                skipped_count += 1
            else:
                print("   [DRY RUN] - Simulação de processamento")
                print("   [DRY RUN] - Cópia original seria removida após processamento")
                processed_count += 1
        else:
            # Apply subtitles directly to video using drawtext filters
            if apply_subtitles_to_video(mp4_file, subtitles, output_path):
                print(f"   ✅ Vídeo com legendas criado: {output_name}")
                
                # Delete the original copy from destination directory to save space
                try:
                    mp4_file.unlink()
                    print(f"   🗑️  Cópia original removida: {mp4_file.name}")
                except Exception as e:
                    print(f"   ⚠️  Não foi possível remover cópia original: {e}")
                
                processed_count += 1
            else:
                print(f"   ❌ Erro ao aplicar legendas")
                error_count += 1
    
    return processed_count, skipped_count, error_count


def find_directories_to_process(assets_dir: Path) -> list[str]:
    """
    Find all directories in assets that have MP4 files and don't have a corresponding _sub directory.
    
    Args:
        assets_dir: Path to the assets directory
        
    Returns:
        List of directory names to process
    """
    if not assets_dir.exists() or not assets_dir.is_dir():
        return []
    
    dirs_to_process = []
    
    for item in assets_dir.iterdir():
        if item.is_dir() and not item.name.endswith('_sub'):
            # Check if corresponding _sub directory exists
            sub_dir = assets_dir / f"{item.name}_sub"
            if not sub_dir.exists():
                # Check if it has MP4 files or base.txt file
                has_mp4s = bool(list(item.glob("*.mp4")))
                has_base_txt = bool(list(item.glob("*_base.txt")))
                
                if has_mp4s or has_base_txt:
                    dirs_to_process.append(item.name)
    
    return sorted(dirs_to_process)


def process_single_directory(directory_name: str, assets_dir: Path, dry_run: bool) -> tuple[int, int, int]:
    """
    Process a single directory.
    
    Args:
        directory_name: Name of the directory to process
        assets_dir: Path to the assets directory
        dry_run: Whether to perform a dry run
        
    Returns:
        Tuple of (processed, skipped, errors)
    """
    source_dir = assets_dir / directory_name
    dest_dir = assets_dir / f"{directory_name}_sub"
    
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"⚠️  Ignorando {directory_name}: não é um diretório válido")
        return 0, 0, 1
    
    print(f"\n🎬 Processando: {directory_name}")
    print(f"📁 Origem: {source_dir}")
    print(f"📁 Destino: {dest_dir}")
    print("-" * 60)
    
    # Copy videos to destination directory
    if not dry_run:
        print(f"📋 Copiando vídeos MP4 para {dest_dir.name}...")
        copied_count = copy_videos_to_destination(source_dir, dest_dir)
        print(f"✅ {copied_count} vídeos copiados")
    else:
        print(f"📋 [DRY RUN] Simulando cópia de vídeos")
        mp4_files = list(source_dir.glob("*.mp4"))
        print(f"✅ [DRY RUN] {len(mp4_files)} vídeos seriam copiados")
    
    # Process directory (work on destination, but read base.txt from source)
    if dry_run:
        # For dry run, we need to check the destination directory for existing files
        # but if destination doesn't exist yet, we simulate with source directory
        if dest_dir.exists():
            processed, skipped, errors = process_directory(dest_dir, dry_run, source_directory=source_dir)
        else:
            processed, skipped, errors = process_directory(source_dir, dry_run, source_directory=source_dir)
    else:
        # For real processing, work on destination directory
        processed, skipped, errors = process_directory(dest_dir, dry_run, source_directory=source_dir)
    
    return processed, skipped, errors


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona legendas chinesas e traduções aos vídeos MP4 baseado no arquivo base.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 video_subtitle_printer.py                              # Processa TODAS as pastas sem _sub
  python3 video_subtitle_printer.py chaves001                    # Copia para assets/chaves001_sub/ e processa
  python3 video_subtitle_printer.py test --dry-run               # Simula o processamento
  python3 video_subtitle_printer.py flipper --assets-root data   # Usa data/ ao invés de assets/

Funcionamento:
  1. Se nenhum diretório for especificado, processa todas as pastas em assets/ que não tenham _sub
  2. Cria pasta destino com sufixo "_sub" (ex: test -> test_sub)
  3. Copia vídeos MP4 da pasta origem para a pasta destino
  4. Busca o arquivo *_base.txt na pasta origem
  5. Processa os vídeos na pasta destino:
     - Aplica legendas diretamente no vídeo usando filtros drawtext do FFmpeg
     - Renderiza pinyin (acima) + chinês (meio) + português (abaixo)
     - Remove a cópia original após processamento bem-sucedido

Saída:
  Para video.mp4 -> video_sub.mp4 (com legendas renderizadas permanentemente)
  A cópia original é removida automaticamente para economizar espaço

Requisitos:
  - FFmpeg deve estar instalado no sistema
  - macOS: brew install ffmpeg
  - Ubuntu: sudo apt install ffmpeg
        """
    )
    
    parser.add_argument('directory', nargs='?',
                       help='Nome do diretório dentro de assets/ para processar (opcional)')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem modificar arquivos')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Construct assets directory path
    assets_dir = Path(args.assets_root)
    
    if not assets_dir.exists():
        print(f"Erro: Diretório assets {assets_dir} não encontrado.")
        return 1
    
    print(f"🎬 Video Subtitle Printer ALL-IN-ONE - Legendas Hardcoded em Vídeos")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print(f"📋 Processamento:")
    print(f"    🎯 Aplica legendas diretamente no vídeo MP4 (hardcoded)")
    print(f"    📝 Pinyin acima + chinês + português abaixo")
    print(f"    🛠️  Usa FFmpeg para processamento de vídeo")
    print("=" * 60)
    
    # Check FFmpeg availability
    if not args.dry_run and not check_ffmpeg():
        print("❌ Erro: FFmpeg não encontrado!")
        print("   Instale FFmpeg:")
        print("   macOS: brew install ffmpeg") 
        print("   Ubuntu: sudo apt install ffmpeg")
        print("   Windows: https://ffmpeg.org/download.html")
        return 1
    
    # Determine directories to process
    if args.directory:
        # Process single directory specified by user
        directories_to_process = [args.directory]
        print(f"📁 Processamento específico: {args.directory}")
    else:
        # Find all directories that need processing
        directories_to_process = find_directories_to_process(assets_dir)
        if not directories_to_process:
            print(f"📂 Nenhuma pasta nova encontrada em {assets_dir}")
            print(f"   (procurando pastas sem _sub que tenham MP4 ou *_base.txt)")
            return 0
        else:
            print(f"📂 Encontradas {len(directories_to_process)} pastas para processar:")
            for dir_name in directories_to_process:
                print(f"   📁 {dir_name}")
    
    # Process each directory
    total_processed = 0
    total_skipped = 0
    total_errors = 0
    
    for directory_name in directories_to_process:
        processed, skipped, errors = process_single_directory(directory_name, assets_dir, args.dry_run)
        total_processed += processed
        total_skipped += skipped
        total_errors += errors
    
    # Print final results
    total_files = total_processed + total_skipped + total_errors
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📂 Diretórios processados: {len(directories_to_process)}")
    print(f"🎬 Total de vídeos: {total_files}")
    print(f"✅ Processados: {total_processed}")
    print(f"   └── Com legendas: aplicadas permanentemente no vídeo")
    print(f"⏭️  Ignorados: {total_skipped}")
    print(f"❌ Erros: {total_errors}")
    
    if args.dry_run and total_processed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para aplicar as legendas")
    
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
