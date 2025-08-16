#!/bin/bash

# Convert R36S Viewer to Game Boy ROM
# Creates a .gb file that can be played on any Game Boy emulator

set -e

echo "=== Converting R36S Viewer to Game Boy ROM ==="
echo

# Check dependencies
if ! command -v gbdk-2020-build &> /dev/null; then
    echo "📦 Installing GBDK (Game Boy Development Kit)..."
    echo "   Download from: https://github.com/gbdk-2020/gbdk-2020/releases"
    echo "   Or install via package manager"
    exit 1
fi

echo "✓ GBDK available"

# Create Game Boy version directory
GB_DIR="r36s_viewer_gameboy"
rm -rf "$GB_DIR"
mkdir -p "$GB_DIR"

# Create simplified Game Boy C code
cat > "$GB_DIR/viewer.c" << 'EOF'
#include <gb/gb.h>
#include <stdio.h>
#include <string.h>

// Game Boy screen: 160x144 pixels, 20x18 tiles
#define SCREEN_WIDTH 20
#define SCREEN_HEIGHT 18

// Episode data (simplified for Game Boy)
const char* episodes[] = {
    "CHAVES 001",
    "CHAVES 002", 
    "CHAVES 003",
    "FLIPPER 001",
    "FLIPPER 002"
};

const char* subtitles[][3] = {
    {"CHAVES: OLA DONA FLORINDA!", "FLORINDA: OLA CHAVES!", "CHAVES: COMO ESTA?"},
    {"CHAVES: HOJE E UM BOM DIA", "FLORINDA: SIM, VERDADE", "CHAVES: VAMOS BRINCAR?"},
    {"CHAVES: QUE DIVERTIDO!", "FLORINDA: CUIDADO CHAVES", "CHAVES: ESTA BEM!"},
    {"FLIPPER: INICIO DO SHOW", "FLIPPER: APRESENTACAO", "FLIPPER: DIVERSAO TOTAL"},
    {"FLIPPER: NOVO EPISODIO", "FLIPPER: AVENTURAS", "FLIPPER: FINAL FELIZ"}
};

UINT8 current_episode = 0;
UINT8 current_subtitle = 0;
UINT8 total_episodes = 5;

void clear_screen() {
    // Clear background
    for (UINT8 y = 0; y < SCREEN_HEIGHT; y++) {
        for (UINT8 x = 0; x < SCREEN_WIDTH; x++) {
            set_bkg_tile_xy(x, y, 0);
        }
    }
}

void print_text(UINT8 x, UINT8 y, const char* text) {
    UINT8 len = strlen(text);
    for (UINT8 i = 0; i < len && i < (SCREEN_WIDTH - x); i++) {
        // Convert ASCII to tile numbers (simple mapping)
        UINT8 tile = text[i] - 32; // ASCII space = tile 0
        if (tile > 95) tile = 0; // Invalid chars become space
        set_bkg_tile_xy(x + i, y, tile + 32); // Offset for font tiles
    }
}

void show_episode_menu() {
    clear_screen();
    
    print_text(2, 2, "R36S VIEWER");
    print_text(2, 4, "SELECIONE EPISODIO:");
    
    for (UINT8 i = 0; i < total_episodes; i++) {
        if (i == current_episode) {
            print_text(1, 6 + i, ">");
        } else {
            print_text(1, 6 + i, " ");
        }
        print_text(3, 6 + i, episodes[i]);
    }
    
    print_text(2, 14, "A=PLAY B=EXIT");
    print_text(2, 15, "UP/DOWN=NAVEGAR");
}

void show_subtitle_viewer() {
    clear_screen();
    
    print_text(2, 1, episodes[current_episode]);
    print_text(2, 3, "LEGENDAS:");
    
    // Show current subtitle
    print_text(1, 6, subtitles[current_episode][current_subtitle]);
    
    // Show progress
    print_text(2, 10, "LEGENDA:");
    char progress[10];
    sprintf(progress, "%d/3", current_subtitle + 1);
    print_text(11, 10, progress);
    
    print_text(2, 13, "A=NEXT START=MENU");
    print_text(2, 14, "B=PREV SELECT=EXIT");
}

void main() {
    // Initialize Game Boy
    DISPLAY_ON;
    SHOW_BKG;
    
    // Set up a simple font (ASCII characters)
    // In real implementation, you'd load actual font tiles
    
    UINT8 in_menu = 1;
    UINT8 keys, previous_keys = 0;
    
    show_episode_menu();
    
    while(1) {
        keys = joypad();
        UINT8 pressed = keys & ~previous_keys;
        
        if (in_menu) {
            // Episode selection menu
            if (pressed & J_UP && current_episode > 0) {
                current_episode--;
                show_episode_menu();
            }
            
            if (pressed & J_DOWN && current_episode < total_episodes - 1) {
                current_episode++;
                show_episode_menu();
            }
            
            if (pressed & J_A) {
                // Start viewing episode
                current_subtitle = 0;
                in_menu = 0;
                show_subtitle_viewer();
            }
            
            if (pressed & J_B) {
                // Exit (in real Game Boy, this would return to menu)
                break;
            }
        } else {
            // Subtitle viewer
            if (pressed & J_A && current_subtitle < 2) {
                current_subtitle++;
                show_subtitle_viewer();
            }
            
            if (pressed & J_B && current_subtitle > 0) {
                current_subtitle--;
                show_subtitle_viewer();
            }
            
            if (pressed & J_START) {
                // Return to menu
                in_menu = 1;
                show_episode_menu();
            }
            
            if (pressed & J_SELECT) {
                // Exit
                break;
            }
        }
        
        previous_keys = keys;
        wait_vbl_done(); // Wait for vertical blank
    }
}
EOF

echo "✓ Game Boy C code created"

# Create makefile
cat > "$GB_DIR/Makefile" << 'EOF'
CC = lcc -Wa-l -Wl-m -Wl-j

BINS = viewer.gb

all: $(BINS)

%.o: %.c
	$(CC) -c -o $@ $<

%.gb: %.o
	$(CC) -o $@ $<

clean:
	rm -f *.o *.lst *.map *.gb *.sym

.PHONY: clean all
EOF

echo "✓ Makefile created"

# Try to compile
cd "$GB_DIR"
if command -v lcc &> /dev/null; then
    echo "🔨 Compiling Game Boy ROM..."
    make
    if [ -f "viewer.gb" ]; then
        echo "✅ Game Boy ROM created: viewer.gb"
        ls -lh viewer.gb
    else
        echo "❌ Compilation failed"
    fi
else
    echo "⚠ GBDK compiler not found. ROM source ready for manual compilation."
fi

cd ..
echo
echo "🎮 Game Boy ROM conversion complete!"
echo "📁 Files in: $GB_DIR/"
echo "🎯 ROM file: $GB_DIR/viewer.gb (if compiled)"
echo
echo "🚀 To test:"
echo "   1. Copy viewer.gb to R36S /roms/gb/ folder"
echo "   2. Launch from Game Boy section in ArkOS"
echo "   3. Use D-pad + A/B buttons to navigate"
echo
echo "📋 Game Boy controls:"
echo "   D-pad: Navigate menus"
echo "   A: Select/Next subtitle"
echo "   B: Back/Previous subtitle"
echo "   Start: Menu"
echo "   Select: Exit"
