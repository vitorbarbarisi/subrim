#!/bin/bash

# Simple ARM cross-compilation for R36S (Ubuntu 24.04 compatible)
# This avoids armhf package dependencies that don't exist in Noble

set -e

echo "=== Simple R36S ARM Cross-Compilation ==="
echo

# Check basic tools
echo "Checking cross-compilation tools..."
if ! command -v arm-linux-gnueabihf-gcc &> /dev/null; then
    echo "Installing ARM cross-compiler..."
    sudo apt-get update
    sudo apt-get install -y gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf
else
    echo "✓ ARM cross-compiler found"
fi

# Simple build without CMake dependencies
echo
echo "Building with direct GCC (no CMake dependencies)..."

# Clean previous build
rm -rf build_simple
mkdir -p build_simple
cd build_simple

# Copy source files
cp ../r36s_viewer.c .
cp ../base.c .
cp ../text.c .
cp ../ui.c .
cp ../*.h .

echo "✓ Source files copied"

# ARM compilation flags
ARM_FLAGS="-march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard"
INCLUDES="-I/usr/arm-linux-gnueabihf/include/SDL2 -I/usr/arm-linux-gnueabihf/include"
LIBS="-lSDL2 -lSDL2_image -lSDL2_ttf -lm -ldl -lpthread"
SYSROOT="--sysroot=/usr/arm-linux-gnueabihf"

echo "Compiling for ARM..."
echo "Flags: $ARM_FLAGS"
echo "Includes: $INCLUDES"

# Try direct compilation first
arm-linux-gnueabihf-gcc \
    $ARM_FLAGS \
    $SYSROOT \
    $INCLUDES \
    -Wall -O2 \
    r36s_viewer.c base.c text.c ui.c \
    $LIBS \
    -o r36s_viewer

if [ $? -eq 0 ]; then
    echo
    echo "✅ ARM compilation successful!"
    echo "Binary: build_simple/r36s_viewer"
    echo "Info: $(file r36s_viewer)"
    echo "Size: $(ls -lh r36s_viewer | awk '{print $5}')"
    
    # Copy to expected location
    mkdir -p ../build_r36s
    cp r36s_viewer ../build_r36s/
    echo "✓ Copied to build_r36s/r36s_viewer"
    
else
    echo
    echo "❌ Direct compilation failed, trying without SDL2..."
    
    # Try minimal build without SDL2 (for testing)
    cat > minimal_test.c << 'EOF'
#include <stdio.h>
int main() {
    printf("Hello from ARM R36S!\n");
    return 0;
}
EOF
    
    arm-linux-gnueabihf-gcc $ARM_FLAGS $SYSROOT minimal_test.c -o minimal_test
    
    if [ $? -eq 0 ]; then
        echo "✅ Minimal ARM compilation works"
        echo "Info: $(file minimal_test)"
        echo
        echo "Issue: SDL2 headers not found for ARM cross-compilation"
        echo "Solutions:"
        echo "1. Install SDL2 development headers for target system"
        echo "2. Use static linking"
        echo "3. Build on actual ARM system"
    else
        echo "❌ ARM cross-compilation completely failed"
        echo "Check if arm-linux-gnueabihf toolchain is properly installed"
    fi
    
    cd ..
    exit 1
fi

cd ..
echo
echo "=== Build Complete! ==="
echo "Ready for: ./prepare_r36s_package_wsl.sh"
