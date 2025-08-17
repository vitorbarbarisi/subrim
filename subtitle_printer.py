#!/usr/bin/env python3
"""
Subtitle Printer - Adiciona legendas chinesas e traduções às imagens

Usage: python3 subtitle_printer.py <directory_name>
Example: python3 subtitle_printer.py chaves001

O script lê as imagens em assets/<directory_name> e o arquivo *_base.txt correspondente.
Para cada imagem, verifica se o nome da imagem (em segundos) corresponde ao timestamp
no arquivo base.txt. Se corresponder, cria três versões:

- Versão A (sufixo 'a'): Legenda chinesa na parte inferior
- Versão B (sufixo 'b'): Versão A + traduções detalhadas na parte superior
- Versão C (sufixo 'c'): Legenda chinesa + tradução portuguesa acima

O arquivo original é removido após criar as versões A, B e C.
"""

import sys
import argparse
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
            
            width, height = img.size
            
            # Keep original image size - no resizing
            new_img = img.copy()
            
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
            
            width, height = img.size
            
            # Keep original image size - no resizing
            new_img = img.copy()
            
            # Draw subtitles
            draw = ImageDraw.Draw(new_img)
            
            # Get specific fonts for each language
            chinese_font_path = get_chinese_font_path()
            portuguese_font_path = get_portuguese_font_path()
            
            # Calculate available height for both texts (bottom 25% of image)
            margin_from_bottom = 50
            available_height = int(height * 0.25)
            available_width = width - 40  # 20px padding on each side
            
            # Start with font sizes
            chinese_font_size = min(48, int(available_height * 0.4))
            portuguese_font_size = min(32, int(available_height * 0.3))
            
            # Load fonts and adjust sizes
            chinese_font = None
            portuguese_font = None
            chinese_text_height = 0
            portuguese_text_height = 0
            
            # Adjust Chinese font size
            for attempt in range(10):
                try:
                    if chinese_font_path:
                        chinese_font = ImageFont.truetype(str(chinese_font_path), chinese_font_size)
                    else:
                        chinese_font = ImageFont.load_default()
                    
                    bbox = draw.textbbox((0, 0), chinese_text, font=chinese_font)
                    text_width = bbox[2] - bbox[0]
                    chinese_text_height = bbox[3] - bbox[1]
                    
                    if text_width <= available_width:
                        break
                    
                    chinese_font_size = int(chinese_font_size * 0.9)
                    if chinese_font_size < 12:
                        break
                        
                except:
                    chinese_font = ImageFont.load_default()
                    bbox = draw.textbbox((0, 0), chinese_text, font=chinese_font)
                    chinese_text_height = bbox[3] - bbox[1]
                    break
            
            # Adjust Portuguese font size (always calculate, use N/A if text is empty)
            display_portuguese = portuguese_text if portuguese_text else "N/A"
            
            for attempt in range(10):
                try:
                    if portuguese_font_path:
                        portuguese_font = ImageFont.truetype(str(portuguese_font_path), portuguese_font_size)
                    else:
                        portuguese_font = ImageFont.load_default()
                    
                    bbox = draw.textbbox((0, 0), display_portuguese, font=portuguese_font)
                    text_width = bbox[2] - bbox[0]
                    portuguese_text_height = bbox[3] - bbox[1]
                    
                    if text_width <= available_width:
                        break
                    
                    portuguese_font_size = int(portuguese_font_size * 0.9)
                    if portuguese_font_size < 10:
                        break
                        
                except Exception as e:
                    portuguese_font = ImageFont.load_default()
                    bbox = draw.textbbox((0, 0), display_portuguese, font=portuguese_font)
                    portuguese_text_height = bbox[3] - bbox[1]
                    break
            
            # Position Chinese text at bottom
            chinese_bbox = draw.textbbox((0, 0), chinese_text, font=chinese_font)
            chinese_width = chinese_bbox[2] - chinese_bbox[0]
            chinese_x = (width - chinese_width) // 2
            chinese_y = height - margin_from_bottom - chinese_text_height
            
            # Position Portuguese text above Chinese (always show, use N/A if empty)
            if portuguese_font:
                # Recalculate for display text
                portuguese_bbox = draw.textbbox((0, 0), display_portuguese, font=portuguese_font)
                portuguese_width = portuguese_bbox[2] - portuguese_bbox[0]
                portuguese_x = (width - portuguese_width) // 2
                portuguese_y = chinese_y - portuguese_text_height - 10  # 10px gap
                
                # Draw Portuguese text in yellow (or N/A)
                draw.text((portuguese_x, portuguese_y), display_portuguese, fill=(255, 255, 0), font=portuguese_font)
            
            # Draw Chinese text in white
            draw.text((chinese_x, chinese_y), chinese_text, fill=(255, 255, 255), font=chinese_font)
            
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
            
            width, height = img.size
            
            # Keep original image size - no resizing
            new_img = img.copy()
            
            # Draw subtitle
            draw = ImageDraw.Draw(new_img)
            
            # Try to load a Chinese font specifically
            font_path = get_chinese_font_path()
            
            # Calculate available height for subtitle (50px from bottom)
            margin_from_bottom = 50
            available_height = margin_from_bottom
            
            # Start with a reasonable font size that should fit in available space
            max_font_size = min(48, int(available_height * 0.8))
            font_size = max_font_size
            
            # Load font and adjust size to fit width
            font = None
            text_width = 0
            text_height = 0
            
            # Calculate available width (with 20px padding on each side)
            available_width = width - 40
            
            for attempt in range(10):  # Try up to 10 different sizes
                try:
                    if font_path:
                        font = ImageFont.truetype(str(font_path), font_size)
                    else:
                        font = ImageFont.load_default()
                    
                    # Get text dimensions
                    bbox = draw.textbbox((0, 0), subtitle_text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    # If text fits within available width, we're good
                    if text_width <= available_width:
                        break
                    
                    # Otherwise, reduce font size by 10% and try again
                    font_size = int(font_size * 0.9)
                    if font_size < 12:  # Minimum readable size
                        break
                        
                except:
                    font = ImageFont.load_default()
                    bbox = draw.textbbox((0, 0), subtitle_text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    break
            
            # Center text horizontally, position 50px above bottom of image
            text_x = (width - text_width) // 2
            
            # Position text 50px above the bottom of the image
            margin_from_bottom = 50
            text_y = height - margin_from_bottom - text_height
            
            # Draw text with white color
            draw.text((text_x, text_y), subtitle_text, fill=(255, 255, 255), font=font)
            
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


def process_directory(directory: Path, dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Process all PNG images in the directory and add subtitles where applicable.
    
    Returns:
        (processed_count, skipped_count, error_count)
    """
    # Find base file
    base_file = find_base_file(directory)
    if not base_file:
        print(f"Erro: Nenhum arquivo *_base.txt encontrado em {directory}")
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
                        import shutil
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
            # No subtitle for this image
            skipped_count += 1
    
    return processed_count, skipped_count, error_count


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona legendas chinesas e traduções às imagens baseado no arquivo base.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 subtitle_printer.py chaves001                    # Cria versões A, B e C em assets/chaves001/
  python3 subtitle_printer.py test --dry-run               # Simula o processamento
  python3 subtitle_printer.py flipper --assets-root data   # Usa data/ ao invés de assets/

Saída:
  Para 5.png -> 5a.png (中文) + 5b.png (中文 + 翻译) + 5c.png (中文 + PT)
  Original 5.png é removido após processamento
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem modificar arquivos')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Construct full path
    assets_dir = Path(args.assets_root)
    target_dir = assets_dir / args.directory
    
    if not target_dir.exists():
        print(f"Erro: Diretório {target_dir} não encontrado.")
        return 1
    
    if not target_dir.is_dir():
        print(f"Erro: {target_dir} não é um diretório.")
        return 1
    
    print(f"🎬 Subtitle Printer - Legendas Chinesas + Traduções")
    print(f"📁 Diretório: {target_dir}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print(f"📋 Saída:")
    print(f"    A: Legenda chinesa (base)")
    print(f"    B: A + traduções detalhadas (topo)")
    print(f"    C: Legenda chinesa + tradução PT (acima)")
    print("-" * 60)
    
    # Process directory
    processed, skipped, errors = process_directory(target_dir, args.dry_run)
    
    # Print results
    total_files = processed + skipped + errors
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de imagens: {total_files}")
    print(f"✅ Processadas (versões A+B+C criadas): {processed}")
    print(f"⏭️  Ignoradas (sem legenda): {skipped}")
    print(f"❌ Erros: {errors}")
    
    if args.dry_run and processed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para criar as versões A, B e C")
    
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
