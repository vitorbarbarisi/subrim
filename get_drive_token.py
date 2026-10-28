#!/usr/bin/env python3
"""Gera/atualiza as credenciais OAuth do Google Drive em google_drive_config.json.

Executa o fluxo OAuth de aplicativo "Desktop" usando redirecionamento via
loopback (http://localhost:<porta>). Abre o navegador, captura o código de
autorização e troca por access_token + refresh_token. Usa apenas a biblioteca
``requests`` (já presente no projeto).

Uso:
    # Se client_id/client_secret já estiverem no google_drive_config.json:
    python3 get_drive_token.py

    # Ou informando explicitamente:
    python3 get_drive_token.py --client-id <ID> --client-secret <SECRET>

O fluxo é dividido para o Subrim Manager poder rodá-lo em duas máquinas:
``start_callback_server``/``wait_for_code`` rodam onde está o navegador (o
client) e ``auth_url``/``exchange_code`` rodam onde mora o
google_drive_config.json (o servidor, via /mgr/call).
"""

import argparse
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CONFIG = Path(__file__).parent / "google_drive_config.json"
SCOPE = "https://www.googleapis.com/auth/drive"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        srv = self.server
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in params and "error" not in params:
            self.send_response(404)     # favicon & cia.
            self.end_headers()
            return
        srv.oauth_error = params.get("error", [None])[0]
        if params.get("state", [None])[0] == srv.oauth_state:
            srv.oauth_code = params.get("code", [None])[0]
        ok = srv.oauth_code and not srv.oauth_error
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("Autenticacao concluida! Pode fechar esta aba."
               if ok else "Falha na autenticacao. Tente de novo.")
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode("utf-8"))

    def log_message(self, *args):
        pass  # silencia logs do http.server


def _load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── Lado do navegador ─────────────────────────────────────────────────────────

def start_callback_server(state: str):
    """Servidor local em porta livre para receber o callback do OAuth.
    Devolve ``(server, redirect_uri)``."""
    server = HTTPServer(("localhost", 0), _CallbackHandler)
    server.oauth_state = state
    server.oauth_code = None
    server.oauth_error = None
    return server, f"http://localhost:{server.server_address[1]}"


def wait_for_code(server, timeout: float = 300.0) -> str:
    """Bloqueia até o callback chegar (ou ``timeout``) e devolve o código."""
    deadline = time.monotonic() + timeout
    try:
        while not (server.oauth_code or server.oauth_error):
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("o login no navegador não foi concluído a tempo")
            server.timeout = min(left, 1.0)
            server.handle_request()
    finally:
        server.server_close()
    if server.oauth_error:
        raise PermissionError(f"autorização negada: {server.oauth_error}")
    return server.oauth_code


# ── Lado do google_drive_config.json ──────────────────────────────────────────

def auth_url(redirect_uri: str, state: str, client_id: str = "") -> str:
    """URL de consentimento do Google para o client_id do config."""
    client_id = client_id or _load_config().get("client_id")
    if not client_id:
        raise ValueError(f"falta client_id em {CONFIG.name}")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # necessário para receber refresh_token
        "prompt": "consent",        # força o consentimento e o refresh_token
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str, redirect_uri: str,
                  client_id: str = "", client_secret: str = "") -> str:
    """Troca o código por tokens e grava no config. Devolve o nome do arquivo."""
    import requests

    cfg = _load_config()
    client_id = client_id or cfg.get("client_id")
    client_secret = client_secret or cfg.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError(f"faltam client_id/client_secret em {CONFIG.name}")

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"falha ao obter tokens [status {resp.status_code}]: {resp.text}")

    tok = resp.json()
    refresh_token = tok.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "a resposta não trouxe refresh_token. Revogue o acesso em "
            "https://myaccount.google.com/permissions e tente de novo.")

    cfg.update({
        "access_token": tok.get("access_token", ""),
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    cfg.setdefault("folder_id", "")
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return CONFIG.name


def _main() -> int:
    parser = argparse.ArgumentParser(description="Gera o refresh_token do Google Drive")
    parser.add_argument("--client-id", help="OAuth client_id (...apps.googleusercontent.com)")
    parser.add_argument("--client-secret", help="OAuth client_secret (GOCSPX-...)")
    args = parser.parse_args()

    cfg = _load_config()
    client_id = args.client_id or cfg.get("client_id")
    client_secret = args.client_secret or cfg.get("client_secret")

    if not client_id or not client_secret:
        print("❌ Faltam client_id/client_secret.")
        print("   Passe via --client-id/--client-secret ou preencha no google_drive_config.json.")
        return 1

    state = secrets.token_urlsafe(16)
    server, redirect_uri = start_callback_server(state)
    url = auth_url(redirect_uri, state, client_id)

    print("🔐 Abrindo o navegador para autorizar o acesso ao Google Drive...")
    print(f"   Se não abrir, acesse manualmente:\n   {url}\n")
    webbrowser.open(url)

    print(f"⏳ Aguardando o retorno em {redirect_uri} ...")
    try:
        code = wait_for_code(server)
        print("🔁 Trocando o código por tokens...")
        name = exchange_code(code, redirect_uri, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        print(f"❌ {e}")
        return 1

    print(f"✅ Credenciais salvas em {name}")
    print("   Já pode rodar: python3 merge_chunks.py <asset>")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
