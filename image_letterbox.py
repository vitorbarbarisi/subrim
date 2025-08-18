#!/usr/bin/env python3
"""
Image Shift + Letterbox - Desloca imagens para cima e adiciona faixas pretas

Usage: python3 image_letterbox.py <directory_name> [--shift PIXELS] [--bars PIXELS]
Example: python3 image_letterbox.py test --shift 50 --bars 30

Este script processa todas as imagens PNG em assets/<directory_name>,
realizando duas operações:
1. Desloca a imagem para cima (--shift)
2. Adiciona faixas pretas no topo e base (--bars)
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

def add_letterbox(image_path: Path, shift_up: int, bar_height: int, output_path: Path = None) -> bool:
    """
    Desloca a imagem para cima, preenche a área inferior com preto e adiciona faixas pretas no topo e base.
    
    Args:
        image_path: Caminho da imagem original
        shift_up: Quantidade de pixels para deslocar a imagem para cima
        bar_height: Altura das faixas pretas no topo e base em pixels
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
            
            # Se o deslocamento é maior que a altura da imagem, não faz nada
            if shift_up >= original_height:
                if output_path and output_path != image_path:
                    img.save(output_path, "PNG")
                return True
            
            # Cria nova imagem com fundo preto
            new_img = Image.new('RGB', (original_width, original_height), (0, 0, 0))
            
            # Cola a imagem original deslocada para cima
            # A imagem será cortada na parte superior se necessário
            paste_y = -shift_up  # Posição negativa para deslocar para cima
            new_img.paste(img, (0, paste_y))
            
            # Adiciona faixas pretas no topo e base usando PIL ImageDraw
            from PIL import ImageDraw
            draw = ImageDraw.Draw(new_img)
            
            # Calcula alturas das faixas (inferior é 180px maior que superior)
            top_bar_height = bar_height
            bottom_bar_height = bar_height + 180
            
            # Faixa preta superior
            if top_bar_height > 0:
                draw.rectangle([0, 0, original_width, top_bar_height], fill=(0, 0, 0))
            
            # Faixa preta inferior
            if bottom_bar_height > 0:
                draw.rectangle([0, original_height - bottom_bar_height, original_width, original_height], fill=(0, 0, 0))
            
            # Salva a imagem processada
            save_path = output_path if output_path else image_path
            new_img.save(save_path, "PNG")
            
            return True
            
    except Exception as e:
        print(f"Erro ao processar {image_path}: {e}")
        return False

def process_images(directory: Path, shift_up: int, bar_height: int, backup: bool = False, dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Processa todas as imagens PNG no diretório.
    
    Returns:
        (processadas_com_sucesso, erros, inalteradas)
    """
    print(f"Processando imagens em: {directory}")
    print(f"Deslocamento para cima: {shift_up} pixels")
    print(f"Faixas pretas: {bar_height}px (topo) / {bar_height + 180}px (base)")
    
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
                    
                    if shift_up >= original_height:
                        print("INALTERADA (deslocamento muito grande)")
                        unchanged_count += 1
                    elif shift_up == 0 and bar_height == 0:
                        print("INALTERADA (sem alterações)")
                        unchanged_count += 1
                    else:
                        operations = []
                        if shift_up > 0:
                            operations.append(f"shift {shift_up}px")
                        if bar_height > 0:
                            operations.append(f"faixas {bar_height}px(topo)/{bar_height + 180}px(base)")
                        print(f"[DRY RUN] {', '.join(operations)}")
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
        
        success = add_letterbox(file_path, shift_up, bar_height)
        
        if success:
            if original_size and shift_up >= original_size[1]:
                print("INALTERADA (deslocamento muito grande)")
                unchanged_count += 1
            elif shift_up == 0 and bar_height == 0:
                print("INALTERADA (sem alterações)")
                unchanged_count += 1
            else:
                operations = []
                if shift_up > 0:
                    operations.append(f"shift {shift_up}px")
                if bar_height > 0:
                    operations.append(f"faixas {bar_height}px(topo)/{bar_height + 180}px(base)")
                print(f"PROCESSADA ({', '.join(operations)})")
                success_count += 1
        else:
            print("ERRO")
            error_count += 1
    
    return success_count, error_count, unchanged_count

def main():
    parser = argparse.ArgumentParser(
        description="Desloca imagens para cima e adiciona faixas pretas no topo e base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 image_letterbox.py test                              # Shift 50px + faixas 50px/230px (padrão)
  python3 image_letterbox.py flipper --shift 80 --bars 40      # Shift 80px + faixas 40px/220px
  python3 image_letterbox.py test --shift 30 --bars 0          # Apenas shift 30px
  python3 image_letterbox.py test --shift 0 --bars 30          # Apenas faixas 30px/210px
  python3 image_letterbox.py test --dry-run                    # Simula processamento
  python3 image_letterbox.py test --backup                     # Cria backup antes de processar
        """
    )
    
    parser.add_argument('directory', 
                       help='Nome do diretório dentro de assets/ para processar')
    
    parser.add_argument('--shift', type=int, default=50,
                       help='Quantidade de pixels para deslocar a imagem para cima. Padrão: 50')
    
    parser.add_argument('--bars', type=int, default=50,
                       help='Altura da faixa preta superior em pixels (base será +180px). Padrão: 50')
    
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Simular operação sem modificar arquivos')
    
    parser.add_argument('--backup', '-b', action='store_true',
                       help='Criar backup das imagens originais')
    
    parser.add_argument('--assets-root', default='assets',
                       help='Diretório raiz dos assets. Padrão: assets')
    
    args = parser.parse_args()
    
    # Validar parâmetros
    if args.shift < 0:
        print("Erro: O deslocamento deve ser maior ou igual a 0")
        return 1
    
    if args.bars < 0:
        print("Erro: A altura das faixas deve ser maior ou igual a 0")
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
    
    print(f"⬆️⬛ Image Shift + Letterbox - Duplo Processamento")
    print(f"📁 Diretório: {target_dir}")
    print(f"📏 Deslocamento para cima: {args.shift} pixels")
    print(f"⬛ Faixas pretas: {args.bars}px (topo) / {args.bars + 180}px (base)")
    print(f"💾 Backup: {'Sim' if args.backup else 'Não'}")
    print(f"🔍 Modo: {'DRY RUN (simulação)' if args.dry_run else 'PROCESSAMENTO REAL'}")
    print("-" * 60)
    
    # Process images
    start_time = time.time()
    success_count, error_count, unchanged_count = process_images(
        target_dir, args.shift, args.bars, args.backup, args.dry_run
    )
    processing_time = time.time() - start_time
    
    # Print results
    total_files = success_count + error_count + unchanged_count
    print("\n" + "=" * 60)
    print("PROCESSAMENTO CONCLUÍDO" if not args.dry_run else "SIMULAÇÃO CONCLUÍDA")
    print("=" * 60)
    print(f"📊 Total de arquivos: {total_files}")
    print(f"✅ Processadas com sucesso: {success_count}")
    print(f"⬆️⬛ Inalteradas (sem alterações): {unchanged_count}")
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
