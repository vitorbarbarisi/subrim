#!/bin/bash

# Complete R36S Viewer build and installation - WSL version
# Run this inside WSL Ubuntu
# Usage: ./build_and_install_r36s_wsl.sh

set -e

echo "============================================"
echo "    R36S Viewer - Complete WSL Setup       "
echo "============================================"
echo
echo "Environment: $(uname -a)"
echo "User: $(whoami)"
echo "PWD: $(pwd)"
echo

# Check WSL environment
if [[ -f /proc/version ]] && grep -q Microsoft /proc/version 2>/dev/null; then
    echo "✓ Running in WSL"
elif [[ -f /proc/version ]] && grep -q WSL /proc/version 2>/dev/null; then
    echo "✓ Running in WSL2"
else
    echo "⚠ Not detected as WSL (probably native Linux - should work)"
fi

echo

# Step 1: Build the viewer
echo "[1/3] Building R36S Viewer..."
echo "----------------------------------------"
./build_for_r36s_wsl.sh
if [ $? -ne 0 ]; then
    echo
    echo "❌ ERROR: Build failed! Cannot continue."
    exit 1
fi

echo
echo "✅ Build completed successfully!"
echo

# Step 2: Prepare the package
echo "[2/3] Preparing installation package..."
echo "----------------------------------------"
./prepare_r36s_package_wsl.sh
if [ $? -ne 0 ]; then
    echo
    echo "❌ ERROR: Package preparation failed!"
    exit 1
fi

echo
echo "✅ Package prepared successfully!"
echo

# Step 3: Check for SD card and offer installation
echo "[3/3] SD Card Installation..."
echo "----------------------------------------"

# Check if SD card appears to be mounted
SD_FOUND=false
for mount_point in "/media/$USER"/* "/mnt"/*; do
    if [ -d "$mount_point" ] && [[ "$mount_point" =~ (R36S|EASYROMS) ]]; then
        SD_FOUND=true
        break
    fi
done

if [ "$SD_FOUND" = true ]; then
    echo "🔍 R36S SD card appears to be mounted"
    echo
    read -p "Install directly to SD card now? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ./copy_to_sd_card_wsl.sh
        if [ $? -ne 0 ]; then
            echo
            echo "❌ ERROR: SD card installation failed!"
            echo "You can copy manually or try again later"
        else
            echo
            echo "✅ SD card installation completed!"
        fi
    else
        echo "⏭ Skipping SD card installation"
    fi
else
    echo "⚠ R36S SD card not detected"
    echo "You can:"
    echo "1. Mount SD card and run: ./copy_to_sd_card_wsl.sh"
    echo "2. Copy package manually to Windows: cd r36s_viewer_package && ./copy_to_windows.sh"
fi

echo
echo "============================================"
echo "    🎉 SETUP COMPLETE! 🎉"
echo "============================================"
echo
echo "📦 Package created: r36s_viewer_package/"
echo "📁 Package size: $(du -sh r36s_viewer_package | cut -f1)"

if [ -f "build_r36s/r36s_viewer" ]; then
    echo "🎯 Binary info: $(file build_r36s/r36s_viewer)"
    echo "📏 Binary size: $(ls -lh build_r36s/r36s_viewer | awk '{print $5}')"
fi

echo
echo "🚀 Next steps:"
echo

if [ "$SD_FOUND" = true ] && [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "✅ SD card ready! On your R36S:"
    echo "   1. Insert SD card"
    echo "   2. sudo /apps/r36s_viewer/install_to_r36s.sh"
    echo "   3. r36s_viewer"
else
    echo "📋 Manual installation options:"
    echo
    echo "   Option A - Direct SD card copy:"
    echo "   1. Mount R36S SD card in WSL"
    echo "   2. ./copy_to_sd_card_wsl.sh"
    echo
    echo "   Option B - Via Windows:"
    echo "   1. cd r36s_viewer_package"
    echo "   2. ./copy_to_windows.sh"
    echo "   3. Copy from Windows to SD card"
    echo
    echo "   Option C - Manual copy:"
    echo "   1. Copy r36s_viewer_package/ to SD card apps/ folder"
    echo "   2. On R36S: sudo /apps/r36s_viewer/install_to_r36s.sh"
fi

echo
echo "🎮 Usage on R36S:"
echo "   r36s_viewer                    # Episode menu"
echo "   r36s_viewer chaves001          # Specific episode"
echo "   r36s_viewer --windowed         # Debug mode"

echo
echo "🎯 Controls:"
echo "   A: Next image     |  Start: Toggle subtitles"
echo "   B: Previous image |  Select: Menu/Exit"
echo "   L/R: Fast navigation"

echo
echo "Enjoy your subtitle viewer on R36S! 🎬✨"
echo
