#!/usr/bin/env python3
"""
Simple periodic screenshoter for macOS

Takes a screenshot every second for up to 1 hour (3600 screenshots max).
Saves images in their original resolution without any resizing.

Usage:
  python3 screenshoter.py <directory_name>
  
Example:
  python3 screenshoter.py test       # Saves to assets/test/
  python3 screenshoter.py flipper    # Saves to assets/flipper/
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path





def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tira screenshots a cada segundo por até 1 hora",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 screenshoter.py test       # Salva em assets/test/
  python3 screenshoter.py flipper    # Salva em assets/flipper/
        """
    )
    
    parser.add_argument(
        "directory", 
        help="Nome do diretório dentro de assets/ onde salvar as imagens"
    )
    

    

    
    parser.add_argument(
        "--max-duration", 
        type=int, 
        default=3600,
        help="Duração máxima em segundos - 1h = 3600s. Padrão: 3600"
    )
    
    parser.add_argument(
        "--assets-root", 
        default="assets",
        help="Diretório raiz dos assets. Padrão: assets"
    )
    
    return parser.parse_args()


def countdown(seconds: int) -> None:
    """Display a countdown timer."""
    for i in range(seconds, 0, -1):
        print(f"Iniciando em {i} segundos...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 30, end="\r")  # Clear the line
    print("🚀 Iniciando capturas!")


def take_screenshot() -> bytes | None:
    """Take a screenshot using macOS screencapture and return raw image data."""
    import tempfile
    import os
    
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_path = temp_file.name
        
        # Take screenshot to file
        result = subprocess.run(
            ["screencapture", "-x", "-t", "png", temp_path],
            capture_output=True,
            check=True,
            timeout=10
        )
        
        # Read file content
        with open(temp_path, 'rb') as f:
            image_data = f.read()
        
        # Clean up temporary file
        os.unlink(temp_path)
        
        return image_data
        
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        print(f"Erro ao capturar tela: {e}")
        # Clean up temp file if it exists
        try:
            if 'temp_path' in locals():
                os.unlink(temp_path)
        except:
            pass
        return None





def find_next_index(output_dir: Path) -> int:
    """Find the next index to continue from by looking at existing PNG files."""
    if not output_dir.exists():
        return 1
    
    max_index = 0
    for png_file in output_dir.glob("*.png"):
        try:
            index = int(png_file.stem)
            max_index = max(max_index, index)
        except ValueError:
            continue
    
    # Continue from the last index + 1
    return max_index + 1


def find_max_duration_from_base(output_dir: Path) -> int | None:
    """Extract the maximum duration from the corresponding base.txt file."""
    # Look for a base.txt file in the same directory
    base_files = list(output_dir.glob("*_base.txt"))
    if not base_files:
        return None
    
    # Use the first base file found
    base_file = base_files[0]
    
    try:
        content = base_file.read_text(encoding="utf-8").strip()
        if not content:
            return None
        
        lines = content.split('\n')
        last_line = lines[-1].strip()
        
        if not last_line:
            return None
        
        # Parse the timestamp from the second column (format: "334.125s")
        parts = last_line.split('\t')
        if len(parts) >= 2:
            timestamp_str = parts[1].strip()
            if timestamp_str.endswith('s'):
                timestamp_seconds = float(timestamp_str[:-1])
                # Add a small buffer (30 seconds) to ensure we capture everything
                return int(timestamp_seconds) + 30
    
    except Exception as e:
        print(f"Aviso: Erro ao ler arquivo base {base_file}: {e}")
    
    return None


def main() -> int:
    args = parse_args()
    
    # Setup output directory
    assets_dir = Path(args.assets_root)
    output_dir = assets_dir / args.directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find starting index
    start_index = find_next_index(output_dir)
    
    # Check for existing images
    existing_pngs = list(output_dir.glob("*.png"))
    last_index = start_index - 1 if start_index > 1 else 0
    
    # Configuration - screenshots will use original resolution
    
    # Try to get duration from base file, fallback to command line argument
    auto_duration = find_max_duration_from_base(output_dir)
    if auto_duration is not None:
        max_screenshots = auto_duration
        duration_source = f"arquivo base ({auto_duration}s)"
    else:
        max_screenshots = args.max_duration
        duration_source = f"padrão ({args.max_duration}s)"
    
    end_index = start_index + max_screenshots - 1
    
    print("🎬 Screenshot Simples")
    print(f"📁 Diretório: {output_dir}")
    print(f"📐 Resolução: Original (sem redimensionamento)")
    print(f"⏱️  Intervalo: 1 segundo")
    print(f"⏰ Duração máxima: {max_screenshots}s ({max_screenshots//60}min) - fonte: {duration_source}")
    
    if existing_pngs:
        print(f"📋 Imagens existentes: {len(existing_pngs)} (último índice: {last_index})")
        print(f"🔄 Continuando do índice: {start_index}")
    else:
        print(f"🆕 Primeira execução - iniciando do índice: {start_index}")
    
    print(f"🏁 Capturará de {start_index} até {end_index}")
    print("-" * 50)
    
    # Pre-start countdown
    countdown(3)
    
    start_time = time.time()
    current_index = start_index
    successful_captures = 0
    errors = 0
    
    try:
        for screenshot_num in range(max_screenshots):
            loop_start = time.time()
            
            # Take screenshot
            image_data = take_screenshot()
            if not image_data:
                errors += 1
                print(f"❌ Erro na captura {current_index}")
                current_index += 1
                time.sleep(max(0, 1.0 - (time.time() - loop_start)))
                continue
            
            # Save image with zero-padded 4-digit filename (original resolution)
            output_path = output_dir / f"{current_index:04d}.png"
            try:
                # Save original image data directly without resizing
                with open(output_path, 'wb') as f:
                    f.write(image_data)
                successful_captures += 1
                
                # Progress indicator
                elapsed = time.time() - start_time
                if current_index % 10 == 0 or current_index <= 10:
                    print(f"📸 {current_index:4d} | {elapsed:6.1f}s | {successful_captures} ok, {errors} err")
                elif current_index % 60 == 0:  # Every minute
                    print(f"⏰ {current_index:4d} | {elapsed/60:5.1f}min | {successful_captures} ok, {errors} err")
                
            except Exception as e:
                errors += 1
                print(f"❌ Erro ao salvar {current_index}: {e}")
            
            current_index += 1
            
            # Sleep to maintain 1 second interval
            elapsed_this_loop = time.time() - loop_start
            sleep_time = max(0, 1.0 - elapsed_this_loop)
            if sleep_time > 0:
                time.sleep(sleep_time)
    
    except KeyboardInterrupt:
        print(f"\n⏹️  Interrompido pelo usuário após {current_index - start_index} capturas")
    
    # Final statistics
    total_time = time.time() - start_time
    print("\n" + "=" * 50)
    print("📊 ESTATÍSTICAS FINAIS")
    print("=" * 50)
    print(f"⏱️  Tempo total: {total_time:.1f}s ({total_time/60:.1f}min)")
    print(f"📸 Capturas realizadas: {current_index - start_index}")
    print(f"✅ Sucessos: {successful_captures}")
    print(f"❌ Erros: {errors}")
    print(f"📁 Pasta de saída: {output_dir}")
    print(f"🔢 Índices: {start_index} - {current_index - 1}")
    
    if successful_captures > 0:
        avg_fps = successful_captures / total_time
        print(f"📈 Taxa média: {avg_fps:.2f} capturas/segundo")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())