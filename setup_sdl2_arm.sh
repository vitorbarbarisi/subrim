#!/bin/bash

# Setup SDL2 for ARM cross-compilation
# Downloads and builds SDL2 libraries for ARM target

set -e

echo "=== Setting up SDL2 for ARM Cross-Compilation ==="
echo

# Create build directory
WORK_DIR="$HOME/sdl2_arm_build"
SDL2_PREFIX="/usr/local/arm-linux-gnueabihf"

echo "Working directory: $WORK_DIR"
echo "Install prefix: $SDL2_PREFIX"

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Download SDL2 and dependencies
echo
echo "[1/4] Downloading SDL2 libraries..."

# SDL2 Core
if [ ! -f "SDL2-2.28.5.tar.gz" ]; then
    echo "Downloading SDL2..."
    wget -q https://github.com/libsdl-org/SDL/releases/download/release-2.28.5/SDL2-2.28.5.tar.gz
fi

# SDL2_image
if [ ! -f "SDL2_image-2.8.2.tar.gz" ]; then
    echo "Downloading SDL2_image..."
    wget -q https://github.com/libsdl-org/SDL_image/releases/download/release-2.8.2/SDL2_image-2.8.2.tar.gz
fi

# SDL2_ttf
if [ ! -f "SDL2_ttf-2.22.0.tar.gz" ]; then
    echo "Downloading SDL2_ttf..."
    wget -q https://github.com/libsdl-org/SDL_ttf/releases/download/release-2.22.0/SDL2_ttf-2.22.0.tar.gz
fi

echo "✓ Downloads complete"

# Extract archives
echo
echo "[2/4] Extracting archives..."
for archive in SDL2-*.tar.gz; do
    if [ ! -d "${archive%.tar.gz}" ]; then
        echo "Extracting $archive..."
        tar xzf "$archive"
    fi
done
echo "✓ Extraction complete"

# Build SDL2 Core
echo
echo "[3/4] Building SDL2 Core..."
cd SDL2-2.28.5

if [ ! -f "Makefile" ]; then
    echo "Configuring SDL2..."
    ./configure \
        --host=arm-linux-gnueabihf \
        --prefix="$SDL2_PREFIX" \
        --disable-shared \
        --enable-static \
        --disable-video-x11 \
        --disable-video-wayland \
        --enable-video-fbcon \
        --disable-pulseaudio \
        --disable-alsa \
        --disable-jack \
        --enable-dummyaudio \
        --disable-oss
fi

echo "Building SDL2..."
make -j$(nproc)
echo "Installing SDL2..."
sudo make install

cd ..
echo "✓ SDL2 Core built and installed"

# Build SDL2_image
echo
echo "[4/4] Building SDL2_image..."
cd SDL2_image-2.8.2

if [ ! -f "Makefile" ]; then
    echo "Configuring SDL2_image..."
    export PKG_CONFIG_PATH="$SDL2_PREFIX/lib/pkgconfig:$PKG_CONFIG_PATH"
    ./configure \
        --host=arm-linux-gnueabihf \
        --prefix="$SDL2_PREFIX" \
        --disable-shared \
        --enable-static \
        --disable-jpg-shared \
        --disable-png-shared \
        --with-sdl-prefix="$SDL2_PREFIX"
fi

echo "Building SDL2_image..."
make -j$(nproc)
echo "Installing SDL2_image..."
sudo make install

cd ..
echo "✓ SDL2_image built and installed"

# Build SDL2_ttf
echo
echo "Building SDL2_ttf..."
cd SDL2_ttf-2.22.0

if [ ! -f "Makefile" ]; then
    echo "Configuring SDL2_ttf..."
    export PKG_CONFIG_PATH="$SDL2_PREFIX/lib/pkgconfig:$PKG_CONFIG_PATH"
    ./configure \
        --host=arm-linux-gnueabihf \
        --prefix="$SDL2_PREFIX" \
        --disable-shared \
        --enable-static \
        --with-sdl-prefix="$SDL2_PREFIX"
fi

echo "Building SDL2_ttf..."
make -j$(nproc)
echo "Installing SDL2_ttf..."
sudo make install

cd ..
echo "✓ SDL2_ttf built and installed"

# Verify installation
echo
echo "=== Installation Verification ==="
echo "SDL2 headers: $SDL2_PREFIX/include/SDL2/"
echo "SDL2 libraries: $SDL2_PREFIX/lib/"

if [ -f "$SDL2_PREFIX/include/SDL2/SDL.h" ]; then
    echo "✅ SDL2 headers found"
else
    echo "❌ SDL2 headers not found"
fi

if [ -f "$SDL2_PREFIX/lib/libSDL2.a" ]; then
    echo "✅ SDL2 static library found"
else
    echo "❌ SDL2 static library not found"
fi

# Create pkg-config files if needed
echo
echo "Setting up pkg-config..."
sudo mkdir -p "$SDL2_PREFIX/lib/pkgconfig"

# Update library search paths
echo "Updating ldconfig..."
echo "$SDL2_PREFIX/lib" | sudo tee /etc/ld.so.conf.d/sdl2-arm.conf
sudo ldconfig

echo
echo "=== SDL2 ARM Setup Complete! ==="
echo
echo "Now you can build with:"
echo "  ./build_with_static_sdl2.sh"
echo
echo "Installation paths:"
echo "  Headers: $SDL2_PREFIX/include/SDL2/"
echo "  Libraries: $SDL2_PREFIX/lib/"
echo "  pkg-config: $SDL2_PREFIX/lib/pkgconfig/"
echo
