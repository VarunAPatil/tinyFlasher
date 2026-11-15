#!/usr/bin/env python3
"""Make a minimal ESP32-S3 ROM boot image from our ELF, without SDK tools."""
import hashlib
import struct
import sys
from pathlib import Path


FLASH_SIZE_CODES = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5}


def make_image(elf: bytes, flash_size_mb: int = 4) -> bytes:
    if flash_size_mb not in FLASH_SIZE_CODES:
        raise ValueError("flash size must be 1, 2, 4, 8, 16, or 32 MB")
    if elf[:4] != b"\x7fELF" or elf[4:6] != b"\x01\x01":
        raise ValueError("expected little-endian ELF32")
    entry = struct.unpack_from("<I", elf, 24)[0]
    shoff = struct.unpack_from("<I", elf, 32)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 46)
    if shentsize != 40 or shstrndx >= shnum:
        raise ValueError("invalid ELF section table")
    sections = [struct.unpack_from("<IIIIIIIIII", elf, shoff + i * 40)
                for i in range(shnum)]
    names = sections[shstrndx]
    strtab = elf[names[4]:names[4] + names[5]]

    def section(name: bytes):
        for s in sections:
            end = strtab.find(b"\0", s[0])
            if strtab[s[0]:end] == name:
                if s[1] != 1 or not s[5] or s[4] + s[5] > len(elf):
                    raise ValueError(f"bad {name.decode()} section")
                return s[3], elf[s[4]:s[4] + s[5]]
        raise ValueError(f"missing {name.decode()} section")

    segments = [(address, data.ljust((len(data) + 3) & ~3, b"\0"))
                for address, data in (section(b".iram"), section(b".dram"))]
    if not (segments[0][0] <= entry < segments[0][0] + len(segments[0][1])):
        raise ValueError("entry is outside IRAM segment")

    # 8-byte header: magic, segment count, DIO mode, flash size / 40 MHz, entry.
    image = bytearray(struct.pack("<BBBBI", 0xE9, len(segments), 2,
                                  FLASH_SIZE_CODES[flash_size_mb] << 4, entry))
    # 16-byte extended header: WP pin, drive strengths, S3 chip ID, rev limits,
    # reserved, and hash-present flag. 0xEE leaves the WP pin on its default.
    image += struct.pack("<BBBBHBHH4sB", 0xEE, 0, 0, 0, 9, 0, 0, 0xFFFF,
                         b"\0" * 4, 1)
    checksum = 0xEF
    for address, data in segments:
        image += struct.pack("<II", address, len(data)) + data
        for byte in data:
            checksum ^= byte
    image += b"\0" * ((-len(image) - 1) % 16)
    image.append(checksum)
    image += hashlib.sha256(image).digest()
    return bytes(image)


def main() -> None:
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: elf2image.py INPUT.elf OUTPUT.bin [FLASH_SIZE_MB]")
    size = int(sys.argv[3]) if len(sys.argv) == 4 else 4
    output = make_image(Path(sys.argv[1]).read_bytes(), size)
    Path(sys.argv[2]).write_bytes(output)
    print(f"Wrote {sys.argv[2]} ({len(output)} bytes)")


if __name__ == "__main__":
    main()
