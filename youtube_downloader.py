#!/usr/bin/env python3
"""
YouTube Downloader robusto usando yt-dlp.

O principal motivo de falhas no download do YouTube é a detecção de bot —
resolvido usando cookies reais do browser Chrome/Firefox/Safari. Além disso,
o script aplica retries, throttle e seleção de qualidade com fallback.

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
import subprocess
import sys
from pathlib import Path

REPO   = Path(__file__).resolve().parent
ASSETS = REPO / "assets"

# Cadeia de fallback de qualidade: preferimos mp4 1080p, aceitamos qualquer coisa.
FORMAT_BEST = (
    "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]"
    "/bestvideo[height<=1080]+bestaudio"
    "/best[ext=mp4]"
    "/best"
)

# Idiomas de legenda em ordem de preferência.
SUB_LANGS = "pt-BR,pt,pt-PT,en,en-US,en-GB"


def _check_yt_dlp() -> str:
    """Retorna o caminho do yt-dlp, preferindo o mais novo (com plugin de PO token).

    O plugin bgutil de PO token (necessário para o YouTube em 2025+) exige um
    yt-dlp recente. O do Homebrew costuma ser mais novo que um pip antigo, então
    é preferido quando existe.
    """
    for candidate in ("/opt/homebrew/bin/yt-dlp", "yt-dlp"):
        try:
            r = subprocess.run([candidate, "--version"], capture_output=True, text=True)
            if r.returncode == 0:
                print(f"✅ yt-dlp {r.stdout.strip()}  ({candidate})")
                return candidate
        except FileNotFoundError:
            continue
    print("❌ yt-dlp não encontrado. Instale com: brew install yt-dlp")
    sys.exit(1)


def _base_flags(browser: str, out_dir: Path, prefix: str) -> list:
    """Flags comuns a todos os modos de download."""
    return [
        # --- Autenticação via cookies reais do browser ---
        "--cookies-from-browser", browser,

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


def download_video(yt: str, url: str, out_dir: Path, prefix: str,
                   browser: str = "chrome") -> bool:
    """Baixa vídeo + legendas."""
    cmd = [yt] + _base_flags(browser, out_dir, prefix) + [
        "--format", FORMAT_BEST,
        "--merge-output-format", "mp4",

        # --- Legendas ---
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", SUB_LANGS,
        "--sub-format", "srt/vtt/best",
        "--convert-subs", "srt",

        url,
    ]
    return _run(cmd, "Vídeo + legendas")


def download_subs_only(yt: str, url: str, out_dir: Path, prefix: str,
                       browser: str = "chrome") -> bool:
    """Baixa apenas as legendas (sem vídeo)."""
    cmd = [yt] + _base_flags(browser, out_dir, prefix) + [
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", SUB_LANGS,
        "--sub-format", "srt/vtt/best",
        "--convert-subs", "srt",

        url,
    ]
    return _run(cmd, "Só legendas")


def download_video_only(yt: str, url: str, out_dir: Path, prefix: str,
                        browser: str = "chrome") -> bool:
    """Baixa apenas o vídeo (sem legendas)."""
    cmd = [yt] + _base_flags(browser, out_dir, prefix) + [
        "--format", FORMAT_BEST,
        "--merge-output-format", "mp4",
        url,
    ]
    return _run(cmd, "Só vídeo")


def _run(cmd: list, label: str) -> bool:
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
    _print_tips()
    return False


def _print_tips():
    print("\n💡 Dicas de solução:")
    print("  • 403 em TODOS os fragmentos = provável proxy corporativo (Netskope).")
    print("    As URLs de mídia do YouTube são travadas por IP; se o proxy sai por")
    print("    um IP diferente do visto na extração, todo download dá 403.")
    print("    → Baixe fora da rede corporativa (ex.: hotspot) ou exclua")
    print("      *.googlevideo.com da interceptação do Netskope.")
    print("  • Confirme que está logado no YouTube no Chrome/Firefox.")
    print("  • Tente --browser firefox se o Chrome não funcionar.")
    print("  • Para PO token: container 'bgutil-provider' deve estar rodando")
    print("    (docker ps) e o yt-dlp precisa ser recente (brew).")
    print("  • Atualize o yt-dlp: brew upgrade yt-dlp")


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
        description="Baixa vídeos do YouTube de forma confiável via yt-dlp com cookies do browser.",
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
        help="Browser do qual ler os cookies (padrão: chrome).",
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
    print(f"🍪 Browser: {args.browser}")

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
