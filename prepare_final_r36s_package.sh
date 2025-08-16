#!/bin/bash

# Prepare final R36S package (run this after successful minimal build)
# Usage: ./prepare_final_r36s_package.sh

set -e

echo "=== Preparing Final R36S Package ==="
echo

# Check if minimal build was successful
if [ ! -f "build_minimal/r36s_source_package.tar.gz" ]; then
    echo "ERROR: Minimal build not found!"
    echo "Run ./build_minimal_r36s.sh first"
    exit 1
fi

echo "✓ Found minimal build package"

# Create final package directory
FINAL_PACKAGE="r36s_viewer_final_package"
rm -rf "$FINAL_PACKAGE"
mkdir -p "$FINAL_PACKAGE"

echo "✓ Created final package directory: $FINAL_PACKAGE"

# Extract source package
cd "$FINAL_PACKAGE"
tar xzf "../build_minimal/r36s_source_package.tar.gz"
echo "✓ Extracted source files"

# Add installation scripts
cat > install_r36s_viewer.sh << 'EOF'
#!/bin/bash
# Complete R36S Viewer installation script
# Run this on R36S console

echo "=== R36S Viewer Installation ==="
echo

# Update system
echo "Updating system packages..."
sudo apt-get update

# Install SDL2 dependencies
echo "Installing SDL2 development libraries..."
sudo apt-get install -y \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-ttf-dev \
    build-essential \
    cmake

# Build the viewer
echo "Building R36S Viewer..."
./build_on_r36s.sh

if [ -f "r36s_viewer" ]; then
    echo "✅ Build successful!"
    
    # Install to system
    echo "Installing to system..."
    sudo mkdir -p /opt/r36s_viewer
    sudo cp r36s_viewer /opt/r36s_viewer/
    sudo cp *.h /opt/r36s_viewer/ 2>/dev/null || true
    
    # Create launcher script
    sudo tee /opt/r36s_viewer/launch_viewer.sh > /dev/null << 'LAUNCH_EOF'
#!/bin/bash
cd "$(dirname "$0")"
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
./r36s_viewer "$@"
LAUNCH_EOF
    
    sudo chmod +x /opt/r36s_viewer/launch_viewer.sh
    
    # Create system-wide command
    sudo ln -sf /opt/r36s_viewer/launch_viewer.sh /usr/local/bin/r36s_viewer
    
    # Create desktop entry
    sudo tee /usr/share/applications/r36s_viewer.desktop > /dev/null << 'DESKTOP_EOF'
[Desktop Entry]
Name=R36S Viewer
Comment=Subtitle and image viewer
Exec=/opt/r36s_viewer/launch_viewer.sh
Terminal=false
Type=Application
Categories=Game;Multimedia;
DESKTOP_EOF
    
    echo "✅ Installation complete!"
    echo ""
    echo "Usage:"
    echo "  r36s_viewer                    # Show episode menu"
    echo "  r36s_viewer chaves001          # View specific episode"
    echo "  r36s_viewer --windowed         # Debug mode"
    echo ""
    echo "Controls:"
    echo "  A: Next image     | Start: Toggle subtitles"
    echo "  B: Previous image | Select: Menu/Exit"
    echo "  L/R: Fast navigation"
    
else
    echo "❌ Build failed!"
    echo "Check build_on_r36s.sh output for errors"
    exit 1
fi
EOF

chmod +x install_r36s_viewer.sh
echo "✓ Created complete installation script"

# Add uninstaller
cat > uninstall_r36s_viewer.sh << 'EOF'
#!/bin/bash
# R36S Viewer uninstaller

echo "Removing R36S Viewer..."

sudo rm -rf /opt/r36s_viewer
sudo rm -f /usr/local/bin/r36s_viewer
sudo rm -f /usr/share/applications/r36s_viewer.desktop

echo "✅ R36S Viewer removed"
EOF

chmod +x uninstall_r36s_viewer.sh
echo "✓ Created uninstaller"

# Add README
cat > README_R36S.txt << 'EOF'
R36S Viewer - Complete Installation Package
==========================================

This package contains everything needed to build and install
the R36S Viewer on your R36S console.

QUICK INSTALL:
1. Copy this entire folder to your R36S
2. Run: sudo ./install_r36s_viewer.sh
3. Use: r36s_viewer

MANUAL INSTALL:
1. Install dependencies: sudo apt-get install libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev
2. Build: ./build_on_r36s.sh
3. Run: ./r36s_viewer

FILES:
- *.c, *.h: Source code
- build_on_r36s.sh: Native build script
- install_r36s_viewer.sh: Complete installer
- uninstall_r36s_viewer.sh: Uninstaller
- README_R36S.txt: This file

USAGE:
- r36s_viewer: Show episode menu
- r36s_viewer chaves001: View specific episode
- r36s_viewer --windowed: Debug mode

CONTROLS:
- A/X: Next image
- B/Y: Previous image
- Start: Toggle subtitles
- Select: Menu/Exit
- L/R: Fast navigation

For support or issues, check the build logs or try manual compilation.
EOF

echo "✓ Created README"

cd ..

# Create final compressed package
echo "Creating final compressed package..."
tar czf "${FINAL_PACKAGE}.tar.gz" "$FINAL_PACKAGE"

echo "✓ Final package created: ${FINAL_PACKAGE}.tar.gz"

# Show package info
echo
echo "=== Final Package Ready! ==="
echo "Package: ${FINAL_PACKAGE}.tar.gz"
echo "Size: $(ls -lh ${FINAL_PACKAGE}.tar.gz | awk '{print $5}')"
echo
echo "Contents:"
ls -la "$FINAL_PACKAGE/"

echo
echo "📋 To install on R36S:"
echo "1. Copy ${FINAL_PACKAGE}.tar.gz to your R36S"
echo "2. Extract: tar xzf ${FINAL_PACKAGE}.tar.gz"
echo "3. cd ${FINAL_PACKAGE}"
echo "4. sudo ./install_r36s_viewer.sh"
echo "5. Run: r36s_viewer"

echo
echo "🎉 R36S Viewer package is ready for deployment!"
