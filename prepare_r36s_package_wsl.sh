#!/bin/bash

# Prepare R36S installation package - WSL version
# Run this inside WSL after building
# Usage: ./prepare_r36s_package_wsl.sh

set -e

echo "=== Preparing R36S Viewer Package (WSL) ==="
echo

# Check if executable exists
if [ ! -f "build_r36s/r36s_viewer" ]; then
    echo "ERROR: r36s_viewer executable not found!"
    echo "Run ./build_for_r36s_wsl.sh first"
    exit 1
fi

echo "✓ Found executable: build_r36s/r36s_viewer"

# Create package directory
PACKAGE_DIR="r36s_viewer_package"
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

echo "✓ Created package directory: $PACKAGE_DIR"

# Copy the main executable
cp build_r36s/r36s_viewer "$PACKAGE_DIR/"
chmod +x "$PACKAGE_DIR/r36s_viewer"
echo "✓ Copied executable"

# Copy assets folder if it exists
if [ -d "assets" ]; then
    cp -r assets "$PACKAGE_DIR/"
    echo "✓ Copied assets folder ($(find assets -name "*.png" | wc -l) images)"
else
    mkdir -p "$PACKAGE_DIR/assets"
    echo "✓ Created empty assets folder"
fi

# Create launch script for R36S
cat > "$PACKAGE_DIR/launch_viewer.sh" << 'EOF'
#!/bin/bash
# R36S Viewer Launcher

# Get script directory
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Set environment for SDL2 (if needed)
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0

# Launch the viewer
./r36s_viewer "$@"
EOF

chmod +x "$PACKAGE_DIR/launch_viewer.sh"
echo "✓ Created launch script"

# Create desktop entry for the R36S menu system
cat > "$PACKAGE_DIR/r36s_viewer.desktop" << 'EOF'
[Desktop Entry]
Name=Subtitle Viewer
Comment=View subtitles and images
Exec=/opt/r36s_viewer/launch_viewer.sh
Icon=/opt/r36s_viewer/icon.png
Terminal=false
Type=Application
Categories=Game;
EOF

echo "✓ Created desktop entry"

# Create installation instructions
cat > "$PACKAGE_DIR/INSTALL.txt" << 'EOF'
=== R36S Viewer Installation ===

1. Copy this entire folder to your R36S SD card
2. Connect to R36S via SSH or use terminal
3. Run the install script: ./install_to_r36s.sh
4. The viewer will be available in the applications menu

Usage:
- Run without arguments to see menu of available assets
- Run with directory name: ./r36s_viewer chaves001
- Use game controller or keyboard for navigation

Controls:
- A/X: Next image
- B/Y: Previous image  
- Start: Toggle subtitle display
- Select: Toggle fullscreen/windowed mode
- L/R: Fast navigation
EOF

echo "✓ Created installation instructions"

# Create installer script for R36S
cat > "$PACKAGE_DIR/install_to_r36s.sh" << 'EOF'
#!/bin/bash

# R36S Viewer Installer
set -e

echo "=== Installing R36S Viewer ==="

# Target directory
TARGET_DIR="/opt/r36s_viewer"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./install_to_r36s.sh"
    exit 1
fi

# Create target directory
mkdir -p "$TARGET_DIR"

# Copy files
cp r36s_viewer "$TARGET_DIR/"
cp launch_viewer.sh "$TARGET_DIR/"
cp -r assets "$TARGET_DIR/" 2>/dev/null || true

# Set permissions
chmod +x "$TARGET_DIR/r36s_viewer"
chmod +x "$TARGET_DIR/launch_viewer.sh"

# Install desktop entry (if desktop environment exists)
if [ -d "/usr/share/applications" ]; then
    cp r36s_viewer.desktop /usr/share/applications/
    echo "✓ Desktop entry installed"
fi

# Create symlink for easy access
ln -sf "$TARGET_DIR/launch_viewer.sh" /usr/local/bin/r36s_viewer

echo "✓ Installation complete!"
echo ""
echo "Usage:"
echo "  r36s_viewer              # Show menu of available content"
echo "  r36s_viewer chaves001    # View specific episode"
echo "  r36s_viewer /path/to/images  # View custom image folder"
EOF

chmod +x "$PACKAGE_DIR/install_to_r36s.sh"
echo "✓ Created installer script"

# Create uninstaller
cat > "$PACKAGE_DIR/uninstall.sh" << 'EOF'
#!/bin/bash
# Uninstaller for R36S Viewer

echo "Removing R36S Viewer..."

# Remove from system
sudo rm -rf /opt/r36s_viewer

# Remove desktop entry
sudo rm -f /usr/share/applications/r36s_viewer.desktop

# Remove symlink
sudo rm -f /usr/local/bin/r36s_viewer

echo "R36S Viewer removed successfully"
EOF

chmod +x "$PACKAGE_DIR/uninstall.sh"
echo "✓ Created uninstaller"

# Create a simple copy script for Windows access
cat > "$PACKAGE_DIR/copy_to_windows.sh" << 'EOF'
#!/bin/bash
# Copy package to Windows accessible location
# Usage: ./copy_to_windows.sh [destination]

DEST_DIR="${1:-/mnt/c/Users/$USER/Desktop/r36s_viewer_package}"

echo "Copying R36S package to Windows location..."
echo "Destination: $DEST_DIR"

mkdir -p "$DEST_DIR"
cp -r . "$DEST_DIR/"

echo "✓ Package copied to: $DEST_DIR"
echo "You can now access it from Windows at:"
echo "C:\\Users\\$USER\\Desktop\\r36s_viewer_package"
EOF

chmod +x "$PACKAGE_DIR/copy_to_windows.sh"
echo "✓ Created Windows copy script"

# Generate package info
cat > "$PACKAGE_DIR/package_info.txt" << EOF
R36S Viewer Package Information
===============================

Build Date: $(date)
Build Host: $(hostname)
WSL Version: $(cat /proc/version | grep -o 'WSL[0-9]*' || echo "Unknown")
Executable Size: $(ls -lh build_r36s/r36s_viewer | awk '{print $5}')
Assets Count: $(find assets -name "*.png" 2>/dev/null | wc -l) images

Package Contents:
- r36s_viewer (ARM Linux executable)
- launch_viewer.sh (startup script)
- install_to_r36s.sh (system installer)
- uninstall.sh (removal script)
- assets/ (subtitle episodes and images)

Installation:
1. Copy entire folder to R36S SD card
2. On R36S: sudo ./install_to_r36s.sh
3. Run: r36s_viewer
EOF

echo "✓ Created package info"

echo
echo "=== Package Ready! ==="
echo "Directory: $PACKAGE_DIR"
echo "Contents:"
ls -la "$PACKAGE_DIR/"

echo
echo "Package size: $(du -sh "$PACKAGE_DIR" | cut -f1)"
echo

echo "Next steps:"
echo
echo "For R36S SD Card (Linux mount):"
echo "  cp -r $PACKAGE_DIR /media/\$USER/R36S-OS/apps/"
echo
echo "For Windows access:"
echo "  cd $PACKAGE_DIR && ./copy_to_windows.sh"
echo
echo "For direct SD card copy:"
echo "  ./copy_to_sd_card_wsl.sh"
echo

echo "Package preparation complete! 🎉"
