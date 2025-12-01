#!/usr/bin/env python3
"""
Script para baixar vídeos do YouTube e extrair transcript/legendas usando yt-dlp.

Uso: python3 youtube_downloader.py <URL_DO_YOUTUBE> [--output-dir DIRETORIO]
Exemplo: python3 youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
"""

import sys
import subprocess
import re
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass


def check_yt_dlp_installed() -> bool:
    """Verifica se yt-dlp está instalado."""
    try:
        result = subprocess.run(['yt-dlp', '--version'], 
                              capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def download_video_and_subtitles(url: str, output_dir: Path) -> bool:
    """
    Baixa vídeo e legendas do YouTube usando yt-dlp.
    
    Args:
        url: URL do vídeo do YouTube
        output_dir: Diretório onde salvar os arquivos
        
    Returns:
        True se bem-sucedido, False caso contrário
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Comando yt-dlp para baixar vídeo e legendas
    # Não usa 'all' para evitar muitas requisições e erro 429
    command = [
        'yt-dlp',
        '--write-subs',                    # Baixa legendas
        '--write-auto-subs',               # Baixa legendas automáticas (transcript)
        '--sub-langs', 'pt,pt-BR,es,es-ES,es-MX,es-AR,en,en-US,en-GB',  # Apenas idiomas específicos
        '--sub-format', 'vtt',             # Formato VTT (mais comum)
        '--convert-subs', 'srt',           # Converte automaticamente para SRT
        '--ignore-errors',                 # Continua mesmo se algumas legendas falharem
        '--sleep-subtitles', '1',          # Delay de 1 segundo entre downloads de legendas
        '--skip-download',                 # Não baixa o vídeo, apenas legendas
        '--output', str(output_dir / '%(title)s.%(ext)s'),
        url
    ]
    
    print(f"📥 Baixando legendas de: {url}")
    print(f"📁 Diretório de saída: {output_dir}")
    print()
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=output_dir)
        
        # Verifica se pelo menos algumas legendas foram baixadas
        subtitle_files = list(output_dir.glob("*.srt")) + list(output_dir.glob("*.vtt"))
        
        if result.returncode == 0 or subtitle_files:
            print("\n" + "="*60)
            print("✅ SUCESSO! Legendas baixadas")
            print("="*60)
            
            if subtitle_files:
                srt_files = [f for f in subtitle_files if f.suffix == '.srt']
                vtt_files = [f for f in subtitle_files if f.suffix == '.vtt']
                
                print(f"\n📝 Total de legendas baixadas: {len(subtitle_files)}")
                
                if srt_files:
                    print(f"\n   • Arquivos SRT: {len(srt_files)}")
                    for sub in sorted(srt_files):
                        size_kb = sub.stat().st_size / 1024
                        # Tenta extrair idioma do nome do arquivo
                        lang_match = re.search(r'\.([a-z]{2}(?:-[A-Z]{2})?)\.srt$', sub.name, re.I)
                        lang = f" ({lang_match.group(1)})" if lang_match else ""
                        print(f"     - {sub.name}{lang} - {size_kb:.2f} KB")
                
                if vtt_files:
                    print(f"\n   • Arquivos VTT: {len(vtt_files)}")
                    for sub in sorted(vtt_files):
                        size_kb = sub.stat().st_size / 1024
                        lang_match = re.search(r'\.([a-z]{2}(?:-[A-Z]{2})?)\.vtt$', sub.name, re.I)
                        lang = f" ({lang_match.group(1)})" if lang_match else ""
                        print(f"     - {sub.name}{lang} - {size_kb:.2f} KB")
                
                # Identifica idiomas únicos baixados
                languages = set()
                for sub in subtitle_files:
                    lang_match = re.search(r'\.([a-z]{2}(?:-[A-Z]{2})?)\.(?:srt|vtt)$', sub.name, re.I)
                    if lang_match:
                        languages.add(lang_match.group(1))
                
                if languages:
                    lang_names = {
                        'pt': 'Português', 'pt-BR': 'Português (BR)', 'pt-PT': 'Português (PT)',
                        'es': 'Espanhol', 'es-ES': 'Espanhol (ES)', 'es-MX': 'Espanhol (MX)', 'es-AR': 'Espanhol (AR)',
                        'en': 'Inglês', 'en-US': 'Inglês (US)', 'en-GB': 'Inglês (GB)'
                    }
                    lang_list = [lang_names.get(lang, lang) for lang in sorted(languages)]
                    print(f"\n🌍 Idiomas disponíveis: {', '.join(lang_list)}")
            else:
                print("\n⚠️  Nenhum arquivo de legenda encontrado no diretório")
            
            if result.returncode != 0 and result.stderr:
                # Mostra apenas erros relevantes se houver
                errors = [line for line in result.stderr.split('\n') 
                         if 'ERROR' in line or '429' in line or 'Too Many Requests' in line]
                if errors:
                    print("\n⚠️  Avisos:")
                    for error in errors[:3]:  # Limita a 3 erros
                        print(f"   • {error}")
            
            print(f"\n📁 Localização: {output_dir.absolute()}")
            print("="*60)
            return True
        else:
            print("❌ Erro ao baixar legendas:")
            if result.stderr:
                print(result.stderr.strip())
            if result.stdout:
                print(result.stdout.strip())
            return False
            
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return False


def download_video_only(url: str, output_dir: Path) -> bool:
    """
    Baixa apenas o vídeo do YouTube (sem legendas).
    
    Args:
        url: URL do vídeo do YouTube
        output_dir: Diretório onde salvar o arquivo
        
    Returns:
        True se bem-sucedido, False caso contrário
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    command = [
        'yt-dlp',
        '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',  # Melhor qualidade MP4
        '--merge-output-format', 'mp4',
        '--output', str(output_dir / '%(title)s.%(ext)s'),
        url
    ]
    
    print(f"📥 Baixando vídeo de: {url}")
    print(f"📁 Diretório de saída: {output_dir}")
    print()
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=output_dir)
        
        video_files = list(output_dir.glob("*.mp4"))
        
        if result.returncode == 0 and video_files:
            print("\n" + "="*60)
            print("✅ SUCESSO! Vídeo baixado")
            print("="*60)
            
            for video in sorted(video_files):
                size_mb = video.stat().st_size / (1024 * 1024)
                size_gb = size_mb / 1024
                size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{size_mb:.2f} MB"
                
                print(f"\n🎬 Vídeo: {video.name}")
                print(f"   📦 Tamanho: {size_str}")
                print(f"   📁 Localização: {video.absolute()}")
            
            print("="*60)
            return True
        else:
            print("❌ Erro ao baixar vídeo:")
            if result.stderr:
                print(result.stderr.strip())
            if result.stdout:
                print(result.stdout.strip())
            return False
            
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return False


def download_video_with_subtitles(url: str, output_dir: Path) -> bool:
    """
    Baixa vídeo e legendas do YouTube.
    
    Args:
        url: URL do vídeo do YouTube
        output_dir: Diretório onde salvar os arquivos
        
    Returns:
        True se bem-sucedido, False caso contrário
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    command = [
        'yt-dlp',
        '--write-subs',                    # Baixa legendas
        '--write-auto-subs',               # Baixa legendas automáticas (transcript)
        '--sub-langs', 'pt,pt-BR,es,es-ES,es-MX,es-AR,en,en-US,en-GB',  # Apenas idiomas específicos
        '--sub-format', 'vtt',             # Formato VTT
        '--convert-subs', 'srt',           # Converte automaticamente para SRT
        '--ignore-errors',                 # Continua mesmo se algumas legendas falharem
        '--sleep-subtitles', '1',          # Delay de 1 segundo entre downloads de legendas
        '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '--merge-output-format', 'mp4',
        '--output', str(output_dir / '%(title)s.%(ext)s'),
        url
    ]
    
    print(f"📥 Baixando vídeo e legendas de: {url}")
    print(f"📁 Diretório de saída: {output_dir}")
    print()
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=output_dir)
        
        # Verifica se vídeo e/ou legendas foram baixados
        video_files = list(output_dir.glob("*.mp4"))
        subtitle_files = list(output_dir.glob("*.srt")) + list(output_dir.glob("*.vtt"))
        
        if result.returncode == 0 or video_files:
            print("\n" + "="*60)
            print("✅ SUCESSO! Download concluído")
            print("="*60)
            
            # Informações do vídeo
            if video_files:
                for video in sorted(video_files):
                    size_mb = video.stat().st_size / (1024 * 1024)
                    size_gb = size_mb / 1024
                    size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{size_mb:.2f} MB"
                    
                    print(f"\n🎬 Vídeo baixado:")
                    print(f"   📹 Nome: {video.name}")
                    print(f"   📦 Tamanho: {size_str}")
                    print(f"   📁 Localização: {video.absolute()}")
            else:
                print("\n⚠️  Vídeo não encontrado (pode ter falhado o download)")
            
            # Informações das legendas
            if subtitle_files:
                srt_files = [f for f in subtitle_files if f.suffix == '.srt']
                vtt_files = [f for f in subtitle_files if f.suffix == '.vtt']
                
                print(f"\n📝 Legendas baixadas: {len(subtitle_files)} arquivo(s)")
                
                if srt_files:
                    print(f"   • SRT: {len(srt_files)} arquivo(s)")
                    for sub in sorted(srt_files):
                        size_kb = sub.stat().st_size / 1024
                        lang_match = re.search(r'\.([a-z]{2}(?:-[A-Z]{2})?)\.srt$', sub.name, re.I)
                        lang = f" ({lang_match.group(1)})" if lang_match else ""
                        print(f"     - {sub.name}{lang} - {size_kb:.2f} KB")
                
                if vtt_files:
                    print(f"   • VTT: {len(vtt_files)} arquivo(s)")
                    for sub in sorted(vtt_files):
                        size_kb = sub.stat().st_size / 1024
                        lang_match = re.search(r'\.([a-z]{2}(?:-[A-Z]{2})?)\.vtt$', sub.name, re.I)
                        lang = f" ({lang_match.group(1)})" if lang_match else ""
                        print(f"     - {sub.name}{lang} - {size_kb:.2f} KB")
                
                # Identifica idiomas únicos
                languages = set()
                for sub in subtitle_files:
                    lang_match = re.search(r'\.([a-z]{2}(?:-[A-Z]{2})?)\.(?:srt|vtt)$', sub.name, re.I)
                    if lang_match:
                        languages.add(lang_match.group(1))
                
                if languages:
                    lang_names = {
                        'pt': 'Português', 'pt-BR': 'Português (BR)', 'pt-PT': 'Português (PT)',
                        'es': 'Espanhol', 'es-ES': 'Espanhol (ES)', 'es-MX': 'Espanhol (MX)', 'es-AR': 'Espanhol (AR)',
                        'en': 'Inglês', 'en-US': 'Inglês (US)', 'en-GB': 'Inglês (GB)'
                    }
                    lang_list = [lang_names.get(lang, lang) for lang in sorted(languages)]
                    print(f"\n🌍 Idiomas disponíveis: {', '.join(lang_list)}")
            else:
                print("\n⚠️  Nenhuma legenda foi baixada")
                if result.stderr:
                    errors = [line for line in result.stderr.split('\n') 
                             if 'ERROR' in line or '429' in line or 'Too Many Requests' in line]
                    if errors:
                        print("   Possíveis causas:")
                        for error in errors[:2]:
                            print(f"   • {error}")
            
            print(f"\n📁 Diretório: {output_dir.absolute()}")
            print("="*60)
            return True
        else:
            print("❌ Erro ao baixar:")
            if result.stderr:
                print(result.stderr.strip())
            if result.stdout:
                print(result.stdout.strip())
            return False
            
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return False


def list_downloaded_files(output_dir: Path) -> None:
    """Lista os arquivos baixados."""
    print("\n📋 Arquivos baixados:")
    print("-" * 60)
    
    video_files = list(output_dir.glob("*.mp4"))
    subtitle_files = list(output_dir.glob("*.srt")) + list(output_dir.glob("*.vtt"))
    
    if video_files:
        print("\n🎬 Vídeos:")
        for video in sorted(video_files):
            size_mb = video.stat().st_size / (1024 * 1024)
            print(f"   • {video.name} ({size_mb:.2f} MB)")
    
    if subtitle_files:
        print("\n📝 Legendas:")
        for sub in sorted(subtitle_files):
            size_kb = sub.stat().st_size / 1024
            print(f"   • {sub.name} ({size_kb:.2f} KB)")
    
    if not video_files and not subtitle_files:
        print("   Nenhum arquivo encontrado.")
    
    print()


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 youtube_downloader.py <URL> [--output-dir DIRETORIO] [--subtitles-only] [--video-only]")
        print()
        print("Opções:")
        print("  --output-dir DIRETORIO    Diretório onde salvar os arquivos (padrão: ./downloads)")
        print("  --subtitles-only          Baixa apenas as legendas (transcript)")
        print("  --video-only              Baixa apenas o vídeo (sem legendas)")
        print()
        print("Exemplos:")
        print('  python3 youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"')
        print('  python3 youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" --output-dir ./meus_videos')
        print('  python3 youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" --subtitles-only')
        sys.exit(1)
    
    # Verifica se yt-dlp está instalado
    if not check_yt_dlp_installed():
        print("❌ yt-dlp não está instalado!")
        print()
        print("Para instalar:")
        print("  pip install yt-dlp")
        print("  ou")
        print("  brew install yt-dlp  # macOS")
        sys.exit(1)
    
    # Parse argumentos
    url = sys.argv[1]
    output_dir = Path("./downloads")
    subtitles_only = False
    video_only = False
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = Path(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--subtitles-only':
            subtitles_only = True
            i += 1
        elif sys.argv[i] == '--video-only':
            video_only = True
            i += 1
        else:
            i += 1
    
    # Valida URL
    if not url.startswith(('http://', 'https://')):
        print(f"❌ URL inválida: {url}")
        sys.exit(1)
    
    # Executa download
    success = False
    if subtitles_only:
        success = download_video_and_subtitles(url, output_dir)
    elif video_only:
        success = download_video_only(url, output_dir)
    else:
        success = download_video_with_subtitles(url, output_dir)
    
    if success:
        # list_downloaded_files já foi chamado nas funções de download
        pass
    else:
        print("\n💡 Dicas:")
        print("   • Verifique se a URL está correta")
        print("   • Alguns vídeos podem não ter legendas disponíveis")
        print("   • Tente usar --subtitles-only para baixar apenas legendas")
        sys.exit(1)


if __name__ == "__main__":
    main()

