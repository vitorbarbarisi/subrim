#!/bin/bash

# Deploy R36S Viewer as Port Game directly to SD card
# Creates and installs the viewer as a "game" in the Ports section

set -e

echo "=== Deploy R36S Viewer as Port Game ==="
echo

# Parse command line arguments (reuse from deploy_precompiled)
COPY_ASSETS=true
HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-assets)
            COPY_ASSETS=false
            shift
            ;;
        --assets)
            COPY_ASSETS=true
            shift
            ;;
        --help|-h)
            HELP=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            HELP=true
            shift
            ;;
    esac
done

if [ "$HELP" = true ]; then
    echo "Usage: $0 [OPTIONS]"
    echo
    echo "Deploy R36S Viewer as a Port Game (appears in games list)"
    echo
    echo "Options:"
    echo "  --assets      Include episode assets (default)"
    echo "  --no-assets   Deploy game only (no episodes)"
    echo "  --help, -h    Show this help message"
    echo
    echo "The viewer will appear in the Ports section like any other game!"
    exit 0
fi

# Check if we have ARM binary
if [ ! -f "build_r36s/r36s_viewer" ]; then
    echo "Building ARM binary first..."
    ./build_simple_arm.sh
fi

echo "✓ ARM binary available"

# Detect R36S partitions (same logic as deploy_precompiled)
echo "Detecting R36S SD card partitions..."

R36S_OS_MOUNT=""
R36S_ROMS_MOUNT=""

for priority_drive in "D" "F"; do
    mount_point="/mnt/${priority_drive,,}"
    sudo mkdir -p "$mount_point" 2>/dev/null || true
    
    if [ -d "$mount_point" ] && mountpoint -q "$mount_point"; then
        echo "✓ ${priority_drive}: already mounted at $mount_point"
    elif sudo mount -t drvfs "${priority_drive}:" "$mount_point" 2>/dev/null; then
        echo "✓ ${priority_drive}: mounted successfully at $mount_point"
    else
        echo "ℹ ${priority_drive}: not available"
        continue
    fi
    
    if [ -d "$mount_point" ]; then
        contents=$(ls "$mount_point" 2>/dev/null | head -10 | tr '\n' ' ' || echo "")
        
        if [[ "$contents" =~ (RetroArch|apps|WHERE_ARE_MY_ROMS) ]]; then
            R36S_OS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: (R36S-OS - System)"
        elif [[ "$contents" =~ (EASYROMS|roms|ports|3do|advision|alg|amiga|arcade) ]]; then
            R36S_ROMS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: (EASYROMS - ROMs/Ports)"
        fi
    fi
done

echo
echo "🎯 R36S Partition Detection:"
echo "   System (OS):  ${R36S_OS_MOUNT:-"Not found"}"
echo "   ROMs/Ports:   ${R36S_ROMS_MOUNT:-"Not found"}"

# Determine where to install the port
if [ -n "$R36S_ROMS_MOUNT" ]; then
    PORTS_BASE="$R36S_ROMS_MOUNT"
    echo "✅ Will install port on F: drive (EASYROMS)"
elif [ -n "$R36S_OS_MOUNT" ]; then
    PORTS_BASE="$R36S_OS_MOUNT"
    echo "⚠ Will install port on D: drive (system partition)"
else
    echo "❌ No R36S partitions found!"
    echo "Make sure SD card is inserted and mounted"
    exit 1
fi

# Find or create ports directory
PORTS_LOCATIONS=("$PORTS_BASE/roms/ports" "$PORTS_BASE/ports" "$PORTS_BASE/ROMS/PORTS" "$PORTS_BASE/games/ports")
PORTS_DIR=""

# Try to find existing ports directory
for location in "${PORTS_LOCATIONS[@]}"; do
    if [ -d "$location" ]; then
        PORTS_DIR="$location"
        echo "✓ Found existing ports directory: $PORTS_DIR"
        break
    fi
done

# If not found, create it
if [ -z "$PORTS_DIR" ]; then
    PORTS_DIR="$PORTS_BASE/roms/ports"
    echo "Creating ports directory: $PORTS_DIR"
    mkdir -p "$PORTS_DIR"
fi

# Create the port installation
PORT_INSTALL_DIR="$PORTS_DIR/R36S_Viewer"
echo
echo "🎮 Installing R36S Viewer as Port Game..."
echo "   Location: $PORT_INSTALL_DIR"

rm -rf "$PORT_INSTALL_DIR"
mkdir -p "$PORT_INSTALL_DIR"

# Copy ARM binary
cp build_r36s/r36s_viewer "$PORT_INSTALL_DIR/"
chmod +x "$PORT_INSTALL_DIR/r36s_viewer"
echo "✓ ARM binary installed"

# Copy assets if requested
if [ "$COPY_ASSETS" = true ] && [ -d "assets" ]; then
    cp -r assets "$PORT_INSTALL_DIR/"
    echo "✓ Episode assets copied"
    ASSETS_INFO="✅ Episodes included"
elif [ "$COPY_ASSETS" = false ]; then
    echo "📁 Assets skipped (--no-assets flag)"
    ASSETS_INFO="⚠ Episodes not included (use --assets)"
else
    echo "⚠ No assets folder found"
    ASSETS_INFO="⚠ No episodes found"
fi

# Create main launcher (what ArkOS will execute)
cat > "$PORT_INSTALL_DIR/R36S Viewer.sh" << 'EOF'
#!/bin/bash

# R36S Viewer - Port Game Launcher
# Executed by ArkOS when user selects the game

cd "$(dirname "$0")"

# Set SDL2 environment for R36S console
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
export SDL_AUDIODRIVER=alsa

# Set display to fullscreen
export SDL_FULLSCREEN=1

# Launch the viewer
echo "Starting R36S Viewer..."
./r36s_viewer "$@"
EOF

chmod +x "$PORT_INSTALL_DIR/R36S Viewer.sh"
echo "✓ Main launcher created"

# Create alternative launchers for compatibility
cat > "$PORT_INSTALL_DIR/launch.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
./r36s_viewer
EOF

chmod +x "$PORT_INSTALL_DIR/launch.sh"

# Create START file (no extension)
cat > "$PORT_INSTALL_DIR/START" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
./r36s_viewer
EOF

chmod +x "$PORT_INSTALL_DIR/START"
echo "✓ Alternative launchers created"

# Create port description
cat > "$PORT_INSTALL_DIR/description.txt" << EOF
R36S Viewer - Episode Subtitle Viewer

A native ARM application for viewing episodes with synchronized
subtitles on the R36S console. 

Features:
- Native ARM performance
- Episode navigation
- Synchronized subtitles
- Fullscreen video playback
- No internet required

Controls:
- D-Pad: Navigate menus and episodes  
- A: Select/Play
- B: Back/Exit
- Start: Toggle subtitles
- Select: Menu/Options

$ASSETS_INFO

Created: $(date)
EOF

echo "✓ Description file created"

echo
echo "🎉 R36S Viewer Port Installation Complete!"
echo
echo "📁 Installed at: $PORT_INSTALL_DIR"
echo "🎮 Will appear in: ArkOS → Ports → R36S Viewer"
echo
echo "🚀 How to use on R36S console:"
echo "   1. Navigate to main menu"
echo "   2. Select 'Ports' or 'Games'"  
echo "   3. Find 'R36S Viewer'"
echo "   4. Press A to launch like any game!"
echo
echo "📋 Port contents:"
ls -la "$PORT_INSTALL_DIR" | sed 's/^/   /'
echo
echo "✅ Ready to use as a port game!"
echo "   $ASSETS_INFO"
echo
echo "🎬 Launch from ArkOS Ports menu! 🎯✨"
