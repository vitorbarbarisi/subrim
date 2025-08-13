#!/usr/bin/env python3
"""
Image Letterbox - Adiciona faixas pretas horizontais nas imagens

Usage: python3 image_letterbox.py <directory_name>
Example: python3 image_letterbox.py test

Este script processa todas as imagens PNG em assets/<directory_name>,
adicionando faixas pretas nas extremidades horizontais (letterboxing)
para ajustar as imagens a um aspect ratio específico.
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

def add_letterbox(image_path: Path, target_aspect_ratio: float, output_path: Path = None) -> bool:
    """
    Adiciona faixas pretas horizontais para ajustar ao aspect ratio desejado.
    
    Args:
        image_path: Caminho da imagem original
        target_aspect_ratio: Aspect ratio alvo (largura/altura)
        output_path: Caminho de saída (se None, sobrescreve a original)
    
    Returns:
        True se processado com sucesso, False caso contrário
    """
    try:
        with Image.open(image_path) as img:
            original_width, original_height = img.size
            original_aspect = original_width / original_height
            
            # Se já está no aspect ratio correto (com tolerância), não faz nada
            if abs(original_aspect - target_aspect_ratio) < 0.01:
                if output_path and output_path != image_path:
                    img.save(output_path, "PNG")
                return True
            
            # Calcula as novas dimensões
            if original_aspect > target_aspect_ratio:
                # Imagem muito larga - adiciona faixas em cima e embaixo
                new_width = original_width
                new_height = int(original_width / target_aspect_ratio)
            else:
                # Imagem muito alta - adiciona faixas nas laterais
                # Para letterboxing horizontal, queremos sempre adicionar nas extremidades horizontais
                # então vamos ajustar a altura mantendo a largura
                new_width = original_width
                new_height = int(original_width / target_aspect_ratio)
            
            # Cria nova imagem com fundo preto
            new_img = Image.new('RGB', (new_width, new_height), (0, 0, 0))
            
            # Calcula posição para centralizar a imagem original
            paste_x = (new_width - original_width) // 2
            paste_y = (new_height - original_height) // 2
            
            # Cola a imagem original no centro
            if img.mode == 'RGBA':
                new_img.paste(img, (paste_x, paste_y), img)
            else:
                new_img.paste(img, (paste_x, paste_y))
            
            # Salva a imagem processada
            save_path = output_path if output_path else image_path
            new_img.save(save_path, "PNG")
            
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False

def process_images(directory: Path, target_aspect_ratio: float, backup: bool = False, dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Processa todas as imagens PNG no diretório.
    
    Returns:
        (processadas_com_sucesso, erros, inalteradas)
    """
    print(f"Processando imagens em: {directory}")
    print(f"Target aspect ratio: {target_aspect_ratio:.3f}")
    
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
                    original_aspect = original_width / original_height
                    
                    if abs(original_aspect - target_aspect_ratio) < 0.01:
                        print("INALTERADA (aspect ratio correto)")
                        unchanged_count += 1
                    else:
                        new_height = int(original_width / target_aspect_ratio)
                        print(f"[DRY RUN] {original_width}x{original_height} → {original_width}x{new_height}")
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
                original_aspect = original_width / original_height
                original_size = (original_width, original_height)
        except Exception:
            pass
        
        success = add_letterbox(file_path, target_aspect_ratio)
        
        if success:
            if original_size:
                try:
                    with Image.open(file_path) as img:
                        new_width, new_height = img.size
                        if (new_width, new_height) == original_size:
                            print("INALTERADA")
                            unchanged_count += 1
                        else:
                            print(f"{original_size[0]}x{original_size[1]} → {new_width}x{new_height}")
                            success_count += 1
                except Exception:
                    print("PROCESSADA")
                    success_count += 1
            else:
                print("PROCESSADA")
                success_count += 1
        else:
            print("ERRO")
            error_count += 1
    
    return success_count, error_count, unchanged_count

def main():
    parser = argparse.ArgumentParser(
        description="Adiciona faixas pretas horizontais nas imagens para ajustar aspect ratio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 image_letterbox.py test                    # Processa assets/test com aspect ratio 4:3
  python3 image_letterbox.py flipper --ratio 16:9    # Aspect ratio 16:9
  python3 image_letterbox.py test --ratio 1.33       # Aspect ratio 1.33 (4:3)
  python3 image_letterbox.py test --dry-run          # Simula processamento
  python3 image_letterbox.py test --backup           # Cria backup antes de processar
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--ratio', '-r', default='4:3',
                       help='Aspect ratio alvo (formato: "16:9", "4:3" ou decimal "1.777"). Padrão: 4:3')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem modificar arquivos')
    
    parser.add_argument('--backup', '-b', action='store_true',
                       help='Criar backup das imagens originais')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Parse aspect ratio
    try:
        if ':' in args.ratio:
            width_str, height_str = args.ratio.split(':')
            target_aspect_ratio = float(width_str) / float(height_str)
        else:
            target_aspect_ratio = float(args.ratio)
    except ValueError:
        print(f"Erro: Aspect ratio inválido '{args.ratio}'. Use formato como '16:9', '4:3' ou '1.777'")
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
    
    print(f"🎬 Image Letterbox")
    print(f"📁 Diretório: {target_dir}")
    print(f"📐 Aspect ratio alvo: {target_aspect_ratio:.3f} ({args.ratio})")
    print(f"💾 Backup: {'Sim' if args.backup else 'Não'}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print("-" * 60)
    
    # Process images
    start_time = time.time()
    success_count, error_count, unchanged_count = process_images(
        target_dir, target_aspect_ratio, args.backup, args.dry_run
    )
    processing_time = time.time() - start_time
    
    # Print results
    total_files = success_count + error_count + unchanged_count
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de arquivos: {total_files}")
    print(f"✅ Processadas com sucesso: {success_count}")
    print(f"📐 Já no aspect ratio correto: {unchanged_count}")
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
