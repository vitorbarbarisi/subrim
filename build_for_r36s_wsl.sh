#!/bin/bash

# Build script for R36S (ARM Linux) - WSL version
# Run this inside WSL Ubuntu environment
# Usage: ./build_for_r36s_wsl.sh

set -e

echo "=== Building R36S Viewer for ARM Linux (WSL) ==="
echo

# Check if we're running inside WSL
if [[ ! -f /proc/version ]] || ! grep -q Microsoft /proc/version 2>/dev/null; then
    if [[ ! -f /proc/version ]] || ! grep -q WSL /proc/version 2>/dev/null; then
        echo "WARNING: This doesn't appear to be WSL environment"
        echo "If you're on native Linux, this should still work"
    fi
fi

echo "Environment: $(uname -a)"
echo

# Update package list if needed
echo "Updating package list..."
sudo apt-get update -qq

# Install ARM cross-compilation toolchain if not present
echo "Checking ARM toolchain..."
if ! command -v arm-linux-gnueabihf-gcc &> /dev/null; then
    echo "Installing ARM cross-compilation toolchain..."
    sudo apt-get install -y gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf
else
    echo "✓ ARM toolchain found: $(arm-linux-gnueabihf-gcc --version | head -1)"
fi

# Install build dependencies if needed
echo "Checking build dependencies..."
if ! command -v cmake &> /dev/null; then
    echo "Installing CMake..."
    sudo apt-get install -y cmake
else
    echo "✓ CMake found: $(cmake --version | head -1)"
fi

if ! command -v make &> /dev/null; then
    echo "Installing build-essential..."
    sudo apt-get install -y build-essential
else
    echo "✓ Make found: $(make --version | head -1)"
fi

# Install pkg-config if needed
if ! command -v pkg-config &> /dev/null; then
    echo "Installing pkg-config..."
    sudo apt-get install -y pkg-config
else
    echo "✓ pkg-config found"
fi

# Install ARM SDL2 libraries for cross-compilation
echo "Checking ARM SDL2 libraries..."
if ! dpkg -l | grep -q libsdl2-dev:armhf; then
    echo "Installing SDL2 ARM libraries..."
    # Add armhf architecture
    sudo dpkg --add-architecture armhf
    sudo apt-get update -qq
    
    # Install ARM SDL2 libraries and cross-compilation tools
    sudo apt-get install -y \
        libsdl2-dev:armhf \
        libsdl2-image-dev:armhf \
        libsdl2-ttf-dev:armhf \
        libc6-dev:armhf \
        pkg-config-arm-linux-gnueabihf
else
    echo "✓ ARM SDL2 libraries found"
fi

# Check if ARM pkg-config exists
if ! command -v arm-linux-gnueabihf-pkg-config &> /dev/null; then
    echo "Installing ARM pkg-config..."
    sudo apt-get install -y pkg-config-arm-linux-gnueabihf
else
    echo "✓ ARM pkg-config found"
fi

echo
echo "All dependencies installed successfully!"
echo

# Create build directory
echo "Setting up build directory..."
rm -rf build_r36s
mkdir -p build_r36s
cd build_r36s

echo "Configuring CMake for ARM cross-compilation..."

# Check if toolchain file exists
TOOLCHAIN_FILE="../arm-linux-gnueabihf.cmake"
if [ ! -f "$TOOLCHAIN_FILE" ]; then
    echo "ERROR: Toolchain file not found: $TOOLCHAIN_FILE"
    echo "Make sure arm-linux-gnueabihf.cmake is in the project root"
    cd ..
    exit 1
fi

# Configure with CMake using toolchain file
cmake .. -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE"

if [ $? -ne 0 ]; then
    echo "ERROR: CMake configuration failed!"
    echo "Make sure all source files are present"
    cd ..
    exit 1
fi

echo "✓ CMake configuration successful"
echo

# Build the project
echo "Building R36S Viewer..."
make -j$(nproc)

if [ $? -ne 0 ]; then
    echo "ERROR: Build failed!"
    cd ..
    exit 1
fi

echo
echo "=== Build Complete! ==="
echo "Executable: build_r36s/r36s_viewer"

# Verify the binary
if [ -f "r36s_viewer" ]; then
    echo "✓ Binary created successfully"
    echo "Binary info:"
    file r36s_viewer
    echo "Size: $(ls -lh r36s_viewer | awk '{print $5}')"
else
    echo "ERROR: Binary not found!"
    cd ..
    exit 1
fi

cd ..

echo
echo "Next steps:"
echo "1. Run: ./prepare_r36s_package_wsl.sh"
echo "2. Copy package to R36S SD card"
echo "3. Install on R36S console"
echo

echo "Build successful! 🎉"
