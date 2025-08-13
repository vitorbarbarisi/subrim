#!/usr/bin/env python3
"""
Image Letterbox - Adiciona faixas pretas sobrepostas nas extremidades horizontais

Usage: python3 image_letterbox.py <directory_name> [--height PIXELS]
Example: python3 image_letterbox.py test --height 60

Este script processa todas as imagens PNG em assets/<directory_name>,
adicionando faixas pretas sobrepostas nas extremidades horizontais (topo e base)
como overlay sobre a imagem original, sem alterar suas dimensões.
"""

import sys
import os
from pathlib import Path
from PIL import Image
import argparse
from typing import List, Tuple
import time

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

def add_letterbox(image_path: Path, bar_height: int, output_path: Path = None) -> bool:
    """
    Adiciona faixas pretas horizontais sobrepostas nas extremidades da imagem.
    
    Args:
        image_path: Caminho da imagem original
        bar_height: Altura das faixas pretas em pixels
        output_path: Caminho de saída (se None, sobrescreve a original)
    
    Returns:
        True se processado com sucesso, False caso contrário
    """
    try:
        with Image.open(image_path) as img:
            # Converte para RGB se necessário
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            original_width, original_height = img.size
            
            # Se a altura das faixas é maior que metade da altura da imagem, não faz nada
            if bar_height * 2 >= original_height:
                if output_path and output_path != image_path:
                    img.save(output_path, "PNG")
                return True
            
            # Cria uma cópia da imagem para modificar
            new_img = img.copy()
            
            # Cria retângulos pretos nas extremidades horizontais
            from PIL import ImageDraw
            draw = ImageDraw.Draw(new_img)
            
            # Faixa superior
            draw.rectangle([0, 0, original_width, bar_height], fill=(0, 0, 0))
            
            # Faixa inferior
            draw.rectangle([0, original_height - bar_height, original_width, original_height], fill=(0, 0, 0))
            
            # Salva a imagem processada
            save_path = output_path if output_path else image_path
            new_img.save(save_path, "PNG")
            
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False

def process_images(directory: Path, bar_height: int, backup: bool = False, dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Processa todas as imagens PNG no diretório.
    
    Returns:
        (processadas_com_sucesso, erros, inalteradas)
    """
    print(f"Processando imagens em: {directory}")
    print(f"Altura das faixas pretas: {bar_height} pixels")
    
    png_files = find_png_files(directory)
    if not png_files:
        print("Nenhum arquivo PNG encontrado.")
        return 0, 0, 0
    
    print(f"Encontrados {len(png_files)} arquivos PNG")
    
    success_count = 0
    error_count = 0
    unchanged_count = 0
    
    # Criar diretório de backup se necessário
    backup_dir = None
    if backup and not dry_run:
        backup_dir = directory / "backup_letterbox"
        backup_dir.mkdir(exist_ok=True)
        print(f"Backup será salvo em: {backup_dir}")
    
    print("\nProcessando imagens...")
    for i, file_path in enumerate(png_files, 1):
        print(f"[{i:4d}/{len(png_files)}] {file_path.name}", end=" ... ")
        
        if dry_run:
            # Em modo dry run, apenas simula o processamento
            try:
                with Image.open(file_path) as img:
                    original_width, original_height = img.size
                    
                    if bar_height * 2 >= original_height:
                        print("INALTERADA (faixas muito grandes)")
                        unchanged_count += 1
                    else:
                        print(f"[DRY RUN] Adicionará faixas de {bar_height}px no topo e base")
                        success_count += 1
            except Exception as e:
                print(f"ERRO: {e}")
                error_count += 1
            continue
        
        # Fazer backup se solicitado
        if backup_dir:
            backup_path = backup_dir / file_path.name
            try:
                with Image.open(file_path) as img:
                    img.save(backup_path, "PNG")
            except Exception as e:
                print(f"ERRO no backup: {e}")
                error_count += 1
                continue
        
        # Processar imagem
        original_size = None
        try:
            with Image.open(file_path) as img:
                original_width, original_height = img.size
                original_size = (original_width, original_height)
        except Exception:
            pass
        
        success = add_letterbox(file_path, bar_height)
        
        if success:
            if original_size and bar_height * 2 >= original_size[1]:
                print("INALTERADA (faixas muito grandes)")
                unchanged_count += 1
            else:
                print(f"PROCESSADA (faixas de {bar_height}px)")
                success_count += 1
        else:
            print("ERRO")
            error_count += 1
    
    return success_count, error_count, unchanged_count

def main():
    parser = argparse.ArgumentParser(
        description="Adiciona faixas pretas horizontais sobrepostas nas extremidades das imagens",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 image_letterbox.py test                    # Adiciona faixas de 60px (padrão)
  python3 image_letterbox.py flipper --height 80     # Faixas de 80px
  python3 image_letterbox.py test --height 40        # Faixas de 40px
  python3 image_letterbox.py test --dry-run          # Simula processamento
  python3 image_letterbox.py test --backup           # Cria backup antes de processar
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--height', type=int, default=60,
                       help='Altura das faixas pretas em pixels. Padrão: 60')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem modificar arquivos')
    
    parser.add_argument('--backup', '-b', action='store_true',
                       help='Criar backup das imagens originais')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Validar altura das faixas
    if args.height <= 0:
        print("Erro: A altura das faixas deve ser maior que 0")
        return 1
    
    # Construct full path
    assets_dir = Path(args.assets_root)
    target_dir = assets_dir / args.directory
    
    if not target_dir.exists():
        print(f"Erro: Diretório {target_dir} não encontrado.")
        return 1
    
    if not target_dir.is_dir():
        print(f"Erro: {target_dir} não é um diretório.")
        return 1
    
    print(f"⬛ Image Letterbox - Faixas Pretas")
    print(f"📁 Diretório: {target_dir}")
    print(f"📏 Altura das faixas: {args.height} pixels (topo e base)")
    print(f"💾 Backup: {'Sim' if args.backup else 'Não'}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print("-" * 60)
    
    # Process images
    start_time = time.time()
    success_count, error_count, unchanged_count = process_images(
        target_dir, args.height, args.backup, args.dry_run
    )
    processing_time = time.time() - start_time
    
    # Print results
    total_files = success_count + error_count + unchanged_count
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de arquivos: {total_files}")
    print(f"✅ Processadas com sucesso: {success_count}")
    print(f"⬛ Inalteradas (faixas muito grandes): {unchanged_count}")
    print(f"❌ Erros: {error_count}")
    print(f"⏱️  Tempo de processamento: {processing_time:.2f}s")
    
    if success_count > 0:
        avg_time = processing_time / total_files if total_files > 0 else 0
        print(f"📈 Tempo médio por imagem: {avg_time:.3f}s")
    
    if args.dry_run and success_count > 0:
        print(f"\n💡 Execute novamente sem --dry-run para aplicar as alterações")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
