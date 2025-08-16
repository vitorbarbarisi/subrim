#ifndef GBA_H
#define GBA_H

// GBA Memory mapped registers
#define REG_DISPCNT *(volatile unsigned short*)0x4000000
#define REG_KEYINPUT *(volatile unsigned short*)0x4000130

// Video Memory
#define VRAM ((volatile unsigned short*)0x6000000)

// Colors (15-bit RGB)
#define BLACK   0x0000
#define WHITE   0x7FFF
#define RED     0x001F
#define GREEN   0x03E0
#define BLUE    0x7C00
#define YELLOW  0x03FF
#define CYAN    0x7FE0
#define MAGENTA 0x7C1F

// Video modes
#define MODE_0  0
#define MODE_3  3
#define MODE_4  4

// Key defines
#define KEY_A       (1 << 0)
#define KEY_B       (1 << 1)
#define KEY_SELECT  (1 << 2)
#define KEY_START   (1 << 3)
#define KEY_RIGHT   (1 << 4)
#define KEY_LEFT    (1 << 5)
#define KEY_UP      (1 << 6)
#define KEY_DOWN    (1 << 7)

#endif
