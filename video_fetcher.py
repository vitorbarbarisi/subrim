#!/usr/bin/env python3
"""
Script para baixar vídeos de episódios usando yt-dlp.
Uso: python3 video_fetcher.py <nome> <episodio_inicial>
Exemplo: python3 video_fetcher.py onibus 138
"""

import json
import os
import sys
import time
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


def download_video(url, directory, retries=3, delay=8):
    """Executa o comando yt-dlp para baixar vídeo e legendas. Retorna True em sucesso.

    Salva os arquivos com o prefixo igual ao nome da pasta (ex.: na pasta
    ``clone40`` gera ``clone40.mp4`` e ``clone40.pt-BR.srt``).

    A Globo às vezes devolve 401 transitório (token de sessão expira/renova);
    por isso tentamos novamente algumas vezes com uma pausa entre tentativas.
    """
    prefix = Path(directory).name
    command = [
        'yt-dlp',
        '--cookies-from-browser', 'chrome',
        '--write-subs',
        '--sub-langs', 'pt,pt-BR,pt-PT,all',
        '--convert-subs', 'srt',
        '-o', f'{prefix}.%(ext)s',
        url
    ]

    # Muda para o diretório antes de executar (uma vez)
    os.chdir(directory)

    for attempt in range(1, retries + 1):
        print(f"Executando (tentativa {attempt}/{retries}): {' '.join(command)}", flush=True)
        print(f"No diretório: {directory}", flush=True)

        saw_401 = False
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            # Transmite a saída do yt-dlp linha a linha em tempo real
            for line in process.stdout:
                line = line.rstrip()
                print(line, flush=True)
                if "401" in line or "Unauthorized" in line:
                    saw_401 = True
            return_code = process.wait()
        except FileNotFoundError:
            print("ERRO: yt-dlp não encontrado. Verifique se está instalado.", flush=True)
            sys.exit(1)
        except Exception as e:
            print(f"ERRO inesperado: {e}", flush=True)
            return False

        if return_code == 0:
            print(f"SUCCESS: Download concluído para {url}", flush=True)
            return True

        print(f"ERROR: Falha no download de {url} (código {return_code})", flush=True)
        if attempt < retries:
            hint = " (401 da Globo — token de sessão transitório)" if saw_401 else ""
            print(f"⏳ Nova tentativa em {delay}s{hint}…", flush=True)
            time.sleep(delay)

    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Baixa episódios de uma série via yt-dlp.")
    parser.add_argument("series_name", help="Nome da série (ex.: onibus)")
    parser.add_argument("start_episode", help="Episódio inicial (ou único com --only)")
    parser.add_argument("--only", action="store_true",
                        help="Baixa apenas o episódio exato, sem avançar para os próximos.")
    args = parser.parse_args()

    series_name   = args.series_name
    start_episode = args.start_episode
    only_one      = args.only

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

    # Modo --only: episódio exato; senão, os 6 próximos.
    if only_one:
        episodes_to_process = filtered_episodes[:1]
        print(f"Modo episódio único: {len(episodes_to_process)} episódio")
    else:
        episodes_to_process = filtered_episodes[:6]
        print(f"Processando {len(episodes_to_process)} episódios (limite de 6)")

    if not episodes_to_process:
        print(f"Nenhum episódio encontrado a partir do número {start_episode}")
        sys.exit(0)

    # Processa cada episódio
    total = len(episodes_to_process)
    ok, fail = [], []
    for i, episode in enumerate(episodes_to_process, 1):
        episode_num = episode['episode_number']
        url = episode['url']
        dirname = f"{series_name}{episode_num}"

        print(f"\n--- Episódio {i}/{total}: {episode_num} ---")
        print(f"URL: {url}")

        # Cria diretório
        episode_dir = create_directory(assets_dir, dirname)
        print(f"Diretório criado: {episode_dir}")

        # Baixa vídeo
        if download_video(url, episode_dir):
            ok.append(str(episode_num))
        else:
            fail.append(str(episode_num))

        # Volta para o diretório original
        os.chdir(base_dir)

    print(f"\nProcessamento concluído! {len(ok)} ok / {len(fail)} falha(s) de {total}.")
    if fail:
        print("Episódios que falharam: " + ", ".join(fail))
        print("💡 401 da Globo costuma ser sessão expirada — abra o globoplay.globo.com "
              "logado no Chrome e rode de novo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
