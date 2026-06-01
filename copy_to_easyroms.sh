#!/bin/bash

# Script to copy roseki01-1_screenshots folder to /assets on EASYROMS partition
# Usage: ./copy_to_easyroms.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SOURCE_DIR="assets/roseki01-1/roseki01-1_screenshots"
DEST_PARTITION="/dev/rdisk6s3"
DEST_PATH="::/assets"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}=== Copying roseki01-1_screenshots to EASYROMS ===${NC}"
echo ""

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: Source directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

# Check if running as root (required for mtools)
if [ "$EUID" -ne 0 ]; then 
    echo -e "${YELLOW}Note: This script requires sudo privileges to access the SD card${NC}"
    echo "Please run with: sudo ./copy_to_easyroms.sh"
    exit 1
fi

# Check if mtools is installed
if ! command -v mcopy &> /dev/null; then
    echo -e "${RED}Error: mtools is not installed${NC}"
    echo "Install it with: brew install mtools"
    exit 1
fi

# Check if partition exists
if [ ! -e "$DEST_PARTITION" ]; then
    echo -e "${RED}Error: Partition $DEST_PARTITION not found${NC}"
    echo "Please make sure the SD card is connected and check with: diskutil list"
    exit 1
fi

echo -e "${GREEN}Source:${NC} $SCRIPT_DIR/$SOURCE_DIR"
echo -e "${GREEN}Destination:${NC} $DEST_PARTITION$DEST_PATH"
echo ""

# Check if /assets directory exists on the card, create if not
echo -e "${YELLOW}Checking if /assets directory exists...${NC}"
if ! mdir -i "$DEST_PARTITION" "$DEST_PATH" &> /dev/null; then
    echo -e "${YELLOW}Creating /assets directory...${NC}"
    # Try to create the directory (mtools may not support this for ExFAT)
    # If it fails, we'll continue anyway
    mmd -i "$DEST_PARTITION" "$DEST_PATH" 2>/dev/null || true
fi

# Count files to copy
FILE_COUNT=$(find "$SOURCE_DIR" -type f | wc -l | tr -d ' ')
echo -e "${GREEN}Found $FILE_COUNT files to copy${NC}"
echo ""

# Copy files recursively
echo -e "${YELLOW}Copying files...${NC}"
echo "This may take a while depending on the number of files..."
echo ""

# Use mcopy with recursive option
# Note: For ExFAT, mtools may have limitations
cd "$SCRIPT_DIR"
if mcopy -i "$DEST_PARTITION" -s "$SOURCE_DIR"/* "$DEST_PATH/roseki01-1_screenshots/" 2>&1; then
    echo ""
    echo -e "${GREEN}✓ Files copied successfully!${NC}"
    echo ""
    echo -e "${GREEN}Verifying...${NC}"
    FILE_COUNT_DEST=$(mdir -i "$DEST_PARTITION" "$DEST_PATH/roseki01-1_screenshots/" 2>/dev/null | grep -c "\.png\|\.jpg\|\.jpeg" || echo "0")
    echo -e "${GREEN}Files in destination: $FILE_COUNT_DEST${NC}"
else
    echo ""
    echo -e "${RED}✗ Error copying files${NC}"
    echo ""
    echo -e "${YELLOW}Note: mtools may not work well with ExFAT partitions${NC}"
    echo "If this failed, try one of these alternatives:"
    echo ""
    echo "1. Mount the partition manually (if possible):"
    echo "   sudo diskutil mount disk6s3"
    echo "   Then copy normally: cp -R $SOURCE_DIR /Volumes/EASYROMS/assets/"
    echo ""
    echo "2. Use rsync if the partition mounts:"
    echo "   rsync -av $SOURCE_DIR/ /Volumes/EASYROMS/assets/roseki01-1_screenshots/"
    echo ""
    echo "3. Try accessing via a Linux VM or different system"
    exit 1
fi

echo ""
echo -e "${GREEN}Done!${NC}"

