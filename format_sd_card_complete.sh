#!/bin/bash

# Script to completely format SD card
# WARNING: This will ERASE ALL DATA and ALL PARTITIONS on the SD card!

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DISK="disk6"
DEFAULT_FILESYSTEM="ExFAT"
DEFAULT_VOLUME_NAME="EASYROMS"

echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║     WARNING: COMPLETE SD CARD FORMATTING                        ║${NC}"
echo -e "${RED}║                                                                  ║${NC}"
echo -e "${RED}║  This will ERASE ALL DATA and ALL PARTITIONS on the SD card!    ║${NC}"
echo -e "${RED}║  All partitions (BOOT, Linux, EASYROMS) will be DELETED!         ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script requires sudo privileges${NC}"
    echo "Please run with: sudo ./format_sd_card_complete.sh"
    exit 1
fi

# Check if disk exists
if ! diskutil list "$DISK" &> /dev/null; then
    echo -e "${RED}Error: Disk $DISK not found${NC}"
    echo "Please make sure the SD card is connected and check with: diskutil list"
    exit 1
fi

# Show current disk structure
echo -e "${YELLOW}Current SD card structure:${NC}"
diskutil list "$DISK"
echo ""

# Show disk info
echo -e "${YELLOW}Disk information:${NC}"
diskutil info "$DISK" | grep -E "(Disk Size|Protocol|Media)"
echo ""

# Ask for filesystem choice
echo -e "${BLUE}Choose filesystem format:${NC}"
echo "  1) ExFAT (Recommended - compatible with Mac, Windows, Linux)"
echo "  2) FAT32 (Compatible with everything, but 4GB file size limit)"
echo "  3) APFS (macOS only, best for Mac-only use)"
echo "  4) HFS+ (Mac OS Extended, macOS only)"
echo ""
read -p "Enter choice [1-4] (default: 1): " fs_choice
fs_choice=${fs_choice:-1}

case $fs_choice in
    1)
        FILESYSTEM="ExFAT"
        ;;
    2)
        FILESYSTEM="MS-DOS FAT32"
        ;;
    3)
        FILESYSTEM="APFS"
        ;;
    4)
        FILESYSTEM="Mac OS Extended"
        ;;
    *)
        echo -e "${RED}Invalid choice. Using ExFAT.${NC}"
        FILESYSTEM="ExFAT"
        ;;
esac

# Ask for volume name
echo ""
read -p "Enter volume name (default: $DEFAULT_VOLUME_NAME): " volume_name
volume_name=${volume_name:-$DEFAULT_VOLUME_NAME}

echo ""
echo -e "${YELLOW}Formatting configuration:${NC}"
echo "  Disk: $DISK"
echo "  Filesystem: $FILESYSTEM"
echo "  Volume name: $volume_name"
echo ""

# Final confirmation
echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${RED}FINAL WARNING: This will DELETE EVERYTHING on the SD card!${NC}"
echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Type 'FORMAT' (all caps) to confirm and proceed:${NC} "
read -r confirmation

if [ "$confirmation" != "FORMAT" ]; then
    echo -e "${YELLOW}Operation cancelled. No changes were made.${NC}"
    exit 0
fi

echo ""
echo -e "${GREEN}Unmounting all partitions...${NC}"
diskutil unmountDisk "$DISK" 2>/dev/null || true
sleep 2

echo ""
echo -e "${GREEN}Formatting entire SD card to $FILESYSTEM...${NC}"
echo -e "${YELLOW}This may take several minutes depending on the card size...${NC}"
echo ""

# Format the entire disk
# eraseDisk creates a new partition table and formats the whole disk
if diskutil eraseDisk "$FILESYSTEM" "$volume_name" "$DISK"; then
    echo ""
    echo -e "${GREEN}✓ Formatting completed successfully!${NC}"
    echo ""
    
    # Show new structure
    echo -e "${YELLOW}New disk structure:${NC}"
    diskutil list "$DISK"
    echo ""
    
    # Try to mount
    NEW_PARTITION="${DISK}s1"
    echo -e "${YELLOW}Attempting to mount the new volume...${NC}"
    if diskutil mount "$NEW_PARTITION"; then
        MOUNT_POINT=$(diskutil info "$NEW_PARTITION" | grep "Mount Point:" | awk '{print $3}')
        echo -e "${GREEN}✓ Volume mounted at: $MOUNT_POINT${NC}"
        echo ""
        echo -e "${GREEN}You can now access the SD card at: $MOUNT_POINT${NC}"
    else
        echo -e "${YELLOW}⚠ Volume formatted but could not be mounted automatically${NC}"
        echo "Try: diskutil mount $NEW_PARTITION"
        echo "Or check in Finder"
    fi
    
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}SD card formatting complete!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    
    if [ "$FILESYSTEM" = "ExFAT" ]; then
        echo -e "${BLUE}ExFAT compatibility:${NC}"
        echo "  ✓ macOS (read/write)"
        echo "  ✓ Windows (read/write)"
        echo "  ✓ Linux (with exfat-utils: sudo apt install exfat-utils)"
    elif [ "$FILESYSTEM" = "MS-DOS FAT32" ]; then
        echo -e "${BLUE}FAT32 compatibility:${NC}"
        echo "  ✓ macOS (read/write)"
        echo "  ✓ Windows (read/write)"
        echo "  ✓ Linux (native support)"
        echo "  ⚠ 4GB file size limit"
    fi
    
else
    echo ""
    echo -e "${RED}✗ Error formatting SD card${NC}"
    echo ""
    echo "Possible causes:"
    echo "  - SD card is write-protected (check the physical lock switch)"
    echo "  - SD card is damaged"
    echo "  - Insufficient permissions"
    echo ""
    echo "Try:"
    echo "  1. Check if the SD card has a physical lock switch"
    echo "  2. Use Disk Utility GUI application"
    echo "  3. Try a different SD card reader"
    exit 1
fi

