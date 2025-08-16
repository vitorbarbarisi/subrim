#!/bin/bash

# Clean build script for R36S development
# Usage: ./clean_build.sh

echo "=== Cleaning R36S Build Files ==="
echo

# Remove build directory
if [ -d "build_r36s" ]; then
    echo "Removing build_r36s directory..."
    rm -rf build_r36s
    echo "✓ build_r36s removed"
else
    echo "✓ build_r36s directory not found"
fi

# Remove package directory
if [ -d "r36s_viewer_package" ]; then
    echo "Removing r36s_viewer_package directory..."
    rm -rf r36s_viewer_package
    echo "✓ r36s_viewer_package removed"
else
    echo "✓ r36s_viewer_package directory not found"
fi

# Remove temporary files
echo "Removing temporary files..."
rm -f test_arm test_arm.c
rm -f *.log
rm -f core.*

echo
echo "=== Clean Complete! ==="
echo "Ready for fresh build with: ./build_for_r36s_wsl.sh"
echo
