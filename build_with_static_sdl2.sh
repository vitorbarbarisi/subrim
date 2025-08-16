#!/bin/bash

# Build R36S Viewer with static SDL2 libraries
# Run setup_sdl2_arm.sh first to build SDL2 for ARM

set -e

echo "=== Building R36S Viewer with Static SDL2 ==="
echo

# SDL2 installation paths
SDL2_PREFIX="/usr/local/arm-linux-gnueabihf"

# Check if SDL2 is installed
if [ ! -f "$SDL2_PREFIX/include/SDL2/SDL.h" ]; then
    echo "ERROR: SDL2 headers not found at $SDL2_PREFIX"
    echo "Run ./setup_sdl2_arm.sh first to build SDL2 for ARM"
    exit 1
fi

if [ ! -f "$SDL2_PREFIX/lib/libSDL2.a" ]; then
    echo "ERROR: SDL2 static library not found at $SDL2_PREFIX"
    echo "Run ./setup_sdl2_arm.sh first to build SDL2 for ARM"
    exit 1
fi

echo "✓ SDL2 ARM libraries found"

# Clean previous build
rm -rf build_static
mkdir -p build_static
cd build_static

# Copy source files
cp ../r36s_viewer.c .
cp ../base.c .
cp ../text.c .
cp ../ui.c .
cp ../*.h .

echo "✓ Source files copied"

# ARM compilation settings
ARM_FLAGS="-march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard"
INCLUDES="-I$SDL2_PREFIX/include/SDL2 -I$SDL2_PREFIX/include"

# Static linking flags
STATIC_LIBS="$SDL2_PREFIX/lib/libSDL2.a"
STATIC_LIBS="$STATIC_LIBS $SDL2_PREFIX/lib/libSDL2_image.a"
STATIC_LIBS="$STATIC_LIBS $SDL2_PREFIX/lib/libSDL2_ttf.a"

# System libraries needed for static linking
SYSTEM_LIBS="-lm -ldl -lpthread -lrt"

# Additional libraries that SDL2 might need
EXTRA_LIBS="-lfreetype -lpng -ljpeg -lz"

echo "Building for ARM with static SDL2..."
echo "Flags: $ARM_FLAGS"
echo "Includes: $INCLUDES"
echo "Static libs: $STATIC_LIBS"

# Compile
arm-linux-gnueabihf-gcc \
    $ARM_FLAGS \
    $INCLUDES \
    -Wall -O2 -static \
    r36s_viewer.c base.c text.c ui.c \
    $STATIC_LIBS \
    $SYSTEM_LIBS \
    $EXTRA_LIBS \
    -o r36s_viewer

if [ $? -eq 0 ]; then
    echo
    echo "✅ Static compilation successful!"
    echo "Binary: build_static/r36s_viewer"
    echo "Info: $(file r36s_viewer)"
    echo "Size: $(ls -lh r36s_viewer | awk '{print $5}')"
    
    # Test if it's properly linked
    echo "Dependencies:"
    arm-linux-gnueabihf-objdump -p r36s_viewer | grep NEEDED || echo "  (statically linked)"
    
    # Copy to expected location
    mkdir -p ../build_r36s
    cp r36s_viewer ../build_r36s/
    echo "✓ Copied to build_r36s/r36s_viewer"
    
else
    echo
    echo "❌ Static compilation failed, trying dynamic linking..."
    
    # Try dynamic linking
    arm-linux-gnueabihf-gcc \
        $ARM_FLAGS \
        $INCLUDES \
        -Wall -O2 \
        r36s_viewer.c base.c text.c ui.c \
        -L$SDL2_PREFIX/lib \
        -lSDL2 -lSDL2_image -lSDL2_ttf \
        $SYSTEM_LIBS \
        -o r36s_viewer_dynamic
    
    if [ $? -eq 0 ]; then
        echo "✅ Dynamic linking successful!"
        echo "Binary: build_static/r36s_viewer_dynamic"
        echo "Info: $(file r36s_viewer_dynamic)"
        
        # Copy dynamic version
        mkdir -p ../build_r36s
        cp r36s_viewer_dynamic ../build_r36s/r36s_viewer
        echo "✓ Copied dynamic version to build_r36s/r36s_viewer"
    else
        echo "❌ Both static and dynamic compilation failed"
        cd ..
        exit 1
    fi
fi

cd ..
echo
echo "=== Build Complete! ==="
echo "Ready for: ./prepare_r36s_package_wsl.sh"

# Show final binary info
if [ -f "build_r36s/r36s_viewer" ]; then
    echo
    echo "Final binary info:"
    file build_r36s/r36s_viewer
    ls -lh build_r36s/r36s_viewer
fi
