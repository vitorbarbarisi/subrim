#!/usr/bin/env python3
"""
YouTube Downloader robusto usando yt-dlp.

Roda no servidor (o Manager dispara via subrim_server). O principal motivo de
falhas no download do YouTube é a detecção de bot — resolvido com cookies reais:
o cookies.txt da raiz do repo (o mesmo do youtube_monitor) ou, sem ele, os
cookies do browser desta máquina. Tenta primeiro a qualidade máxima (melhor
vídeo + melhor áudio, sem teto de resolução) e, se o download falhar, cai para
o stream progressivo mp4.

Saída segue o padrão do pipeline: os arquivos são gravados em
  assets/<nome>/
e nomeados como <nome>.mp4 e <nome>.pt-BR.srt (ou o idioma disponível).

Uso:
  python3 youtube_downloader.py <URL> --name <nome> [opções]

Exemplos:
  python3 youtube_downloader.py "https://youtu.be/abc" --name clone45
  python3 youtube_downloader.py "https://youtu.be/abc" --name clone45 --subs-only
  python3 youtube_downloader.py "https://youtu.be/abc" --name clone45 --video-only
  python3 youtube_downloader.py "https://youtu.be/abc" --name clone45 --browser firefox
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO    = Path(__file__).resolve().parent
ASSETS  = REPO / "assets"
COOKIES = REPO / "cookies.txt"   # exportado do navegador logado no YouTube

# Tentativas de formato, em ordem. A primeira é a qualidade máxima (qualquer
# codec/resolução, mesclada em mp4). O yt-dlp não troca de formato quando o
# download em si falha (403/SABR), então a segunda é outra execução: o
# progressivo, que costuma passar quando os streams separados são barrados.
FORMAT_ATTEMPTS = [
    ("qualidade máxima", "bestvideo*+bestaudio/best"),
    ("progressivo mp4",  "best[ext=mp4]/best"),
]

# Idiomas de legenda em ordem de preferência.
SUB_LANGS = "pt-BR,pt,pt-PT,en,en-US,en-GB"


def _check_yt_dlp() -> str:
    """Retorna o caminho do yt-dlp: o da venv do Python em uso (no servidor ele
    não está no PATH global), depois o do PATH e, no Mac, o do Homebrew."""
    venv_bin = Path(sys.executable).with_name("yt-dlp")
    candidates = [str(venv_bin), shutil.which("yt-dlp"), "/opt/homebrew/bin/yt-dlp"]
    for candidate in filter(None, candidates):
        try:
            r = subprocess.run([candidate, "--version"], capture_output=True, text=True)
            if r.returncode == 0:
                print(f"✅ yt-dlp {r.stdout.strip()}  ({candidate})")
                return candidate
        except (FileNotFoundError, PermissionError):
            continue
    print("❌ yt-dlp não encontrado. Instale na venv: pip install -U yt-dlp")
    sys.exit(1)


def _cookie_flags(browser: str) -> list:
    if COOKIES.is_file():
        return ["--cookies", str(COOKIES)]
    return ["--cookies-from-browser", browser]


def _base_flags(browser: str, out_dir: Path, prefix: str) -> list:
    """Flags comuns a todos os modos de download."""
    return [
        # --- Autenticação: cookies.txt do servidor (ou do browser local) ---
        *_cookie_flags(browser),

        # --- Robustez ---
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "exp=1:5",   # backoff exponencial entre tentativas
        "--sleep-requests", "1",       # 1 s entre requests (evita rate-limit)
        "--throttled-rate", "100K",    # desacelera automaticamente se throttled

        # --- Saída padronizada para o pipeline ---
        "--output", str(out_dir / f"{prefix}.%(ext)s"),

        # --- Progresso ---
        "--newline",
        "--no-warnings",
    ]


SUB_FLAGS = [
    "--write-subs",
    "--write-auto-subs",
    "--sub-langs", SUB_LANGS,
    "--sub-format", "srt/vtt/best",
    "--convert-subs", "srt",
]


def _download_best(yt: str, url: str, out_dir: Path, prefix: str, browser: str,
                   extra: list, label: str) -> bool:
    """Tenta cada formato de FORMAT_ATTEMPTS até um baixar."""
    for i, (nome, fmt) in enumerate(FORMAT_ATTEMPTS, 1):
        cmd = [yt] + _base_flags(browser, out_dir, prefix) + [
            "--format", fmt,
            "--merge-output-format", "mp4",
            *extra,
            url,
        ]
        if _run(cmd, f"{label} — {nome}", tips=i == len(FORMAT_ATTEMPTS)):
            return True
        if i < len(FORMAT_ATTEMPTS):
            print(f"⚠️ Falhou em {nome}; tentando {FORMAT_ATTEMPTS[i][0]}…", flush=True)
    return False


def download_video(yt: str, url: str, out_dir: Path, prefix: str,
                   browser: str = "chrome") -> bool:
    """Baixa vídeo + legendas."""
    return _download_best(yt, url, out_dir, prefix, browser, SUB_FLAGS, "Vídeo + legendas")


def download_subs_only(yt: str, url: str, out_dir: Path, prefix: str,
                       browser: str = "chrome") -> bool:
    """Baixa apenas as legendas (sem vídeo)."""
    cmd = [yt] + _base_flags(browser, out_dir, prefix) + ["--skip-download", *SUB_FLAGS, url]
    return _run(cmd, "Só legendas")


def download_video_only(yt: str, url: str, out_dir: Path, prefix: str,
                        browser: str = "chrome") -> bool:
    """Baixa apenas o vídeo (sem legendas)."""
    return _download_best(yt, url, out_dir, prefix, browser, [], "Só vídeo")


def _run(cmd: list, label: str, tips: bool = True) -> bool:
    print(f"\n{'='*60}")
    print(f"📥 {label}")
    print(f"{'='*60}")
    print(f"$ {' '.join(cmd[:8])} …\n", flush=True)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout:
        print(line.rstrip(), flush=True)
    rc = proc.wait()

    if rc == 0:
        print(f"\n✅ {label} concluído.")
        return True
    print(f"\n❌ yt-dlp encerrou com código {rc}.")
    if tips:
        _print_tips()
    return False


def _print_tips():
    print("\n💡 Dicas de solução:")
    print("  • 403 em TODOS os fragmentos = provável proxy corporativo (Netskope).")
    print("    As URLs de mídia do YouTube são travadas por IP; se o proxy sai por")
    print("    um IP diferente do visto na extração, todo download dá 403.")
    print("    → Baixe fora da rede corporativa (ex.: hotspot) ou exclua")
    print("      *.googlevideo.com da interceptação do Netskope.")
    print(f"  • Sessão expirada: exporte de novo o {COOKIES.name} de um navegador")
    print("    logado no YouTube e copie para a raiz do repo no servidor.")
    print("  • Para PO token: container 'bgutil-provider' deve estar rodando")
    print("    (docker ps) e o yt-dlp precisa ser recente.")
    print("  • Atualize o yt-dlp: pip install -U yt-dlp (na venv)")


def _list_results(out_dir: Path):
    print("\n📋 Arquivos gerados:")
    for f in sorted(out_dir.iterdir()):
        if f.suffix in (".mp4", ".srt", ".vtt", ".webm", ".mkv"):
            size = f.stat().st_size
            unit = "MB" if size > 1_000_000 else "KB"
            val  = size / (1_000_000 if unit == "MB" else 1_000)
            print(f"   • {f.name}  ({val:.1f} {unit})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Baixa vídeos do YouTube de forma confiável via yt-dlp, na qualidade máxima.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("url", help="URL do vídeo do YouTube")
    parser.add_argument(
        "--name", required=True,
        help="Nome do asset (ex.: clone45). Cria assets/<nome>/ e nomeia os arquivos.",
    )
    parser.add_argument(
        "--output-dir",
        help="Diretório pai onde a pasta <name> será criada (padrão: assets/).",
    )
    parser.add_argument(
        "--browser", default="chrome",
        choices=["chrome", "firefox", "safari", "chromium", "edge", "brave", "opera"],
        help="Browser do qual ler os cookies quando não há cookies.txt (padrão: chrome).",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--subs-only", action="store_true",
                      help="Baixa apenas as legendas (sem vídeo).")
    mode.add_argument("--video-only", action="store_true",
                      help="Baixa apenas o vídeo (sem legendas).")
    # Alias legado para compatibilidade com chamadas antigas.
    mode.add_argument("--subtitles-only", action="store_true",
                      dest="subs_only", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print(f"❌ URL inválida: {args.url}")
        return 1

    yt = _check_yt_dlp()

    parent  = Path(args.output_dir) if args.output_dir else ASSETS
    out_dir = parent / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"📁 Destino: {out_dir}")
    print(f"🌐 URL:     {args.url}")
    print(f"🍪 Cookies: {COOKIES if COOKIES.is_file() else 'browser ' + args.browser}")

    if args.subs_only:
        ok = download_subs_only(yt, args.url, out_dir, args.name, args.browser)
    elif args.video_only:
        ok = download_video_only(yt, args.url, out_dir, args.name, args.browser)
    else:
        ok = download_video(yt, args.url, out_dir, args.name, args.browser)

    if ok:
        _list_results(out_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
