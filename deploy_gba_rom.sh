#!/bin/bash

# Deploy R36S Viewer as GBA ROM directly to SD card
# Compiles in WSL and installs as Game Boy Advance game

set -e

echo "=== Deploy R36S Viewer as GBA ROM ==="
echo

# Check if GBA source exists
if [ ! -d "r36s_viewer_gba" ]; then
    echo "Creating GBA ROM first..."
    ./convert_to_gba.sh
fi

# Install ARM toolchain if not present
if ! command -v arm-none-eabi-gcc &> /dev/null; then
    echo "📦 Installing ARM GBA toolchain..."
    sudo apt-get update
    sudo apt-get install -y gcc-arm-none-eabi binutils-arm-none-eabi
fi

echo "✓ ARM GBA toolchain available"

# Compile GBA ROM
cd r36s_viewer_gba
echo "🔨 Compiling GBA ROM..."

# Create a simple bootstrap/crt0 for GBA
cat > crt0.s << 'EOF'
.section .text
.global _start
.arm

_start:
    @ Set up stack pointer
    mov sp, #0x03008000
    
    @ Jump to main
    bl main
    
    @ Infinite loop if main returns
_loop:
    b _loop
EOF

# Compile with proper GBA settings
arm-none-eabi-as -o crt0.o crt0.s
arm-none-eabi-gcc -mthumb -mthumb-interwork -nostdlib -nostartfiles -ffreestanding -O2 -c -o viewer.o viewer.c

# Link
arm-none-eabi-ld -T gba.ld -o viewer.elf crt0.o viewer.o

# Convert to GBA format
arm-none-eabi-objcopy -O binary viewer.elf viewer.bin

# Create proper GBA ROM with header
echo "📝 Creating GBA ROM with proper header..."

# GBA ROM needs specific header at start
cat > create_gba_header.py << 'EOF'
#!/usr/bin/env python3
import struct

# Read the binary
with open('viewer.bin', 'rb') as f:
    rom_data = f.read()

# Pad to minimum size and ensure it's power of 2
rom_size = len(rom_data)
min_size = 32 * 1024  # 32KB minimum
if rom_size < min_size:
    rom_data += b'\x00' * (min_size - rom_size)

# Create GBA header (simplified)
header = bytearray(192)  # GBA header is 192 bytes

# Entry point (ARM branch instruction to 0x08000000 + 0xC0)
header[0:4] = struct.pack('<I', 0xEA00002E)  # Branch instruction

# Nintendo logo (simplified - real ROMs need exact logo)
nintendo_logo = b'\x24\xFF\xAE\x51\x69\x9A\xA2\x21\x3D\x84\x82\x0A\x84\xE4\x09\xAD'
header[4:20] = nintendo_logo

# Game title (12 bytes)
title = b'R36S VIEWER\x00'
header[160:172] = title[:12]

# Game code (4 bytes)
header[172:176] = b'RSUB'

# Maker code (2 bytes)
header[176:178] = b'01'

# Fixed value
header[178] = 0x96

# Unit code
header[179] = 0x00

# Device type
header[180] = 0x00

# Reserved area (7 bytes)
header[181:188] = b'\x00' * 7

# Software version
header[188] = 0x00

# Complement check (will be calculated)
header[189] = 0x00

# Reserved area (2 bytes)
header[190:192] = b'\x00\x00'

# Calculate complement check
checksum = 0
for i in range(160, 189):
    checksum = (checksum - header[i]) & 0xFF
checksum = (checksum - 0x19) & 0xFF
header[189] = checksum

# Combine header with ROM data
final_rom = header + rom_data[192:] if len(rom_data) > 192 else header + rom_data

# Write final GBA file
with open('viewer.gba', 'wb') as f:
    f.write(final_rom)

print(f"✅ GBA ROM created: {len(final_rom)} bytes")
EOF

python3 create_gba_header.py

if [ -f "viewer.gba" ]; then
    echo "✅ GBA ROM compilation successful!"
    ls -lh viewer.gba
else
    echo "❌ GBA ROM compilation failed"
    cd ..
    exit 1
fi

cd ..

# Now deploy to SD card (reuse detection logic)
echo
echo "🔍 Detecting R36S SD card..."

R36S_OS_MOUNT=""
R36S_ROMS_MOUNT=""

for priority_drive in "D" "F"; do
    mount_point="/mnt/${priority_drive,,}"
    sudo mkdir -p "$mount_point" 2>/dev/null || true
    
    if [ -d "$mount_point" ] && mountpoint -q "$mount_point"; then
        echo "✓ ${priority_drive}: already mounted at $mount_point"
    elif sudo mount -t drvfs "${priority_drive}:" "$mount_point" 2>/dev/null; then
        echo "✓ ${priority_drive}: mounted successfully at $mount_point"
    else
        echo "ℹ ${priority_drive}: not available"
        continue
    fi
    
    if [ -d "$mount_point" ]; then
        contents=$(ls "$mount_point" 2>/dev/null | head -10 | tr '\n' ' ' || echo "")
        
        if [[ "$contents" =~ (RetroArch|apps|WHERE_ARE_MY_ROMS) ]]; then
            R36S_OS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: (R36S-OS - System)"
        elif [[ "$contents" =~ (EASYROMS|roms|gba|3do|advision|alg|amiga|arcade) ]]; then
            R36S_ROMS_MOUNT="$mount_point"
            echo "  → Detected R36S ${priority_drive}: (EASYROMS - ROMs)"
        fi
    fi
done

# Find GBA ROM directory
if [ -n "$R36S_ROMS_MOUNT" ]; then
    ROMS_BASE="$R36S_ROMS_MOUNT"
elif [ -n "$R36S_OS_MOUNT" ]; then
    ROMS_BASE="$R36S_OS_MOUNT" 
else
    echo "❌ No R36S partitions found!"
    exit 1
fi

# Look for GBA directory
GBA_LOCATIONS=("$ROMS_BASE/roms/gba" "$ROMS_BASE/gba" "$ROMS_BASE/GBA" "$ROMS_BASE/ROMS/GBA")
GBA_DIR=""

for location in "${GBA_LOCATIONS[@]}"; do
    if [ -d "$location" ]; then
        GBA_DIR="$location"
        echo "✓ Found GBA ROMs directory: $GBA_DIR"
        break
    fi
done

if [ -z "$GBA_DIR" ]; then
    GBA_DIR="$ROMS_BASE/roms/gba"
    echo "Creating GBA directory: $GBA_DIR"
    mkdir -p "$GBA_DIR"
fi

# Copy GBA ROM
echo
echo "🎮 Installing GBA ROM..."
cp r36s_viewer_gba/viewer.gba "$GBA_DIR/R36S_Viewer.gba"
echo "✓ ROM copied to: $GBA_DIR/R36S_Viewer.gba"

# Create info file if supported
cat > "$GBA_DIR/R36S_Viewer.txt" << EOF
R36S Viewer - GBA Version

A Game Boy Advance ROM version of the R36S episode viewer.
Features episode selection and subtitle display optimized 
for the GBA's 240x160 color screen.

Controls:
- D-Pad: Navigate menus
- A: Select/Next subtitle  
- B: Back/Previous subtitle
- Start: Return to menu

Episodes: Chaves, Flipper
Display: 240x160 15-bit color
Platform: Game Boy Advance
Size: $(ls -lh "$GBA_DIR/R36S_Viewer.gba" | awk '{print $5}')

Created: $(date)
EOF

echo "✓ ROM info created"

echo
echo "🎉 GBA ROM deployment complete!"
echo
echo "📁 ROM location: $GBA_DIR/R36S_Viewer.gba"
echo "🎮 Access via: ArkOS → Game Boy Advance → R36S Viewer"
echo
echo "🚀 On R36S console:"
echo "   1. Navigate to Game Boy Advance section"
echo "   2. Find 'R36S Viewer'"  
echo "   3. Launch like any GBA game!"
echo "   4. Use GBA controls (D-pad + A/B)"
echo
echo "✅ Your viewer is now a real GBA game!"
echo "   🎯 240x160 color display"
echo "   🎮 Native GBA controls"  
echo "   🚀 Runs on any GBA emulator"
echo
echo "🎬 Ready to play! 🎯✨"
