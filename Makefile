XTENSA_PREFIX ?= xtensa-esp32s3-elf-
CC := $(XTENSA_PREFIX)gcc
OBJDUMP := $(XTENSA_PREFIX)objdump

CFLAGS := -Os -ffreestanding -fno-builtin -fno-stack-protector -fdata-sections -ffunction-sections -mtext-section-literals -mabi=call0 -Wall -Wextra
LDFLAGS := -nostdlib -Wl,--gc-sections -Wl,-T,firmware/linker.ld -Wl,-Map,build/hello.map
FLASH_SIZE_MB ?= 4

.PHONY: all clean inspect
all: build/hello.bin

build:
	mkdir -p build

build/start.o: firmware/start.S | build
	$(CC) $(CFLAGS) -c $< -o $@

build/main.o: firmware/main.c | build
	$(CC) $(CFLAGS) -c $< -o $@

build/hello.elf: build/start.o build/main.o firmware/linker.ld
	$(CC) $(CFLAGS) $(LDFLAGS) build/start.o build/main.o -o $@

build/hello.bin: build/hello.elf tools/elf2image.py
	python3 tools/elf2image.py $< $@ $(FLASH_SIZE_MB)

inspect: build/hello.elf
	$(OBJDUMP) -h -d $<

clean:
	rm -f build/start.o build/main.o build/hello.elf build/hello.bin build/hello.map
