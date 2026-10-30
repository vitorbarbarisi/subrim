#!/usr/bin/env python3
"""Exporta do Chrome só os cookies da Globo para o cookies_globo.txt.

O servidor (WSL) não tem Chrome logado no Globoplay; o video_fetcher.py lá usa
este arquivo (formato Netscape). Rode no Mac, com o Chrome logado no
globoplay.globo.com, e mande o arquivo para o servidor:

  python3 tools/export_globo_cookies.py
  scp -p cookies_globo.txt barbarisi@192.168.0.132:dev/subrim/

O macOS pede acesso ao "Chrome Safe Storage" no Chaves: clique em Permitir.
Repita quando o download voltar a dar 401 (sessão expirada).
"""
import http.cookiejar
import sys
import time
from pathlib import Path

from yt_dlp.cookies import extract_cookies_from_browser

OUT = Path(__file__).resolve().parent.parent / "cookies_globo.txt"


def main() -> int:
    jar = extract_cookies_from_browser(sys.argv[1] if len(sys.argv) > 1 else "chrome")
    keep = http.cookiejar.MozillaCookieJar(str(OUT))
    for c in jar:
        if "globo" in c.domain:
            keep.set_cookie(c)
    if not len(keep):
        print("❌ Nenhum cookie da Globo — o navegador está logado no globoplay.globo.com?")
        return 1
    keep.save(ignore_discard=True, ignore_expires=True)
    OUT.chmod(0o600)
    login = [c for c in keep if c.name.upper().startswith("GLB")]
    print(f"✓ {len(keep)} cookie(s) da Globo em {OUT.name} "
          f"(login: {', '.join(sorted({c.name for c in login})) or 'nenhum GLB*'})")
    exp = [c.expires for c in login if c.expires]
    if exp:
        print(f"  a sessão expira em ~{(min(exp) - time.time()) / 86400:.0f} dia(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
