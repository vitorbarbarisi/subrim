#!/usr/bin/env python3
"""
Subtitle Printer - Adiciona legendas chinesas às imagens

Usage: python3 subtitle_printer.py <directory_name>
Example: python3 subtitle_printer.py chaves001

O script lê as imagens em assets/<directory_name> e o arquivo *_base.txt correspondente.
Para cada imagem, verifica se o nome da imagem (em segundos) corresponde ao timestamp
no arquivo base.txt. Se corresponder, adiciona a legenda chinesa tradicional na imagem.
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


def parse_base_file(base_file_path: Path) -> Dict[int, str]:
    """
    Parse the base.txt file and return a mapping of seconds -> chinese subtitle.
    
    Returns:
        Dict mapping second (as int) to chinese subtitle text
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
                if len(parts) < 3:
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
                
                if chinese_text and chinese_text != 'N/A':
                    subtitles[seconds_int] = chinese_text
                    
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


def get_font_path() -> Optional[Path]:
    """Try to find a suitable font for Chinese characters."""
    # Fonts that support Chinese characters on macOS (in order of preference)
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",  # Best for Chinese
        "/System/Library/Fonts/Hiragino Sans GB.ttc",  # Good for Simplified Chinese
        "/System/Library/Fonts/STSong.ttc",  # Chinese font
        "/System/Library/Fonts/Songti.ttc",  # Traditional Chinese
        "/Library/Fonts/Arial Unicode MS.ttf",  # Fallback with Unicode support
        "/System/Library/Fonts/Apple Symbols.ttf"  # Another Unicode fallback
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            return Path(font_path)
    
    return None


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
            
            # Try to load a font, fallback to default if not found
            font_path = get_font_path()
            
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
            
            # Remove original file if we're creating a new one with "a" suffix
            if not output_path and save_path != image_path:
                import os
                try:
                    os.unlink(image_path)
                except OSError as e:
                    print(f"Aviso: Não foi possível remover {image_path}: {e}")
                    # Continue execution even if deletion fails
            
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
            return int(path.stem)
        except ValueError:
            return float('inf'), path.stem
    
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
            subtitle_text = subtitles[image_index]
            # Generate output filename with "a" suffix
            output_filename = f"{png_file.stem}a{png_file.suffix}"
            print(f"📸 {png_file.name} -> {output_filename} \"{subtitle_text}\"", end="")
            
            if dry_run:
                print(" [DRY RUN]")
                processed_count += 1
            else:
                success = add_subtitle_to_image(png_file, subtitle_text)
                if success:
                    print(" ✅")
                    processed_count += 1
                else:
                    print(" ❌")
                    error_count += 1
        else:
            # No subtitle for this image
            skipped_count += 1
    
    return processed_count, skipped_count, error_count


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona legendas chinesas às imagens baseado no arquivo base.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 subtitle_printer.py chaves001                    # Processa assets/chaves001/
  python3 subtitle_printer.py test --dry-run               # Simula o processamento
  python3 subtitle_printer.py flipper --assets-root data   # Usa data/ ao invés de assets/
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
    
    print(f"🎬 Subtitle Printer - Legendas Chinesas")
    print(f"📁 Diretório: {target_dir}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print("-" * 60)
    
    # Process directory
    processed, skipped, errors = process_directory(target_dir, args.dry_run)
    
    # Print results
    total_files = processed + skipped + errors
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de imagens: {total_files}")
    print(f"✅ Processadas (com legenda): {processed}")
    print(f"⏭️  Ignoradas (sem legenda): {skipped}")
    print(f"❌ Erros: {errors}")
    
    if args.dry_run and processed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para aplicar as alterações")
    
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
