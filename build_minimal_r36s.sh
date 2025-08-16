#!/bin/bash

# Minimal R36S build without SDL2 dependencies
# Creates a stub version that can be completed on the R36S itself

set -e

echo "=== Minimal R36S Build (No SDL2 Dependencies) ==="
echo

# Check cross-compiler
if ! command -v arm-linux-gnueabihf-gcc &> /dev/null; then
    echo "Installing ARM cross-compiler..."
    sudo apt-get update
    sudo apt-get install -y gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf
else
    echo "✓ ARM cross-compiler found"
fi

# Create minimal build
rm -rf build_minimal
mkdir -p build_minimal
cd build_minimal

echo "Creating minimal version without SDL2..."

# Create a minimal main that can be completed on R36S
cat > r36s_minimal.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Minimal R36S Viewer - To be completed on target system
// This version demonstrates ARM compilation works

int main(int argc, char **argv) {
    printf("R36S Viewer (Minimal Version)\n");
    printf("Compiled for ARM architecture\n");
    printf("Arguments: %d\n", argc);
    
    for (int i = 0; i < argc; i++) {
        printf("  [%d]: %s\n", i, argv[i]);
    }
    
    printf("\nThis minimal version confirms ARM cross-compilation works.\n");
    printf("To complete the build:\n");
    printf("1. Copy source files to R36S\n");
    printf("2. Install SDL2 on R36S: apt-get install libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev\n");
    printf("3. Compile natively on R36S: gcc r36s_viewer.c base.c text.c ui.c -lSDL2 -lSDL2_image -lSDL2_ttf -o r36s_viewer\n");
    
    return 0;
}
EOF

echo "✓ Minimal source created"

# ARM compilation flags for R36S
ARM_FLAGS="-march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard"

echo "Compiling minimal version for ARM..."
arm-linux-gnueabihf-gcc \
    $ARM_FLAGS \
    -Wall -O2 \
    r36s_minimal.c \
    -o r36s_minimal

if [ $? -eq 0 ]; then
    echo "✅ Minimal ARM compilation successful!"
    echo "Binary: build_minimal/r36s_minimal"
    echo "Info: $(file r36s_minimal)"
    echo "Size: $(ls -lh r36s_minimal | awk '{print $5}')"
    
    # Test execution (will fail on x86 but shows it's ARM)
    echo
    echo "Testing binary (should fail on x86_64, confirming it's ARM):"
    ./r36s_minimal 2>&1 || echo "✓ Correctly fails on x86_64 - confirms ARM binary"
    
else
    echo "❌ Even minimal compilation failed"
    cd ..
    exit 1
fi

# Create native build script for R36S
cat > build_on_r36s.sh << 'EOF'
#!/bin/bash
# Native build script to run on R36S console

echo "=== Building R36S Viewer Natively ==="

# Install SDL2 on R36S
sudo apt-get update
sudo apt-get install -y libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev

# Compile natively
gcc -march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard \
    -Wall -O2 \
    r36s_viewer.c base.c text.c ui.c \
    $(pkg-config --cflags --libs sdl2 SDL2_image SDL2_ttf) \
    -o r36s_viewer

echo "Native compilation complete!"
file r36s_viewer
EOF

chmod +x build_on_r36s.sh
echo "✓ Created native build script for R36S"

# Copy source files for transfer
echo "Copying source files for R36S native build..."
cp ../r36s_viewer.c .
cp ../base.c .
cp ../text.c .
cp ../ui.c .
cp ../*.h .

# Create transfer package
echo "Creating transfer package..."
tar czf r36s_source_package.tar.gz *.c *.h build_on_r36s.sh

echo "✓ Source package created: r36s_source_package.tar.gz"

cd ..

echo
echo "=== Minimal Build Complete! ==="
echo
echo "✅ ARM cross-compilation works (minimal test passed)"
echo
echo "📦 Options for full R36S Viewer:"
echo
echo "Option 1 - Native build on R36S:"
echo "  1. Copy build_minimal/r36s_source_package.tar.gz to R36S"
echo "  2. Extract: tar xzf r36s_source_package.tar.gz"
echo "  3. Run: ./build_on_r36s.sh"
echo
echo "Option 2 - Setup SDL2 for cross-compilation:"
echo "  1. Run: ./setup_sdl2_arm.sh"
echo "  2. Run: ./build_with_static_sdl2.sh"
echo
echo "Option 3 - Manual SDL2 headers:"
echo "  1. Copy SDL2 headers from R36S to cross-compiler"
echo "  2. Update build paths"
echo
echo "Recommendation: Use Option 1 (native build on R36S) for simplicity"
