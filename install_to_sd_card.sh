#!/bin/bash

# Direct installation to R36S SD Card
# This script copies the viewer directly to the mounted SD card

set -e

echo "=== R36S Viewer SD Card Installation ==="

# Default mount points (adjust if different)
R36S_OS_MOUNT="/Volumes/R36S-OS V50 16GB"  # macOS
EASYROMS_MOUNT="/Volumes/EASYROMS"           # macOS

# Linux alternatives (uncomment if using Linux)
# R36S_OS_MOUNT="/media/R36S-OS V50 16GB"
# EASYROMS_MOUNT="/media/EASYROMS"

# Check if package exists
if [ ! -d "r36s_viewer_package" ]; then
    echo "ERROR: Package not found! Run ./prepare_r36s_package.sh first"
    exit 1
fi

echo "Looking for R36S SD card mounts..."

# Check for R36S-OS partition
if [ ! -d "$R36S_OS_MOUNT" ]; then
    echo "ERROR: R36S-OS partition not found at: $R36S_OS_MOUNT"
    echo "Please ensure the SD card is mounted and update the mount path in this script"
    exit 1
fi

echo "✓ Found R36S-OS partition: $R36S_OS_MOUNT"

# Check for EASYROMS partition  
if [ ! -d "$EASYROMS_MOUNT" ]; then
    echo "WARNING: EASYROMS partition not found at: $EASYROMS_MOUNT"
    echo "This is optional - viewer will work without it"
else
    echo "✓ Found EASYROMS partition: $EASYROMS_MOUNT"
fi

# Create applications directory on R36S-OS
APPS_DIR="$R36S_OS_MOUNT/apps"
VIEWER_DIR="$APPS_DIR/r36s_viewer"

echo "Creating application directory..."
mkdir -p "$APPS_DIR"
rm -rf "$VIEWER_DIR"
mkdir -p "$VIEWER_DIR"

# Copy viewer files to R36S-OS
echo "Copying viewer files..."
cp -r r36s_viewer_package/* "$VIEWER_DIR/"

# Copy assets to EASYROMS if available (better for large files)
if [ -d "$EASYROMS_MOUNT" ]; then
    echo "Copying assets to EASYROMS for better performance..."
    ASSETS_DIR="$EASYROMS_MOUNT/r36s_viewer_assets"
    rm -rf "$ASSETS_DIR"
    
    if [ -d "assets" ]; then
        cp -r assets "$ASSETS_DIR"
        echo "✓ Assets copied to EASYROMS"
        
        # Create symlink on R36S-OS pointing to EASYROMS
        rm -rf "$VIEWER_DIR/assets"
        # Note: This symlink will work on the R36S Linux system
        echo "ln -sf /storage/roms/r36s_viewer_assets \$DIR/assets" >> "$VIEWER_DIR/launch_viewer.sh.tmp"
        mv "$VIEWER_DIR/launch_viewer.sh" "$VIEWER_DIR/launch_viewer.sh.orig"
        
        # Update launch script to handle symlink
        cat > "$VIEWER_DIR/launch_viewer.sh" << 'EOF'
#!/bin/bash
# R36S Viewer Launcher with EASYROMS assets support

# Get script directory
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Create symlink to assets on EASYROMS if not exists
if [ ! -L "assets" ] && [ -d "/storage/roms/r36s_viewer_assets" ]; then
    ln -sf /storage/roms/r36s_viewer_assets assets
fi

# Set environment for SDL2 (if needed)
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0

# Launch the viewer
./r36s_viewer "$@"
EOF
        chmod +x "$VIEWER_DIR/launch_viewer.sh"
    fi
fi

# Create autostart entry (optional - for direct boot to viewer)
cat > "$VIEWER_DIR/autostart.sh" << 'EOF'
#!/bin/bash
# Optional: Auto-start viewer on boot
# To enable: copy this file to /etc/autostart/ on R36S

# Wait for system to fully boot
sleep 5

# Start viewer in fullscreen
/apps/r36s_viewer/launch_viewer.sh

EOF

chmod +x "$VIEWER_DIR/autostart.sh"

# Create uninstaller
cat > "$VIEWER_DIR/uninstall.sh" << 'EOF'
#!/bin/bash
# Uninstaller for R36S Viewer

echo "Removing R36S Viewer..."

# Remove from R36S-OS
rm -rf /apps/r36s_viewer

# Remove from EASYROMS
rm -rf /storage/roms/r36s_viewer_assets

# Remove desktop entry
rm -f /usr/share/applications/r36s_viewer.desktop

# Remove symlink
rm -f /usr/local/bin/r36s_viewer

echo "R36S Viewer removed successfully"
EOF

chmod +x "$VIEWER_DIR/uninstall.sh"

echo ""
echo "=== Installation Complete! ==="
echo ""
echo "Viewer installed to: $VIEWER_DIR"
if [ -d "$EASYROMS_MOUNT" ]; then
    echo "Assets stored in: $EASYROMS_MOUNT/r36s_viewer_assets"
fi
echo ""
echo "On your R36S console:"
echo "1. Insert the SD card"
echo "2. Navigate to: /apps/r36s_viewer/"
echo "3. Run: sudo ./install_to_r36s.sh"
echo "4. Or run directly: ./launch_viewer.sh"
echo ""
echo "Controls:"
echo "- D-pad/Analog: Navigate"
echo "- A button: Next image"
echo "- B button: Previous image"
echo "- Start: Toggle subtitles"
echo "- Select: Menu/Exit"
echo ""
echo "Usage examples:"
echo "- ./launch_viewer.sh                    # Show episode menu"
echo "- ./launch_viewer.sh chaves001          # View specific episode"
echo "- ./launch_viewer.sh --windowed         # Run in windowed mode"
