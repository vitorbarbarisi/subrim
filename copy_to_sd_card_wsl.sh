#!/bin/bash

# Copy R36S Viewer to SD Card - WSL version
# Run this inside WSL with R36S SD card mounted
# Usage: ./copy_to_sd_card_wsl.sh

set -e

echo "=== R36S Viewer SD Card Installation (WSL) ==="
echo

# Check if package exists
if [ ! -d "r36s_viewer_package" ]; then
    echo "ERROR: Package not found!"
    echo "Run ./prepare_r36s_package_wsl.sh first"
    exit 1
fi

echo "✓ Found package: r36s_viewer_package"

# Common mount points for SD card in WSL
R36S_MOUNTS=(
    "/media/$USER/R36S-OS V50 16GB"
    "/media/$USER/R36S-OS"
    "/mnt/r36s"
    "/media/r36s"
    "/mnt/d"
    "/mnt/e"
)

EASYROMS_MOUNTS=(
    "/media/$USER/EASYROMS"
    "/mnt/easyroms"
    "/mnt/f"
    "/mnt/g"
)

echo "Searching for R36S SD card mounts..."

# Find R36S-OS partition
R36S_MOUNT=""
for mount in "${R36S_MOUNTS[@]}"; do
    if [ -d "$mount" ]; then
        R36S_MOUNT="$mount"
        echo "✓ Found R36S-OS partition: $mount"
        break
    fi
done

if [ -z "$R36S_MOUNT" ]; then
    echo "ERROR: R36S-OS partition not found!"
    echo
    echo "Searched locations:"
    for mount in "${R36S_MOUNTS[@]}"; do
        echo "  $mount"
    done
    echo
    echo "Manual mounting options:"
    echo "1. Mount manually:"
    echo "   sudo mkdir -p /mnt/r36s"
    echo "   sudo mount /dev/sdX1 /mnt/r36s  # Replace X with correct letter"
    echo
    echo "2. Check available drives:"
    echo "   lsblk"
    echo "   fdisk -l"
    echo
    echo "3. Or mount Windows drives (if SD card shows as D:):"
    echo "   ls /mnt/d/  # Check if this is the R36S partition"
    exit 1
fi

# Find EASYROMS partition (optional)
EASYROMS_MOUNT=""
for mount in "${EASYROMS_MOUNTS[@]}"; do
    if [ -d "$mount" ]; then
        EASYROMS_MOUNT="$mount"
        echo "✓ Found EASYROMS partition: $mount"
        break
    fi
done

if [ -z "$EASYROMS_MOUNT" ]; then
    echo "⚠ EASYROMS partition not found (optional)"
    echo "Assets will be stored on R36S-OS partition"
fi

# Create application directory
APPS_DIR="$R36S_MOUNT/apps"
VIEWER_DIR="$APPS_DIR/r36s_viewer"

echo
echo "Creating installation directories..."
mkdir -p "$APPS_DIR"

if [ -d "$VIEWER_DIR" ]; then
    echo "Removing existing installation..."
    rm -rf "$VIEWER_DIR"
fi

mkdir -p "$VIEWER_DIR"
echo "✓ Created: $VIEWER_DIR"

# Copy viewer files
echo
echo "Copying R36S Viewer files..."
cp -r r36s_viewer_package/* "$VIEWER_DIR/"
echo "✓ Files copied to R36S-OS partition"

# Handle assets optimization
if [ -n "$EASYROMS_MOUNT" ] && [ -d "assets" ]; then
    echo
    echo "Optimizing assets storage..."
    
    ASSETS_TARGET="$EASYROMS_MOUNT/r36s_viewer_assets"
    
    # Remove existing assets on EASYROMS
    if [ -d "$ASSETS_TARGET" ]; then
        rm -rf "$ASSETS_TARGET"
    fi
    
    # Copy assets to EASYROMS
    cp -r assets "$ASSETS_TARGET"
    echo "✓ Assets copied to EASYROMS: $ASSETS_TARGET"
    
    # Remove assets from R36S-OS and create symlink setup
    rm -rf "$VIEWER_DIR/assets"
    
    # Update launch script to create symlink
    cat > "$VIEWER_DIR/launch_viewer.sh" << 'EOF'
#!/bin/bash
# R36S Viewer Launcher with EASYROMS assets support

# Get script directory
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Create symlink to assets on EASYROMS if not exists
if [ ! -L "assets" ] && [ -d "/storage/roms/r36s_viewer_assets" ]; then
    ln -sf /storage/roms/r36s_viewer_assets assets
elif [ ! -L "assets" ] && [ -d "/media/EASYROMS/r36s_viewer_assets" ]; then
    ln -sf /media/EASYROMS/r36s_viewer_assets assets
fi

# Set environment for SDL2 (if needed)
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0

# Launch the viewer
./r36s_viewer "$@"
EOF
    
    chmod +x "$VIEWER_DIR/launch_viewer.sh"
    echo "✓ Updated launch script for EASYROMS assets"
fi

# Set proper permissions
echo
echo "Setting permissions..."
chmod +x "$VIEWER_DIR/r36s_viewer"
chmod +x "$VIEWER_DIR"/*.sh
echo "✓ Permissions set"

# Create quick access script on R36S-OS root
cat > "$R36S_MOUNT/run_viewer.sh" << 'EOF'
#!/bin/bash
# Quick launcher for R36S Viewer
cd /apps/r36s_viewer
./launch_viewer.sh "$@"
EOF

chmod +x "$R36S_MOUNT/run_viewer.sh"
echo "✓ Created quick launcher: run_viewer.sh"

# Generate installation summary
cat > "$VIEWER_DIR/INSTALLATION_LOG.txt" << EOF
R36S Viewer Installation Log
============================

Installation Date: $(date)
Installation Host: $(hostname)
WSL Environment: $(cat /proc/version | head -1)

Locations:
- R36S-OS Mount: $R36S_MOUNT
- EASYROMS Mount: ${EASYROMS_MOUNT:-"Not found"}
- Viewer Directory: $VIEWER_DIR
- Assets Location: ${EASYROMS_MOUNT:+$EASYROMS_MOUNT/r36s_viewer_assets}${EASYROMS_MOUNT:-"$VIEWER_DIR/assets"}

Files Installed:
$(ls -la "$VIEWER_DIR/")

Next Steps on R36S Console:
1. sudo /apps/r36s_viewer/install_to_r36s.sh
2. r36s_viewer

Quick Access:
- /run_viewer.sh (from SD card root)
- /apps/r36s_viewer/launch_viewer.sh
EOF

echo "✓ Created installation log"

echo
echo "=== Installation Complete! ==="
echo
echo "📍 Installation Summary:"
echo "   R36S-OS: $R36S_MOUNT"
echo "   Viewer: $VIEWER_DIR"
if [ -n "$EASYROMS_MOUNT" ]; then
    echo "   Assets: $EASYROMS_MOUNT/r36s_viewer_assets"
else
    echo "   Assets: $VIEWER_DIR/assets"
fi

echo
echo "🎮 On your R36S console:"
echo "1. Insert the SD card"
echo "2. Boot the console"
echo "3. Run: sudo /apps/r36s_viewer/install_to_r36s.sh"
echo "4. Launch: r36s_viewer"
echo
echo "⚡ Quick access options:"
echo "- ./run_viewer.sh (from SD root)"
echo "- r36s_viewer chaves001"
echo "- r36s_viewer --windowed"

echo
echo "Installation successful! 🎉"

# Show disk usage
echo
echo "💾 Disk usage:"
du -sh "$VIEWER_DIR"
if [ -n "$EASYROMS_MOUNT" ] && [ -d "$EASYROMS_MOUNT/r36s_viewer_assets" ]; then
    du -sh "$EASYROMS_MOUNT/r36s_viewer_assets"
fi
