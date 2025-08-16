#!/bin/bash

# WSL Environment Setup for R36S Development
# Run this once after installing WSL Ubuntu
# Usage: ./setup_wsl_environment.sh

set -e

echo "============================================"
echo "    WSL Environment Setup for R36S         "
echo "============================================"
echo

# Check if running in WSL
if [[ ! -f /proc/version ]] || ! grep -q -E "(Microsoft|WSL)" /proc/version 2>/dev/null; then
    echo "⚠ WARNING: This doesn't appear to be WSL"
    echo "Script should work on native Linux too"
fi

echo "Environment: $(uname -a)"
echo "User: $(whoami)"
echo

# Update system packages
echo "[1/5] Updating system packages..."
echo "----------------------------------------"
sudo apt-get update
echo "✅ Package list updated"

# Install essential build tools
echo
echo "[2/5] Installing build essentials..."
echo "----------------------------------------"
sudo apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    git \
    curl \
    wget \
    unzip

echo "✅ Build tools installed"

# Install ARM cross-compilation toolchain
echo
echo "[3/5] Installing ARM cross-compilation toolchain..."
echo "----------------------------------------"
sudo apt-get install -y \
    gcc-arm-linux-gnueabihf \
    g++-arm-linux-gnueabihf

echo "✅ ARM toolchain installed"

# Install SDL2 development libraries (for reference/testing)
echo
echo "[4/5] Installing SDL2 development libraries..."
echo "----------------------------------------"
sudo apt-get install -y \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-ttf-dev \
    || echo "⚠ SDL2 libraries installation failed (not critical for cross-compilation)"

echo "✅ SDL2 libraries installed"

# Verify installation
echo
echo "[5/5] Verifying installation..."
echo "----------------------------------------"

echo "Testing compilers:"
echo "  GCC: $(gcc --version | head -1)"
echo "  ARM GCC: $(arm-linux-gnueabihf-gcc --version | head -1)"
echo "  CMake: $(cmake --version | head -1)"
echo "  Make: $(make --version | head -1)"

# Test cross-compilation with a simple program
echo
echo "Testing ARM cross-compilation..."
cat > test_arm.c << 'EOF'
#include <stdio.h>
int main() {
    printf("Hello from ARM!\n");
    return 0;
}
EOF

arm-linux-gnueabihf-gcc test_arm.c -o test_arm
if [ $? -eq 0 ]; then
    echo "✅ ARM cross-compilation test successful"
    echo "   Binary info: $(file test_arm)"
    rm -f test_arm test_arm.c
else
    echo "❌ ARM cross-compilation test failed"
    rm -f test_arm test_arm.c
    exit 1
fi

# Create helpful aliases
echo
echo "Creating helpful aliases..."
cat >> ~/.bashrc << 'EOF'

# R36S Development Aliases
alias r36s-build='./build_for_r36s_wsl.sh'
alias r36s-package='./prepare_r36s_package_wsl.sh'
alias r36s-install='./copy_to_sd_card_wsl.sh'
alias r36s-full='./build_and_install_r36s_wsl.sh'
alias r36s-clean='rm -rf build_r36s r36s_viewer_package'

# Useful commands
alias ll='ls -la'
alias la='ls -A'
alias l='ls -CF'
EOF

echo "✅ Aliases added to ~/.bashrc"

# Setup Windows integration
echo
echo "Setting up Windows integration..."

# Create Windows Desktop shortcut script
mkdir -p "/mnt/c/Users/$USER/Desktop" 2>/dev/null || true

cat > "/mnt/c/Users/$USER/Desktop/R36S_Development.txt" << EOF
R36S Development Quick Reference
===============================

WSL Commands (run in Ubuntu terminal):
--------------------------------------
cd /mnt/c/path/to/your/subrim/project

# Full build and install:
./build_and_install_r36s_wsl.sh

# Step by step:
./build_for_r36s_wsl.sh          # Build for ARM
./prepare_r36s_package_wsl.sh    # Create package
./copy_to_sd_card_wsl.sh         # Install to SD

# Shortcuts (after sourcing ~/.bashrc):
r36s-full                        # Full build & install
r36s-build                       # Build only
r36s-package                     # Package only
r36s-install                     # SD card install
r36s-clean                       # Clean build files

Project Location in WSL:
/mnt/c/Users/$USER/path/to/subrim

Access WSL from Windows:
\\\\wsl$\\Ubuntu\\home\\$USER
EOF

echo "✅ Created Windows reference file"

# Final setup summary
echo
echo "============================================"
echo "    🎉 WSL SETUP COMPLETE! 🎉"
echo "============================================"
echo
echo "✅ Environment ready for R36S development"
echo
echo "📋 What's installed:"
echo "   • Build tools (gcc, cmake, make)"
echo "   • ARM cross-compiler (arm-linux-gnueabihf)"
echo "   • SDL2 development libraries"
echo "   • Helpful aliases and shortcuts"
echo
echo "🚀 Next steps:"
echo "1. Navigate to your project:"
echo "   cd /mnt/c/path/to/your/subrim/project"
echo
echo "2. Make scripts executable:"
echo "   chmod +x *.sh"
echo
echo "3. Run full build:"
echo "   ./build_and_install_r36s_wsl.sh"
echo
echo "💡 Helpful aliases (restart terminal or run 'source ~/.bashrc'):"
echo "   r36s-full    # Complete build & install"
echo "   r36s-build   # Build only"
echo "   r36s-clean   # Clean build files"
echo
echo "📁 Windows integration:"
echo "   Reference file: C:\\Users\\$USER\\Desktop\\R36S_Development.txt"
echo "   WSL access: \\\\wsl$\\Ubuntu\\home\\$USER"
echo
echo "Ready to build R36S Viewer! 🎮✨"
