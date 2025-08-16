#!/bin/bash

# Prepare R36S installation package
# This script creates a ready-to-copy folder structure for the R36S SD card

set -e

echo "=== Preparing R36S Viewer Package ==="

# Check if executable exists
if [ ! -f "build_r36s/r36s_viewer" ]; then
    echo "ERROR: r36s_viewer executable not found!"
    echo "Run ./build_for_r36s.sh first"
    exit 1
fi

# Create package directory
PACKAGE_DIR="r36s_viewer_package"
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

# Copy the main executable
cp build_r36s/r36s_viewer "$PACKAGE_DIR/"
echo "✓ Copied executable"

# Copy assets folder if it exists
if [ -d "assets" ]; then
    cp -r assets "$PACKAGE_DIR/"
    echo "✓ Copied assets folder"
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

# Create installer script
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

echo ""
echo "=== Package ready! ==="
echo "Directory: $PACKAGE_DIR"
echo ""
echo "Next steps:"
echo "1. Copy the '$PACKAGE_DIR' folder to your R36S SD card"
echo "2. On R36S, run: sudo ./$PACKAGE_DIR/install_to_r36s.sh"
echo "3. Launch with: r36s_viewer"
