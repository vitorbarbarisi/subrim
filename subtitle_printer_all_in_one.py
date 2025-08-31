#!/usr/bin/env python3
"""
Subtitle Printer - Adiciona legendas chinesas e traduções às imagens

Usage: python3 subtitle_printer.py <directory_name>
Example: python3 subtitle_printer.py chaves001

O script lê as imagens em assets/<directory_name>/screenshots/ e o arquivo *_base.txt correspondente.
Para cada imagem, verifica se o nome da imagem (em segundos) corresponde ao timestamp
no arquivo base.txt. Se corresponder:
1. Aplica legendas diretamente na imagem original (modo all-in-one):

- Legenda chinesa com pinyin acima e traduções em português abaixo de cada palavra
- A imagem original é modificada diretamente (não são criadas versões separadas)
"""

import sys
import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import re

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Erro: PIL (Pillow) não encontrado. Instale com: pip install Pillow")
    sys.exit(1)



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


def parse_base_file(base_file_path: Path) -> Dict[int, Tuple[str, str, str, str]]:
    """
    Parse the base.txt file and return a mapping of seconds -> (chinese subtitle, translations, translations_json, portuguese).
    
    Supports both old format (5 columns) and new format (6 columns):
    - Old: index, begin_time, chinese_text, translations, portuguese
    - New: index, begin_time, end_time, chinese_text, translations, portuguese
    
    For new format, creates entries for ALL seconds within the begin-end interval.
    
    Returns:
        Dict mapping second (as int) to tuple of (chinese_text, translations_text, translations_json, portuguese_text)
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
                
                begin_seconds_float = float(begin_match.group(1))
                begin_seconds_int = int(round(begin_seconds_float))
                
                # Extract end timestamp if available (third column in new format)
                end_seconds_int = begin_seconds_int  # Default to same as begin
                if is_new_format:
                    end_timestamp_str = parts[2].strip()
                    end_match = re.match(r'([\d.]+)s?', end_timestamp_str)
                    if end_match:
                        end_seconds_float = float(end_match.group(1))
                        end_seconds_int = int(round(end_seconds_float))
                
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
                    # Create entries for all seconds in the interval [begin_seconds_int, end_seconds_int]
                    for second in range(begin_seconds_int, end_seconds_int + 1):
                        subtitles[second] = (chinese_text, formatted_translations, translations_json, portuguese_text)
                    
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


def get_chinese_font_path() -> Optional[Path]:
    """Try to find a suitable font specifically for Chinese characters."""
    # Fonts optimized for Chinese characters (in order of preference)
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",  # Best for Chinese + Latin
        "/System/Library/Fonts/Hiragino Sans GB.ttc",  # Good for Simplified Chinese
        "/System/Library/Fonts/STSong.ttc",  # Chinese font
        "/System/Library/Fonts/Songti.ttc",  # Traditional Chinese
        "/Library/Fonts/Arial Unicode MS.ttf",  # Comprehensive Unicode support
        "/System/Library/Fonts/Apple Symbols.ttf"  # Unicode fallback
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            return Path(font_path)
    
    return None


def get_portuguese_font_path() -> Optional[Path]:
    """Try to find a suitable font specifically for Portuguese accents."""
    # Fonts optimized for Latin characters and accents (in order of preference)
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",  # Excellent Latin support including accents
        "/System/Library/Fonts/ArialHB.ttc",  # Arial with good Unicode support
        "/System/Library/Fonts/HelveticaNeue.ttc",  # Modern Helvetica with good Unicode
        "/System/Library/Fonts/Times.ttc",  # Times with accent support
        "/Library/Fonts/Arial Unicode MS.ttf",  # Comprehensive Unicode support
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            return Path(font_path)
    
    return None


def get_font_path() -> Optional[Path]:
    """Legacy function - try Chinese font first as fallback."""
    return get_chinese_font_path()


# resize_image_only function removed - no longer needed without R36S resizing


def break_text_for_subtitle(text: str, font, max_width: int, draw, is_chinese: bool = True) -> list[str]:
    """
    Break text into multiple lines for subtitle display.
    
    Args:
        text: Text to break (Chinese or Portuguese)
        font: Font object for measuring text width
        max_width: Maximum width for each line
        draw: ImageDraw object for text measurement
        is_chinese: True for Chinese text (break by characters), False for Portuguese (break by words)
        
    Returns:
        List of text lines
    """
    # First check if text contains dialogue marker "-"
    if "-" in text:
        # Split on dialogue marker and treat as separate lines
        parts = text.split("-", 1)  # Split only on first "-"
        if len(parts) == 2:
            # Format as dialogue: first part + "-" + second part
            lines = []
            first_part = parts[0].strip()
            second_part = parts[1].strip()
            
            if first_part:
                lines.append(first_part)
            if second_part:
                lines.append("-" + second_part)
                
            # Check if any line is still too long and needs further breaking
            final_lines = []
            for line in lines:
                if draw.textbbox((0, 0), line, font=font)[2] <= max_width:
                    final_lines.append(line)
                else:
                    # Break long line appropriately for language
                    if is_chinese:
                        final_lines.extend(_break_line_by_characters(line, font, max_width, draw))
                    else:
                        final_lines.extend(_break_line_by_words(line, font, max_width, draw))
            
            return final_lines
    
    # Check if single line fits
    text_width = draw.textbbox((0, 0), text, font=font)[2]
    if text_width <= max_width:
        return [text]
    
    # Break long text appropriately for language
    if is_chinese:
        return _break_line_by_characters(text, font, max_width, draw)
    else:
        return _break_line_by_words(text, font, max_width, draw)


def _break_line_by_characters(text: str, font, max_width: int, draw) -> list[str]:
    """
    Break text into lines by characters when it's too long (for Chinese text).
    
    Args:
        text: Text to break
        font: Font object
        max_width: Maximum width per line
        draw: ImageDraw object
        
    Returns:
        List of text lines
    """
    if not text:
        return []
    
    lines = []
    current_line = ""
    
    for char in text:
        test_line = current_line + char
        test_width = draw.textbbox((0, 0), test_line, font=font)[2]
        
        if test_width <= max_width:
            current_line = test_line
        else:
            # Current line is full, start new line
            if current_line:
                lines.append(current_line)
            current_line = char
    
    # Add remaining text
    if current_line:
        lines.append(current_line)
    
    return lines


def _break_line_by_words(text: str, font, max_width: int, draw) -> list[str]:
    """
    Break text into lines by words when it's too long (for Portuguese text).
    
    Args:
        text: Text to break
        font: Font object
        max_width: Maximum width per line
        draw: ImageDraw object
        
    Returns:
        List of text lines
    """
    if not text:
        return []
    
    words = text.split()
    if not words:
        return []
    
    lines = []
    current_line = ""
    
    for word in words:
        # Test adding this word to current line
        test_line = current_line + (" " if current_line else "") + word
        test_width = draw.textbbox((0, 0), test_line, font=font)[2]
        
        if test_width <= max_width:
            current_line = test_line
        else:
            # Current line is full, start new line
            if current_line:
                lines.append(current_line)
                current_line = word
            else:
                # Single word is too long, break by characters as fallback
                lines.extend(_break_line_by_characters(word, font, max_width, draw))
    
    # Add remaining text
    if current_line:
        lines.append(current_line)
    
    return lines


def break_chinese_text_for_subtitle(text: str, font, max_width: int, draw) -> list[str]:
    """
    Legacy function - wrapper for break_text_for_subtitle with Chinese settings.
    
    Args:
        text: Chinese text to break
        font: Font object for measuring text width
        max_width: Maximum width for each line
        draw: ImageDraw object for text measurement
        
    Returns:
        List of text lines
    """
    return break_text_for_subtitle(text, font, max_width, draw, is_chinese=True)


# resize_image_for_r36s function removed - no longer needed without R36S resizing


def copy_images_to_destination(source_dir: Path, dest_dir: Path) -> int:
    """
    Copy only PNG images from source to destination directory.
    
    Args:
        source_dir: Source directory path
        dest_dir: Destination directory path
    
    Returns:
        Number of images copied
    """
    # Create destination directory if it doesn't exist
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all PNG files in source directory
    png_files = list(source_dir.glob("*.png"))
    
    copied_count = 0
    for png_file in png_files:
        dest_file = dest_dir / png_file.name
        try:
            shutil.copy2(png_file, dest_file)
            copied_count += 1
        except Exception as e:
            print(f"⚠️  Erro ao copiar {png_file.name}: {e}")
    
    return copied_count


def add_top_translations(image_path: Path, translations_text: str, output_path: Path = None) -> bool:
    """
    Add translations to the top of the image.
    
    Args:
        image_path: Path to the original image
        translations_text: Translation text to add at the top
        output_path: Output path (if None, overwrites original)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Use original image dimensions (no R36S resizing)
            new_img = img.copy()
            width, height = new_img.size
            
            # Draw translations
            draw = ImageDraw.Draw(new_img)
            
            # For detailed translations, we need a font that supports BOTH Chinese and Portuguese
            # Try Arial Unicode MS first (comprehensive Unicode support), then fallback
            font_path = None
            unicode_fonts = [
                Path("/Library/Fonts/Arial Unicode.ttf"),  # Best for mixed content
                Path("/System/Library/Fonts/PingFang.ttc"),  # Also good for mixed
                get_chinese_font_path()  # Fallback to Chinese font
            ]
            
            for font_candidate in unicode_fonts:
                if font_candidate and font_candidate.exists():
                    font_path = font_candidate
                    break
            
            # Calculate available area for translations (top 30% of image)
            available_height = int(height * 0.3)
            available_width = width - 40  # 20px padding on each side
            
            # Start with a reasonable font size
            max_font_size = 24
            font_size = max_font_size
            
            # Load font and adjust size to fit
            font = None
            lines = translations_text.split('\n')
            
            for attempt in range(10):  # Try up to 10 different sizes
                try:
                    if font_path:
                        font = ImageFont.truetype(str(font_path), font_size)
                    else:
                        font = ImageFont.load_default()
                    
                    # Test if all lines fit within available area
                    total_height = 0
                    max_line_width = 0
                    
                    for line in lines:
                        if line.strip():
                            bbox = draw.textbbox((0, 0), line, font=font)
                            line_width = bbox[2] - bbox[0]
                            line_height = bbox[3] - bbox[1]
                            
                            max_line_width = max(max_line_width, line_width)
                            total_height += line_height + 2  # 2px line spacing
                    
                    # Check if text fits within available area
                    if max_line_width <= available_width and total_height <= available_height:
                        break
                    
                    # Reduce font size and try again
                    font_size = int(font_size * 0.9)
                    if font_size < 8:  # Minimum readable size
                        break
                        
                except:
                    font = ImageFont.load_default()
                    break
            
            # Draw translations at the top with semi-transparent background
            if lines and font:
                # Calculate total text height
                total_height = 0
                for line in lines:
                    if line.strip():
                        bbox = draw.textbbox((0, 0), line, font=font)
                        total_height += bbox[3] - bbox[1] + 2
                
                # Add semi-transparent background
                bg_height = min(total_height + 20, available_height)
                background = Image.new('RGBA', (width, bg_height), (0, 0, 0, 180))
                new_img.paste(background, (0, 0), background)
                
                # Draw text lines
                y_offset = 10
                for line in lines:
                    if line.strip():
                        bbox = draw.textbbox((0, 0), line, font=font)
                        line_width = bbox[2] - bbox[0]
                        line_height = bbox[3] - bbox[1]
                        
                        # Center horizontally
                        x = (width - line_width) // 2
                        
                        # Draw text in white
                        draw.text((x, y_offset), line, fill=(255, 255, 255), font=font)
                        y_offset += line_height + 2
            
            # Save the result
            if output_path:
                save_path = output_path
            else:
                save_path = image_path
            
            new_img.save(save_path, "PNG")
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False


def add_subtitle_with_portuguese(image_path: Path, chinese_text: str, portuguese_text: str, output_path: Path = None) -> bool:
    """
    Add Chinese subtitle to the bottom and Portuguese translation above it.
    
    Args:
        image_path: Path to the original image
        chinese_text: Chinese subtitle text to add at the bottom
        portuguese_text: Portuguese translation to add above Chinese text
        output_path: Output path (if None, overwrites original)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Use original image dimensions (no R36S resizing)
            new_img = img.copy()
            width, height = new_img.size
            
            # Draw subtitles
            draw = ImageDraw.Draw(new_img)
            
            # Get specific fonts for each language
            chinese_font_path = get_chinese_font_path()
            portuguese_font_path = get_portuguese_font_path()
            
            # Calculate available height for both texts (bottom 25% of image)
            margin_from_bottom = 50
            available_height = int(height * 0.25)
            available_width = width - 40  # 20px padding on each side
            
            # Start with larger font sizes for better readability
            chinese_font_size = min(64, int(available_height * 0.5))  # Increased from 48
            portuguese_font_size = min(40, int(available_height * 0.35))  # Increased from 32
            
            # Load fonts and adjust sizes with line breaking for Chinese
            chinese_font = None
            portuguese_font = None
            chinese_text_lines = []
            chinese_total_height = 0
            portuguese_text_height = 0
            
            # Adjust Chinese font size with line breaking
            for attempt in range(10):
                try:
                    if chinese_font_path:
                        chinese_font = ImageFont.truetype(str(chinese_font_path), chinese_font_size)
                    else:
                        chinese_font = ImageFont.load_default()
                    
                    # Break Chinese text into lines
                    chinese_text_lines = break_text_for_subtitle(chinese_text, chinese_font, available_width, draw, is_chinese=True)
                    
                    # Calculate total height for Chinese text lines
                    line_height = draw.textbbox((0, 0), "測試", font=chinese_font)[3] - draw.textbbox((0, 0), "測試", font=chinese_font)[1]
                    chinese_total_height = len(chinese_text_lines) * line_height + (len(chinese_text_lines) - 1) * 5  # 5px line spacing
                    
                    # Check if Chinese text fits in available space (reserve space for Portuguese)
                    reserved_height_for_portuguese = available_height * 0.4
                    if chinese_total_height <= (available_height - reserved_height_for_portuguese):
                        break
                    
                    chinese_font_size = int(chinese_font_size * 0.9)
                    if chinese_font_size < 16:  # Increased minimum size
                        break
                        
                except:
                    chinese_font = ImageFont.load_default()
                    chinese_text_lines = [chinese_text]
                    chinese_total_height = draw.textbbox((0, 0), chinese_text, font=chinese_font)[3] - draw.textbbox((0, 0), chinese_text, font=chinese_font)[1]
                    break
            
            # Adjust Portuguese font size with line breaking (always calculate, use N/A if text is empty)
            display_portuguese = portuguese_text if portuguese_text else "N/A"
            portuguese_text_lines = []
            portuguese_total_height = 0
            
            for attempt in range(10):
                try:
                    if portuguese_font_path:
                        portuguese_font = ImageFont.truetype(str(portuguese_font_path), portuguese_font_size)
                    else:
                        portuguese_font = ImageFont.load_default()
                    
                    # Break Portuguese text into lines
                    portuguese_text_lines = break_text_for_subtitle(display_portuguese, portuguese_font, available_width, draw, is_chinese=False)
                    
                    # Calculate total height for Portuguese text lines
                    line_height = draw.textbbox((0, 0), "Test", font=portuguese_font)[3] - draw.textbbox((0, 0), "Test", font=portuguese_font)[1]
                    portuguese_total_height = len(portuguese_text_lines) * line_height + (len(portuguese_text_lines) - 1) * 5  # 5px line spacing
                    
                    # Check if Portuguese text fits in available space
                    if portuguese_total_height <= (available_height * 0.4):  # Portuguese should use max 40% of available height
                        break
                    
                    portuguese_font_size = int(portuguese_font_size * 0.9)
                    if portuguese_font_size < 10:
                        break
                        
                except Exception as e:
                    portuguese_font = ImageFont.load_default()
                    portuguese_text_lines = [display_portuguese]
                    portuguese_total_height = draw.textbbox((0, 0), display_portuguese, font=portuguese_font)[3] - draw.textbbox((0, 0), display_portuguese, font=portuguese_font)[1]
                    break
            
            # Calculate position for Chinese text (bottom area)
            chinese_start_y = height - margin_from_bottom - chinese_total_height
            
            # Position and draw Portuguese text lines above Chinese (always show, use N/A if empty)
            if portuguese_font and portuguese_text_lines:
                # Calculate starting position for Portuguese text (above Chinese with 10px gap)
                portuguese_start_y = chinese_start_y - portuguese_total_height - 10
                
                # Draw each Portuguese line
                line_height = draw.textbbox((0, 0), "Test", font=portuguese_font)[3] - draw.textbbox((0, 0), "Test", font=portuguese_font)[1]
                
                for i, line in enumerate(portuguese_text_lines):
                    # Calculate width of this line for centering
                    line_bbox = draw.textbbox((0, 0), line, font=portuguese_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_x = (width - line_width) // 2
                    
                    # Calculate Y position for this line
                    line_y = portuguese_start_y + i * (line_height + 5)  # 5px line spacing
                    
                    # Draw line with yellow color
                    draw.text((line_x, line_y), line, fill=(255, 255, 0), font=portuguese_font)
            
            # Draw Chinese text lines in white
            if chinese_text_lines and chinese_font:
                line_height = draw.textbbox((0, 0), "測試", font=chinese_font)[3] - draw.textbbox((0, 0), "測試", font=chinese_font)[1]
                
                for i, line in enumerate(chinese_text_lines):
                    # Calculate width of this line for centering
                    line_bbox = draw.textbbox((0, 0), line, font=chinese_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_x = (width - line_width) // 2
                    
                    # Calculate Y position for this line
                    line_y = chinese_start_y + i * (line_height + 5)  # 5px line spacing
                    
                    # Draw line with white color
                    draw.text((line_x, line_y), line, fill=(255, 255, 255), font=chinese_font)
            
            # Save the result
            if output_path:
                save_path = output_path
            else:
                # Add "c" suffix to the filename (e.g., 5.png -> 5c.png)
                stem = image_path.stem  # filename without extension
                suffix = image_path.suffix  # file extension
                save_path = image_path.parent / f"{stem}c{suffix}"
            
            new_img.save(save_path, "PNG")
            
            # NOTE: Don't remove original here - let the main process handle it
            
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False




def wrap_text_to_width(text, font, draw, max_width):
    """
    Break text into lines that fit within the specified width.
    
    Args:
        text: Text to wrap
        font: Font to use for measuring
        draw: ImageDraw object for text measurement
        max_width: Maximum width in pixels
        
    Returns:
        List of text lines that fit within max_width
    """
    if not text:
        return []
    
    words = text.split()
    if not words:
        return []
    
    lines = []
    current_line = []
    
    for word in words:
        # Test if adding this word would exceed max width
        test_line = ' '.join(current_line + [word])
        test_width = draw.textbbox((0, 0), test_line, font=font)[2]
        
        if test_width <= max_width or not current_line:
            # Word fits or it's the first word in line
            current_line.append(word)
        else:
            # Word doesn't fit, start new line
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    # Don't forget the last line
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def draw_text_with_border(draw, x, y, text, font, fill_color, border_color=(0, 0, 0), border_width=2):
    """
    Draw text with a black border for better visibility.
    
    Args:
        draw: ImageDraw object
        x, y: Position coordinates
        text: Text to draw
        font: Font to use
        fill_color: Main text color
        border_color: Border color (default black)
        border_width: Width of border in pixels
    """
    # Draw border by drawing text in multiple positions around the main position
    for dx in range(-border_width, border_width + 1):
        for dy in range(-border_width, border_width + 1):
            if dx != 0 or dy != 0:  # Don't draw on the main position yet
                draw.text((x + dx, y + dy), text, fill=border_color, font=font)
    
    # Draw main text on top
    draw.text((x, y), text, fill=fill_color, font=font)


def draw_multiline_text_with_border(draw, x, y, text_lines, font, fill_color, border_color=(0, 0, 0), border_width=2, line_spacing=2):
    """
    Draw multiple lines of text with borders, centered horizontally.
    
    Args:
        draw: ImageDraw object
        x, y: Starting position (top-left of text block)
        text_lines: List of text lines to draw
        font: Font to use
        fill_color: Main text color
        border_color: Border color (default black)
        border_width: Width of border in pixels
        line_spacing: Extra spacing between lines
    """
    if not text_lines:
        return
    
    line_height = draw.textbbox((0, 0), "Test", font=font)[3] - draw.textbbox((0, 0), "Test", font=font)[1]
    current_y = y
    
    for line in text_lines:
        line_width = draw.textbbox((0, 0), line, font=font)[2]
        line_x = x - line_width // 2  # Center the line horizontally
        
        draw_text_with_border(draw, line_x, current_y, line, font, fill_color, border_color, border_width)
        current_y += line_height + line_spacing


def add_pinyin_subtitle_to_image(image_path: Path, chinese_text: str, translations_json: str, output_path: Path = None) -> bool:
    """
    Add Chinese subtitle with pinyin above and Portuguese translations below each word.
    
    Args:
        image_path: Path to the original image
        chinese_text: Chinese subtitle text
        translations_json: JSON string with word translations containing pinyin
        output_path: Output path (if None, overwrites original)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Use original image dimensions (no R36S resizing)
            new_img = img.copy()
            width, height = new_img.size
            
            # Draw subtitle
            draw = ImageDraw.Draw(new_img)
            
            # Parse translations to get pinyin and Portuguese
            word_data = parse_pinyin_translations(translations_json) if translations_json else []
            
            # Get font paths
            chinese_font_path = get_chinese_font_path()
            portuguese_font_path = get_portuguese_font_path()
            
            # Calculate available space for subtitles  
            margin_from_bottom = 80
            available_width = width - 40  # 20px padding on each side
            available_height = margin_from_bottom
            
            # Start with reasonable font sizes and adjust if needed
            max_chinese_font_size = min(56, int(width * 0.08))  # Increased from 48 and 0.06
            max_pinyin_font_size = int(max_chinese_font_size * 0.7)
            max_portuguese_font_size = int(max_chinese_font_size * 0.6)
            
            chinese_font_size = max_chinese_font_size
            pinyin_font_size = max_pinyin_font_size
            portuguese_font_size = max_portuguese_font_size
            
            # Load fonts
            chinese_font = None
            pinyin_font = None  
            portuguese_font = None
            
            # Build display text by grouping characters into words
            clean_text = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '')  # Remove spaces and punctuation
            display_items = []
            processed_chars = set()
            
            # First pass: identify complete words from translation data
            text_position = 0
            remaining_text = clean_text
            
            while remaining_text:
                found_word = False
                
                # Try to find the longest matching word starting at current position
                for chinese_word, word_pinyin, word_portuguese in sorted(word_data, key=lambda x: len(x[0]), reverse=True):
                    if remaining_text.startswith(chinese_word):
                        # Found a word match
                        word_chars = list(chinese_word)
                        display_items.append((word_chars, word_pinyin, word_portuguese))
                        
                        # Mark characters as processed
                        for char in word_chars:
                            processed_chars.add(text_position)
                            text_position += 1
                        
                        remaining_text = remaining_text[len(chinese_word):]
                        found_word = True
                        break
                
                if not found_word:
                    # No word match found, treat as single character
                    char = remaining_text[0]
                    display_items.append(([char], "", ""))  # Single character with no pinyin/portuguese
                    text_position += 1
                    remaining_text = remaining_text[1:]
            
            # Auto-adjust font sizes and create line breaks
            final_lines = []
            fonts_ready = False
            
            for attempt in range(10):  # Try different font sizes
                try:
                    # Load fonts with current sizes
                    if chinese_font_path:
                        chinese_font = ImageFont.truetype(str(chinese_font_path), chinese_font_size)
                        pinyin_font = ImageFont.truetype(str(chinese_font_path), pinyin_font_size)
                    else:
                        chinese_font = ImageFont.load_default()
                        pinyin_font = ImageFont.load_default()
                        
                    if portuguese_font_path:
                        portuguese_font = ImageFont.truetype(str(portuguese_font_path), portuguese_font_size)
                    else:
                        portuguese_font = ImageFont.load_default()
                    
                    # Break text into lines that fit within available width
                    lines = []
                    current_line = []
                    current_line_width = 0
                    
                    for item in display_items:
                        word_chars, pinyin, portuguese = item
                        
                        # Calculate width needed for this word block
                        word_text = ''.join(word_chars)  # Join characters to form word
                        word_width = draw.textbbox((0, 0), word_text, font=chinese_font)[2]
                        pinyin_width = draw.textbbox((0, 0), pinyin, font=pinyin_font)[2] if pinyin else 0
                        portuguese_width = draw.textbbox((0, 0), portuguese, font=portuguese_font)[2] if portuguese else 0
                        
                        max_width = max(word_width, pinyin_width, portuguese_width) + 12  # 12px spacing between words
                        
                        # Check if adding this word would exceed line width
                        if current_line_width + max_width > available_width and current_line:
                            # Start new line
                            lines.append(current_line)
                            current_line = [item]
                            current_line_width = max_width
                        else:
                            # Add to current line
                            current_line.append(item)
                            current_line_width += max_width
                    
                    # Don't forget the last line
                    if current_line:
                        lines.append(current_line)
                    
                    # Calculate total height needed - need to consider Portuguese multiline text
                    # Estimate height more accurately by considering max Portuguese lines per word
                    max_portuguese_lines = 1
                    for line in lines:
                        for word_chars, pinyin, portuguese in line:
                            if portuguese:
                                word_text = ''.join(word_chars)
                                word_width = draw.textbbox((0, 0), word_text, font=chinese_font)[2]
                                portuguese_lines = wrap_text_to_width(portuguese, portuguese_font, draw, word_width)
                                max_portuguese_lines = max(max_portuguese_lines, len(portuguese_lines))
                    
                    # Calculate height: Chinese + Pinyin + (Portuguese lines * font size) + spacing
                    portuguese_height = max_portuguese_lines * portuguese_font_size + (max_portuguese_lines - 1) * 2  # 2px line spacing
                    single_line_height = chinese_font_size + pinyin_font_size + portuguese_height + 20
                    total_height = len(lines) * single_line_height
                    
                    # Check if it fits within available height
                    if total_height <= available_height or chinese_font_size <= 16:
                        final_lines = lines
                        fonts_ready = True
                        break
                    
                    # Reduce font sizes
                    chinese_font_size = int(chinese_font_size * 0.9)
                    pinyin_font_size = int(pinyin_font_size * 0.9)
                    portuguese_font_size = int(portuguese_font_size * 0.9)
                        
                except Exception as e:
                    # Fallback to default fonts
                    chinese_font = ImageFont.load_default()
                    pinyin_font = ImageFont.load_default()
                    portuguese_font = ImageFont.load_default()
                    
                    # Simple single line fallback
                    final_lines = [display_items]
                    fonts_ready = True
                    break
            
            if not fonts_ready:
                # Final fallback
                chinese_font = ImageFont.load_default()
                pinyin_font = ImageFont.load_default()
                portuguese_font = ImageFont.load_default()
                final_lines = [display_items]
            
            # Draw lines of text from bottom up
            # Calculate dynamic line height based on actual Portuguese lines needed
            max_portuguese_lines = 1
            for line in final_lines:
                for word_chars, pinyin, portuguese in line:
                    if portuguese:
                        word_text = ''.join(word_chars)
                        word_width = draw.textbbox((0, 0), word_text, font=chinese_font)[2]
                        portuguese_lines = wrap_text_to_width(portuguese, portuguese_font, draw, word_width)
                        max_portuguese_lines = max(max_portuguese_lines, len(portuguese_lines))
            
            portuguese_height = max_portuguese_lines * portuguese_font_size + (max_portuguese_lines - 1) * 2
            line_height = chinese_font_size + pinyin_font_size + portuguese_height + 25  # Extra spacing for multiline
            total_subtitle_height = len(final_lines) * line_height
            
            # Start from bottom and work up
            base_y = height - margin_from_bottom
            
            # Light purple color for pinyin and Portuguese
            light_purple_color = (147, 112, 219)  # Medium slate blue - lighter purple
            
            for line_idx, line in enumerate(reversed(final_lines)):  # Draw from bottom line up
                line_y_offset = line_idx * line_height
                
                # Calculate total width of this line for centering
                line_width = 0
                char_widths = []
                
                for word_chars, pinyin, portuguese in line:
                    word_text = ''.join(word_chars)  # Join characters to form word
                    word_width = draw.textbbox((0, 0), word_text, font=chinese_font)[2]
                    pinyin_width = draw.textbbox((0, 0), pinyin, font=pinyin_font)[2] if pinyin else 0
                    portuguese_width = draw.textbbox((0, 0), portuguese, font=portuguese_font)[2] if portuguese else 0
                    
                    max_width = max(word_width, pinyin_width, portuguese_width) + 12
                    char_widths.append(max_width)
                    line_width += max_width
                
                # Center the line horizontally
                start_x = (width - line_width) // 2
                current_x = start_x
                
                # Calculate vertical positions for this line
                chinese_y = base_y - line_y_offset
                pinyin_y = chinese_y - pinyin_font_size - 8  # Above Chinese
                portuguese_y = chinese_y + chinese_font_size + 8  # Below Chinese
                
                # Draw each word in the line
                for i, (word_chars, pinyin, portuguese) in enumerate(line):
                    word_max_width = char_widths[i]  # This is actually word width now
                    
                    # Calculate center position for this word block
                    word_text = ''.join(word_chars)
                    word_width = draw.textbbox((0, 0), word_text, font=chinese_font)[2]
                    word_x = current_x + (word_max_width - word_width) // 2
                    
                    # Draw Chinese word (white) with black border
                    draw_text_with_border(draw, word_x, chinese_y, word_text, chinese_font, (255, 255, 255))
                    
                    # Draw pinyin above (light purple) with black border - centered over the word
                    if pinyin:
                        pinyin_width = draw.textbbox((0, 0), pinyin, font=pinyin_font)[2]
                        pinyin_x = current_x + (word_max_width - pinyin_width) // 2
                        draw_text_with_border(draw, pinyin_x, pinyin_y, pinyin, pinyin_font, light_purple_color)
                    
                    # Draw Portuguese below (light purple) with black border - wrapped to fit word width
                    if portuguese:
                        # Use word width as the maximum width for Portuguese text
                        word_width = draw.textbbox((0, 0), word_text, font=chinese_font)[2]
                        portuguese_lines = wrap_text_to_width(portuguese, portuguese_font, draw, word_width)
                        
                        if portuguese_lines:
                            # Calculate center position for the multiline text block
                            portuguese_center_x = current_x + word_max_width // 2
                            draw_multiline_text_with_border(draw, portuguese_center_x, portuguese_y, portuguese_lines, 
                                                          portuguese_font, light_purple_color)
                    
                    current_x += word_max_width
            
            # Save the result
            if output_path:
                save_path = output_path
            else:
                # Add "a" suffix to the filename (e.g., 5.png -> 5a.png)
                stem = image_path.stem  # filename without extension
                suffix = image_path.suffix  # file extension
                save_path = image_path.parent / f"{stem}a{suffix}"
            
            new_img.save(save_path, "PNG")
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False


def add_subtitle_to_image(image_path: Path, subtitle_text: str, output_path: Path = None) -> bool:
    """
    Add Chinese subtitle to the bottom of the image.
    
    Args:
        image_path: Path to the original image
        subtitle_text: Chinese subtitle text to add
        output_path: Output path (if None, overwrites original)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Use original image dimensions (no R36S resizing)
            new_img = img.copy()
            width, height = new_img.size
            
            # Draw subtitle
            draw = ImageDraw.Draw(new_img)
            
            # Try to load a Chinese font specifically
            font_path = get_chinese_font_path()
            
            # Calculate available height for subtitle (50px from bottom)
            margin_from_bottom = 50
            available_height = margin_from_bottom
            
            # Start with a larger font size for better readability
            max_font_size = min(72, int(available_height * 1.2))  # Increased from 48
            font_size = max_font_size
            
            # Calculate available width (with 20px padding on each side)
            available_width = width - 40
            
            # Load font and adjust size to fit with line breaking
            font = None
            text_lines = []
            total_text_height = 0
            
            for attempt in range(10):  # Try up to 10 different sizes
                try:
                    if font_path:
                        font = ImageFont.truetype(str(font_path), font_size)
                    else:
                        font = ImageFont.load_default()
                    
                    # Break text into lines that fit the width
                    text_lines = break_text_for_subtitle(subtitle_text, font, available_width, draw, is_chinese=True)
                    
                    # Calculate total height needed for all lines
                    line_height = draw.textbbox((0, 0), "測試", font=font)[3] - draw.textbbox((0, 0), "測試", font=font)[1]
                    total_text_height = len(text_lines) * line_height + (len(text_lines) - 1) * 5  # 5px line spacing
                    
                    # Check if all lines fit within available height
                    if total_text_height <= available_height:
                        break
                    
                    # Otherwise, reduce font size and try again
                    font_size = int(font_size * 0.9)
                    if font_size < 16:  # Increased minimum size from 12
                        break
                        
                except:
                    font = ImageFont.load_default()
                    text_lines = [subtitle_text]  # Fallback to single line
                    total_text_height = draw.textbbox((0, 0), subtitle_text, font=font)[3] - draw.textbbox((0, 0), subtitle_text, font=font)[1]
                    break
            
            # Render multiple lines of text
            if text_lines and font:
                # Calculate starting position for multi-line text
                line_height = draw.textbbox((0, 0), "測試", font=font)[3] - draw.textbbox((0, 0), "測試", font=font)[1]
                
                # Start from bottom and work upward
                start_y = height - margin_from_bottom - total_text_height
                
                # Draw each line
                for i, line in enumerate(text_lines):
                    # Calculate width of this line for centering
                    line_bbox = draw.textbbox((0, 0), line, font=font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_x = (width - line_width) // 2
                    
                    # Calculate Y position for this line
                    line_y = start_y + i * (line_height + 5)  # 5px line spacing
                    
                    # Draw line with white color
                    draw.text((line_x, line_y), line, fill=(255, 255, 255), font=font)
            
            # Save the result with "a" suffix if no output path specified
            if output_path:
                save_path = output_path
            else:
                # Add "a" suffix to the filename (e.g., 5.png -> 5a.png)
                stem = image_path.stem  # filename without extension
                suffix = image_path.suffix  # file extension
                save_path = image_path.parent / f"{stem}a{suffix}"
            
            new_img.save(save_path, "PNG")
            
            # NOTE: Don't remove original here - let the main process handle it
            
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False


def find_png_files(directory: Path) -> List[Path]:
    """Find all PNG files in the directory, sorted numerically."""
    png_files = []
    
    for file_path in directory.glob("*.png"):
        png_files.append(file_path)
    
    # Sort numerically by filename
    def sort_key(path):
        try:
            # Extract seconds from filename (e.g., "00072_1.png" -> 72, or "0001.png" -> 1)
            stem = path.stem
            if '_' in stem:
                # New format: 00072_1 -> extract 72
                seconds_str = stem.split('_')[0]
                seconds = int(seconds_str.lstrip('0') or '0')  # Remove leading zeros, handle "00000"
                frame = int(stem.split('_')[1])
                return (0, seconds, frame)  # Sort by seconds, then frame
            else:
                # Old format: 0001 -> 1
                return (0, int(stem), 0)
        except ValueError:
            return (1, path.stem, 0)
    
    return sorted(png_files, key=sort_key)


def process_directory(directory: Path, dry_run: bool = False, source_directory: Path = None) -> Tuple[int, int, int]:
    """
    Process all PNG images in the directory and add subtitles where applicable.
    
    Args:
        directory: Directory containing images to process
        dry_run: If True, simulate operations without modifying files
        source_directory: Directory to search for base.txt file (if None, uses directory)
    
    Returns:
        (processed_count, skipped_count, error_count)
    """
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
    
    # Find PNG files
    png_files = find_png_files(directory)
    if not png_files:
        print("Erro: Nenhum arquivo PNG encontrado")
        return 0, 0, 1
    
    print(f"🖼️  Encontradas {len(png_files)} imagens PNG")
    print("-" * 60)
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    
    for png_file in png_files:
        # Extract image index from filename
        try:
            stem = png_file.stem
            if '_' in stem:
                # New format: 00072_1 -> extract 72 as seconds
                seconds_str = stem.split('_')[0]
                image_index = int(seconds_str.lstrip('0') or '0')  # Remove leading zeros, handle "00000"
            else:
                # Old format: 72 -> 72
                image_index = int(stem)
        except ValueError:
            print(f"⚠️  Ignorando {png_file.name} (nome inválido)")
            skipped_count += 1
            continue
        
        # Check if we have a subtitle for this time (image name represents seconds)
        if image_index in subtitles:
            chinese_text, translations_text, translations_json, portuguese_text = subtitles[image_index]
            
            print(f"📸 {png_file.name} -> legendado all-in-one")
            print(f"   中文: \"{chinese_text}\"")
            if portuguese_text:
                print(f"   PT: \"{portuguese_text}\"")
            
            if dry_run:
                print("   [DRY RUN]")
                processed_count += 1
            else:
                # Apply subtitle directly to original image (all-in-one mode)
                # Use pinyin version as it's the most complete
                success = add_pinyin_subtitle_to_image(png_file, chinese_text, translations_json, output_path=png_file)
                
                if success:
                    print(f"   ✅ Legenda aplicada diretamente na imagem original")
                            processed_count += 1
                    else:
                    print("   ❌ Erro ao aplicar legenda")
                        error_count += 1
                else:
            # No subtitle for this image - skip processing
            print(f"⏭️  {png_file.name} -> sem legenda (ignorado)")
            skipped_count += 1
    
    return processed_count, skipped_count, error_count


def find_directories_to_process(assets_dir: Path) -> list[str]:
    """
    Find all directories in assets that don't have a corresponding _sub directory.
    
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
                # Check if it has screenshots subfolder with PNG files or base.txt file
                screenshots_dir = item / "screenshots"
                has_screenshots = screenshots_dir.exists() and screenshots_dir.is_dir()
                has_pngs_in_screenshots = has_screenshots and bool(list(screenshots_dir.glob("*.png")))
                has_base_txt = bool(list(item.glob("*_base.txt")))
                
                if has_pngs_in_screenshots or has_base_txt:
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
    screenshots_dir = source_dir / "screenshots"  # Look for screenshots subfolder
    dest_dir = assets_dir / f"{directory_name}_sub"
    
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"⚠️  Ignorando {directory_name}: não é um diretório válido")
        return 0, 0, 1
    
    if not screenshots_dir.exists() or not screenshots_dir.is_dir():
        print(f"⚠️  Ignorando {directory_name}: pasta 'screenshots' não encontrada")
        return 0, 0, 1
    
    print(f"\n🎬 Processando: {directory_name}")
    print(f"📁 Origem (screenshots): {screenshots_dir}")
    print(f"📁 Destino: {dest_dir}")
    print("-" * 60)
    
    # Copy images to destination directory
    if not dry_run:
        print(f"📋 Copiando imagens PNG de {screenshots_dir.name} para {dest_dir.name}...")
        copied_count = copy_images_to_destination(screenshots_dir, dest_dir)
        print(f"✅ {copied_count} imagens copiadas")
    else:
        print(f"📋 [DRY RUN] Simulando cópia de imagens de {screenshots_dir.name} para {dest_dir.name}")
        png_files = list(screenshots_dir.glob("*.png"))
        print(f"✅ [DRY RUN] {len(png_files)} imagens seriam copiadas")
    
    # Process directory (work on destination, but read base.txt from source)
    if dry_run:
        # For dry run, simulate processing with screenshots directory since dest might not exist yet
        processed, skipped, errors = process_directory(screenshots_dir, dry_run, source_directory=source_dir)
    else:
        # For real processing, work on destination directory
        processed, skipped, errors = process_directory(dest_dir, dry_run, source_directory=source_dir)
    
    return processed, skipped, errors


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona legendas chinesas e traduções às imagens baseado no arquivo base.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 subtitle_printer.py                              # Processa TODAS as pastas sem _sub
  python3 subtitle_printer.py chaves001                    # Copia para assets/chaves001_sub/ e processa
  python3 subtitle_printer.py test --dry-run               # Simula o processamento
  python3 subtitle_printer.py flipper --assets-root data   # Usa data/ ao invés de assets/

Funcionamento:
  1. Se nenhum diretório for especificado, processa todas as pastas em assets/ que não tenham _sub
  2. Cria pasta destino com sufixo "_sub" (ex: test -> test_sub)
  3. Copia apenas imagens PNG da subpasta "screenshots" para a pasta destino
  4. Busca o arquivo *_base.txt na pasta origem (não na subpasta screenshots)
  5. Processa as imagens na pasta destino:
     - Aplica legendas diretamente na imagem original (all-in-one)

Saída:
  Para 5.png -> 5.png (modificada com legendas all-in-one)
  Original é mantido mas com legendas aplicadas diretamente
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
    
    print(f"🎬 Subtitle Printer ALL-IN-ONE - Legendas Diretamente nas Imagens")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print(f"📋 Processamento:")
    print(f"    🎯 Aplica legendas diretamente na imagem original (all-in-one)")
    print(f"    📝 Pinyin acima + chinês + português abaixo de cada palavra")
    print("=" * 60)
    
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
            print(f"   (procurando pastas sem _sub que tenham PNG ou *_base.txt)")
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
    print(f"📊 Total de imagens: {total_files}")
    print(f"✅ Processadas: {total_processed}")
    print(f"   └── Com legendas: aplicadas diretamente na imagem original")
    print(f"⏭️  Ignoradas (nomes inválidos): {total_skipped}")
    print(f"❌ Erros: {total_errors}")
    
    if args.dry_run and total_processed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para aplicar as legendas")
    
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
