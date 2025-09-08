#!/usr/bin/env python3
"""
Script para baixar vídeos de episódios usando yt-dlp.
Uso: python3 video_fetcher.py <nome> <episodio_inicial>
Exemplo: python3 video_fetcher.py onibus 138
"""

import json
import os
import sys
import subprocess
from pathlib import Path


def load_episodes(json_file_path):
    """Carrega os episódios do arquivo JSON."""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('episodes', [])
    except FileNotFoundError:
        print(f"Erro: Arquivo {json_file_path} não encontrado.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Erro: Falha ao decodificar JSON em {json_file_path}.")
        sys.exit(1)


def filter_episodes(episodes, start_episode):
    """Filtra episódios a partir do número especificado."""
    try:
        start_num = int(start_episode)
        filtered = [ep for ep in episodes if int(ep['episode_number']) >= start_num]
        return sorted(filtered, key=lambda x: int(x['episode_number']))
    except ValueError:
        print(f"Erro: Número do episódio '{start_episode}' inválido.")
        sys.exit(1)


def create_directory(base_path, dirname):
    """Cria diretório se não existir."""
    full_path = base_path / dirname
    full_path.mkdir(parents=True, exist_ok=True)
    return full_path


def download_video(url, directory):
    """Executa o comando yt-dlp para baixar vídeo e legendas."""
    command = [
        'yt-dlp',
        '--cookies-from-browser', 'chrome',
        '--write-subs',
        '--sub-langs', 'pt,pt-BR,pt-PT,all',
        url
    ]

    print(f"Executando: {' '.join(command)}")
    print(f"No diretório: {directory}")

    try:
        # Muda para o diretório antes de executar
        os.chdir(directory)
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"SUCCESS: Download concluído para {url}")
            if result.stdout:
                print("Output:", result.stdout.strip())
        else:
            print(f"ERROR: Falha no download de {url}")
            if result.stderr:
                print("Stderr:", result.stderr.strip())
            if result.stdout:
                print("Stdout:", result.stdout.strip())

    except FileNotFoundError:
        print("ERRO: yt-dlp não encontrado. Verifique se está instalado.")
        sys.exit(1)
    except Exception as e:
        print(f"ERRO inesperado: {e}")
        sys.exit(1)


def main():
    if len(sys.argv) != 3:
        print("Uso: python3 video_fetcher.py <nome> <episodio_inicial>")
        print("Exemplo: python3 video_fetcher.py onibus 138")
        sys.exit(1)

    series_name = sys.argv[1]
    start_episode = sys.argv[2]

    # Caminhos
    base_dir = Path(__file__).parent
    json_file_path = base_dir / 'assets' / 'source' / f'{series_name}.json'
    assets_dir = base_dir / 'assets'

    print(f"Processando série: {series_name}")
    print(f"Episódio inicial: {start_episode}")
    print(f"Arquivo JSON: {json_file_path}")

    # Carrega episódios
    episodes = load_episodes(json_file_path)
    print(f"Total de episódios encontrados: {len(episodes)}")

    # Filtra episódios
    filtered_episodes = filter_episodes(episodes, start_episode)
    print(f"Episódios a partir de {start_episode}: {len(filtered_episodes)}")

    # Processa apenas os primeiros 6 episódios
    episodes_to_process = filtered_episodes[:6]
    print(f"Processando {len(episodes_to_process)} episódios (limite de 6)")

    if not episodes_to_process:
        print(f"Nenhum episódio encontrado a partir do número {start_episode}")
        sys.exit(0)

    # Processa cada episódio
    for i, episode in enumerate(episodes_to_process, 1):
        episode_num = episode['episode_number']
        url = episode['url']
        dirname = f"{series_name}{episode_num}"

        print(f"\n--- Episódio {i}/6: {episode_num} ---")
        print(f"URL: {url}")

        # Cria diretório
        episode_dir = create_directory(assets_dir, dirname)
        print(f"Diretório criado: {episode_dir}")

        # Baixa vídeo
        download_video(url, episode_dir)

        # Volta para o diretório original
        os.chdir(base_dir)

    print(f"\nProcessamento concluído! {len(episodes_to_process)} episódios processados.")


if __name__ == "__main__":
    main()
