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

# Quick check for D: drive first, then F: (user specified priority)
echo "Checking priority drives D: and F:..."
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
    
    # Quick check if this looks like R36S and identify type
    if [ -d "$mount_point" ]; then
        contents=$(ls "$mount_point" 2>/dev/null | head -10 | tr '\n' ' ' || echo "")
        partition_type=""
        
        if [[ "$contents" =~ (RetroArch|apps|WHERE_ARE_MY_ROMS) ]]; then
            partition_type="(R36S-OS - System)"
            R36S_CANDIDATES+=("$mount_point:OS")
        elif [[ "$contents" =~ (EASYROMS|roms|3do|advision|alg|amiga|arcade|atari|gb|gba|gbc|genesis|mame|n64|nes|psx|snes) ]]; then
            partition_type="(EASYROMS - Assets)"  
            R36S_CANDIDATES+=("$mount_point:ROMS")
        elif [[ "$priority_drive" == "F" && "$contents" =~ (3do|advision|alg|amiga) ]]; then
            # Special case: F: drive with emulator folders is likely EASYROMS
            partition_type="(EASYROMS - Assets)"  
            R36S_CANDIDATES+=("$mount_point:ROMS")
        elif [[ "$contents" =~ (retroarch|Image.*R36S) ]]; then
            partition_type="(R36S partition)"
            R36S_CANDIDATES+=("$mount_point:UNKNOWN")
        fi
        
        if [ -n "$partition_type" ]; then
            echo "  → Detected R36S ${priority_drive}: $partition_type - $contents"
        else
            echo "  → Contents: $contents"
        fi
    fi
done
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

# List of possible Windows drives for R36S SD card (D: first, then F: - user specified)
POSSIBLE_DRIVES=("D" "F" "E" "G" "H")

# Handle R36S partitions intelligently
R36S_OS_MOUNT=""
R36S_ROMS_MOUNT=""

for candidate in "${R36S_CANDIDATES[@]}"; do
    mount_path="${candidate%:*}"
    partition_type="${candidate#*:}"
    
    case "$partition_type" in
        "OS")
            R36S_OS_MOUNT="$mount_path"
            ;;
        "ROMS")
            R36S_ROMS_MOUNT="$mount_path"
            ;;
    esac
done

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
    R36S_MOUNT="$R36S_OS_MOUNT"
elif [ -n "$R36S_ROMS_MOUNT" ]; then
    echo "⚠ Only assets partition found, installing everything there:"
    R36S_MOUNT="$R36S_ROMS_MOUNT"
    USE_DUAL_PARTITION=false
elif [ ${#R36S_CANDIDATES[@]} -gt 0 ]; then
    echo "🔍 R36S partitions found but type unclear:"
    for i in "${!R36S_CANDIDATES[@]}"; do
        candidate="${R36S_CANDIDATES[$i]}"
        mount_path="${candidate%:*}"
        drive_letter=$(echo "$mount_path" | sed 's|/mnt/||')
        contents=$(ls "$mount_path" 2>/dev/null | head -3 | tr '\n' ' ')
        echo "  $((i+1)). $mount_path ($drive_letter): $contents"
    done
    echo
    read -p "Choose primary R36S partition (1-${#R36S_CANDIDATES[@]}): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#R36S_CANDIDATES[@]} ]; then
        R36S_MOUNT="${R36S_CANDIDATES[$((choice-1))]%:*}"
        USE_DUAL_PARTITION=false
        echo "✓ Selected: $R36S_MOUNT"
    else
        echo "ERROR: Invalid choice"
        exit 1
    fi
else
    echo "❌ No R36S partitions found, trying other drives..."
    # Continue with original logic for other drives
    for drive in "${POSSIBLE_DRIVES[@]}"; do
        mount_point="/mnt/${drive,,}"
        if [ ! -d "$mount_point" ] || ! mountpoint -q "$mount_point"; then
            mount_windows_drive "$drive"
        else
            echo "✓ $drive: already mounted at $mount_point"
        fi
    done
fi

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

# Dual partition installation logic
if [ "$USE_DUAL_PARTITION" = true ] && [ -n "$R36S_ROMS_MOUNT" ]; then
    echo
    echo "🎯 Implementing dual partition installation:"
    echo "   📱 App → $R36S_MOUNT (System)"
    echo "   📁 Assets → $R36S_ROMS_MOUNT (Assets)"
    
    # Install app on system partition
    APP_INSTALL_DIR="$R36S_MOUNT/r36s_viewer_install"
    mkdir -p "$APP_INSTALL_DIR"
    
    # Install assets on assets partition  
    ASSETS_INSTALL_DIR="$R36S_ROMS_MOUNT/r36s_viewer_assets"
    mkdir -p "$ASSETS_INSTALL_DIR"
    
    echo "Copying app package to system partition..."
    cp "$PACKAGE_FILE" "$APP_INSTALL_DIR/"
    
    echo "Extracting app package..."
    cd "$APP_INSTALL_DIR"
    tar xzf "$PACKAGE_FILE"
    rm "$PACKAGE_FILE"
    
    # Copy assets to assets partition (from package and local)
    assets_copied=false
    
    # First try from package
    if [ -d "r36s_viewer_final_package/assets" ]; then
        echo "Moving assets from package to assets partition..."
        mv "r36s_viewer_final_package/assets"/* "$ASSETS_INSTALL_DIR/" 2>/dev/null || true
        rmdir "r36s_viewer_final_package/assets" 2>/dev/null || true
        assets_copied=true
        echo "✓ Package assets moved to $ASSETS_INSTALL_DIR"
    fi
    
    # Then copy from local assets folder (main source)
    if [ -d "$(dirname "$0")/assets" ]; then
        echo "Copying local assets to assets partition..."
        cp -r "$(dirname "$0")/assets"/* "$ASSETS_INSTALL_DIR/" 2>/dev/null || true
        assets_copied=true
        
        # Count episodes copied
        episodes_count=$(ls -1 "$ASSETS_INSTALL_DIR" 2>/dev/null | wc -l)
        images_count=$(find "$ASSETS_INSTALL_DIR" -name "*.png" 2>/dev/null | wc -l)
        echo "✓ Local assets copied: $episodes_count episodes, $images_count images"
    fi
    
    if [ "$assets_copied" = false ]; then
        echo "⚠ No assets found to copy"
        echo "  Package assets: $([ -d "r36s_viewer_final_package/assets" ] && echo "found" || echo "not found")"
        echo "  Local assets: $([ -d "$(dirname "$0")/assets" ] && echo "found" || echo "not found")"
    fi
    
    INSTALL_DIR="$APP_INSTALL_DIR"
    echo "✓ Dual partition setup complete"
    
else
    # Single partition installation (original logic)
    echo
    echo "📁 Single partition installation: $R36S_MOUNT"
    INSTALL_DIR="$R36S_MOUNT/r36s_viewer_install"
    mkdir -p "$INSTALL_DIR"

    echo "Copying package to SD card..."
    cp "$PACKAGE_FILE" "$INSTALL_DIR/"
    echo "✓ Package copied to SD card"

    echo "Extracting package on SD card..."
    cd "$INSTALL_DIR"
    tar xzf "$PACKAGE_FILE"
    rm "$PACKAGE_FILE"
    echo "✓ Package extracted and cleaned up"
    
    # Copy local assets if available (single partition mode)
    if [ -d "$(dirname "$0")/assets" ]; then
        echo "Copying local assets to package..."
        if [ -d "r36s_viewer_final_package/assets" ]; then
            # Merge with existing assets
            cp -r "$(dirname "$0")/assets"/* "r36s_viewer_final_package/assets/" 2>/dev/null || true
        else
            # Create assets folder and copy
            mkdir -p "r36s_viewer_final_package/assets"
            cp -r "$(dirname "$0")/assets"/* "r36s_viewer_final_package/assets/" 2>/dev/null || true
        fi
        
        episodes_count=$(ls -1 "r36s_viewer_final_package/assets" 2>/dev/null | wc -l)
        images_count=$(find "r36s_viewer_final_package/assets" -name "*.png" 2>/dev/null | wc -l)
        echo "✓ Local assets added: $episodes_count episodes, $images_count images"
    fi
fi

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
