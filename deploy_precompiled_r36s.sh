#!/bin/bash

# Deploy precompiled R36S Viewer (cross-compiled binary ready to run)
# No terminal/SSH needed on R36S - just copy and run!

set -e

echo "=== Precompiled R36S Deploy (No Terminal Needed) ==="
echo

# Check if we have ARM binary ready
if [ ! -f "build_r36s/r36s_viewer" ]; then
    echo "No ARM binary found, building now..."
    
    # Use simple ARM build
    echo "Using simple ARM build (avoids SDL2 linking issues)..."
    ./build_simple_arm.sh
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Simple ARM build failed"
        exit 1
    fi
fi

# Check if binary exists now
if [ ! -f "build_r36s/r36s_viewer" ]; then
    echo "ERROR: No ARM binary available. Please run build script first."
    exit 1
fi

echo "✓ ARM binary found: $(file build_r36s/r36s_viewer 2>/dev/null || echo 'ARM binary')"

# Find R36S partitions (reuse logic from smart deploy)
R36S_OS_MOUNT=""
R36S_ROMS_MOUNT=""

echo "Detecting R36S SD card partitions..."

# Quick check for D: drive first, then F: (smart mount detection)
R36S_CANDIDATES=()
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
    
    # Check if this looks like R36S and identify type
    if [ -d "$mount_point" ]; then
        contents=$(ls "$mount_point" 2>/dev/null | head -10 | tr '\n' ' ' || echo "")
        partition_type=""
        
        if [[ "$contents" =~ (RetroArch|apps|WHERE_ARE_MY_ROMS) ]]; then
            partition_type="(R36S-OS - System)"
            R36S_OS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: $partition_type"
        elif [[ "$contents" =~ (EASYROMS|roms|3do|advision|alg|amiga|arcade|atari|gb|gba|gbc|genesis|mame|n64|nes|psx|snes) ]]; then
            partition_type="(EASYROMS - Assets)"  
            R36S_ROMS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: $partition_type"
        elif [[ "$priority_drive" == "F" && "$contents" =~ (3do|advision|alg|amiga) ]]; then
            # Special case: F: drive with emulator folders is likely EASYROMS
            partition_type="(EASYROMS - Assets)"  
            R36S_ROMS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: $partition_type"
        else
            echo "  → ${priority_drive}: Contents: $contents"
        fi
    fi
done

echo
echo "🎯 R36S Partition Detection:"
echo "   System (OS):  ${R36S_OS_MOUNT:-"Not found"}"
echo "   Assets (ROM): ${R36S_ROMS_MOUNT:-"Not found"}"
echo

# Determine installation strategy
if [ -n "$R36S_OS_MOUNT" ]; then
    echo "✅ Perfect! Using optimized installation:"
    echo "   📱 App → $R36S_OS_MOUNT (System partition)"
    if [ -n "$R36S_ROMS_MOUNT" ]; then
        echo "   📁 Assets → $R36S_ROMS_MOUNT (Assets partition)"
        USE_DUAL_PARTITION=true
    else
        echo "   📁 Assets → $R36S_OS_MOUNT (Same partition)"
        USE_DUAL_PARTITION=false
    fi
elif [ -n "$R36S_ROMS_MOUNT" ]; then
    echo "⚠ Only assets partition found, installing everything there:"
    R36S_OS_MOUNT="$R36S_ROMS_MOUNT"  # Use ROMS partition for everything
    USE_DUAL_PARTITION=false
else
    echo "ERROR: R36S partitions not found!"
    echo "Make sure SD card is inserted and has proper drive letters (D:, F:)"
    echo
    echo "Manual mount commands:"
    echo "   sudo mount -t drvfs D: /mnt/d"
    echo "   sudo mount -t drvfs F: /mnt/f"
    exit 1
fi

echo
echo "🎯 Creating precompiled installation..."

# Create installation directory
INSTALL_DIR="$R36S_OS_MOUNT/r36s_viewer_precompiled"
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# Copy precompiled binary
echo "Copying precompiled ARM binary..."
cp build_r36s/r36s_viewer "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/r36s_viewer"

# Copy source files as backup
echo "Copying source files (backup)..."
if [ -d "build_r36s" ]; then
    cp build_r36s/*.c "$INSTALL_DIR/" 2>/dev/null || true
    cp build_r36s/*.h "$INSTALL_DIR/" 2>/dev/null || true
fi

# Copy assets to appropriate partition
if [ -n "$R36S_ROMS_MOUNT" ] && [ -d "assets" ]; then
    echo "Copying assets to assets partition..."
    ASSETS_DIR="$R36S_ROMS_MOUNT/r36s_viewer_assets"
    rm -rf "$ASSETS_DIR"
    cp -r assets "$ASSETS_DIR"
    echo "✓ Assets copied to $ASSETS_DIR"
    
    # Create symlink setup for launcher
    LAUNCHER_ASSETS_PATH="/storage/roms/r36s_viewer_assets"
elif [ -d "assets" ]; then
    echo "Copying assets to same partition..."
    cp -r assets "$INSTALL_DIR/"
    echo "✓ Assets copied to $INSTALL_DIR/assets"
    
    LAUNCHER_ASSETS_PATH="./assets"
else
    echo "⚠ No assets folder found"
    LAUNCHER_ASSETS_PATH="./assets"
fi

# Create launcher script (no compilation needed)
cat > "$INSTALL_DIR/run_viewer.sh" << EOF
#!/bin/bash
# R36S Viewer Launcher - Precompiled Version

cd "\$(dirname "\$0")"

# Create assets symlink if using dual partition
if [ ! -d "assets" ] && [ -d "$LAUNCHER_ASSETS_PATH" ]; then
    ln -sf "$LAUNCHER_ASSETS_PATH" assets
fi

# Set SDL2 environment for R36S
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0

# Run precompiled viewer
./r36s_viewer "\$@"
EOF

chmod +x "$INSTALL_DIR/run_viewer.sh"
echo "✓ Created launcher script"

# Create auto-installer that doesn't need compilation
cat > "$INSTALL_DIR/install_precompiled.sh" << 'EOF'
#!/bin/bash
# Precompiled R36S Viewer Installer - No compilation needed!

echo "=== Installing Precompiled R36S Viewer ==="

INSTALL_PATH="/opt/r36s_viewer"
SOURCE_DIR="$(dirname "$0")"

# Create installation directory
sudo mkdir -p "$INSTALL_PATH"

# Copy precompiled binary and launcher
sudo cp "$SOURCE_DIR/r36s_viewer" "$INSTALL_PATH/"
sudo cp "$SOURCE_DIR/run_viewer.sh" "$INSTALL_PATH/"
sudo chmod +x "$INSTALL_PATH/r36s_viewer"
sudo chmod +x "$INSTALL_PATH/run_viewer.sh"

# Copy assets if they exist locally
if [ -d "$SOURCE_DIR/assets" ]; then
    sudo cp -r "$SOURCE_DIR/assets" "$INSTALL_PATH/"
fi

# Create global command
sudo ln -sf "$INSTALL_PATH/run_viewer.sh" /usr/local/bin/r36s_viewer

# Create desktop entry
sudo tee /usr/share/applications/r36s_viewer.desktop > /dev/null << 'DESKTOP_EOF'
[Desktop Entry]
Name=R36S Viewer
Comment=Precompiled subtitle viewer
Exec=/opt/r36s_viewer/run_viewer.sh
Terminal=false
Type=Application
Categories=Game;
DESKTOP_EOF

echo "✅ Precompiled R36S Viewer installed!"
echo ""
echo "Usage:"
echo "  r36s_viewer                # Show episode menu"
echo "  r36s_viewer chaves001      # View specific episode"
echo ""
echo "No compilation needed - ready to run!"
EOF

chmod +x "$INSTALL_DIR/install_precompiled.sh"
echo "✓ Created precompiled installer"

# Create simple runner for SD card root
cat > "$R36S_OS_MOUNT/run_r36s_viewer.sh" << EOF
#!/bin/bash
# Direct runner for R36S Viewer (no installation needed)

cd "\$(dirname "\$0")/r36s_viewer_precompiled"
./run_viewer.sh "\$@"
EOF

chmod +x "$R36S_OS_MOUNT/run_r36s_viewer.sh"
echo "✓ Created direct runner"

# Create instructions file
cat > "$R36S_OS_MOUNT/R36S_VIEWER_INSTRUCTIONS.txt" << 'EOF'
R36S Viewer - Precompiled Version (No Terminal Needed!)
=======================================================

OPTION 1 - Direct Run (No Installation):
   Just double-click: run_r36s_viewer.sh

OPTION 2 - Install to System:
   1. Open file manager on R36S
   2. Navigate to: r36s_viewer_precompiled/
   3. Run: install_precompiled.sh
   4. Then use: r36s_viewer command

FILES ON SD CARD:
- run_r36s_viewer.sh               (direct runner)
- r36s_viewer_precompiled/         (main folder)
  ├── r36s_viewer                  (ARM binary - ready to run!)
  ├── run_viewer.sh                (launcher script)
  ├── install_precompiled.sh       (system installer)
  └── assets/                      (episodes - if copied)

CONTROLS:
- A/X: Next image
- B/Y: Previous image  
- Start: Toggle subtitles
- Select: Menu/Exit
- L/R: Fast navigation

No compilation, no terminal, no SSH needed!
Just run the scripts with file manager.
EOF

echo "✓ Created instructions file"

echo
echo "=== Precompiled Deploy Complete! ==="
echo
echo "📁 Files ready on R36S SD card:"
echo "   $R36S_OS_MOUNT/run_r36s_viewer.sh (direct runner)"
echo "   $R36S_OS_MOUNT/r36s_viewer_precompiled/ (main installation)"
if [ -n "$R36S_ROMS_MOUNT" ]; then
    echo "   $R36S_ROMS_MOUNT/r36s_viewer_assets/ (episodes)"
fi

echo
echo "🎮 On R36S (NO TERMINAL NEEDED):"
echo "   Option 1: File Manager → run_r36s_viewer.sh (direct run)"
echo "   Option 2: File Manager → r36s_viewer_precompiled/install_precompiled.sh (install)"
echo
echo "✅ Precompiled ARM binary ready to run!"
echo "   No compilation, no terminal, no SSH required!"
echo

# Show binary info
if [ -f "$INSTALL_DIR/r36s_viewer" ]; then
    echo "📊 Binary info:"
    file "$INSTALL_DIR/r36s_viewer" 2>/dev/null || echo "ARM executable"
    ls -lh "$INSTALL_DIR/r36s_viewer" | awk '{print "Size: " $5}'
fi

echo
echo "🎬 Ready for R36S! 🎯✨"
