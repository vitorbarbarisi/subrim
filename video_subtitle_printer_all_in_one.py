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
    print(f"   📐 Resolução do vídeo: {video_width}x{video_height}")
    
    # Calculate adaptive font sizes based on video resolution
    # Base the font sizes on video height, similar to the C code logic
    base_chinese_font_size = max(24, min(120, int(video_height * 0.06)))  # 6% of video height
    base_pinyin_font_size = int(base_chinese_font_size * 0.65)  # 65% of Chinese font size
    base_portuguese_font_size = int(base_chinese_font_size * 0.45)  # 45% of Chinese font size
    
    # Calculate adaptive spacing based on video width
    # Aim to use about 85% of the video width for subtitles
    max_subtitle_width = int(video_width * 0.85)
    
    print(f"   📝 Tamanhos adaptativos: Chinês={base_chinese_font_size}px, Pinyin={base_pinyin_font_size}px, PT={base_portuguese_font_size}px")
    print(f"   📏 Largura máxima das legendas: {max_subtitle_width}px ({(max_subtitle_width/video_width)*100:.1f}% da tela)")
    
    # Sort subtitles by time and validate content
    valid_subtitles = {}
    for begin_time, subtitle_data in subtitles.items():
        chinese_text, translations_text, translations_json, portuguese_text, duration = subtitle_data
        # Skip empty or invalid subtitles
        if chinese_text and chinese_text.strip() and chinese_text != 'N/A':
            valid_subtitles[begin_time] = subtitle_data
    
    if not valid_subtitles:
        print("   ⚠️  Nenhuma legenda válida encontrada, usando filtro de cópia")
        return "[0:v]copy[v]"
    
    print(f"   📊 Processando {len(valid_subtitles)} legendas válidas de {len(subtitles)} totais")
    
    # Sort subtitles by time
    for begin_time in sorted(valid_subtitles.keys()):
        chinese_text, translations_text, translations_json, portuguese_text, duration = valid_subtitles[begin_time]
        
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
        
        # Calculate adaptive positioning based on video height and font sizes
        # Ensure subtitle area is large enough for the adaptive font sizes
        min_subtitle_area = base_chinese_font_size + base_pinyin_font_size + (base_portuguese_font_size * 2) + 80  # Extra space for margins
        subtitle_area_height = max(int(video_height * 0.25), min_subtitle_area)  # Use 25% of video height or minimum needed
        
        # Calculate margins based on font sizes for better proportions
        bottom_margin = max(30, int(video_height * 0.04))  # 4% of height or minimum 30px (increased)
        vertical_spacing = max(10, int(base_chinese_font_size * 0.20))  # 20% of Chinese font size (increased)
        
        # Reserve extra space for Portuguese multi-line text (can have 2-3 lines)
        portuguese_extra_height = base_portuguese_font_size * 2  # Space for 2 additional lines
        
        # Calculate total height needed for all elements (more conservative)
        total_text_height = (base_pinyin_font_size + vertical_spacing + 
                           base_chinese_font_size + vertical_spacing + 
                           base_portuguese_font_size + portuguese_extra_height)
        
        # Ensure we don't use more than 35% of screen height for subtitles
        max_subtitle_height = int(video_height * 0.35)
        if total_text_height > max_subtitle_height:
            # Scale down spacing proportionally
            scale_factor = max_subtitle_height / total_text_height
            vertical_spacing = max(6, int(vertical_spacing * scale_factor))
            portuguese_extra_height = int(portuguese_extra_height * scale_factor)
            total_text_height = max_subtitle_height
        
        # Calculate Y positions from bottom up, with safety margins
        # Portuguese starts higher to avoid bottom crop (considering baseline positioning)
        portuguese_y = video_height - bottom_margin - portuguese_extra_height - (base_portuguese_font_size // 2)
        chinese_y = portuguese_y - vertical_spacing - base_chinese_font_size
        pinyin_y = chinese_y - vertical_spacing - base_pinyin_font_size
        
        # Safety check: ensure pinyin doesn't go off-screen at top
        min_pinyin_y = base_pinyin_font_size + 15  # Keep at least 15px from top (increased)
        if pinyin_y < min_pinyin_y:
            # Recalculate with compressed layout
            available_height = video_height - min_pinyin_y - bottom_margin - portuguese_extra_height
            compressed_spacing = max(6, available_height // 8)  # Divide available space
            
            pinyin_y = min_pinyin_y
            chinese_y = pinyin_y + base_pinyin_font_size + compressed_spacing
            portuguese_y = chinese_y + base_chinese_font_size + compressed_spacing
            
            # Final safety check for bottom crop
            max_portuguese_bottom = portuguese_y + base_portuguese_font_size + portuguese_extra_height
            if max_portuguese_bottom > video_height - 10:
                # Emergency compression - reduce font sizes if needed
                overflow = max_portuguese_bottom - (video_height - 10)
                portuguese_y -= overflow
        
        # Debug info for positioning (only for first subtitle to avoid spam)
        if begin_time == sorted(subtitles.keys())[0]:
            print(f"   📐 Posições Y adaptativas: Pinyin={pinyin_y}px, Chinês={chinese_y}px, PT={portuguese_y}px")
            print(f"   📏 Área de legendas: {subtitle_area_height}px ({(subtitle_area_height/video_height)*100:.1f}% da altura)")
            print(f"   🔵 Margem inferior: {bottom_margin}px, Espaçamento: {vertical_spacing}px")
            print(f"   🛡️  Altura extra PT: {portuguese_extra_height}px, Altura total: {total_text_height}px")
            
            # Check for potential cropping
            max_y_used = portuguese_y + base_portuguese_font_size + portuguese_extra_height
            bottom_clearance = video_height - max_y_used
            if bottom_clearance < 20:
                print(f"   ⚠️  ATENÇÃO: Pouco espaço inferior ({bottom_clearance}px restantes)")
            else:
                print(f"   ✅ Espaço inferior seguro: {bottom_clearance}px restantes")
        
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
        
        # Calculate adaptive character widths based on font sizes (with safety margin)
        chinese_char_width = int(base_chinese_font_size * 0.95)  # Increased from 0.85 to 0.95 for safety
        pinyin_char_width = int(base_pinyin_font_size * 0.65)    # Increased from 0.6 to 0.65 for safety
        min_word_spacing = max(80, int(video_width * 0.05))      # Increased minimum spacing: 5% of width (was 4%)
        
        # Calculate width of each word for positioning
        for chinese_word, word_pinyin, word_portuguese in display_items:
            # Calculate adaptive word width based on resolution
            chinese_word_width = len(chinese_word) * chinese_char_width
            pinyin_width = len(word_pinyin) * pinyin_char_width if word_pinyin else 0
            
            # Use the wider of the two for spacing, with adaptive minimum + extra safety margin
            base_word_width = max(chinese_word_width, pinyin_width, min_word_spacing)
            # Add extra padding for safety (10% of base width, minimum 20px)
            safety_padding = max(20, int(base_word_width * 0.10))
            word_width = base_word_width + safety_padding
            word_widths.append(word_width)
            total_line_width += word_width
        
        # If the line is too wide, scale down word widths proportionally to fit max_subtitle_width
        if total_line_width > max_subtitle_width:
            scale_factor = max_subtitle_width / total_line_width
            
            # Apply more conservative scaling to preserve minimum spacing
            min_word_width = 40  # Minimum width per word to avoid complete overlap
            scaled_widths = []
            for w in word_widths:
                scaled_width = max(min_word_width, int(w * scale_factor))
                scaled_widths.append(scaled_width)
            
            word_widths = scaled_widths
            total_line_width = sum(word_widths)
            
            # If still too wide after conservative scaling, try reducing font sizes instead
            if total_line_width > max_subtitle_width:
                font_reduction_factor = max_subtitle_width / total_line_width
                print(f"   📏 Linha ainda muito larga, reduzindo fontes por fator {font_reduction_factor:.2f}")
            else:
                print(f"   📏 Linha muito larga, reduzida por fator {scale_factor:.2f} (conservativo)")
        
        # Calculate starting x position to center the entire line
        start_x = (video_width - total_line_width) // 2
        
        # Create time conditions - escape commas for FFmpeg enable parameter
        end_time = begin_time + duration
        time_condition = f"between(t\\,{begin_time:.3f}\\,{end_time:.3f})"
        
        # Calculate adaptive border widths based on font size
        chinese_border_width = max(2, int(base_chinese_font_size * 0.05))  # 5% of font size
        pinyin_border_width = max(1, int(base_pinyin_font_size * 0.05))
        portuguese_border_width = max(1, int(base_portuguese_font_size * 0.05))
        
        # Add each word with its pinyin and Portuguese positioned individually
        current_x = start_x
        for i, (chinese_word, word_pinyin, word_portuguese) in enumerate(display_items):
            word_width = word_widths[i]
            
            # Escape text for FFmpeg
            chinese_escaped = escape_ffmpeg_text(chinese_word)
            pinyin_escaped = escape_ffmpeg_text(word_pinyin) if word_pinyin else ""
            
            # Skip if Chinese text is empty after escaping
            if not chinese_escaped or chinese_escaped.strip() == '':
                current_x += word_width
                continue
            
            # Calculate center position for this word within its allocated width
            word_center_x = current_x + word_width // 2
            
            # Chinese text (centered within word width) - using adaptive font size
            chinese_filter = f'drawtext=text="{chinese_escaped}":x={word_center_x}-text_w/2:y={chinese_y}:fontfile=\'{chinese_font_path}\':fontsize={base_chinese_font_size}:fontcolor=white:borderw={chinese_border_width}:bordercolor=black:enable=\'{time_condition}\''
            if chinese_filter:  # Validate filter is not empty
                filter_parts.append(chinese_filter)
            
            # Pinyin text (centered over the Chinese word) - using adaptive font size
            if pinyin_escaped and pinyin_escaped.strip():
                pinyin_filter = f'drawtext=text="{pinyin_escaped}":x={word_center_x}-text_w/2:y={pinyin_y}:fontfile=\'{chinese_font_path}\':fontsize={base_pinyin_font_size}:fontcolor=#9370DB:borderw={pinyin_border_width}:bordercolor=black:enable=\'{time_condition}\''
                if pinyin_filter:  # Validate filter is not empty
                    filter_parts.append(pinyin_filter)
            
            # Portuguese text (centered below each Chinese word, with line breaks if needed) - using adaptive font size
            if word_portuguese and word_portuguese.strip():
                portuguese_lines = wrap_portuguese_to_chinese_width(word_portuguese, latin_font_path, word_width, base_portuguese_font_size)
                portuguese_line_height = int(base_portuguese_font_size * 1.2)  # Adaptive line height (120% of font size)
                
                for line_idx, portuguese_line in enumerate(portuguese_lines):
                    if portuguese_line and portuguese_line.strip():  # Only add non-empty lines
                        portuguese_escaped = escape_ffmpeg_text(portuguese_line)
                        if portuguese_escaped and portuguese_escaped.strip():  # Validate escaped text
                            portuguese_line_y = portuguese_y + (line_idx * portuguese_line_height)
                            portuguese_filter = f'drawtext=text="{portuguese_escaped}":x={word_center_x}-text_w/2:y={portuguese_line_y}:fontfile=\'{latin_font_path}\':fontsize={base_portuguese_font_size}:fontcolor=yellow:borderw={portuguese_border_width}:bordercolor=black:enable=\'{time_condition}\''
                            if portuguese_filter:  # Validate filter is not empty
                                filter_parts.append(portuguese_filter)
            
            current_x += word_width
    
    # Format for filter complex script file - with validation
    # Remove any empty or invalid filter parts
    valid_filter_parts = [f for f in filter_parts if f and f.strip() and 'drawtext=' in f]
    
    print(f"   🔧 Gerados {len(valid_filter_parts)} filtros válidos de {len(filter_parts)} totais")
    
    if valid_filter_parts:
        # Use pipeline approach for better reliability with many filters
        if len(valid_filter_parts) == 1:
            # Single filter case
            return f"[0:v]{valid_filter_parts[0]}[v]"
        else:
            # Multiple filters - chain them sequentially
            result_parts = []
            current_input = "[0:v]"
            
            for i, filter_part in enumerate(valid_filter_parts):
                if i == len(valid_filter_parts) - 1:
                    # Last filter outputs to [v]
                    result_parts.append(f"{current_input}{filter_part}[v]")
                else:
                    # Intermediate filter
                    temp_label = f"[tmp{i}]"
                    result_parts.append(f"{current_input}{filter_part}{temp_label}")
                    current_input = temp_label
            
            filter_result = "; ".join(result_parts)
            
            # Final validation - ensure the result contains [v] output
            if "[v]" not in filter_result:
                print("   ⚠️  Filtro final não contém saída [v], usando cópia")
                return "[0:v]copy[v]"
            
            return filter_result
    else:
        print("   ⚠️  Nenhum filtro válido criado, usando filtro de cópia")
        return "[0:v]copy[v]"  # No filters, just copy video


def wrap_portuguese_to_chinese_width(portuguese_text: str, font_path: str, max_width: int, font_size: int = 20) -> List[str]:
    """
    Break Portuguese text into multiple lines to fit within the Chinese word width.
    Never breaks words in the middle - only breaks at word boundaries.
    
    Args:
        portuguese_text: Portuguese text to break
        font_path: Path to the font file
        max_width: Maximum width in pixels (width of the Chinese word)
        font_size: Font size in pixels (default 20)
        
    Returns:
        List of text lines that fit within max_width
    """
    if not portuguese_text:
        return []
    
    # Calculate character width based on actual font size
    char_width = int(font_size * 0.6)  # Approximate: 60% of font size for Latin characters
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
    """Escape text for FFmpeg drawtext filter using double quotes."""
    if not text or not isinstance(text, str):
        return ""
    
    # Remove any null bytes that could cause issues
    text = text.replace('\x00', '')
    
    # Strip whitespace and check if empty
    text = text.strip()
    if not text:
        return ""
    
    # Escape special characters for FFmpeg (using double quotes strategy)
    text = text.replace('\\', '\\\\')  # Backslash
    text = text.replace('"', '\\"')    # Double quote (since we'll use double quotes)
    text = text.replace(':', '\\:')    # Colon
    text = text.replace('[', '\\[')    # Left bracket
    text = text.replace(']', '\\]')    # Right bracket
    text = text.replace('%', '\\%')    # Percent sign
    text = text.replace(';', '\\;')    # Semicolon
    text = text.replace(',', '\\,')    # Comma (critical for FFmpeg parsing)
    # NOTE: Single quotes don't need escaping when using double quotes
    
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


def get_video_encoding_info(video_path: Path) -> dict:
    """Get detailed video encoding information to preserve quality."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'v:0',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if result.stdout:
            import json
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            
            if streams:
                stream = streams[0]
                return {
                    'codec_name': stream.get('codec_name', 'h264'),
                    'profile': stream.get('profile', ''),
                    'pix_fmt': stream.get('pix_fmt', 'yuv420p'),
                    'bit_rate': int(stream.get('bit_rate', 0)) if stream.get('bit_rate') else 0,
                    'width': int(stream.get('width', 1920)),
                    'height': int(stream.get('height', 1080))
                }
    except:
        pass
    
    # Default fallback
    return {
        'codec_name': 'h264',
        'profile': '',
        'pix_fmt': 'yuv420p',
        'bit_rate': 0,
        'width': 1920,
        'height': 1080
    }


def convert_to_chromecast_format(input_video: Path, output_video: Path) -> bool:
    """
    Converte vídeo para formato compatível com Chromecast.
    
    Args:
        input_video: Vídeo original
        output_video: Vídeo convertido para Chromecast
        
    Returns:
        True se conversão bem-sucedida
    """
    print(f"📱 Convertendo para formato Chromecast...")
    print(f"   📁 Entrada: {input_video.name}")
    print(f"   📁 Saída: {output_video.name}")
    
    # Configurações testadas e aprovadas para Chromecast
    cmd = [
        'ffmpeg',
        '-i', str(input_video),
        
        # Codec de vídeo: H.264 software (máxima compatibilidade)
        '-c:v', 'libx264',
        '-profile:v', 'high',
        '-level', '4.1',
        
        # Qualidade otimizada para streaming
        '-crf', '20',              # Alta qualidade
        '-preset', 'medium',       # Equilíbrio qualidade/velocidade
        
        # Codec de áudio: AAC (padrão Chromecast)
        '-c:a', 'aac',
        '-b:a', '128k',           # Bitrate áudio adequado
        '-ar', '48000',           # Sample rate padrão
        
        # Configurações de compatibilidade
        '-pix_fmt', 'yuv420p',    # Formato pixel compatível
        '-movflags', '+faststart', # Otimização streaming
        
        # Resolução máxima suportada pelo Chromecast
        '-vf', 'scale=min(1920\\,iw):min(1080\\,ih):force_original_aspect_ratio=decrease',
        
        # Progresso e otimizações
        '-progress', 'pipe:1',
        '-nostats',
        '-y',                     # Sobrescrever arquivo se existir
        
        str(output_video)
    ]
    
    try:
        print("   🔄 Processando...")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True
        )
        
        # Mostrar progresso básico
        for line in process.stdout:
            if line.startswith('frame='):
                parts = line.strip().split()
                for part in parts:
                    if part.startswith('time='):
                        time_str = part.split('=')[1]
                        print(f"   ⏱️  Progresso: {time_str}", end='\r')
        
        return_code = process.wait()
        
        if return_code != 0:
            stderr_output = process.stderr.read()
            print(f"\n❌ Erro na conversão:")
            print(f"   {stderr_output}")
            return False
        
        print(f"\n✅ Vídeo convertido para Chromecast com sucesso!")
        
        # Mostrar informações de tamanho
        if output_video.exists():
            original_size = input_video.stat().st_size / (1024*1024)
            converted_size = output_video.stat().st_size / (1024*1024)
            reduction = ((original_size - converted_size) / original_size) * 100
            
            print(f"   📊 Tamanho original: {original_size:.1f} MB")
            print(f"   📊 Tamanho Chromecast: {converted_size:.1f} MB")
            print(f"   📊 Otimização: {reduction:.1f}% menor")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro na conversão: {e}")
        return False


def get_optimal_encoding_settings(video_info: dict) -> dict:
    """Get optimal encoding settings to preserve original quality."""
    codec_name = video_info['codec_name']
    bit_rate = video_info['bit_rate']
    width = video_info['width']
    height = video_info['height']
    pix_fmt = video_info['pix_fmt']
    
    # Choose codec based on original
    if codec_name == 'hevc':
        # Use HEVC hardware encoder to preserve quality
        video_codec = 'hevc_videotoolbox'
        preset = 'medium'  # Better quality for HEVC
    else:
        # Use H.264 hardware encoder
        video_codec = 'h264_videotoolbox'
        preset = 'medium'  # Better quality than 'fast'
    
    # Calculate optimal settings
    is_4k = width >= 3840 or height >= 2160
    is_hd = width >= 1920 or height >= 1080
    
    if bit_rate > 0:
        # Use CRF for better quality control instead of fixed bitrate
        if is_4k:
            crf = 18  # Very high quality for 4K
            max_bitrate = max(15000, bit_rate // 1000)  # At least 15Mbps for 4K
        elif is_hd:
            crf = 20  # High quality for HD
            max_bitrate = max(8000, bit_rate // 1000)   # At least 8Mbps for HD
        else:
            crf = 22  # Good quality for SD
            max_bitrate = max(3000, bit_rate // 1000)   # At least 3Mbps for SD
    else:
        # Fallback values
        if is_4k:
            crf = 18
            max_bitrate = 15000
        elif is_hd:
            crf = 20
            max_bitrate = 8000
        else:
            crf = 22
            max_bitrate = 3000
    
    return {
        'video_codec': video_codec,
        'crf': crf,
        'max_bitrate': f'{max_bitrate}k',
        'preset': preset,
        'pix_fmt': pix_fmt
    }


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
    # Validate that filter contains [v] output before writing
    if "[v]" not in drawtext_filters:
        print(f"   ⚠️  ERRO: Filtro não contém saída [v]:")
        print(f"   📄 Conteúdo do filtro: {drawtext_filters[:500]}...")
        raise ValueError("Filter does not contain required [v] output label")
    
    # Create temporary file for filters
    fd, temp_path = tempfile.mkstemp(suffix='.txt', prefix='ffmpeg_filters_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            # Write the filter chain to the file
            f.write(drawtext_filters)
        
        print(f"   📄 Filtro escrito em arquivo temporário: {temp_path}")
        print(f"   📄 Tamanho do filtro: {len(drawtext_filters):,} caracteres")
        print(f"   📄 Primeiros 200 chars: {drawtext_filters[:200]}...")
        print(f"   📄 Últimos 200 chars: ...{drawtext_filters[-200:]}")
        
        # Verify the file was written correctly by reading it back
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                written_content = f.read()
                if written_content != drawtext_filters:
                    print(f"   ⚠️  AVISO: Conteúdo do arquivo difere do original!")
                    print(f"   📊 Original: {len(drawtext_filters)} chars, Arquivo: {len(written_content)} chars")
                else:
                    print(f"   ✅ Arquivo verificado: conteúdo OK")
                    
            # Show a sample of what's actually in the file for debugging
            lines = written_content.split('\n')
            print(f"   📋 Total de linhas no arquivo: {len(lines)}")
            if len(lines) > 0:
                print(f"   📋 Primeira linha: {lines[0][:100]}...")
                if len(lines) > 1:
                    print(f"   📋 Última linha: ...{lines[-1][-100:] if lines[-1] else '(linha vazia)'}")
                    
        except Exception as e:
            print(f"   ⚠️  ERRO ao verificar arquivo: {e}")
        
        # DO NOT delete the file - preserve for debugging
        print(f"   🔧 ARQUIVO PRESERVADO PARA DEBUG: {temp_path}")
        print(f"   🔧 Para examinar: cat '{temp_path}'")
        
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
        
        # Get optimal encoding settings based on input video
        video_encoding_info = get_video_encoding_info(input_video)
        encoding_settings = get_optimal_encoding_settings(video_encoding_info)
        
        print(f"🎯 Configurações de qualidade detectadas:")
        print(f"   📹 Codec original: {video_encoding_info['codec_name']} → {encoding_settings['video_codec']}")
        print(f"   📊 Bitrate original: {video_encoding_info['bit_rate']//1000 if video_encoding_info['bit_rate'] > 0 else 'N/A'}kbps")
        print(f"   🎨 Pixel format: {video_encoding_info['pix_fmt']}")
        print(f"   ⚙️  CRF: {encoding_settings['crf']} (qualidade alta), Max bitrate: {encoding_settings['max_bitrate']}")
        
        # Clean up any existing batch files from previous runs
        cleanup_existing_batch_files(output_video)
        
        # Use moderate batch size to balance performance and avoid overlap issues
        batch_size = 5  # Balanced: Not too big to cause overlap, not too small to be inefficient
        print(f"   📦 Usando {batch_size} legendas por lote (otimizado para evitar sobreposição)")
        subtitle_times = sorted(subtitles.keys())
        batches = [subtitle_times[i:i + batch_size] for i in range(0, len(subtitle_times), batch_size)]
        
        print(f"📦 Dividido em {len(batches)} lotes de até {batch_size} legendas cada")
        
        # Check for existing batch files to resume processing
        existing_batches = []
        start_batch_idx = 0
        current_input = input_video
        temp_files = []
        
        print(f"🔍 Verificando lotes existentes...")
        
        # Clean up the name to get the original base name without suffixes
        base_name_for_batches = input_video.stem
        
        # If input_video is a chromecast_temp file, we need to find the original name for batch detection
        is_chromecast_temp_input = '_chromecast_temp' in base_name_for_batches
        
        if is_chromecast_temp_input:
            # Remove _chromecast_temp suffix to get original base name
            base_name_for_batches = base_name_for_batches.replace('_chromecast_temp', '')
            print(f"📝 Detectado input chromecast_temp - usando nome original para busca de lotes")
        
        if '_sub' in base_name_for_batches:
            base_name_for_batches = base_name_for_batches.replace('_sub', '')
        
        print(f"📝 Nome base para lotes: {base_name_for_batches}")
        print(f"📝 Input é chromecast_temp: {is_chromecast_temp_input}")
        
        # Look for existing batch files with multiple patterns
        # Instead of using glob patterns with special characters, list all files and filter with regex
        import re
        
        print(f"🔍 Procurando lotes no diretório: {input_video.parent}")
        
        # Get all MP4 files in the directory
        all_mp4_files = list(input_video.parent.glob("*.mp4"))
        print(f"🔍 Total de arquivos MP4 no diretório: {len(all_mp4_files)}")
        
        # Create regex patterns to match batch files (escape special regex chars)
        def escape_regex_chars(text):
            # Escape characters that have special meaning in regex
            return re.escape(text)
        
        escaped_base = escape_regex_chars(base_name_for_batches)
        
        batch_patterns_regex = [
            f"{escaped_base}_batch_\\d+\\.mp4$",
            f"{escaped_base}_sub_batch_\\d+\\.mp4$", 
            f"{escaped_base}_chromecast_temp_sub_batch_\\d+\\.mp4$"
        ]
        
        print(f"🔍 Padrões regex de busca:")
        for pattern in batch_patterns_regex:
            print(f"   - {pattern}")
        
        all_existing_batch_files = []
        
        for pattern_regex in batch_patterns_regex:
            pattern_obj = re.compile(pattern_regex)
            matching_files = []
            
            for mp4_file in all_mp4_files:
                if pattern_obj.search(mp4_file.name):
                    matching_files.append(mp4_file)
            
            print(f"   ➜ Padrão regex: {len(matching_files)} arquivos encontrados")
            for f in matching_files:
                print(f"     • {f.name}")
            all_existing_batch_files.extend(matching_files)
        
        # Extract batch numbers and sort
        print(f"🔍 Total de arquivos encontrados: {len(all_existing_batch_files)}")
        
        batch_file_info = []
        for batch_file in all_existing_batch_files:
            # Extract batch number from filename (look for _batch_X.mp4 pattern)
            import re
            match = re.search(r'_batch_(\d+)\.mp4$', batch_file.name)
            if match:
                batch_num = int(match.group(1))
                batch_file_info.append((batch_num, batch_file))
                print(f"   ✅ Lote {batch_num}: {batch_file.name}")
            else:
                print(f"   ❌ Não conseguiu extrair número do lote: {batch_file.name}")
        
        # Sort by batch number
        batch_file_info.sort(key=lambda x: x[0])
        
        if batch_file_info:
            print(f"📁 Encontrados {len(batch_file_info)} arquivos de lote existentes:")
            for batch_num, batch_file in batch_file_info:
                print(f"   📄 Lote {batch_num + 1}: {batch_file.name}")
            
            # Use the highest batch number + 1 as starting point
            last_batch_num = batch_file_info[-1][0]
            last_batch_file = batch_file_info[-1][1]
            
            start_batch_idx = last_batch_num + 1
            current_input = last_batch_file
            
            # Add existing batch files to temp_files for later cleanup
            for batch_num, batch_file in batch_file_info:
                if batch_file != output_video:  # Don't add final output to temp_files
                    temp_files.append(batch_file)
            
            print(f"🔄 Retomando processamento a partir do lote {start_batch_idx + 1}/{len(batches)}")
            print(f"📂 Usando como entrada: {current_input.name}")
        else:
            print(f"🆕 Nenhum lote existente encontrado, iniciando do zero")
        
        # For new batches, determine consistent naming based on current input
        if start_batch_idx > 0:
            # Use the pattern from the last existing batch
            last_batch_name = current_input.stem
            if '_batch_' in last_batch_name:
                # Extract everything before _batch_X
                base_pattern = last_batch_name.split('_batch_')[0]
            else:
                base_pattern = base_name_for_batches
        else:
            base_pattern = base_name_for_batches
        
        print(f"📝 Padrão para novos lotes: {base_pattern}_batch_X.mp4")
        
        # Check if all batches are already complete
        if start_batch_idx >= len(batches):
            print(f"✅ Todos os lotes já foram processados!")
            return True
        
        # Update video duration to reflect current input if we're resuming
        if start_batch_idx > 0:
            print(f"📏 Atualizando duração do vídeo para arquivo atual: {current_input.name}")
            _, _, video_duration = get_video_info(current_input)
            if video_duration > 0:
                duration_min = int(video_duration // 60)
                duration_sec = int(video_duration % 60)
                print(f"⏱️  Nova duração: {duration_min}m{duration_sec:02d}s")
        
        for batch_idx, batch_times in enumerate(batches):
            # Skip batches that are already completed
            if batch_idx < start_batch_idx:
                continue
                
            print(f"\n🔄 Processando lote {batch_idx + 1}/{len(batches)} ({len(batch_times)} legendas)...")
            
            # Create batch subtitles dictionary
            batch_subtitles = {time: subtitles[time] for time in batch_times}
            
            # Create drawtext filters for this batch
            print(f"   🔧 Criando filtros para lote {batch_idx + 1} com {len(batch_subtitles)} legendas")
            
            batch_filters = create_ffmpeg_drawtext_filters(batch_subtitles, video_width, video_height)
            
            if not batch_filters:
                print(f"   ⚠️  Lote {batch_idx + 1}: Nenhum filtro gerado, pulando")
                continue
                
            if "[v]" not in batch_filters:
                print(f"   ❌ ERRO: Lote {batch_idx + 1} - filtros não contêm [v]:")
                print(f"   📄 Início: {batch_filters[:300]}...")
                print(f"   📄 Fim: ...{batch_filters[-300:]}")
                print(f"   🆘 Forçando filtro de cópia para lote {batch_idx + 1}")
                batch_filters = "[0:v]copy[v]"
            else:
                print(f"   ✅ Lote {batch_idx + 1}: Filtros válidos gerados ({len(batch_filters):,} chars)")
            
            # Determine output file for this batch (use consistent naming)
            if batch_idx == len(batches) - 1:
                # Last batch outputs to final file
                batch_output = output_video
            else:
                # Intermediate batch outputs to temp file with consistent naming based on existing pattern
                temp_suffix = f"_batch_{batch_idx}.mp4"
                batch_output = output_video.parent / (base_pattern + temp_suffix)
                temp_files.append(batch_output)
            
            # For large filter chains, use a filter file to avoid command line length limits
            filter_file_path = None
            try:
                if len(batch_filters) > 50000:  # Use filter file for very long filters
                    print(f"   📄 Filtro longo ({len(batch_filters):,} chars) - usando arquivo temporário")
                    try:
                        filter_file_path = create_filter_file(batch_filters)
                        # Use the EXACT syntax recommended by FFmpeg 8.0
                        filter_arg = ['-/filter_complex', filter_file_path]
                        print(f"   ✅ [TESTE] Usando -/filter_complex (sintaxe recomendada pelo FFmpeg): {filter_file_path}")
                        print(f"   📝 [TESTE] Testando com lotes menores E sintaxe correta")
                        print(f"   🔧 DEBUG: Preservando arquivo temporário para investigação")
                    except Exception as filter_error:
                        print(f"   ❌ ERRO ao criar arquivo de filtro: {filter_error}")
                        print(f"   🆘 Forçando filtro simples de cópia")
                        filter_arg = ['-filter_complex', '[0:v]copy[v]']
                else:
                    filter_arg = ['-filter_complex', batch_filters]
                    print(f"   ✅ Usando filter_complex direto ({len(batch_filters):,} chars)")
                
                # FFmpeg command for this batch with optimal quality settings
                cmd = [
                    'ffmpeg',
                    '-i', str(current_input)
                ]
                cmd.extend(filter_arg)  # Add filter argument (complex or script file)
                cmd.extend([
                    '-map', '[v]',       # Map filtered video
                    '-map', '0:a',       # Map original audio
                    '-c:v', encoding_settings['video_codec'],  # Use optimal codec based on input
                    '-c:a', 'copy',      # Copy audio without re-encoding
                    '-crf', str(encoding_settings['crf']),     # Use CRF for quality control
                    '-maxrate', encoding_settings['max_bitrate'],  # Maximum bitrate cap
                    '-bufsize', encoding_settings['max_bitrate'],  # Buffer size
                    '-preset', encoding_settings['preset'],    # Quality-focused preset
                    '-pix_fmt', encoding_settings['pix_fmt'],  # Preserve pixel format
                    '-progress', 'pipe:1',
                    '-nostats',
                    '-y',
                    str(batch_output)
                ])
                
                print(f"   ⚙️  Aplicando {len(batch_subtitles)} legendas...")
                print(f"   📂 Saída: {batch_output.name}")
                
                # DEBUG: Show complete command being executed
                print(f"   🔧 DEBUG - Comando FFmpeg completo para lote {batch_idx + 1}:")
                for i, arg in enumerate(cmd):
                    if i < 10 or arg.startswith('-') or arg.endswith('.mp4') or arg.endswith('.txt'):
                        print(f"   🔧   [{i:2d}]: {arg}")
                    elif len(arg) > 100:
                        print(f"   🔧   [{i:2d}]: {arg[:50]}...{arg[-50:]}")
                    else:
                        print(f"   🔧   [{i:2d}]: {arg}")
                        
                # If using filter file, show its current content right before execution
                if filter_file_path and os.path.exists(filter_file_path):
                    try:
                        with open(filter_file_path, 'r', encoding='utf-8') as f:
                            current_content = f.read()
                        print(f"   🔧 DEBUG - Arquivo de filtro antes da execução:")
                        print(f"   🔧   Arquivo: {filter_file_path}")
                        print(f"   🔧   Tamanho: {len(current_content)} chars")
                        print(f"   🔧   [v] presente: {'✅' if '[v]' in current_content else '❌'}")
                        if current_content:
                            lines = current_content.split('\n')
                            print(f"   🔧   Total linhas: {len(lines)}")
                            print(f"   🔧   Primeira linha: {lines[0][:100]}...")
                            if len(lines) > 1 and lines[-1]:
                                print(f"   🔧   Última linha: ...{lines[-1][-100:]}")
                        else:
                            print(f"   🔧   ❌ ARQUIVO VAZIO!")
                    except Exception as debug_error:
                        print(f"   🔧 DEBUG - ERRO ao ler arquivo de filtro: {debug_error}")
                
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
                    
                    # Update video duration for next batch if not the last batch
                    if batch_idx < len(batches) - 1:
                        _, _, video_duration = get_video_info(current_input)
                else:
                    print(f"   ❌ Erro no lote {batch_idx + 1} (código: {return_code})")
                    if stderr_output:
                        print(f"   STDERR: {''.join(stderr_output)}")
                    return False
                    
            finally:
                # TEMPORARY: Don't clean up filter file for investigation
                if filter_file_path and os.path.exists(filter_file_path):
                    print(f"   🔧 [DEBUG] PRESERVANDO arquivo de filtro: {filter_file_path}")
                    print(f"   🔧 [DEBUG] Para examinar: cat '{filter_file_path}'")
                    # try:
                    #     os.unlink(filter_file_path)
                    # except OSError:
                    #     pass  # Ignore cleanup errors
        
        # Clean up temporary files
        cleanup_temp_files(temp_files)
        
        print(f"🎉 Processamento em lotes concluído com sucesso!")
        return True
        
    except Exception as e:
        print(f"❌ Erro no processamento em lotes: {e}")
        # Clean up temporary files even on error
        cleanup_temp_files(temp_files)
        return False


def cleanup_temp_files(temp_files: list) -> None:
    """Clean up temporary batch files."""
    if not temp_files:
        return
        
    print(f"\n🧹 Limpando {len(temp_files)} arquivos temporários...")
    cleaned_count = 0
    
    for temp_file in temp_files:
        try:
            if temp_file.exists():
                temp_file.unlink()
                cleaned_count += 1
                print(f"   🗑️  Removido: {temp_file.name}")
        except OSError as e:
            print(f"   ⚠️  Não foi possível remover {temp_file.name}: {e}")
    
    print(f"✅ {cleaned_count}/{len(temp_files)} arquivos temporários limpos")


def cleanup_existing_batch_files(output_video: Path) -> None:
    """Clean up any existing batch files from previous runs."""
    if not output_video.parent.exists():
        return
    
    # Pattern to match batch files: *_batch_*.mp4
    batch_pattern = f"{output_video.stem}_batch_*.mp4"
    existing_batch_files = list(output_video.parent.glob(batch_pattern))
    
    if existing_batch_files:
        print(f"🧹 Encontrados {len(existing_batch_files)} arquivos de lotes anteriores - limpando...")
        cleaned_count = 0
        
        for batch_file in existing_batch_files:
            try:
                if batch_file.exists():
                    batch_file.unlink()
                    cleaned_count += 1
                    print(f"   🗑️  Removido: {batch_file.name}")
            except OSError as e:
                print(f"   ⚠️  Não foi possível remover {batch_file.name}: {e}")
        
        print(f"✅ {cleaned_count}/{len(existing_batch_files)} arquivos de lotes anteriores limpos")


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
        
        # Get optimal encoding settings based on input video
        video_encoding_info = get_video_encoding_info(input_video)
        encoding_settings = get_optimal_encoding_settings(video_encoding_info)
        
        print(f"🎯 Configurações de qualidade detectadas:")
        print(f"   📹 Codec: {video_encoding_info['codec_name']} → {encoding_settings['video_codec']}")
        print(f"   📊 Bitrate: {video_encoding_info['bit_rate']//1000 if video_encoding_info['bit_rate'] > 0 else 'N/A'}kbps")
        print(f"   ⚙️  CRF: {encoding_settings['crf']}, Max: {encoding_settings['max_bitrate']}")
        
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
        
        # For large filter chains, use a filter file to avoid command line length limits
        filter_file_path = None
        try:
            if len(drawtext_filters) > 50000:  # Use filter file for very long filters
                print(f"   📄 Filtro longo ({len(drawtext_filters):,} chars) - usando arquivo temporário")
                filter_file_path = create_filter_file(drawtext_filters)
                # Use the EXACT syntax recommended by FFmpeg 8.0
                filter_arg = ['-/filter_complex', filter_file_path]
                print(f"   ✅ [TESTE] Usando -/filter_complex (sintaxe recomendada pelo FFmpeg): {filter_file_path}")
                print(f"   📝 [TESTE] Testando com lotes menores E sintaxe correta")
                print(f"   🔧 DEBUG: Preservando arquivo temporário para investigação")
            else:
                filter_arg = ['-filter_complex', drawtext_filters]
            
            # For manageable filter chains, use direct method with optimal quality
            cmd = [
                'ffmpeg',
                '-i', str(input_video)
            ]
            cmd.extend(filter_arg)  # Add filter argument (complex or script file)
            cmd.extend([
                '-map', '[v]',       # Map filtered video
                '-map', '0:a',       # Map original audio
                '-c:v', encoding_settings['video_codec'],  # Use optimal codec based on input
                '-c:a', 'copy',      # Copy audio without re-encoding
                '-crf', str(encoding_settings['crf']),     # Use CRF for quality control
                '-maxrate', encoding_settings['max_bitrate'],  # Maximum bitrate cap
                '-bufsize', encoding_settings['max_bitrate'],  # Buffer size
                '-preset', encoding_settings['preset'],    # Quality-focused preset
                '-pix_fmt', encoding_settings['pix_fmt'],  # Preserve pixel format
                '-progress', 'pipe:1',
                '-nostats',
                '-y',
                str(output_video)
            ])
            
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
            # TEMPORARY: Don't clean up filter file for investigation
            if filter_file_path and os.path.exists(filter_file_path):
                print(f"   🔧 [DEBUG] PRESERVANDO arquivo de filtro: {filter_file_path}")
                print(f"   🔧 [DEBUG] Para examinar: cat '{filter_file_path}'")
                # try:
                #     os.unlink(filter_file_path)
                # except OSError:
                #     pass  # Ignore cleanup errors
                    
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
        # If input file is already a chromecast_temp file, derive original name for output
        if '_chromecast_temp' in mp4_file.stem:
            # Remove all chromecast_temp suffixes to get original base name
            original_base_name = mp4_file.stem
            while '_chromecast_temp' in original_base_name:
                original_base_name = original_base_name.replace('_chromecast_temp', '')
            output_name = original_base_name + '_sub' + mp4_file.suffix
            print(f"   🔍 Derivando nome de saída do original: {original_base_name}")
        else:
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
                # Check for existing temp file in dry-run
                # If input file is already a chromecast_temp file, use it directly
                if '_chromecast_temp' in mp4_file.stem:
                    chromecast_temp_path = mp4_file
                    chromecast_temp_name = mp4_file.name
                else:
                    chromecast_temp_name = mp4_file.stem + '_chromecast_temp' + mp4_file.suffix
                    chromecast_temp_path = mp4_file.parent / chromecast_temp_name
                
                if chromecast_temp_path.exists():
                    print("   [DRY RUN] - Arquivo temporário Chromecast encontrado")
                    print("   [DRY RUN] - Conversão seria pulada, aplicaria apenas legendas")
                else:
                    print("   [DRY RUN] - Simulação de processamento em 2 etapas:")
                    print("   [DRY RUN] - 1. Conversão para formato Chromecast")
                    print("   [DRY RUN] - 2. Aplicação de legendas")
                print("   [DRY RUN] - Arquivos temporários seriam removidos")
                processed_count += 1
        else:
            # Prepare paths for processing
            # Check if the file is already a chromecast_temp file
            if '_chromecast_temp' in mp4_file.stem:
                # This file is already a chromecast_temp file, use it directly
                chromecast_temp_path = mp4_file
                chromecast_temp_name = mp4_file.name
                print(f"   🔍 Arquivo de entrada já é chromecast_temp: {chromecast_temp_name}")
            else:
                # This is an original file, prepare chromecast_temp path
                chromecast_temp_name = mp4_file.stem + '_chromecast_temp' + mp4_file.suffix
                chromecast_temp_path = mp4_file.parent / chromecast_temp_name
            
            # Also check for batch files from previous failed runs
            base_name = mp4_file.stem
            existing_batch_files = list(mp4_file.parent.glob(f"{base_name}_batch_*.mp4"))
            
            # Check if Chromecast conversion was already done (resumption logic)
            chromecast_ready = False
            
            if '_chromecast_temp' in mp4_file.stem:
                # Input file is already a chromecast_temp file
                print(f"   🔄 Arquivo de entrada já está no formato Chromecast: {chromecast_temp_name}")
                print(f"   ⏭️  Pulando conversão, continuando com aplicação de legendas...")
                chromecast_ready = True
            elif chromecast_temp_path.exists():
                print(f"   🔄 Arquivo Chromecast temporário encontrado: {chromecast_temp_name}")
                print(f"   ⏭️  Pulando conversão, continuando com aplicação de legendas...")
                chromecast_ready = True
            elif existing_batch_files:
                # If we have batch files but no chromecast_temp, use the last batch as input
                latest_batch = max(existing_batch_files, key=lambda p: int(p.stem.split('_batch_')[1]))
                print(f"   🔄 Encontrados arquivos de lote de execução anterior")
                print(f"   🔄 Usando último lote como entrada: {latest_batch.name}")
                chromecast_temp_path = latest_batch  # Use the latest batch as chromecast_temp
                chromecast_ready = True
            else:
                # Step 1: Convert original video to Chromecast format
                print(f"   🔄 Passo 1/2: Convertendo para formato Chromecast...")
                if convert_to_chromecast_format(mp4_file, chromecast_temp_path):
                    print(f"   📱 Vídeo Chromecast criado: {chromecast_temp_name}")
                    chromecast_ready = True
                else:
                    print(f"   ❌ Erro na conversão para Chromecast: {mp4_file.name}")
                    error_count += 1
            
            # Step 2: Apply subtitles (only if Chromecast conversion succeeded or was already done)
            if chromecast_ready:
                print(f"   🔄 Passo 2/2: Aplicando legendas...")
                if apply_subtitles_to_video(chromecast_temp_path, subtitles, output_path):
                    print(f"   ✅ Vídeo final com legendas criado: {output_name}")
                    print(f"   📱 Formato: 100% compatível com Chromecast!")
                    
                    # Clean up temporary files only after successful completion
                    try:
                        mp4_file.unlink()  # Remove original
                        
                        # Only remove chromecast_temp if it's the actual chromecast temp file, not a batch file
                        if chromecast_temp_path.name.endswith('_chromecast_temp.mp4'):
                            chromecast_temp_path.unlink()  # Remove temp chromecast version
                        
                        # Clean up any remaining batch files
                        base_name = mp4_file.stem
                        batch_files_to_clean = list(mp4_file.parent.glob(f"{base_name}_batch_*.mp4"))
                        for batch_file in batch_files_to_clean:
                            batch_file.unlink()
                        
                        if batch_files_to_clean:
                            print(f"   🗑️  Arquivos temporários removidos ({len(batch_files_to_clean)} lotes + chromecast)")
                        else:
                            print(f"   🗑️  Arquivos temporários removidos")
                    except Exception as e:
                        print(f"   ⚠️  Aviso na limpeza: {e}")
                    
                    processed_count += 1
                else:
                    print(f"   ❌ Erro ao aplicar legendas")
                    print(f"   💡 Arquivos temporários mantidos para nova tentativa")
                    print(f"   📁 Chromecast temp: {chromecast_temp_path.name}")
                    # List any existing batch files for debugging
                    base_name = mp4_file.stem
                    existing_batch_files = list(mp4_file.parent.glob(f"{base_name}_batch_*.mp4"))
                    if existing_batch_files:
                        print(f"   📁 Lotes existentes: {len(existing_batch_files)} arquivos")
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
