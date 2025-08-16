# GBA Cross-compilation makefile
CC = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy

CFLAGS = -mthumb -mthumb-interwork -nostdlib -fno-builtin -O2
LDFLAGS = -T gba.ld

SOURCES = viewer.c
OBJECTS = $(SOURCES:.c=.o)
TARGET = viewer

all: $(TARGET).gba

$(TARGET).elf: $(OBJECTS)
	$(CC) $(LDFLAGS) -o $@ $^

$(TARGET).gba: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@
	# Add GBA header (would need gbafix tool in real setup)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f *.o *.elf *.gba

.PHONY: all clean
