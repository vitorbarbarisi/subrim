#!/usr/bin/env python3
"""
Subtitle Printer - Adiciona legendas chinesas e traduções às imagens

Usage: python3 subtitle_printer.py <directory_name>
Example: python3 subtitle_printer.py chaves001

O script lê as imagens em assets/<directory_name> e o arquivo *_base.txt correspondente.
Para cada imagem, verifica se o nome da imagem (em segundos) corresponde ao timestamp
no arquivo base.txt. Se corresponder:
1. Redimensiona a imagem para resolução R36S (640x480) mantendo aspect ratio
2. Cria três versões com legendas:

- Versão A (sufixo 'a'): Legenda chinesa na parte inferior
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


def parse_base_file(base_file_path: Path) -> Dict[int, Tuple[str, str, str]]:
    """
    Parse the base.txt file and return a mapping of seconds -> (chinese subtitle, translations, portuguese).
    
    Returns:
        Dict mapping second (as int) to tuple of (chinese_text, translations_text, portuguese_text)
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
                
                # Extract timestamp (second column)
                timestamp_str = parts[1].strip()
                
                # Extract seconds from timestamp (e.g., "186.645s" -> 186.645)
                match = re.match(r'([\d.]+)s?', timestamp_str)
                if not match:
                    continue
                
                seconds_float = float(match.group(1))
                seconds_int = int(round(seconds_float))
                
                # Extract Chinese subtitle (third column)
                chinese_text = parts[2].strip()
                
                # Remove parentheses if present
                chinese_text = re.sub(r'^（(.*)）$', r'\1', chinese_text)
                
                # Extract translations (fourth column)
                translations_text = parts[3].strip()
                
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
                
                # Extract Portuguese translation (fifth column)
                portuguese_text = ""
                if len(parts) >= 5:
                    portuguese_text = parts[4].strip()
                    if portuguese_text == 'N/A':
                        portuguese_text = ""
                
                if chinese_text and chinese_text != 'N/A':
                    subtitles[seconds_int] = (chinese_text, formatted_translations, portuguese_text)
                    
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
            # Extract number from filename (e.g., "0001.png" -> 1)
            return (0, int(path.stem))
        except ValueError:
            return (1, path.stem)
    
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
            image_index = int(png_file.stem)
        except ValueError:
            print(f"⚠️  Ignorando {png_file.name} (nome inválido)")
            skipped_count += 1
            continue
        
        # Check if we have a subtitle for this time (image name represents seconds)
        if image_index in subtitles:
            chinese_text, translations_text, portuguese_text = subtitles[image_index]
            
            # Generate output filenames with "a", "b", and "c" suffixes
            output_a = f"{png_file.stem}a{png_file.suffix}"
            output_b = f"{png_file.stem}b{png_file.suffix}"
            output_c = f"{png_file.stem}c{png_file.suffix}"
            
            print(f"📸 {png_file.name} -> {output_a} + {output_b} + {output_c}")
            print(f"   中文: \"{chinese_text}\"")
            if translations_text:
                print(f"   翻译: {len(translations_text.split())} words")
            if portuguese_text:
                print(f"   PT: \"{portuguese_text}\"")
            
            if dry_run:
                print("   [DRY RUN]")
                processed_count += 1
            else:
                # Create version A (Chinese subtitle at bottom)
                success_a = add_subtitle_to_image(png_file, chinese_text)
                
                # Create version C (Chinese + Portuguese above it)
                success_c = add_subtitle_with_portuguese(png_file, chinese_text, portuguese_text)
                
                if success_a and success_c:
                    # Create version B (copy A + add translations at top)
                    a_path = png_file.parent / output_a
                    b_path = png_file.parent / output_b
                    
                    if translations_text:
                        success_b = add_top_translations(a_path, translations_text, b_path)
                    else:
                        # If no translations, just copy A to B
                        try:
                            shutil.copy2(a_path, b_path)
                            success_b = True
                        except Exception as e:
                            print(f"   ❌ Erro ao copiar para versão B: {e}")
                            success_b = False
                    
                    if success_b:
                        # Remove original file after all versions are created successfully
                        try:
                            import os
                            os.unlink(png_file)
                            print("   ✅ Versões A, B e C criadas (original removido)")
                            processed_count += 1
                        except OSError as e:
                            print(f"   ⚠️  Versões A, B e C criadas, mas erro ao remover original: {e}")
                            processed_count += 1
                    else:
                        print("   ❌ Erro na versão B")
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


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona legendas chinesas e traduções às imagens baseado no arquivo base.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 subtitle_printer.py chaves001                    # Copia para assets/chaves001_sub/ e processa
  python3 subtitle_printer.py test --dry-run               # Simula o processamento
  python3 subtitle_printer.py flipper --assets-root data   # Usa data/ ao invés de assets/

Funcionamento:
  1. Cria pasta destino com sufixo "_sub" (ex: test -> test_sub)
  2. Copia apenas imagens PNG da pasta origem para a pasta destino
  3. Busca o arquivo *_base.txt na pasta origem
  4. Processa as imagens na pasta destino:
     - Redimensiona para R36S (640x480) mantendo aspect ratio
     - Adiciona legendas nas três versões

Saída:
  Para 5.png -> 5a.png (中文) + 5b.png (中文 + 翻译) + 5c.png (中文 + PT)
  Original 5.png é removido após processamento (na pasta destino)
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem modificar arquivos')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Construct full paths
    assets_dir = Path(args.assets_root)
    source_dir = assets_dir / args.directory
    dest_dir = assets_dir / f"{args.directory}_sub"
    
    if not source_dir.exists():
        print(f"Erro: Diretório origem {source_dir} não encontrado.")
        return 1
    
    if not source_dir.is_dir():
        print(f"Erro: {source_dir} não é um diretório.")
        return 1
    
    print(f"🎬 Subtitle Printer - Legendas Chinesas + Traduções")
    print(f"📁 Origem: {source_dir}")
    print(f"📁 Destino: {dest_dir}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print(f"📋 Saída:")
    print(f"    A: Legenda chinesa (base)")
    print(f"    B: A + traduções detalhadas (topo)")
    print(f"    C: Legenda chinesa + tradução PT (acima)")
    print("-" * 60)
    
    # Copy images to destination directory
    if not args.dry_run:
        print(f"📋 Copiando imagens PNG de {source_dir.name} para {dest_dir.name}...")
        copied_count = copy_images_to_destination(source_dir, dest_dir)
        print(f"✅ {copied_count} imagens copiadas")
        print("-" * 60)
    else:
        print(f"📋 [DRY RUN] Simulando cópia de imagens de {source_dir.name} para {dest_dir.name}")
        png_files = list(source_dir.glob("*.png"))
        print(f"✅ [DRY RUN] {len(png_files)} imagens seriam copiadas")
        print("-" * 60)
    
    # Process directory (work on destination, but read base.txt from source)
    if args.dry_run:
        # For dry run, simulate processing with source directory since dest might not exist yet
        processed, skipped, errors = process_directory(source_dir, args.dry_run, source_directory=source_dir)
    else:
        # For real processing, work on destination directory
        processed, skipped, errors = process_directory(dest_dir, args.dry_run, source_directory=source_dir)
    
    # Print results
    total_files = processed + skipped + errors
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de imagens: {total_files}")
    print(f"✅ Processadas: {processed}")
    print(f"   ├── Com legendas (A+B+C): legendas aplicadas + R36S")
    print(f"   └── Sem legendas: apenas redimensionamento R36S")
    print(f"⏭️  Ignoradas (nomes inválidos): {skipped}")
    print(f"❌ Erros: {errors}")
    
    if args.dry_run and processed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para criar as versões A, B e C")
    
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
