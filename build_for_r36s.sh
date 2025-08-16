#!/bin/bash

# Build script for R36S (ARM Linux) - Unix/Linux/macOS version
# Requires cross-compilation toolchain

set -e

echo "=== Building R36S Viewer for ARM Linux ==="

# Check if we have the ARM toolchain
if ! command -v arm-linux-gnueabihf-gcc &> /dev/null; then
    echo "ERROR: ARM cross-compilation toolchain not found!"
    echo "Install with: sudo apt-get install gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf"
    echo "Or use a different method depending on your OS"
    exit 1
fi

# Create build directory
mkdir -p build_r36s
cd build_r36s

# Configure with CMake for ARM cross-compilation
cmake .. \
    -DCMAKE_SYSTEM_NAME=Linux \
    -DCMAKE_SYSTEM_PROCESSOR=arm \
    -DCMAKE_C_COMPILER=arm-linux-gnueabihf-gcc \
    -DCMAKE_CXX_COMPILER=arm-linux-gnueabihf-g++ \
    -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY

# Build
make -j$(nproc)

echo "=== Build complete! ==="
echo "Executable: build_r36s/r36s_viewer"

cd ..
