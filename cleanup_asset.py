#!/usr/bin/env python3
"""
Clean-up de Asset - Arquiva o asset e libera espaço após o upload ao Drive.

Este script é executado SOB DEMANDA (não faz parte da pipeline). Para um asset
já finalizado (merge + upload ao Drive concluídos) ele:

  1. Verifica se o upload para o Google Drive ocorreu DE VERDADE (consulta a API
     usando o file_id gravado no marcador <asset>_drive.json). Se o arquivo não
     existir/estiver na lixeira, interrompe com erro e NADA mais é feito.
  2. Renomeia o arquivo base (ex.: 'capítulo ... _secs_base.txt') para o padrão
     do asset: '<asset>_base.txt' (ex.: clone40_base.txt).
  3. Envia o vídeo original (<asset>.mp4) e o arquivo base para o warehouse/.
  4. Verifica se o envio foi feito corretamente (existência + tamanho). Se sim,
     remove DEFINITIVAMENTE as pastas assets/<asset>/ e assets/<asset>_sub/.

Usage: python3 cleanup_asset.py <asset>
Example: python3 cleanup_asset.py clone40
"""

import argparse
import shutil
import sys
from pathlib import Path

import requests

# Reaproveita as credenciais e helpers de Drive do merge_chunks.
from merge_chunks import DRIVE_CONFIG, _drive_access_token  # noqa: E402

import json

REPO = Path(__file__).resolve().parent
ASSETS = REPO / "assets"
WAREHOUSE = REPO / "warehouse"


# ─── Etapa 1: validar upload no Drive ───────────────────────────────────────────
def _drive_file_info(token: str, file_id: str) -> dict | None:
    """Consulta a API do Drive e retorna metadados do arquivo (ou None se ausente)."""
    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "fields": "id,name,size,trashed",
            "supportsAllDrives": "true",
        },
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(
            f"Falha ao consultar o arquivo no Drive [status {resp.status_code}]: {resp.text}"
        )
    return resp.json()


def verify_drive_upload(asset: str, sub_dir: Path) -> bool:
    """Confirma que o vídeo final realmente está no Google Drive."""
    print("📋 ETAPA 1: Verificação do upload no Google Drive")

    marker = sub_dir / f"{asset}_drive.json"
    if not marker.exists():
        print(f"❌ Marcador de upload não encontrado: {marker.name}")
        print("   O upload para o Drive não foi registrado. Abortando — nada será removido.")
        return False

    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"❌ Não foi possível ler o marcador {marker.name}: {e}")
        return False

    file_id = info.get("file_id")
    if not file_id:
        print(f"❌ Marcador {marker.name} não contém 'file_id'. Abortando.")
        return False

    if not DRIVE_CONFIG.exists():
        print(f"❌ {DRIVE_CONFIG.name} não encontrado — impossível validar o upload.")
        return False
    try:
        cfg = json.loads(DRIVE_CONFIG.read_text(encoding="utf-8"))
        token = _drive_access_token(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Falha ao obter acesso ao Drive: {e}")
        return False

    print(f"🔎 Consultando o Drive pelo file_id={file_id} ...")
    try:
        drive_info = _drive_file_info(token, file_id)
    except Exception as e:  # noqa: BLE001
        print(f"❌ {e}")
        return False

    if drive_info is None:
        print("❌ Arquivo não encontrado no Drive (404). O upload NÃO ocorreu. Abortando.")
        return False
    if drive_info.get("trashed"):
        print("❌ O arquivo está na lixeira do Drive. Abortando — nada será removido.")
        return False

    drive_size = int(drive_info.get("size", 0))
    print(f"✅ Confirmado no Drive: {drive_info.get('name')} "
          f"({drive_size / 1e9:.2f} GB, id={drive_info.get('id')})")

    # Confronto opcional com o arquivo merged local, se ainda existir.
    merged = next(iter(sub_dir.glob(f"{asset}_chromecast_merged.mp4")), None) \
        or next(iter(sub_dir.glob("*_merged.mp4")), None)
    if merged and drive_size:
        local_size = merged.stat().st_size
        if local_size != drive_size:
            print(f"❌ Tamanho diverge: local={local_size} vs Drive={drive_size}. "
                  "Upload pode estar incompleto. Abortando.")
            return False
        print("✅ Tamanho do arquivo no Drive confere com o merged local.")

    return True


# ─── Etapa 2: renomear o arquivo base ───────────────────────────────────────────
def rename_base_file(asset: str, asset_dir: Path) -> Path | None:
    """Renomeia o '*_base.txt' do asset para '<asset>_base.txt'. Retorna o novo caminho."""
    print("\n📋 ETAPA 2: Renomear o arquivo base")

    target = asset_dir / f"{asset}_base.txt"
    if target.exists():
        print(f"✅ Base já está no padrão: {target.name}")
        return target

    bases = [b for b in asset_dir.glob("*base.txt") if b.suffix == ".txt"]
    if not bases:
        print(f"❌ Nenhum arquivo *_base.txt encontrado em {asset_dir.name}/")
        return None
    if len(bases) > 1:
        print(f"⚠️  {len(bases)} arquivos base encontrados; usando o maior:")
        for b in bases:
            print(f"     - {b.name} ({b.stat().st_size} bytes)")
        bases.sort(key=lambda p: p.stat().st_size, reverse=True)

    src = bases[0]
    src.rename(target)
    print(f"✅ Renomeado: {src.name}  →  {target.name}")
    return target


# ─── Etapa 3: localizar o vídeo original ─────────────────────────────────────────
def find_original_video(asset: str, asset_dir: Path) -> Path | None:
    """Retorna o vídeo original do asset (preferindo '<asset>.mp4')."""
    preferred = asset_dir / f"{asset}.mp4"
    if preferred.exists():
        return preferred
    mp4s = list(asset_dir.glob("*.mp4"))
    if len(mp4s) == 1:
        return mp4s[0]
    if not mp4s:
        print(f"❌ Nenhum vídeo .mp4 encontrado em {asset_dir.name}/")
    else:
        print(f"❌ Vídeo '{asset}.mp4' não encontrado e há {len(mp4s)} .mp4 ambíguos:")
        for m in mp4s:
            print(f"     - {m.name}")
    return None


# ─── Etapas 3+4: enviar ao warehouse e remover as pastas ─────────────────────────
def send_to_warehouse_and_cleanup(asset: str, asset_dir: Path, sub_dir: Path,
                                  video: Path, base: Path) -> bool:
    print("\n📋 ETAPA 3: Envio para o warehouse")
    WAREHOUSE.mkdir(parents=True, exist_ok=True)

    dest_video = WAREHOUSE / f"{asset}.mp4"
    dest_base = WAREHOUSE / f"{asset}_base.txt"

    for dest in (dest_video, dest_base):
        if dest.exists():
            print(f"❌ Já existe no warehouse: {dest.name}. Abortando para não sobrescrever.")
            return False

    video_size = video.stat().st_size
    base_size = base.stat().st_size

    print(f"📦 Movendo vídeo:  {video.name}  →  warehouse/{dest_video.name} "
          f"({video_size / 1e9:.2f} GB)")
    shutil.move(str(video), str(dest_video))
    print(f"📦 Movendo base:   {base.name}  →  warehouse/{dest_base.name}")
    shutil.move(str(base), str(dest_base))

    print("\n📋 ETAPA 4: Verificação do envio e limpeza")
    ok = True
    if not dest_video.exists() or dest_video.stat().st_size != video_size:
        print(f"❌ Verificação falhou para {dest_video.name} (ausente ou tamanho divergente).")
        ok = False
    if not dest_base.exists() or dest_base.stat().st_size != base_size:
        print(f"❌ Verificação falhou para {dest_base.name} (ausente ou tamanho divergente).")
        ok = False

    if not ok:
        print("❌ Envio ao warehouse não confirmado. As pastas NÃO serão removidas.")
        return False

    print("✅ Envio confirmado no warehouse (existência + tamanho conferem).")

    for folder in (asset_dir, sub_dir):
        if folder.exists():
            print(f"🗑️  Removendo pasta: {folder.relative_to(REPO)}")
            shutil.rmtree(folder)
        else:
            print(f"   (pasta {folder.name} já não existe)")

    print(f"\n🎉 Clean-up de '{asset}' concluído com sucesso!")
    print(f"   • warehouse/{dest_video.name}")
    print(f"   • warehouse/{dest_base.name}")
    print("   • pastas do asset removidas do disco.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Arquiva um asset finalizado no warehouse e remove as pastas locais.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pré-requisitos:
  - O merge final (<asset>_chromecast_merged.mp4) e o upload ao Drive já feitos.
  - O marcador assets/<asset>_sub/<asset>_drive.json deve existir e ser válido.

Exemplo:
  python3 cleanup_asset.py clone40
        """,
    )
    parser.add_argument("asset", help="Nome do asset (sem _sub)")
    args = parser.parse_args()
    asset = args.asset

    asset_dir = ASSETS / asset
    sub_dir = ASSETS / f"{asset}_sub"

    print("🧹 Clean-up de Asset")
    print("=" * 60)
    print(f"📂 Asset:     {asset_dir}")
    print(f"📂 Sub:       {sub_dir}")
    print(f"📂 Warehouse: {WAREHOUSE}")

    if not asset_dir.exists():
        print(f"\n❌ Pasta do asset não encontrada: {asset_dir}")
        return 1
    if not sub_dir.exists():
        print(f"\n❌ Pasta _sub não encontrada: {sub_dir}")
        print("   Sem ela não há marcador de upload para validar. Abortando.")
        return 1

    # Etapa 1 — bloqueante: sem upload confirmado, nada é feito.
    if not verify_drive_upload(asset, sub_dir):
        return 1

    # Etapa 2 — renomear base.
    base = rename_base_file(asset, asset_dir)
    if base is None:
        return 1

    # Localizar o vídeo original.
    video = find_original_video(asset, asset_dir)
    if video is None:
        return 1

    # Etapas 3 + 4 — enviar ao warehouse e (se confirmado) remover as pastas.
    if not send_to_warehouse_and_cleanup(asset, asset_dir, sub_dir, video, base):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
