#!/bin/bash

# Build GBA ROM using devkitPro/devkitarm Docker image (no apt/pacman needed)
# Then deploy to SD card via deploy_gba_direct.sh

set -euo pipefail

echo "=== Build GBA using Docker (devkitARM) ==="

# 1) Check Docker
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker não encontrado. Instale Docker Desktop no Windows e reinicie o WSL."
  echo "Download: https://www.docker.com/products/docker-desktop/"
  echo "Fallback: gerando ROM standalone simples..."
  if [ -x ./create_gba_welcome.sh ]; then
    ./create_gba_welcome.sh
  elif [ -x ./create_gba_standalone.sh ]; then
    ./create_gba_standalone.sh
  else
    echo "Sem fallback disponível."
    exit 1
  fi
  bash ./deploy_gba_direct.sh
  exit 0
fi

# 2) Clone template se necessário
TEMPLATE_DIR="gba-template"
if [ ! -d "$TEMPLATE_DIR" ]; then
  echo "Clonando gba-template (devkitPro)..."
  git clone https://github.com/devkitPro/gba-template.git "$TEMPLATE_DIR"
fi

# 3) Build dentro do container
echo "Baixando imagem devkitpro/devkitarm (se necessário)..."
docker pull devkitpro/devkitarm:latest >/dev/null

echo "Compilando dentro do container..."
docker run --rm -v "$PWD":/work -w /work/"$TEMPLATE_DIR" devkitpro/devkitarm:latest bash -lc "make clean && make"

if [ ! -f "$TEMPLATE_DIR/build/gba-template.gba" ]; then
  echo "❌ Build falhou: arquivo não encontrado: $TEMPLATE_DIR/build/gba-template.gba"
  exit 1
fi

# 4) Preparar para deploy
mkdir -p r36s_viewer_gba
cp -f "$TEMPLATE_DIR/build/gba-template.gba" r36s_viewer_gba/viewer.gba

# 5) Deploy
if [ ! -x ./deploy_gba_direct.sh ]; then
  echo "❌ deploy_gba_direct.sh não encontrado ou sem execução"
  exit 1
fi

echo "Deployando ROM para o SD..."
bash ./deploy_gba_direct.sh

echo "\n✅ Concluído. Abra no console: GBA → 0_R36S_Viewer"
