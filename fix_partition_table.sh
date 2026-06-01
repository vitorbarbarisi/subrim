#!/bin/bash

# Script to fix partition table type for EASYROMS after ExFAT formatting
# This updates the MBR partition table to reflect the ExFAT filesystem

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PARTITION="disk6s3"
DISK="disk6"

echo -e "${YELLOW}=== Fixing Partition Table for EASYROMS ===${NC}"
echo ""

if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script requires sudo privileges${NC}"
    echo "Please run with: sudo ./fix_partition_table.sh"
    exit 1
fi

# Check if partition exists
if ! diskutil info "$PARTITION" &> /dev/null; then
    echo -e "${RED}Error: Partition $PARTITION not found${NC}"
    exit 1
fi

echo -e "${YELLOW}Current partition info:${NC}"
diskutil info "$PARTITION" | grep -E "(Partition Type|File System)"
echo ""

# The issue is that the MBR partition table still shows NTFS type
# We need to use gpt or fdisk to change it, but macOS doesn't easily support
# changing MBR partition types without reformatting

echo -e "${YELLOW}The partition table shows NTFS but filesystem is ExFAT${NC}"
echo "This inconsistency may prevent mounting."
echo ""
echo -e "${YELLOW}Options:${NC}"
echo "1. Try to force mount using mount command directly"
echo "2. Reformat the partition (will erase data again)"
echo "3. Use a different tool to fix MBR partition type"
echo ""

# Try mounting directly with mount command
echo -e "${GREEN}Attempting direct mount...${NC}"
if mount -t exfat /dev/rdisk6s3 /Volumes/EASYROMS 2>&1; then
    echo -e "${GREEN}✓ Successfully mounted!${NC}"
    MOUNT_POINT=$(mount | grep rdisk6s3 | awk '{print $3}')
    echo -e "${GREEN}Mounted at: $MOUNT_POINT${NC}"
    exit 0
else
    MOUNT_ERROR=$?
    echo -e "${RED}Direct mount failed${NC}"
fi

echo ""
echo -e "${YELLOW}Since direct mount failed, you may need to:${NC}"
echo ""
echo "Option A: Use Disk Utility GUI:"
echo "  1. Open Disk Utility"
echo "  2. Select the EASYROMS partition"
echo "  3. Click 'Erase' and choose ExFAT"
echo "  4. This should update both filesystem and partition table"
echo ""
echo "Option B: Reformat via command line (will erase data):"
echo "  sudo diskutil eraseVolume ExFAT EASYROMS disk6s3"
echo ""
echo "Option C: Try using a Linux system or VM to fix the partition table"
echo ""

exit 1

