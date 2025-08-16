#!/bin/bash

# Create R36S Viewer as a "Port" game for ArkOS/R36S
# This makes it appear in the games list like any other game

set -e

echo "=== Creating R36S Viewer as Port Game ==="
echo

# Check if we have the binary
if [ ! -f "build_r36s/r36s_viewer" ]; then
    echo "Building ARM binary first..."
    ./build_simple_arm.sh
fi

# Check if we have assets
if [ ! -d "assets" ]; then
    echo "⚠ No assets folder found"
    echo "The port will work but won't have episodes to show"
fi

echo "✓ ARM binary available"
echo "✓ Creating port structure..."

# Create port directory structure
PORT_DIR="r36s_viewer_port"
rm -rf "$PORT_DIR"
mkdir -p "$PORT_DIR"

# Copy the ARM binary
cp build_r36s/r36s_viewer "$PORT_DIR/"
chmod +x "$PORT_DIR/r36s_viewer"

# Copy assets if available
if [ -d "assets" ]; then
    cp -r assets "$PORT_DIR/"
    echo "✓ Assets copied"
fi

# Create port launcher script (ArkOS style)
cat > "$PORT_DIR/R36S Viewer.sh" << 'EOF'
#!/bin/bash

# R36S Viewer Port Launcher
# This script runs the viewer as if it were a game

cd "$(dirname "$0")"

# Set SDL2 environment for R36S
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
export SDL_AUDIODRIVER=alsa

# Launch the viewer
./r36s_viewer "$@"
EOF

chmod +x "$PORT_DIR/R36S Viewer.sh"

# Create port info file (some ArkOS versions use this)
cat > "$PORT_DIR/R36S Viewer.txt" << 'EOF'
R36S Viewer - Episode Subtitle Viewer

A native ARM application for viewing episodes with subtitles
on the R36S console. Navigate episodes, view synchronized
subtitles, and enjoy your content.

Controls:
- D-Pad: Navigate menus and episodes
- A: Select/Play
- B: Back/Exit
- Start: Toggle subtitles
- Select: Menu/Options

Episodes are loaded from the assets/ directory.
No internet connection required.
EOF

# Create generic launcher (no extension for maximum compatibility)
cat > "$PORT_DIR/START" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
./r36s_viewer
EOF

chmod +x "$PORT_DIR/START"

echo "✓ Port structure created"

# Package as distributable archive
tar -czf "r36s_viewer_port.tar.gz" "$PORT_DIR"

echo
echo "🎮 R36S Viewer Port Created!"
echo
echo "📁 Port directory: $PORT_DIR/"
echo "📦 Archive: r36s_viewer_port.tar.gz"
echo
echo "🚀 Installation on R36S:"
echo "   1. Copy r36s_viewer_port.tar.gz to SD card"
echo "   2. Extract to: /roms/ports/ or /storage/roms/ports/"
echo "   3. The viewer will appear in the Ports section"
echo "   4. Launch like any other port/game"
echo
echo "📋 Alternative locations to try:"
echo "   - /roms/ports/r36s_viewer_port/"
echo "   - /storage/roms/ports/r36s_viewer_port/"
echo "   - /roms/linux/r36s_viewer_port/ (if linux section exists)"
echo
echo "✅ Ready to deploy as a port game!"
