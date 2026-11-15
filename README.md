# tinyFlasher

Bare-metal ESP32-S3 firmware with a custom native USB ROM flasher and monitor.
It builds and flashes without ESP-IDF.

Demo: [tinyFlasher-demo.mp4](demo/tinyFlasher-demo.mp4)

## Requirements

- ESP32-S3 board with its **native USB Serial/JTAG** connector wired to
  GPIO19 (D-) and GPIO20 (D+). Use that connector, not a separate UART bridge
  or the USB-OTG interface.
- An Xtensa compiler, `make`, and Python 3 on Linux. The compiler can be
  installed in a separate directory; the project does not look inside any
  vendor SDK installation. Put `xtensa-esp32s3-elf-gcc` on `PATH` or pass its
  executable prefix to `make` as shown below.
- A board with ordinary, unencrypted SPI flash and ROM download mode enabled.
  The default image header assumes 4 MB flash at 40 MHz in DIO mode.

## Build

```sh
make
```

With a compiler installed outside `PATH`:

```sh
make XTENSA_PREFIX=/path/to/toolchain/bin/xtensa-esp32s3-elf-
```

`XTENSA_PREFIX` is the path and name before `gcc` and `objdump`. The compiler
is still required to turn Xtensa assembly and C into machine code; it is an
external build tool, separate from the firmware and flasher.

For a different flash capacity, use the same value for build and flash:

```sh
make clean
make FLASH_SIZE_MB=8
```

The output is `build/hello.bin`. The ELF and linker map are also in `build/`.

## Flash over native USB

1. Connect the board's native USB connector.
2. Run the custom flasher and monitor:

```sh
python3 tools/flash.py flash --monitor
```

The script auto-detects one Espressif native USB tty under `/dev/serial/by-id/`.
If several boards are connected, pass `--port /dev/ttyACM0` or a stable
`/dev/serial/by-id/...` path. It uses CDC DTR/RTS control signals to enter
download mode and to boot the new firmware after verification. No BOOT or
RESET button press is needed on boards that support these native USB controls.

For an 8 MB board built with `FLASH_SIZE_MB=8`, add `--flash-size-mb 8`.
The script checks the chip ID, writes only the beginning of flash, and asks
the ROM to calculate MD5 over the image. It does not use a third-party flash
stub. Flashing at offset `0x0` replaces the previous boot image.

To open only the terminal later:

```sh
python3 tools/flash.py monitor
```

It should print `Hello, world from ESP32-S3 USB Serial/JTAG!` repeatedly.
Press Ctrl-C to exit. The monitor reconnects if the USB tty re-enumerates.

## Scope and layout

- `firmware/start.S` sets a stack and calls `main`.
- `firmware/main.c` polls the USB Serial/JTAG transmit FIFO and flushes each
  short message into a USB packet. It also finishes ROM clock and watchdog
  setup needed for a bare-metal runtime.
- `firmware/linker.ld` places code and constants in SRAM for the ROM to load.
- `tools/elf2image.py` emits the ESP32-S3 ROM image header, two load segments,
  checksum, and SHA-256 digest.
- `tools/flash.py` implements SLIP framing and the ROM `SYNC`, SPI attach,
  flash write, and MD5 verification commands using Linux tty access. It also
  controls DTR/RTS for automatic boot transitions and monitors the tty.

The CPU uses the USB controller's built-in CDC interface; implementing a new
USB descriptor stack is unnecessary for this peripheral. The PC still uses
its normal USB and tty kernel drivers. This is a minimal hello-world program,
not a general purpose board support package. It does not handle flash
encryption, secure boot, custom flash pins, or USB-OTG boards.

## Hardware references

- [ESP32-S3 Technical Reference Manual, chapters 4, 8 and 33](https://documentation.espressif.com/esp32-s3_technical_reference_manual_en.pdf)
- [ESP32-S3 ROM serial protocol](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/serial-protocol.html)
- [ESP32-S3 ROM firmware image format](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/firmware-image-format.html)
