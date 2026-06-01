#!/bin/bash

# Script to format EASYROMS partition to ExFAT (compatible with Mac, Windows, Linux)
# WARNING: This will erase all data on the EASYROMS partition!

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PARTITION="disk6s3"
PARTITION_NAME="EASYROMS"
FILESYSTEM="ExFAT"

echo -e "${RED}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║  WARNING: This will ERASE ALL DATA on EASYROMS partition! ║${NC}"
echo -e "${RED}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script requires sudo privileges${NC}"
    echo "Please run with: sudo ./format_easyroms.sh"
    exit 1
fi

# Check if partition exists
if ! diskutil info "$PARTITION" &> /dev/null; then
    echo -e "${RED}Error: Partition $PARTITION not found${NC}"
    echo "Please make sure the SD card is connected and check with: diskutil list"
    exit 1
fi

# Show current partition info
echo -e "${YELLOW}Current partition information:${NC}"
diskutil info "$PARTITION" | grep -E "(Volume Name|File System|Disk Size|Mounted)"
echo ""

# Check if partition is mounted
MOUNT_STATUS=$(diskutil info "$PARTITION" | grep "Mounted:" | awk '{print $2}')
if [ "$MOUNT_STATUS" = "Yes" ]; then
    echo -e "${YELLOW}Unmounting partition first...${NC}"
    diskutil unmount "$PARTITION" || diskutil unmount force "$PARTITION"
    sleep 2
fi

# Confirm before proceeding
echo -e "${YELLOW}Are you sure you want to format $PARTITION_NAME to $FILESYSTEM?${NC}"
echo -e "${YELLOW}Type 'YES' to continue (all data will be lost):${NC} "
read -r confirmation

if [ "$confirmation" != "YES" ]; then
    echo -e "${YELLOW}Operation cancelled.${NC}"
    exit 0
fi

echo ""
echo -e "${GREEN}Formatting $PARTITION_NAME to $FILESYSTEM...${NC}"
echo "This may take a few minutes..."
echo ""

# Format to ExFAT (eraseVolume formats only the partition, not the whole disk)
if diskutil eraseVolume "$FILESYSTEM" "$PARTITION_NAME" "$PARTITION"; then
    echo ""
    echo -e "${GREEN}✓ Formatting completed successfully!${NC}"
    echo ""
    
    # Try to mount the new partition
    echo -e "${YELLOW}Attempting to mount the new partition...${NC}"
    if diskutil mount "$PARTITION"; then
        MOUNT_POINT=$(diskutil info "$PARTITION" | grep "Mount Point:" | awk '{print $3}')
        echo -e "${GREEN}✓ Partition mounted at: $MOUNT_POINT${NC}"
        echo ""
        echo -e "${GREEN}You can now access the partition at: $MOUNT_POINT${NC}"
    else
        echo -e "${YELLOW}⚠ Partition formatted but could not be mounted automatically${NC}"
        echo "Try mounting manually with: diskutil mount $PARTITION"
        echo "Or check in Finder - it should appear in the sidebar"
    fi
    
    echo ""
    echo -e "${GREEN}Formatting complete!${NC}"
    echo ""
    echo -e "${YELLOW}Note: ExFAT is compatible with:${NC}"
    echo "  - macOS (read/write)"
    echo "  - Windows (read/write)"
    echo "  - Linux (with exfat-utils)"
    echo ""
else
    echo ""
    echo -e "${RED}✗ Error formatting partition${NC}"
    echo ""
    echo "If the error persists, you may need to:"
    echo "1. Check if the SD card is write-protected"
    echo "2. Try formatting the entire disk (this will erase ALL partitions)"
    echo "3. Use Disk Utility GUI application"
    exit 1
fi

