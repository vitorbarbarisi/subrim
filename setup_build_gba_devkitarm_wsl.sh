#!/bin/bash

# Setup devkitARM (devkitPro) on WSL, build a GBA ROM using official template,
# and deploy it to the R36S SD card using our deploy script.

set -euo pipefail

echo "=== Setup + Build GBA (devkitARM) on WSL ==="

# 0) Ensure running with bash
if [ -z "${BASH_VERSION:-}" ]; then
  echo "This script must be run with bash" >&2
  exit 1
fi

# 1) Prereqs
sudo apt-get update -y
sudo apt-get install -y wget git make tar xz-utils ca-certificates

# 2) Install devkitPro pacman and gba-dev (devkitARM + libgba)
if ! command -v dkp-pacman >/dev/null 2>&1; then
  echo "Installing devkitPro pacman..."
  wget -O install-devkitpro-pacman https://apt.devkitpro.org/install-devkitpro-pacman
  sudo bash install-devkitpro-pacman
fi

# Reload env if needed
if [ -f /etc/profile.d/devkitpro.sh ]; then
  source /etc/profile.d/devkitpro.sh || true
fi

# Fallback env exports in case current shell doesn't get the profile
export DEVKITPRO=${DEVKITPRO:-/opt/devkitpro}
export DEVKITARM=${DEVKITARM:-$DEVKITPRO/devkitARM}
export PATH=$PATH:$DEVKITPRO/tools/bin

if ! command -v dkp-pacman >/dev/null 2>&1; then
  echo "ERROR: dkp-pacman not found after install" >&2
  exit 1
fi

# Install GBA toolchain
sudo dkp-pacman -S --noconfirm gba-dev || true

# 3) Clone official GBA template (if not exists)
TEMPLATE_DIR="gba-template"
if [ ! -d "$TEMPLATE_DIR" ]; then
  echo "Cloning devkitPro gba-template..."
  git clone https://github.com/devkitPro/gba-template.git "$TEMPLATE_DIR"
fi

# 4) Build ROM
cd "$TEMPLATE_DIR"
# Ensure make uses the right toolchain
export DEVKITPRO
export DEVKITARM
export PATH=$PATH:$DEVKITARM/bin

echo "Building GBA template..."
make clean || true
make

if [ ! -f build/gba-template.gba ]; then
  echo "ERROR: Build did not produce build/gba-template.gba" >&2
  exit 1
fi

# 5) Prepare for our deploy script (expects r36s_viewer_gba/viewer.gba)
cd ..
mkdir -p r36s_viewer_gba
cp -f "$TEMPLATE_DIR/build/gba-template.gba" r36s_viewer_gba/viewer.gba

# 6) Deploy to SD card using our robust deployer
if [ ! -x ./deploy_gba_direct.sh ]; then
  echo "ERROR: deploy_gba_direct.sh not found or not executable" >&2
  exit 1
fi

echo "Deploying ROM to SD card..."
# Force bash to avoid /bin/sh bad substitution issues
bash ./deploy_gba_direct.sh

echo
echo "✅ GBA ROM built and deployed!"
echo "   Look for: 0_R36S_Viewer.gba (top of GBA list)"
echo "   Menu path: Game Boy Advance → 0_R36S_Viewer"
