#!/usr/bin/env python3
"""
Subtitle Printer - Adiciona legendas chinesas e traduções às imagens

Usage: python3 subtitle_printer.py <directory_name>
Example: python3 subtitle_printer.py chaves001

O script lê as imagens em assets/<directory_name>/screenshots/ e o arquivo *_base.txt correspondente.
Para cada imagem, verifica se o nome da imagem (em segundos) corresponde ao timestamp
no arquivo base.txt. Se corresponder:
1. Redimensiona a imagem para resolução R36S (640x480) mantendo aspect ratio
2. Cria três versões com legendas:

- Versão A (sufixo 'a'): Legenda chinesa com pinyin acima e traduções em português abaixo de cada palavra
- Versão B (sufixo 'b'): Versão A + traduções detalhadas na parte superior
- Versão C (sufixo 'c'): Legenda chinesa + tradução portuguesa acima

O arquivo original é removido após criar as versões A, B e C.
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


def parse_individual_translations(translation_list_str: str) -> list[tuple[str, str]]:
    """
    Parse the translation list string to extract individual word translations.
    
    Args:
        translation_list_str: String like '["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'
        
    Returns:
        List of tuples (chinese_chars, full_translation)
        Example: [("三", "三 (sān): três"), ("號", "號 (hào): número"), ("碼頭", "碼頭 (mǎ tóu): cais")]
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
            # Extract Chinese characters before the first space or parenthesis
            # Format: "三 (sān): três" -> chinese_chars = "三"
            match = re.match(r'^([^\s\(]+)', item)
            if match:
                chinese_chars = match.group(1)
                full_translation = item
                result.append((chinese_chars, full_translation))
        
        return result
        
    except Exception as e:
        print(f"Erro ao fazer parsing da lista de traduções: {e}")
        return []


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
                
                # Extract timestamp (second column - begin time)
                timestamp_str = parts[1].strip()
                
                # Extract seconds from timestamp (e.g., "186.645s" -> 186.645)
                match = re.match(r'([\d.]+)s?', timestamp_str)
                if not match:
                    continue
                
                seconds_float = float(match.group(1))
                seconds_int = int(round(seconds_float))
                
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
                    subtitles[seconds_int] = (chinese_text, formatted_translations, translations_json, portuguese_text)
                    
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


def resize_image_only(image_path: Path, output_path: Path = None) -> bool:
    """
    Resize image to R36S compatible resolution (640x480) without adding subtitles.
    
    Args:
        image_path: Path to the original image
        output_path: Output path (if None, overwrites original)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize image to R36S compatible resolution (640x480)
            resized_img = resize_image_for_r36s(img)
            
            # Save the resized image
            save_path = output_path if output_path else image_path
            resized_img.save(save_path, "PNG")
            
            return True
            
    except Exception as e:
        print(f"Erro ao redimensionar {image_path}: {e}")
        return False


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


def resize_image_for_r36s(img: Image.Image) -> Image.Image:
    """
    Resize image to R36S compatible resolution (640x480) while maintaining aspect ratio.
    Uses letterboxing (black bars) when needed to preserve original proportions.
    
    Args:
        img: PIL Image object
        
    Returns:
        Resized PIL Image object (always 640x480)
    """
    # R36S target resolution
    target_width = 640
    target_height = 480
    
    # Get original dimensions
    original_width, original_height = img.size
    
    # Calculate aspect ratios
    original_aspect = original_width / original_height
    target_aspect = target_width / target_height
    
    # Calculate new dimensions to fit within target while maintaining aspect ratio
    if original_aspect > target_aspect:
        # Image is wider - fit to width, add horizontal letterboxing
        new_width = target_width
        new_height = int(target_width / original_aspect)
    else:
        # Image is taller - fit to height, add vertical letterboxing
        new_height = target_height
        new_width = int(target_height * original_aspect)
    
    # Resize the image with high quality
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Create final image with black letterboxing
    final_img = Image.new('RGB', (target_width, target_height), (0, 0, 0))
    
    # Center the resized image
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    final_img.paste(resized_img, (paste_x, paste_y))
    
    return final_img


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
            
            # Resize image to R36S compatible resolution (640x480)
            new_img = resize_image_for_r36s(img)
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
            
            # Resize image to R36S compatible resolution (640x480)
            new_img = resize_image_for_r36s(img)
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


def add_highlighted_word_subtitle(image_path: Path, full_subtitle: str, highlight_chars: str, word_translation: str, output_path: Path = None) -> bool:
    """
    Create an image with Chinese subtitle where specific characters are highlighted in blue/violet,
    and the word translation is shown at the top.
    
    Args:
        image_path: Path to the original image
        full_subtitle: Full Chinese subtitle text
        highlight_chars: Characters to highlight (e.g., "三", "碼頭")
        word_translation: Translation to show at top (e.g., "三 (sān): três")
        output_path: Output path (if None, overwrites original)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize image to R36S compatible resolution (640x480)
            new_img = resize_image_for_r36s(img)
            width, height = new_img.size
            
            # Draw elements
            draw = ImageDraw.Draw(new_img)
            
            # Get Chinese font
            chinese_font_path = get_chinese_font_path()
            
            # Calculate areas for both texts
            margin_from_bottom = 50
            available_width = width - 40  # 20px padding on each side
            
            # === BOTTOM SUBTITLE (Chinese with highlighted characters) ===
            # Start with larger font size for Chinese subtitle
            max_chinese_font_size = min(72, int(50 * 1.2))
            chinese_font_size = max_chinese_font_size
            chinese_font = None
            chinese_text_lines = []
            chinese_total_height = 0
            
            # Adjust Chinese font size
            for attempt in range(10):
                try:
                    if chinese_font_path:
                        chinese_font = ImageFont.truetype(str(chinese_font_path), chinese_font_size)
                    else:
                        chinese_font = ImageFont.load_default()
                    
                    # Break text into lines
                    chinese_text_lines = break_text_for_subtitle(full_subtitle, chinese_font, available_width, draw, is_chinese=True)
                    
                    # Calculate total height needed
                    line_height = draw.textbbox((0, 0), "測試", font=chinese_font)[3] - draw.textbbox((0, 0), "測試", font=chinese_font)[1]
                    chinese_total_height = len(chinese_text_lines) * line_height + (len(chinese_text_lines) - 1) * 5
                    
                    # Check if fits (reserve space for top translation)
                    if chinese_total_height <= 80:  # Max 80px for Chinese subtitle
                        break
                    
                    chinese_font_size = int(chinese_font_size * 0.9)
                    if chinese_font_size < 16:
                        break
                        
                except:
                    chinese_font = ImageFont.load_default()
                    chinese_text_lines = [full_subtitle]
                    chinese_total_height = draw.textbbox((0, 0), full_subtitle, font=chinese_font)[3] - draw.textbbox((0, 0), full_subtitle, font=chinese_font)[1]
                    break
            
            # === TOP TRANSLATION ===
            # Adjust font size for word translation at top
            max_translation_font_size = min(48, int(height * 0.1))
            translation_font_size = max_translation_font_size
            translation_font = None
            translation_text_lines = []
            translation_total_height = 0
            
            # Try to get Unicode font for mixed content
            unicode_font_path = None
            unicode_fonts = [
                Path("/Library/Fonts/Arial Unicode.ttf"),
                Path("/System/Library/Fonts/PingFang.ttc"),
                get_chinese_font_path()
            ]
            for font_candidate in unicode_fonts:
                if font_candidate and font_candidate.exists():
                    unicode_font_path = font_candidate
                    break
            
            for attempt in range(10):
                try:
                    if unicode_font_path:
                        translation_font = ImageFont.truetype(str(unicode_font_path), translation_font_size)
                    else:
                        translation_font = ImageFont.load_default()
                    
                    # Break translation text
                    translation_text_lines = break_text_for_subtitle(word_translation, translation_font, available_width, draw, is_chinese=False)
                    
                    # Calculate total height
                    line_height = draw.textbbox((0, 0), "Test", font=translation_font)[3] - draw.textbbox((0, 0), "Test", font=translation_font)[1]
                    translation_total_height = len(translation_text_lines) * line_height + (len(translation_text_lines) - 1) * 5
                    
                    # Check if fits in top area
                    if translation_total_height <= height * 0.2:  # Max 20% of height
                        break
                    
                    translation_font_size = int(translation_font_size * 0.9)
                    if translation_font_size < 12:
                        break
                        
                except:
                    translation_font = ImageFont.load_default()
                    translation_text_lines = [word_translation]
                    translation_total_height = draw.textbbox((0, 0), word_translation, font=translation_font)[3] - draw.textbbox((0, 0), word_translation, font=translation_font)[1]
                    break
            
            # === DRAW TOP TRANSLATION ===
            if translation_font and translation_text_lines:
                # Add semi-transparent background for better readability
                padding = 10
                bg_height = translation_total_height + 2 * padding
                bg_rect = [0, 0, width, bg_height]
                
                # Create overlay for background
                overlay = Image.new('RGBA', new_img.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                overlay_draw.rectangle(bg_rect, fill=(0, 0, 0, 128))  # Semi-transparent black
                new_img = Image.alpha_composite(new_img.convert('RGBA'), overlay).convert('RGB')
                draw = ImageDraw.Draw(new_img)
                
                # Draw translation lines
                line_height = draw.textbbox((0, 0), "Test", font=translation_font)[3] - draw.textbbox((0, 0), "Test", font=translation_font)[1]
                start_y = padding
                
                for i, line in enumerate(translation_text_lines):
                    line_bbox = draw.textbbox((0, 0), line, font=translation_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_x = (width - line_width) // 2
                    line_y = start_y + i * (line_height + 5)
                    
                    # Draw in blue-violet (same color as highlighted characters)
                    draw.text((line_x, line_y), line, fill=(138, 43, 226), font=translation_font)
            
            # === DRAW CHINESE SUBTITLE WITH HIGHLIGHTED CHARACTERS ===
            if chinese_text_lines and chinese_font:
                # Calculate starting position for Chinese text
                chinese_start_y = height - margin_from_bottom - chinese_total_height
                line_height = draw.textbbox((0, 0), "測試", font=chinese_font)[3] - draw.textbbox((0, 0), "測試", font=chinese_font)[1]
                
                for i, line in enumerate(chinese_text_lines):
                    # Calculate position for this line
                    line_bbox = draw.textbbox((0, 0), line, font=chinese_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_x = (width - line_width) // 2
                    line_y = chinese_start_y + i * (line_height + 5)
                    
                    # Draw line with character highlighting
                    _draw_line_with_highlight(draw, line, line_x, line_y, chinese_font, highlight_chars)
            
            # Save the result
            if output_path:
                save_path = output_path
            else:
                stem = image_path.stem
                suffix = image_path.suffix
                save_path = image_path.parent / f"{stem}ba{suffix}"
            
            new_img.save(save_path, "PNG")
            return True
            
    except Exception as e:
        print(f"Erro ao criar imagem com palavra destacada {image_path}: {e}")
        return False


def _draw_line_with_highlight(draw, line: str, start_x: int, start_y: int, font, highlight_chars: str):
    """
    Draw a line of text with specific characters highlighted in blue/violet.
    
    Args:
        draw: ImageDraw object
        line: Text line to draw
        start_x: Starting X position
        start_y: Y position
        font: Font to use
        highlight_chars: Characters to highlight
    """
    current_x = start_x
    
    for char in line:
        # Check if this character should be highlighted
        if char in highlight_chars:
            color = (138, 43, 226)  # Blue-violet color
        else:
            color = (255, 255, 255)  # White
        
        # Draw the character
        draw.text((current_x, start_y), char, fill=color, font=font)
        
        # Move to next character position
        char_width = draw.textbbox((0, 0), char, font=font)[2]
        current_x += char_width


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
            
            # Resize image to R36S compatible resolution (640x480)
            new_img = resize_image_for_r36s(img)
            width, height = new_img.size
            
            # Draw subtitle
            draw = ImageDraw.Draw(new_img)
            
            # Parse translations to get pinyin and Portuguese
            word_data = parse_pinyin_translations(translations_json) if translations_json else []
            
            # Get font paths
            chinese_font_path = get_chinese_font_path()
            portuguese_font_path = get_portuguese_font_path()
            
            # Font sizes
            chinese_font_size = 32
            pinyin_font_size = 20
            portuguese_font_size = 16
            
            # Load fonts
            chinese_font = None
            pinyin_font = None
            portuguese_font = None
            
            try:
                if chinese_font_path:
                    chinese_font = ImageFont.truetype(str(chinese_font_path), chinese_font_size)
                else:
                    chinese_font = ImageFont.load_default()
                    
                if chinese_font_path:  # Use same font for pinyin
                    pinyin_font = ImageFont.truetype(str(chinese_font_path), pinyin_font_size)
                else:
                    pinyin_font = ImageFont.load_default()
                    
                if portuguese_font_path:
                    portuguese_font = ImageFont.truetype(str(portuguese_font_path), portuguese_font_size)
                else:
                    portuguese_font = ImageFont.load_default()
            except:
                chinese_font = ImageFont.load_default()
                pinyin_font = ImageFont.load_default()
                portuguese_font = ImageFont.load_default()
            
            # Calculate total width needed for all characters
            total_width = 0
            char_widths = []
            
            # Build display text by matching Chinese characters with translations
            chinese_chars = list(chinese_text.replace(' ', '').replace('　', ''))  # Remove spaces
            display_items = []
            
            for char in chinese_chars:
                # Find matching translation data - prioritize exact matches, then partial matches
                pinyin = ""
                portuguese = ""
                
                # First try exact match
                for chinese_word, word_pinyin, word_portuguese in word_data:
                    if char == chinese_word:
                        pinyin = word_pinyin
                        portuguese = word_portuguese
                        break
                
                # If no exact match, try partial match
                if not pinyin:
                    for chinese_word, word_pinyin, word_portuguese in word_data:
                        if char in chinese_word:
                            pinyin = word_pinyin
                            portuguese = word_portuguese
                            break
                
                display_items.append((char, pinyin, portuguese))
                
                # Calculate width needed for this character (max of chinese, pinyin, portuguese)
                char_width = draw.textbbox((0, 0), char, font=chinese_font)[2]
                pinyin_width = draw.textbbox((0, 0), pinyin, font=pinyin_font)[2] if pinyin else 0
                portuguese_width = draw.textbbox((0, 0), portuguese, font=portuguese_font)[2] if portuguese else 0
                
                max_width = max(char_width, pinyin_width, portuguese_width) + 5  # 5px spacing
                char_widths.append(max_width)
                total_width += max_width
            
            # Calculate starting position (center horizontally)
            start_x = (width - total_width) // 2
            
            # Calculate vertical positions
            margin_from_bottom = 60
            chinese_y = height - margin_from_bottom
            pinyin_y = chinese_y - 35  # 35px above Chinese
            portuguese_y = chinese_y + 25  # 25px below Chinese
            
            # Draw each character with its pinyin and translation
            current_x = start_x
            
            for i, (char, pinyin, portuguese) in enumerate(display_items):
                char_max_width = char_widths[i]
                
                # Calculate center position for this character block
                char_width = draw.textbbox((0, 0), char, font=chinese_font)[2]
                char_x = current_x + (char_max_width - char_width) // 2
                
                # Draw Chinese character (white)
                draw.text((char_x, chinese_y), char, fill=(255, 255, 255), font=chinese_font)
                
                # Draw pinyin above (light blue)
                if pinyin:
                    pinyin_width = draw.textbbox((0, 0), pinyin, font=pinyin_font)[2]
                    pinyin_x = current_x + (char_max_width - pinyin_width) // 2
                    draw.text((pinyin_x, pinyin_y), pinyin, fill=(173, 216, 230), font=pinyin_font)
                
                # Draw Portuguese below (yellow)
                if portuguese:
                    portuguese_width = draw.textbbox((0, 0), portuguese, font=portuguese_font)[2]
                    portuguese_x = current_x + (char_max_width - portuguese_width) // 2
                    draw.text((portuguese_x, portuguese_y), portuguese, fill=(255, 255, 0), font=portuguese_font)
                
                current_x += char_max_width
            
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
            
            # Resize image to R36S compatible resolution (640x480)
            new_img = resize_image_for_r36s(img)
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
            
            # Generate output filenames with "a", "b", and "c" suffixes
            output_a = f"{png_file.stem}a{png_file.suffix}"
            output_b = f"{png_file.stem}b{png_file.suffix}"
            output_c = f"{png_file.stem}c{png_file.suffix}"
            
            # Count individual translations for B versions  
            individual_translations = parse_individual_translations(translations_json) if translations_json else []
            b_versions_text = f"{len(individual_translations)}×B" if individual_translations else "B"
            
            print(f"📸 {png_file.name} -> {output_a} + {b_versions_text} + {output_c}")
            print(f"   中文: \"{chinese_text}\"")
            if translations_text:
                print(f"   翻译: {len(individual_translations)} palavras individuais")
            if portuguese_text:
                print(f"   PT: \"{portuguese_text}\"")
            
            if dry_run:
                print("   [DRY RUN]")
                processed_count += 1
            else:
                # Create version A (Chinese subtitle with pinyin above and Portuguese below)
                success_a = add_pinyin_subtitle_to_image(png_file, chinese_text, translations_json)
                
                # Create version C (Chinese + Portuguese above it)
                success_c = add_subtitle_with_portuguese(png_file, chinese_text, portuguese_text)
                
                if success_a and success_c:
                    # Create multiple B versions (ba, bb, bc, etc.) for individual word translations  
                    individual_translations = parse_individual_translations(translations_json) if translations_json else []
                    success_b_versions = []
                    
                    # Get stem and suffix for building filenames
                    stem = png_file.stem
                    suffix = png_file.suffix
                    
                    if individual_translations:
                        # Create one image for each word translation
                        for idx, (chinese_chars, full_translation) in enumerate(individual_translations):
                            # Generate suffix: ba, bb, bc, bd, etc.
                            suffix_letter = chr(ord('a') + idx)  # a, b, c, d, ...
                            output_b_variant = f"{stem}b{suffix_letter}{suffix}"
                            b_variant_path = png_file.parent / output_b_variant
                            
                            # Create highlighted word image
                            success_variant = add_highlighted_word_subtitle(
                                png_file, 
                                chinese_text, 
                                chinese_chars, 
                                full_translation, 
                                b_variant_path
                            )
                            
                            success_b_versions.append(success_variant)
                            
                            if success_variant:
                                print(f"   ✅ Criada versão {output_b_variant} (destaque: {chinese_chars})")
                            else:
                                print(f"   ❌ Erro na versão {output_b_variant}")
                    else:
                        # No individual translations available
                        print("   ⚠️  Nenhuma tradução individual disponível para versões B")
                        success_b_versions = [True]  # Consider it successful to proceed
                    
                    # Check if all B versions were created successfully
                    all_b_success = all(success_b_versions) if success_b_versions else True
                    
                    if all_b_success:
                        # Remove original file after all versions are created successfully
                        try:
                            import os
                            os.unlink(png_file)
                            b_count = len(success_b_versions) if individual_translations else 0
                            print(f"   ✅ Versões A, {b_count}×B e C criadas (original removido)")
                            processed_count += 1
                        except OSError as e:
                            print(f"   ⚠️  Versões criadas, mas erro ao remover original: {e}")
                            processed_count += 1
                    else:
                        print("   ❌ Erro em uma ou mais versões B")
                        error_count += 1
                else:
                    print("   ❌ Erro nas versões A ou C")
                    error_count += 1
        else:
            # No subtitle for this image, but still resize it for R36S compatibility
            print(f"🖼️  {png_file.name} -> redimensionamento R36S (sem legenda)")
            
            if dry_run:
                print("   [DRY RUN] Redimensionamento apenas")
                processed_count += 1
            else:
                # Just resize the image to R36S resolution
                success = resize_image_only(png_file)
                
                if success:
                    print("   ✅ Redimensionada para R36S (640x480)")
                    processed_count += 1
                else:
                    print("   ❌ Erro no redimensionamento")
                    error_count += 1
    
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
     - Redimensiona para R36S (640x480) mantendo aspect ratio
     - Adiciona legendas nas versões A, Ba/Bb/Bc, C

Saída:
  Para 5.png -> 5a.png (中文) + 5ba.png/5bb.png/5bc.png (destaque individual) + 5c.png (中文 + PT)
  Original 5.png é removido após processamento (na pasta destino)
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
    
    print(f"🎬 Subtitle Printer - Legendas Chinesas + Traduções")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print(f"📋 Saída:")
    print(f"    A: Legenda chinesa com pinyin acima e português abaixo de cada palavra")
    print(f"    B: Ba/Bb/Bc... (destaque individual + tradução)")
    print(f"    C: Legenda chinesa + tradução PT (acima)")
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
    print(f"   ├── Com legendas (A+B+C): legendas aplicadas + R36S")
    print(f"   └── Sem legendas: apenas redimensionamento R36S")
    print(f"⏭️  Ignoradas (nomes inválidos): {total_skipped}")
    print(f"❌ Erros: {total_errors}")
    
    if args.dry_run and total_processed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para criar as versões A, B e C")
    
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
