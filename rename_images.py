#!/usr/bin/env python3
"""
Rename Images - Padroniza nomes de imagens com 4 dígitos

Usage: python3 rename_images.py <directory_name>
Example: python3 rename_images.py chaves001

O script renomeia todas as imagens PNG em assets/<directory_name> para seguir o padrão:
- 1.png → 0001.png
- 13.png → 0013.png
- 123.png → 0123.png
- 15a.png → 0015a.png
- 1234b.png → 1234b.png (já tem 4 dígitos)
"""

import sys
import argparse
import re
from pathlib import Path


def parse_filename(filename: str) -> tuple[str, str, str] | None:
    """
    Parse filename to extract number, suffix, and extension.
    
    Args:
        filename: Name of the file (e.g., "123a.png")
        
    Returns:
        Tuple of (number, suffix, extension) or None if not a valid image
        
    Examples:
        "1.png" → ("1", "", ".png")
        "15a.png" → ("15", "a", ".png") 
        "123b.png" → ("123", "b", ".png")
        "1234.png" → ("1234", "", ".png")
    """
    # Pattern to match: number + optional suffix + .png
    pattern = r'^(\d+)([a-zA-Z]*)\.png$'
    match = re.match(pattern, filename)
    
    if not match:
        return None
        
    number = match.group(1)
    suffix = match.group(2)
    extension = ".png"
    
    return (number, suffix, extension)


def format_filename(number: str, suffix: str, extension: str) -> str:
    """
    Format filename with 4-digit zero-padded number.
    
    Args:
        number: The numeric part as string
        suffix: The suffix part (e.g., "a", "b", "c")
        extension: The file extension (e.g., ".png")
        
    Returns:
        Formatted filename with 4-digit padding
        
    Examples:
        ("1", "", ".png") → "0001.png"
        ("15", "a", ".png") → "0015a.png"
        ("123", "b", ".png") → "0123b.png"
        ("1234", "", ".png") → "1234.png" (already 4 digits)
    """
    # Pad number to 4 digits
    padded_number = number.zfill(4)
    return f"{padded_number}{suffix}{extension}"


def rename_images_in_directory(directory: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """
    Rename all PNG images in directory to follow 4-digit naming convention.
    
    Args:
        directory: Directory containing images to rename
        dry_run: If True, simulate operations without actually renaming files
        
    Returns:
        Tuple of (renamed_count, skipped_count, error_count)
    """
    if not directory.exists():
        print(f"❌ Erro: Diretório {directory} não encontrado.")
        return 0, 0, 1
        
    if not directory.is_dir():
        print(f"❌ Erro: {directory} não é um diretório.")
        return 0, 0, 1
    
    # Find all PNG files
    png_files = list(directory.glob("*.png"))
    
    if not png_files:
        print(f"📁 Nenhuma imagem PNG encontrada em {directory}")
        return 0, 0, 0
    
    renamed_count = 0
    skipped_count = 0
    error_count = 0
    
    print(f"🔍 Encontradas {len(png_files)} imagens PNG em {directory.name}")
    print("-" * 60)
    
    for png_file in png_files:
        try:
            # Parse current filename
            parsed = parse_filename(png_file.name)
            
            if not parsed:
                print(f"⚠️  Ignorando {png_file.name} (formato inválido)")
                skipped_count += 1
                continue
                
            number, suffix, extension = parsed
            
            # Generate new filename
            new_filename = format_filename(number, suffix, extension)
            new_path = directory / new_filename
            
            # Check if rename is needed
            if png_file.name == new_filename:
                print(f"✅ {png_file.name} (já no formato correto)")
                skipped_count += 1
                continue
                
            # Check if target file already exists
            if new_path.exists() and new_path != png_file:
                print(f"❌ {png_file.name} → {new_filename} (arquivo destino já existe)")
                error_count += 1
                continue
            
            # Perform rename
            if dry_run:
                print(f"📝 [DRY RUN] {png_file.name} → {new_filename}")
            else:
                png_file.rename(new_path)
                print(f"✅ {png_file.name} → {new_filename}")
                
            renamed_count += 1
            
        except Exception as e:
            print(f"❌ Erro ao processar {png_file.name}: {e}")
            error_count += 1
    
    return renamed_count, skipped_count, error_count


def main():
    parser = argparse.ArgumentParser(
        description="Padroniza nomes de imagens PNG com 4 dígitos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 rename_images.py chaves001              # Renomeia imagens em assets/chaves001/
  python3 rename_images.py test --dry-run         # Simula o processo sem renomear
  python3 rename_images.py flipper --assets-root data  # Usa data/ ao invés de assets/

Padrão de renomeação:
  1.png → 0001.png
  13.png → 0013.png
  123.png → 0123.png
  15a.png → 0015a.png
  1234b.png → 1234b.png (já tem 4 dígitos)
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem renomear arquivos')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Construct full path
    assets_dir = Path(args.assets_root)
    target_dir = assets_dir / args.directory
    
    print(f"🏷️  Rename Images - Padronização de Nomes")
    print(f"📁 Diretório: {target_dir}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'RENOMEAÇÃO REAL'}")
    print(f"📋 Padrão: NNNN[sufixo].png (4 dígitos com zeros à esquerda)")
    print("-" * 60)
    
    # Process directory
    renamed, skipped, errors = rename_images_in_directory(target_dir, args.dry_run)
    
    # Print results
    total_files = renamed + skipped + errors
    print("\n" + "=" * 60)
    print("RENOMEAÇÃO CONCLUÍDA" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de arquivos: {total_files}")
    print(f"✅ Renomeados: {renamed}")
    print(f"⏭️  Ignorados (já corretos): {skipped}")
    print(f"❌ Erros: {errors}")
    
    if args.dry_run and renamed > 0:
        print(f"\n💡 Execute novamente sem --dry-run para renomear {renamed} arquivos")
    
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
