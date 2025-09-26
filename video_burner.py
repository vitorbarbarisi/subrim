#!/usr/bin/env python3
"""
Orquestrador automático do processo de queima de legendas em vídeos

Este script automatiza todo o fluxo de processamento de vídeos com legendas:
1. processor.py → adjust_base_times.py → sanitize_base.py
2. split_video.py → process_chunks.py → merge_chunks.py

Usage:
  python3 video_burner.py <directory_prefix> [options]

Examples:
  python3 video_burner.py onibus     # Processa todas as pastas onibusXXX
  python3 video_burner.py onibus138  # Processa apenas onibus138
  python3 video_burner.py amor       # Processa todas as pastas amor*
  python3 video_burner.py onibus --upload-drive  # Com upload para Drive
  python3 video_burner.py onibus --cleanup  # Com limpeza automática
  python3 video_burner.py onibus --upload-drive --drive-folder-id 123456789

Funcionamento:
  1. Encontra todas as pastas que começam com o prefixo especificado
  2. Para cada pasta, verifica se já foi processada (_merged.mp4 existe)
  3. Se não foi processada, executa todo o fluxo:
     - processor.py → adjust_base_times.py → sanitize_base.py
     - split_video.py → process_chunks.py → merge_chunks.py
  4. Faz upload opcional para Google Drive
  5. Limpa arquivos temporários (opcional)

Características:
  - IDÉMPOTENTE: Pode ser executado múltiplas vezes
  - RESUMÍVEL: Continua de onde parou se interrompido
  - VERBOSE: Mostra progresso detalhado de cada etapa
  - SEGURO: Não sobrescreve arquivos já processados

Requisitos:
  - Todos os scripts Python devem estar no mesmo diretório
  - Diretório assets/ deve existir com as pastas de vídeos
  - FFmpeg deve estar instalado
  - Python 3.6+ com dependências necessárias
  - Para upload no Google Drive: pip install requests
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional
import time


class VideoBurner:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.assets_dir = Path("assets")
        self.scripts = [
            "processor.py",
            "adjust_base_times.py", 
            "sanitize_base.py",
            "split_video.py",
            "process_chunks.py",
            "merge_chunks.py"
        ]
        
    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp"""
        if self.verbose:
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level}] {message}")
    
    def find_directories(self, prefix: str) -> List[Path]:
        """Find all directories in assets/ that start with the given prefix"""
        if not self.assets_dir.exists():
            self.log(f"Diretório assets/ não encontrado!", "ERROR")
            return []
        
        directories = []
        for item in self.assets_dir.iterdir():
            if item.is_dir() and item.name.startswith(prefix) and not item.name.endswith("_sub"):
                directories.append(item)
        
        directories.sort(key=lambda x: x.name)
        return directories
    
    def is_processed(self, directory: Path) -> bool:
        """Check if directory has been processed (contains _merged.mp4)"""
        # Check for _merged.mp4 in the main directory
        merged_file = directory / "_merged.mp4"
        if merged_file.exists():
            return True
        
        # Check for *_merged.mp4 in the _sub directory
        sub_dir = self.assets_dir / f"{directory.name}_sub"
        if sub_dir.exists():
            for merged_file in sub_dir.glob("*_merged.mp4"):
                return True
        
        return False
    
    def run_script(self, script: str, directory: str, args: List[str] = None) -> bool:
        """Run a Python script with the given directory and arguments"""
        if args is None:
            args = []
        
        cmd = [sys.executable, script, directory] + args
        self.log(f"Executando: {' '.join(cmd)}")
        
        try:
            # Special handling for process_chunks.py to show real-time output
            if script == "process_chunks.py":
                return self.run_script_realtime(cmd)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path.cwd()
            )
            
            if result.returncode == 0:
                self.log(f"✓ {script} executado com sucesso")
                if result.stdout and self.verbose:
                    print(f"  Output: {result.stdout.strip()}")
                return True
            else:
                self.log(f"✗ {script} falhou com código {result.returncode}", "ERROR")
                if result.stderr:
                    print(f"  Error: {result.stderr.strip()}")
                return False
                
        except Exception as e:
            self.log(f"✗ Erro ao executar {script}: {e}", "ERROR")
            return False
    
    def run_script_realtime(self, cmd: List[str]) -> bool:
        """Run a script with real-time output display"""
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=Path.cwd()
            )
            
            # Read output line by line and display in real-time
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    print(line.rstrip())
            
            # Wait for process to complete
            return_code = process.wait()
            
            if return_code == 0:
                self.log(f"✓ process_chunks.py executado com sucesso")
                return True
            else:
                self.log(f"✗ process_chunks.py falhou com código {return_code}", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"✗ Erro ao executar process_chunks.py: {e}", "ERROR")
            return False
    
    def process_directory(self, directory: Path, force: bool = False) -> bool:
        """Process a single directory through the complete pipeline"""
        dir_name = directory.name
        self.log(f"Processando diretório: {dir_name}")
        
        # Check if already processed
        if not force and self.is_processed(directory):
            self.log(f"Diretório {dir_name} já foi processado (encontrado _merged.mp4)")
            return True
        
        # Phase 1: Subtitle processing
        self.log(f"Fase 1: Processamento de legendas para {dir_name}")
        
        if not self.run_script("processor.py", dir_name):
            self.log(f"Falha no processor.py para {dir_name}", "ERROR")
            return False
        
        if not self.run_script("adjust_base_times.py", dir_name):
            self.log(f"Falha no adjust_base_times.py para {dir_name}", "ERROR")
            return False
        
        if not self.run_script("sanitize_base.py", dir_name):
            self.log(f"Falha no sanitize_base.py para {dir_name}", "ERROR")
            return False
        
        # Phase 2: Video processing
        self.log(f"Fase 2: Processamento de vídeo para {dir_name}")
        
        if not self.run_script("split_video.py", dir_name):
            self.log(f"Falha no split_video.py para {dir_name}", "ERROR")
            return False
        
        if not self.run_script("process_chunks.py", dir_name):
            self.log(f"Falha no process_chunks.py para {dir_name}", "ERROR")
            return False
        
        if not self.run_script("merge_chunks.py", dir_name):
            self.log(f"Falha no merge_chunks.py para {dir_name}", "ERROR")
            return False
        
        # Verify final result
        if self.is_processed(directory):
            self.log(f"✓ {dir_name} processado com sucesso!")
            return True
        else:
            self.log(f"✗ {dir_name} processamento incompleto - _merged.mp4 não encontrado", "ERROR")
            return False
    
    def cleanup_directory(self, directory: Path) -> None:
        """Clean up temporary files in a directory"""
        dir_name = directory.name
        sub_dir = self.assets_dir / f"{dir_name}_sub"
        
        if sub_dir.exists():
            self.log(f"Limpando arquivos temporários em {sub_dir}")
            try:
                # Remove chunk files but keep the final merged video
                for file in sub_dir.glob("*_processed.mp4"):
                    file.unlink()
                    self.log(f"  Removido: {file.name}")
                
                # Remove concat file if exists
                concat_file = sub_dir / "concat_list.txt"
                if concat_file.exists():
                    concat_file.unlink()
                    self.log(f"  Removido: concat_list.txt")
                    
            except Exception as e:
                self.log(f"Erro durante limpeza: {e}", "WARNING")
    
    def upload_to_drive(self, directory: Path, drive_folder_id: Optional[str] = None) -> bool:
        """Upload processed video to Google Drive"""
        # This is a placeholder - would need to implement Google Drive API
        self.log(f"Upload para Google Drive não implementado ainda", "WARNING")
        return True
    
    def process_all(self, prefix: str, force: bool = False, cleanup: bool = False, 
                   upload_drive: bool = False, drive_folder_id: Optional[str] = None) -> None:
        """Process all directories matching the prefix"""
        self.log(f"Iniciando processamento para prefixo: {prefix}")
        
        directories = self.find_directories(prefix)
        if not directories:
            self.log(f"Nenhuma pasta encontrada com prefixo '{prefix}' em assets/", "WARNING")
            return
        
        self.log(f"Encontradas {len(directories)} pastas para processar")
        
        successful = 0
        failed = 0
        
        for directory in directories:
            self.log(f"\n{'='*60}")
            self.log(f"Processando: {directory.name}")
            self.log(f"{'='*60}")
            
            if self.process_directory(directory, force):
                successful += 1
                
                # Cleanup if requested
                if cleanup:
                    self.cleanup_directory(directory)
                
                # Upload if requested
                if upload_drive:
                    self.upload_to_drive(directory, drive_folder_id)
            else:
                failed += 1
                self.log(f"Falha no processamento de {directory.name}", "ERROR")
        
        # Summary
        self.log(f"\n{'='*60}")
        self.log(f"RESUMO DO PROCESSAMENTO")
        self.log(f"{'='*60}")
        self.log(f"Total de pastas: {len(directories)}")
        self.log(f"Processadas com sucesso: {successful}")
        self.log(f"Falharam: {failed}")
        
        if failed > 0:
            self.log(f"Algumas pastas falharam no processamento", "WARNING")
            sys.exit(1)
        else:
            self.log(f"Todos os processamentos concluídos com sucesso!")


def main():
    parser = argparse.ArgumentParser(
        description="Orquestrador automático do processo de queima de legendas em vídeos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 video_burner.py onibus     # Processa todas as pastas onibusXXX
  python3 video_burner.py onibus138  # Processa apenas onibus138
  python3 video_burner.py amor       # Processa todas as pastas amor*
  python3 video_burner.py onibus --upload-drive  # Com upload para Drive
  python3 video_burner.py onibus --cleanup  # Com limpeza automática
  python3 video_burner.py onibus --upload-drive --drive-folder-id 123456789

Funcionamento:
  1. Encontra todas as pastas que começam com o prefixo especificado
  2. Para cada pasta, verifica se já foi processada (_merged.mp4 existe)
  3. Se não foi processada, executa todo o fluxo:
     - processor.py → adjust_base_times.py → sanitize_base.py
     - split_video.py → process_chunks.py → merge_chunks.py
  4. Faz upload opcional para Google Drive
  5. Limpa arquivos temporários (opcional)

Características:
  - IDÉMPOTENTE: Pode ser executado múltiplas vezes
  - RESUMÍVEL: Continua de onde parou se interrompido
  - VERBOSE: Mostra progresso detalhado de cada etapa
  - SEGURO: Não sobrescreve arquivos já processados

Requisitos:
  - Todos os scripts Python devem estar no mesmo diretório
  - Diretório assets/ deve existir com as pastas de vídeos
  - FFmpeg deve estar instalado
  - Python 3.6+ com dependências necessárias
  - Para upload no Google Drive: pip install requests
        """
    )
    
    parser.add_argument(
        "directory_prefix",
        help="Prefixo das pastas a processar (ex: 'onibus', 'amor')"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força reprocessamento mesmo se _merged.mp4 existir"
    )
    
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove arquivos temporários automaticamente após merge"
    )
    
    parser.add_argument(
        "--upload-drive",
        action="store_true",
        help="Faz upload automático para Google Drive após processamento"
    )
    
    parser.add_argument(
        "--drive-folder-id",
        help="ID da pasta do Google Drive para upload (opcional)"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Modo silencioso (menos output)"
    )
    
    args = parser.parse_args()
    
    # Create burner instance
    burner = VideoBurner(verbose=not args.quiet)
    
    # Process all directories
    burner.process_all(
        prefix=args.directory_prefix,
        force=args.force,
        cleanup=args.cleanup,
        upload_drive=args.upload_drive,
        drive_folder_id=args.drive_folder_id
    )


if __name__ == "__main__":
    main()
