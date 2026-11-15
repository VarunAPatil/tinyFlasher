#!/usr/bin/env python3
"""ESP32-S3 ROM serial flasher using only Python's standard library."""
import argparse
import errno
import fcntl
import hashlib
import os
import select
import struct
import sys
import termios
import time
from pathlib import Path

SYNC = 0x08
FLASH_BEGIN = 0x02
FLASH_DATA = 0x03
SPI_SET_PARAMS = 0x0B
SPI_ATTACH = 0x0D
SPI_FLASH_MD5 = 0x13
GET_SECURITY_INFO = 0x14
BLOCK = 1024
DEVICE_GLOB = "usb-Espressif_USB_JTAG_serial_debug_unit_*-if00"


def validate_image(image: bytes, flash_size_mb: int):
    if len(image) < 64 or image[0] != 0xE9 or image[1] == 0 or image[1] > 16:
        raise ValueError("invalid ESP boot image header")
    size_code = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5}[flash_size_mb]
    if image[3] >> 4 != size_code:
        raise ValueError("image flash size differs from --flash-size-mb; rebuild with FLASH_SIZE_MB set")
    if struct.unpack_from("<H", image, 12)[0] != 9 or image[23] != 1:
        raise ValueError("expected an ESP32-S3 image with SHA-256 digest")
    checksum = 0xEF
    offset = 24
    for _ in range(image[1]):
        if offset + 8 > len(image):
            raise ValueError("truncated image segment")
        _, size = struct.unpack_from("<II", image, offset)
        offset += 8
        if offset + size > len(image):
            raise ValueError("truncated image data")
        for byte in image[offset:offset + size]:
            checksum ^= byte
        offset += size
    checksum_offset = ((offset + 16) // 16) * 16 - 1
    if (checksum_offset + 33 != len(image) or image[checksum_offset] != checksum
            or hashlib.sha256(image[:checksum_offset + 1]).digest()
            != image[checksum_offset + 1:]):
        raise ValueError("image checksum or SHA-256 is invalid")


def slip_encode(payload: bytes) -> bytes:
    return b"\xc0" + payload.replace(b"\xdb", b"\xdb\xdd").replace(
        b"\xc0", b"\xdb\xdc") + b"\xc0"


class SerialPort:
    def __init__(self, path: str):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            settings = termios.tcgetattr(self.fd)
            settings[0] = 0
            settings[1] = 0
            settings[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            settings[3] = 0
            settings[4] = termios.B115200
            settings[5] = termios.B115200
            settings[6][termios.VMIN] = 1
            settings[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, settings)
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def set_lines(self, dtr: bool, rts: bool):
        bits = (termios.TIOCM_DTR if dtr else 0) | (termios.TIOCM_RTS if rts else 0)
        fcntl.ioctl(self.fd, termios.TIOCMSET, struct.pack("I", bits))

    def reset_to_download(self):
        # TRM 33.4.2: DTR sets the download flag; RTS with DTR low resets.
        self.set_lines(False, False)
        time.sleep(0.05)
        self.set_lines(True, False)
        time.sleep(0.05)
        self.set_lines(True, True)
        time.sleep(0.05)
        self.set_lines(False, True)
        time.sleep(0.10)
        self._release_reset()

    def reset_to_flash(self):
        self.set_lines(False, False)  # Clear download flag before reset.
        time.sleep(0.05)
        self.set_lines(False, True)
        time.sleep(0.10)
        self._release_reset()

    def _release_reset(self):
        try:
            self.set_lines(False, False)
        except OSError as exc:
            # Native USB can re-enumerate while the reset request is in flight.
            if exc.errno not in (errno.EIO, errno.ENODEV, errno.ENOENT):
                raise

    def write(self, data: bytes):
        while data:
            _, ready, _ = select.select([], [self.fd], [], 3)
            if not ready:
                raise TimeoutError("serial write timed out")
            try:
                data = data[os.write(self.fd, data):]
            except BlockingIOError:
                continue

    def read_byte(self, deadline: float) -> int:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [],
                                        max(0, deadline - time.monotonic()))
            if ready:
                try:
                    data = os.read(self.fd, 1)
                except BlockingIOError:
                    continue
                if data:
                    return data[0]
        raise TimeoutError("serial response timed out")

    def read_slip(self, deadline: float) -> bytes:
        frame = bytearray()
        started = False
        escaped = False
        while True:
            byte = self.read_byte(deadline)
            if byte == 0xC0:
                if started and frame:
                    return bytes(frame)
                started, escaped = True, False
                frame.clear()
            elif started:
                if escaped:
                    if byte not in (0xDC, 0xDD):
                        raise ValueError("bad SLIP escape")
                    frame.append(0xC0 if byte == 0xDC else 0xDB)
                    escaped = False
                elif byte == 0xDB:
                    escaped = True
                else:
                    frame.append(byte)
                if len(frame) > 4096:
                    raise ValueError("oversized ROM response")


class Rom:
    def __init__(self, port: SerialPort):
        self.port = port

    def command(self, opcode: int, payload: bytes = b"", checksum: int = 0,
                timeout: float = 5) -> tuple[int, bytes]:
        header = struct.pack("<BBHI", 0, opcode, len(payload), checksum)
        self.port.write(slip_encode(header + payload))
        deadline = time.monotonic() + timeout
        while True:
            reply = self.port.read_slip(deadline)
            if len(reply) < 12 or reply[0] != 1 or reply[1] != opcode:
                continue  # Boot text or an extra SYNC reply.
            size, value = struct.unpack_from("<HI", reply, 2)
            if len(reply) != size + 8 or size < 4:
                raise ValueError(f"invalid ROM response to 0x{opcode:02x}")
            status, error = reply[-4:-2]
            if status:
                raise RuntimeError(f"ROM command 0x{opcode:02x} failed: 0x{error:02x}")
            return value, reply[8:-4]

    def sync(self):
        for _ in range(5):
            try:
                self.command(SYNC, b"\x07\x07\x12\x20" + b"\x55" * 32,
                             timeout=1)
                return
            except TimeoutError:
                pass
        raise TimeoutError("No ROM response after automatic download reset")

    def flash(self, data: bytes, flash_size: int):
        self.sync()
        _, info = self.command(GET_SECURITY_INFO)
        if len(info) < 16 or struct.unpack_from("<I", info, 12)[0] != 9:
            raise RuntimeError("connected ROM did not identify as ESP32-S3")
        self.command(SPI_ATTACH, struct.pack("<II", 0, 0))
        self.command(SPI_SET_PARAMS, struct.pack("<IIIIII", 0, flash_size,
                                                0x10000, 0x1000, 0x100, 0xFFFF))
        blocks = (len(data) + BLOCK - 1) // BLOCK
        erase_size = ((len(data) + 4095) // 4096) * 4096
        self.command(FLASH_BEGIN, struct.pack("<IIIII", erase_size,
                                              blocks, BLOCK, 0, 0), timeout=20)
        for index in range(blocks):
            chunk = data[index * BLOCK:(index + 1) * BLOCK].ljust(BLOCK, b"\xff")
            checksum = 0xEF
            for byte in chunk:
                checksum ^= byte
            self.command(FLASH_DATA, struct.pack("<IIII", BLOCK, index, 0, 0)
                         + chunk, checksum=checksum, timeout=15)
            print(f"\rWriting: {index + 1}/{blocks} blocks", end="", flush=True)
        print()
        _, md5 = self.command(SPI_FLASH_MD5,
                              struct.pack("<IIII", 0, len(data), 0, 0), timeout=20)
        actual = bytes.fromhex(md5.decode("ascii"))
        expected = hashlib.md5(data).digest()
        if actual != expected:
            raise RuntimeError(f"flash MD5 mismatch: got {actual.hex()}, expected {expected.hex()}")
        print(f"Verified {len(data)} bytes at flash offset 0x0 (MD5 {actual.hex()}).")


def find_port(requested: str) -> str:
    if requested == "auto":
        deadline = time.monotonic() + 10
        while True:
            stable = list(Path("/dev/serial/by-id").glob(DEVICE_GLOB))
            if len(stable) == 1:
                return str(stable[0])
            if len(stable) > 1:
                raise OSError("multiple ESP32-S3 native USB ports found; pass --port")
            if time.monotonic() >= deadline:
                raise TimeoutError("ESP32-S3 native USB port did not appear")
            time.sleep(0.1)
    stable = list(Path("/dev/serial/by-id").glob(DEVICE_GLOB))
    for candidate in stable:
        try:
            if os.path.samefile(candidate, requested):
                return str(candidate)
        except OSError:
            pass
    return requested


def wait_for_port(path: str, seconds: float = 10) -> SerialPort:
    deadline = time.monotonic() + seconds
    while True:
        try:
            return SerialPort(path)
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENODEV, errno.EIO, errno.EBUSY):
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"USB serial port {path} did not reappear") from exc
            time.sleep(0.1)


def monitor(path: str):
    print("Monitoring USB Serial/JTAG at 115200. Ctrl-C to stop.", file=sys.stderr)
    while True:
        port = wait_for_port(path, 30)
        print("[monitor] connected", file=sys.stderr)
        try:
            while True:
                ready, _, _ = select.select([port.fd], [], [], 1)
                if not ready:
                    continue
                try:
                    data = os.read(port.fd, 4096)
                except BlockingIOError:
                    continue
                if not data:
                    break
                os.write(sys.stdout.fileno(), data)
        except OSError as exc:
            if exc.errno not in (errno.EIO, errno.ENODEV, errno.ENOENT):
                raise
        finally:
            port.close()
        print("[monitor] USB disconnected; waiting for reconnect", file=sys.stderr)
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("flash", "monitor"))
    parser.add_argument("--port", default="auto", help="native USB Serial/JTAG tty (default: auto-detect)")
    parser.add_argument("--image", type=Path, default=Path("build/hello.bin"))
    parser.add_argument("--monitor", action="store_true", help="monitor after flashing and automatic reboot")
    parser.add_argument("--flash-size-mb", type=int, default=4,
                        choices=(1, 2, 4, 8, 16, 32), help="physical flash capacity")
    args = parser.parse_args()
    path = find_port(args.port)
    if args.action == "flash":
        image = args.image.read_bytes()
        validate_image(image, args.flash_size_mb)
        port = wait_for_port(path)
        try:
            print("Resetting ESP32-S3 into ROM download mode...")
            port.reset_to_download()
        finally:
            port.close()
        time.sleep(0.2)
        port = wait_for_port(path)
        try:
            Rom(port).flash(image, args.flash_size_mb * 1024 * 1024)
            print("Resetting ESP32-S3 to run the new image...")
            port.reset_to_flash()
        finally:
            port.close()
        if args.monitor:
            monitor(path)
    else:
        monitor(path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except (OSError, ValueError, TimeoutError, RuntimeError) as exc:
        raise SystemExit(f"error: {exc}")
