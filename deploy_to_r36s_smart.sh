#!/bin/bash

# Smart deploy to R36S SD card with auto-mount detection and fixes
# Handles cases where SD card is mounted in Windows but not accessible in WSL

set -e

echo "=== Smart R36S Deploy with Mount Detection ==="
echo

# Check if package exists
PACKAGE_FILE="r36s_viewer_final_package.tar.gz"
if [ ! -f "$PACKAGE_FILE" ]; then
    echo "ERROR: Package not found: $PACKAGE_FILE"
    echo "Run ./prepare_final_r36s_package.sh first"
    exit 1
fi

echo "✓ Found package: $PACKAGE_FILE ($(ls -lh $PACKAGE_FILE | awk '{print $5}'))"
echo

# Function to try mounting a Windows drive
mount_windows_drive() {
    local drive_letter="$1"
    local mount_point="/mnt/${drive_letter,,}"  # lowercase
    
    if [ ! -d "$mount_point" ]; then
        echo "Creating mount point: $mount_point"
        sudo mkdir -p "$mount_point"
    fi
    
    if ! mountpoint -q "$mount_point"; then
        echo "Trying to mount Windows $drive_letter: → $mount_point"
        if sudo mount -t drvfs "$drive_letter:" "$mount_point" 2>/dev/null; then
            echo "✓ Successfully mounted $drive_letter: at $mount_point"
            return 0
        else
            echo "✗ Failed to mount $drive_letter:"
            return 1
        fi
    else
        echo "✓ $mount_point already mounted"
        return 0
    fi
}

# Check existing mounts
echo "Checking existing WSL mounts..."
echo "Available /mnt/ directories:"
ls -la /mnt/ 2>/dev/null || echo "  (none found)"
echo

# List of possible Windows drives for R36S SD card
POSSIBLE_DRIVES=("D" "E" "F" "G" "H")

# Try to mount Windows drives
echo "Attempting to mount Windows drives..."
for drive in "${POSSIBLE_DRIVES[@]}"; do
    mount_windows_drive "$drive"
done

echo

# Now look for R36S SD card
echo "Searching for R36S SD card..."
R36S_MOUNT=""

# Check all mounted drives
for mount_point in /mnt/*; do
    if [ -d "$mount_point" ] && [ "$mount_point" != "/mnt/wsl" ] && [ "$mount_point" != "/mnt/wslg" ]; then
        drive_name=$(basename "$mount_point")
        echo "Checking $mount_point ($drive_name)..."
        
        # List contents to help identify
        contents=$(ls "$mount_point" 2>/dev/null | head -5 | tr '\n' ' ' || echo "empty/inaccessible")
        echo "  Contents: $contents"
        
        # Check for R36S indicators
        if [ -d "$mount_point/RetroArch" ] || [ -d "$mount_point/EASYROMS" ] || 
           [ -d "$mount_point/apps" ] || [[ "$contents" =~ (retroarch|roms|apps|RetroArch) ]]; then
            R36S_MOUNT="$mount_point"
            echo "  ✓ Detected as R36S SD card!"
            break
        else
            echo "  ✗ Not R36S SD card"
        fi
    fi
done

# If not found automatically, let user choose
if [ -z "$R36S_MOUNT" ]; then
    echo
    echo "⚠ R36S SD card not auto-detected"
    echo
    echo "Available mount points:"
    for mount_point in /mnt/*; do
        if [ -d "$mount_point" ] && [ "$mount_point" != "/mnt/wsl" ] && [ "$mount_point" != "/mnt/wslg" ]; then
            contents=$(ls "$mount_point" 2>/dev/null | head -3 | tr '\n' ' ' || echo "inaccessible")
            echo "  $mount_point: $contents"
        fi
    done
    
    echo
    echo "Options:"
    echo "1. Enter mount point manually (e.g., /mnt/d)"
    echo "2. Try to mount specific Windows drive (e.g., D, E, F)"
    echo "3. Exit and mount manually"
    echo
    read -p "Choose option (1/2/3): " choice
    
    case $choice in
        1)
            read -p "Enter R36S mount point: " R36S_MOUNT
            if [ ! -d "$R36S_MOUNT" ]; then
                echo "ERROR: Directory not found: $R36S_MOUNT"
                exit 1
            fi
            ;;
        2)
            read -p "Enter Windows drive letter (D, E, F, etc.): " drive_letter
            drive_letter=$(echo "$drive_letter" | tr '[:lower:]' '[:upper:]')
            if mount_windows_drive "$drive_letter"; then
                R36S_MOUNT="/mnt/${drive_letter,,}"
            else
                echo "ERROR: Failed to mount drive $drive_letter"
                exit 1
            fi
            ;;
        3)
            echo "Manual mounting instructions:"
            echo "1. Find SD card: lsblk"
            echo "2. Create mount: sudo mkdir -p /mnt/r36s"  
            echo "3. Mount device: sudo mount /dev/sdX1 /mnt/r36s"
            echo "4. Or mount Windows drive: sudo mount -t drvfs D: /mnt/d"
            echo "5. Re-run this script"
            exit 1
            ;;
        *)
            echo "Invalid option"
            exit 1
            ;;
    esac
fi

echo
echo "Using R36S mount: $R36S_MOUNT"

# Verify it's writable
if ! touch "$R36S_MOUNT/.test_write" 2>/dev/null; then
    echo "ERROR: Cannot write to $R36S_MOUNT"
    echo "Try running with sudo or check mount permissions"
    exit 1
fi
rm -f "$R36S_MOUNT/.test_write"
echo "✓ Mount point is writable"

# Continue with deployment (same as original script)
INSTALL_DIR="$R36S_MOUNT/r36s_viewer_install"
echo
echo "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

echo "Copying package to SD card..."
cp "$PACKAGE_FILE" "$INSTALL_DIR/"
echo "✓ Package copied to SD card"

echo "Extracting package on SD card..."
cd "$INSTALL_DIR"
tar xzf "$PACKAGE_FILE"
rm "$PACKAGE_FILE"
echo "✓ Package extracted and cleaned up"

# Create quick installer on SD card root
cd "$R36S_MOUNT"
cat > quick_install_r36s_viewer.sh << 'EOF'
#!/bin/bash
echo "=== R36S Viewer Quick Install ==="
echo "Installing from SD card..."
cd "$(dirname "$0")/r36s_viewer_install/r36s_viewer_final_package"
sudo ./install_r36s_viewer.sh
echo "Installation complete! Use: r36s_viewer"
EOF

chmod +x quick_install_r36s_viewer.sh
echo "✓ Created quick installer"

# Create README
cat > R36S_VIEWER_README.txt << 'EOF'
R36S Viewer - Ready to Install!

On R36S console, run: ./quick_install_r36s_viewer.sh
Then use: r36s_viewer

Controls: A/B (navigate), Start (subtitles), Select (menu)
EOF

cd - > /dev/null

echo
echo "=== Smart Deploy Complete! ==="
echo "📁 SD card location: $R36S_MOUNT"
echo "💾 Installation size: $(du -sh $INSTALL_DIR | cut -f1)"
echo
echo "🎮 On R36S console:"
echo "   ./quick_install_r36s_viewer.sh"
echo
echo "Ready for R36S! 🎯✨"
