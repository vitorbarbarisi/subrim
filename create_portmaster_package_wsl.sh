#!/bin/bash

# Build ARM binary, package PortMaster structure, and deploy to SD card (WSL)
# Usage:
#   ./create_portmaster_package_wsl.sh [--no-assets] [--name NAME]
#
# Defaults:
#   - Copies ./assets into data/assets (unless --no-assets)
#   - Installs to /roms/ports/0_r36s_viewer on the ROMS partition

set -euo pipefail

COPY_ASSETS=true
PORT_NAME="r36s_viewer"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-assets)
      COPY_ASSETS=false
      shift
      ;;
    --assets)
      COPY_ASSETS=true
      shift
      ;;
    --name)
      PORT_NAME="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--no-assets] [--assets] [--name NAME]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

echo "=== Build + Package PortMaster (WSL) ==="

# 1) Ensure ARM binary exists
if [ ! -f "build_r36s/r36s_viewer" ]; then
  echo "Building ARM binary with build_simple_arm.sh..."
  if [ ! -x ./build_simple_arm.sh ]; then
    echo "ERROR: build_simple_arm.sh not found or not executable" >&2
    exit 1
  fi
  ./build_simple_arm.sh
fi

if [ ! -f "build_r36s/r36s_viewer" ]; then
  echo "ERROR: r36s_viewer binary not found after build" >&2
  exit 1
fi

# 2) Create PortMaster package structure
PKG_ROOT="build_portmaster/0_${PORT_NAME}"
rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/bin" "$PKG_ROOT/data"

cp -f build_r36s/r36s_viewer "$PKG_ROOT/bin/"
chmod +x "$PKG_ROOT/bin/r36s_viewer"

echo "Creating launcher..."
cat > "$PKG_ROOT/${PORT_NAME}.sh" << 'LAUNCH_EOF'
#!/bin/sh
DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P)"
cd "$DIR"

export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
export SDL_AUDIODRIVER=alsa

# Prefer bundled assets, else try global
if [ -d "./data/assets" ]; then
  ln -snf ./data/assets ./assets 2>/dev/null || true
elif [ -d "./assets" ]; then
  :
elif [ -d "/storage/roms/r36s_viewer_assets" ]; then
  ln -snf /storage/roms/r36s_viewer_assets ./assets 2>/dev/null || true
fi

exec ./bin/r36s_viewer "$@"
LAUNCH_EOF
chmod +x "$PKG_ROOT/${PORT_NAME}.sh"

echo "Creating port.json..."
cat > "$PKG_ROOT/port.json" << PORT_EOF
{
  "name": "R36S Viewer",
  "description": "Subtitle/image viewer for R36S",
  "author": "R36S Team",
  "version": "1.0.0",
  "arch": ["armhf", "armv7"],
  "exec": "${PORT_NAME}.sh",
  "data_dir": "data",
  "bin_dir": "bin"
}
PORT_EOF

# 3) Copy assets if requested
if [ "$COPY_ASSETS" = true ] && [ -d "assets" ]; then
  echo "Copying assets into package..."
  mkdir -p "$PKG_ROOT/data"
  cp -r assets "$PKG_ROOT/data/" 2>/dev/null || true
  echo "✓ Assets included at $PKG_ROOT/data/assets"
else
  echo "Assets not included (use --assets to include)"
fi

# 4) Detect ROMS partition and install to /roms/ports

echo "Detecting ROMS partition..."
R36S_ROMS_MOUNT=""
for DRIVE in D F E G H; do
  M="/mnt/${DRIVE,,}"
  sudo mkdir -p "$M" 2>/dev/null || true
  if [ -d "$M" ] && mountpoint -q "$M"; then
    :
  else
    sudo mount -t drvfs "${DRIVE}:" "$M" 2>/dev/null || true
  fi
  if [ -d "$M" ]; then
    contents=$(ls "$M" 2>/dev/null | tr '\n' ' ' | head -c 200)
    if echo "$contents" | grep -qiE "(EASYROMS|roms|ports|gba|snes|nes|psx)"; then
      R36S_ROMS_MOUNT="$M"
      echo "→ Using ROMS partition: $M"
      break
    fi
  fi
done

if [ -z "$R36S_ROMS_MOUNT" ]; then
  echo "ERROR: Could not detect ROMS partition (D:/ F:/ etc)." >&2
  echo "Please mount your SD card and re-run." >&2
  exit 1
fi

DEST_DIR="$R36S_ROMS_MOUNT/roms/ports/0_${PORT_NAME}"
echo "Installing to: $DEST_DIR"
sudo mkdir -p "$R36S_ROMS_MOUNT/roms/ports"
sudo rm -rf "$DEST_DIR"
sudo mkdir -p "$DEST_DIR"
sudo cp -r "$PKG_ROOT"/* "$DEST_DIR"/

# 5) Summary
echo
echo "=== PortMaster package installed ==="
echo "Launcher: $DEST_DIR/${PORT_NAME}.sh"
echo "Binary:   $DEST_DIR/bin/r36s_viewer"
if [ -d "$DEST_DIR/data/assets" ]; then
  echo "Assets:   $DEST_DIR/data/assets (included)"
else
  echo "Assets:   not included (place episodes later or use --assets)"
fi

echo
echo "Open on console: Ports → 0_${PORT_NAME} → ${PORT_NAME}.sh"
