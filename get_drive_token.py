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
"""

import argparse
import json
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

CONFIG = Path(__file__).parent / "google_drive_config.json"
SCOPE = "https://www.googleapis.com/auth/drive"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class _CallbackHandler(BaseHTTPRequestHandler):
    code = None
    state = None
    error = None

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.error = params.get("error", [None])[0]
        got_state = params.get("state", [None])[0]
        if got_state == _CallbackHandler.state:
            _CallbackHandler.code = params.get("code", [None])[0]
        ok = _CallbackHandler.code and not _CallbackHandler.error
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("Autenticacao concluida! Pode fechar esta aba e voltar ao terminal."
               if ok else "Falha na autenticacao. Veja o terminal.")
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


def main() -> int:
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

    # Servidor local em porta livre para receber o callback do OAuth.
    server = HTTPServer(("localhost", 0), _CallbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://localhost:{port}"

    state = secrets.token_urlsafe(16)
    _CallbackHandler.state = state

    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # necessário para receber refresh_token
        "prompt": "consent",        # força o consentimento e o refresh_token
        "state": state,
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    print("🔐 Abrindo o navegador para autorizar o acesso ao Google Drive...")
    print(f"   Se não abrir, acesse manualmente:\n   {auth_url}\n")
    webbrowser.open(auth_url)

    print(f"⏳ Aguardando o retorno em {redirect_uri} ...")
    server.handle_request()  # bloqueia até o callback chegar
    server.server_close()

    if _CallbackHandler.error:
        print(f"❌ Autorização negada: {_CallbackHandler.error}")
        return 1
    code = _CallbackHandler.code
    if not code:
        print("❌ Não recebi o código de autorização (state inválido ou cancelado).")
        return 1

    print("🔁 Trocando o código por tokens...")
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
        print(f"❌ Falha ao obter tokens [status {resp.status_code}]: {resp.text}")
        return 1

    tok = resp.json()
    refresh_token = tok.get("refresh_token")
    if not refresh_token:
        print("⚠️  A resposta não trouxe refresh_token.")
        print("   Revogue o acesso em https://myaccount.google.com/permissions e rode de novo")
        print("   (o prompt=consent já força isso, mas contas que já autorizaram podem reusar).")
        return 1

    cfg.update({
        "access_token": tok.get("access_token", ""),
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    cfg.setdefault("folder_id", "")
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✅ Credenciais salvas em {CONFIG.name}")
    print("   Já pode rodar: python3 merge_chunks.py <asset>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
