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
ROMS_DRIVE_OVERRIDE=""
ROMS_MOUNT_OVERRIDE=""

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
    --roms-drive)
      ROMS_DRIVE_OVERRIDE="$2"
      shift 2
      ;;
    --roms-mount)
      ROMS_MOUNT_OVERRIDE="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--no-assets] [--assets] [--name NAME] [--roms-drive F] [--roms-mount /mnt/f]"
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

echo "Attempting to mount Windows drives via PowerShell..."
# Mount all Windows drives that exist (D:, E:, F:, etc.)
DRIVE_LETTERS=$(powershell.exe -NoProfile -Command "$d=Get-Volume ^| ? DriveLetter ^| % DriveLetter; $d -join ' '" 2>/dev/null | tr -d '\r') || true
if [ -n "$DRIVE_LETTERS" ]; then
  for L in $DRIVE_LETTERS; do
    l=$(echo "$L" | tr '[:upper:]' '[:lower:]')
    sudo mkdir -p "/mnt/$l" 2>/dev/null || true
    if ! mountpoint -q "/mnt/$l" 2>/dev/null; then
      sudo mount -t drvfs "${L}:" "/mnt/$l" 2>/dev/null || true
    fi
  done
fi

echo "Detecting ROMS partition (prefer F:, else largest free space)..."
R36S_ROMS_MOUNT=""

# If user forced drive or mount, honor it
if [ -n "$ROMS_MOUNT_OVERRIDE" ]; then
  R36S_ROMS_MOUNT="$ROMS_MOUNT_OVERRIDE"
elif [ -n "$ROMS_DRIVE_OVERRIDE" ]; then
  TRY_DRIVES=("$ROMS_DRIVE_OVERRIDE" F D E G H)
else
  TRY_DRIVES=(F D E G H)
fi

declare -a CANDIDATES=()
for DRIVE in "${TRY_DRIVES[@]}"; do
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
      free_kb=$(df -k "$M" 2>/dev/null | awk 'NR==2{print $4}')
      [ -n "$free_kb" ] || free_kb=0
      CANDIDATES+=("$M:$free_kb")
    fi
  fi
done

# Choose best mount: prefer /mnt/f if present, else largest free space
if [ -z "$R36S_ROMS_MOUNT" ]; then
  for ent in "${CANDIDATES[@]}"; do
    m=${ent%%:*}
    if [ "$m" = "/mnt/f" ]; then R36S_ROMS_MOUNT="$m"; break; fi
  done
  if [ -z "$R36S_ROMS_MOUNT" ]; then
    best=""; bestv=0
    for ent in "${CANDIDATES[@]}"; do
      m=${ent%%:*}; v=${ent##*:}
      # numeric compare; default 0
      [ -n "$v" ] || v=0
      if [ "$v" -gt "$bestv" ]; then best="$m"; bestv="$v"; fi
    done
    R36S_ROMS_MOUNT="$best"
  fi
fi

if [ -z "$R36S_ROMS_MOUNT" ]; then
  echo "ERROR: Could not detect ROMS partition (D:/ F:/ etc)." >&2
  echo "Please mount your SD card and re-run." >&2
  exit 1
fi

echo "→ Using ROMS partition: $R36S_ROMS_MOUNT"
DEST_DIR="$R36S_ROMS_MOUNT/roms/ports/0_${PORT_NAME}"
echo "Installing to: $DEST_DIR"
sudo mkdir -p "$R36S_ROMS_MOUNT/roms/ports"
sudo rm -rf "$DEST_DIR"
sudo mkdir -p "$DEST_DIR"
sudo cp -r "$PKG_ROOT"/* "$DEST_DIR"/

# 4.1) Update EmulationStation gamelist.xml for Ports
PORTS_GAMELIST="$R36S_ROMS_MOUNT/roms/ports/gamelist.xml"
GAME_PATH="./0_${PORT_NAME}/${PORT_NAME}.sh"

echo "Updating Ports gamelist: $PORTS_GAMELIST"
if [ ! -f "$PORTS_GAMELIST" ]; then
  # Create minimal gamelist with our entry
  sudo tee "$PORTS_GAMELIST" > /dev/null <<EOF
<?xml version="1.0"?>
<gameList>
  <game>
    <path>$GAME_PATH</path>
    <name>R36S Viewer</name>
    <desc>Subtitle/image viewer for R36S</desc>
  </game>
</gameList>
EOF
else
  # Append entry if not already present, before </gameList>
  if ! grep -q "<path>$GAME_PATH</path>" "$PORTS_GAMELIST" 2>/dev/null; then
    tmpfile=$(mktemp)
    awk -v node="  <game>\n    <path>$GAME_PATH</path>\n    <name>R36S Viewer</name>\n    <desc>Subtitle/image viewer for R36S</desc>\n  </game>\n" '
      /<\/gameList>/ { print node; print; next }
      { print }
    ' "$PORTS_GAMELIST" > "$tmpfile" && sudo mv "$tmpfile" "$PORTS_GAMELIST"
  else
    echo "Entry already present in gamelist.xml"
  fi
fi

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
