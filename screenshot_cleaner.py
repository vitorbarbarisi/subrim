#!/usr/bin/env python3
"""
Screenshot Cleaner - Remove duplicate or very similar images

Usage: python3 screenshot_cleaner.py <directory_name>
Example: python3 screenshot_cleaner.py test

This script scans the assets/<directory_name> folder for PNG images,
detects duplicates or very similar images using perceptual hashing,
and removes the duplicates keeping only the first occurrence.
"""

import sys
import os
from pathlib import Path
from PIL import Image
import hashlib
import argparse
from typing import List, Tuple, Dict, Set
import time

def calculate_image_hash(image_path: Path) -> str:
    """Calculate a perceptual hash for an image to detect similarity."""
    try:
        with Image.open(image_path) as img:
            # Convert to grayscale and resize to 8x8 for perceptual hashing
            img = img.convert('L').resize((8, 8), Image.Resampling.LANCZOS)
            
            # Get pixel values
            pixels = list(img.getdata())
            
            # Calculate average
            avg = sum(pixels) / len(pixels)
            
            # Create hash based on whether each pixel is above/below average
            hash_bits = ''.join('1' if pixel >= avg else '0' for pixel in pixels)
            
            # Convert to hex for easier handling
            return format(int(hash_bits, 2), '016x')
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return None

def calculate_file_hash(image_path: Path) -> str:
    """Calculate MD5 hash of the file for exact duplicate detection."""
    try:
        with open(image_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        print(f"Erro ao calcular hash do arquivo {image_path}: {e}")
        return None

def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculate Hamming distance between two hash strings."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return float('inf')
    
    return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

def find_png_files(directory: Path) -> List[Path]:
    """Find all PNG files in the directory, sorted numerically."""
    png_files = []
    
    for file_path in directory.glob("*.png"):
        png_files.append(file_path)
    
    # Sort numerically by filename (extract number from filename)
    def sort_key(path):
        try:
            return int(path.stem)
        except ValueError:
            return float('inf'), path.stem
    
    return sorted(png_files, key=sort_key)

def analyze_images(directory: Path, similarity_threshold: int = 5) -> Tuple[List[Path], List[Path], Dict]:
    """
    Analyze images for duplicates and similar images.
    
    Returns:
        - List of files to keep
        - List of files to remove
        - Dictionary with analysis info
    """
    print(f"Analisando imagens em: {directory}")
    
    png_files = find_png_files(directory)
    if not png_files:
        print("Nenhum arquivo PNG encontrado.")
        return [], [], {}
    
    print(f"Encontrados {len(png_files)} arquivos PNG")
    
    # Calculate hashes for all images
    file_hashes = {}  # MD5 hash -> first file with this hash
    perceptual_hashes = {}  # perceptual hash -> first file with this hash
    
    files_to_keep = []
    files_to_remove = []
    analysis_info = {
        'total_files': len(png_files),
        'exact_duplicates': 0,
        'similar_images': 0,
        'errors': 0
    }
    
    print("\nCalculando hashes...")
    for i, file_path in enumerate(png_files, 1):
        print(f"Processando {i}/{len(png_files)}: {file_path.name}", end=" ... ")
        
        # Calculate file hash (for exact duplicates)
        file_hash = calculate_file_hash(file_path)
        if not file_hash:
            analysis_info['errors'] += 1
            print("ERRO")
            continue
            
        # Check for exact duplicate
        if file_hash in file_hashes:
            files_to_remove.append(file_path)
            analysis_info['exact_duplicates'] += 1
            print(f"DUPLICATA EXATA de {file_hashes[file_hash].name}")
            continue
        
        # Calculate perceptual hash (for similar images)
        perceptual_hash = calculate_image_hash(file_path)
        if not perceptual_hash:
            analysis_info['errors'] += 1
            print("ERRO")
            continue
        
        # Check for similar images
        is_similar = False
        for existing_hash, existing_file in perceptual_hashes.items():
            distance = hamming_distance(perceptual_hash, existing_hash)
            if distance <= similarity_threshold:
                files_to_remove.append(file_path)
                analysis_info['similar_images'] += 1
                print(f"SIMILAR a {existing_file.name} (distância: {distance})")
                is_similar = True
                break
        
        if not is_similar:
            # Keep this file - it's unique
            file_hashes[file_hash] = file_path
            perceptual_hashes[perceptual_hash] = file_path
            files_to_keep.append(file_path)
            print("ÚNICO")
    
    return files_to_keep, files_to_remove, analysis_info

def remove_files(files_to_remove: List[Path], dry_run: bool = False) -> int:
    """Remove the specified files. Returns number of files actually removed."""
    if not files_to_remove:
        return 0
    
    removed_count = 0
    
    for file_path in files_to_remove:
        try:
            if dry_run:
                print(f"[DRY RUN] Removeria: {file_path.name}")
            else:
                file_path.unlink()
                print(f"Removido: {file_path.name}")
            removed_count += 1
        except Exception as e:
            print(f"Erro ao remover {file_path.name}: {e}")
    
    return removed_count

def main():
    parser = argparse.ArgumentParser(
        description="Remove imagens duplicadas ou muito similares",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 screenshot_cleaner.py test           # Limpa assets/test
  python3 screenshot_cleaner.py flipper        # Limpa assets/flipper
  python3 screenshot_cleaner.py test --dry-run # Simula limpeza sem remover arquivos
  python3 screenshot_cleaner.py test -t 3      # Threshold mais restritivo (menos tolerante)
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem remover arquivos')
    
    parser.add_argument('--threshold', '-t', type=int, default=5,
                       help='Threshold de similaridade (0=idêntico, 10=muito similar). Padrão: 5')
    
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
    
    print(f"Screenshot Cleaner")
    print(f"Diretório: {target_dir}")
    print(f"Threshold de similaridade: {args.threshold}")
    print(f"Modo: {'DRY RUN (simulação)' if args.dry_run else 'REMOÇÃO REAL'}")
    print("-" * 50)
    
    # Analyze images
    start_time = time.time()
    files_to_keep, files_to_remove, analysis_info = analyze_images(target_dir, args.threshold)
    analysis_time = time.time() - start_time
    
    # Print analysis results
    print("\n" + "=" * 50)
    print("ANÁLISE COMPLETA")
    print("=" * 50)
    print(f"Total de arquivos analisados: {analysis_info['total_files']}")
    print(f"Arquivos únicos (manter): {len(files_to_keep)}")
    print(f"Duplicatas exatas: {analysis_info['exact_duplicates']}")
    print(f"Imagens similares: {analysis_info['similar_images']}")
    print(f"Erros de processamento: {analysis_info['errors']}")
    print(f"Total a remover: {len(files_to_remove)}")
    print(f"Tempo de análise: {analysis_time:.2f}s")
    
    if not files_to_remove:
        print("\n✅ Nenhuma imagem duplicada ou similar encontrada!")
        return 0
    
    # Show files to be removed
    print(f"\n📋 ARQUIVOS A SEREM REMOVIDOS ({len(files_to_remove)}):")
    for file_path in sorted(files_to_remove):
        file_size = file_path.stat().st_size / 1024  # KB
        print(f"  - {file_path.name} ({file_size:.1f} KB)")
    
    # Calculate space savings
    total_size = sum(f.stat().st_size for f in files_to_remove) / (1024 * 1024)  # MB
    print(f"\n💾 Espaço a ser liberado: {total_size:.2f} MB")
    
    # Confirm action if not dry run
    if not args.dry_run:
        print(f"\n⚠️  ATENÇÃO: Esta operação irá DELETAR {len(files_to_remove)} arquivos permanentemente!")
        confirm = input("Deseja continuar? (digite 'sim' para confirmar): ").strip().lower()
        if confirm != 'sim':
            print("❌ Operação cancelada pelo usuário.")
            return 0
    
    # Remove files
    print(f"\n🗑️  {'SIMULANDO REMOÇÃO' if args.dry_run else 'REMOVENDO ARQUIVOS'}...")
    removed_count = remove_files(files_to_remove, args.dry_run)
    
    print(f"\n✅ {'Simulação concluída' if args.dry_run else 'Limpeza concluída'}!")
    print(f"📊 Arquivos {'que seriam removidos' if args.dry_run else 'removidos'}: {removed_count}")
    
    if not args.dry_run and removed_count > 0:
        print(f"💾 Espaço liberado: {total_size:.2f} MB")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
