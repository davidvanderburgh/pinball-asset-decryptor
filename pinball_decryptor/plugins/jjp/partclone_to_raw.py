#!/usr/bin/env python3
"""
Convert a partclone v2 image (gzipped, possibly split) to a raw disk image.
Based on the partclone source code struct definitions:
  image_desc_v2 = image_head_v2 + file_system_info_v2 + image_options_v2 + crc
"""

import struct
import gzip
import sys
import os
import math


def read_exact(f, n):
    """Read exactly n bytes from file-like object."""
    data = b""
    while len(data) < n:
        chunk = f.read(n - len(data))
        if not chunk:
            raise EOFError(f"Expected {n} bytes, got {len(data)}")
        data += chunk
    return data


class MultiFileReader:
    """Read from multiple files as if they were one concatenated file."""
    def __init__(self, file_paths):
        self.file_paths = sorted(file_paths)
        self.current_index = 0
        self.current_file = open(self.file_paths[0], "rb")

    def read(self, n):
        data = b""
        while len(data) < n:
            if self.current_file is None:
                break
            chunk = self.current_file.read(n - len(data))
            if chunk:
                data += chunk
            else:
                self.current_file.close()
                self.current_index += 1
                if self.current_index >= len(self.file_paths):
                    self.current_file = None
                    break
                self.current_file = open(self.file_paths[self.current_index], "rb")
        return data

    def close(self):
        if self.current_file is not None:
            self.current_file.close()
            self.current_file = None


def convert_partclone_to_raw(input_parts, output_path):
    print(f"Opening {len(input_parts)} input part(s)...")
    multi = MultiFileReader(input_parts)
    f = gzip.open(multi, "rb")

    # === image_head_v2 (36 bytes) ===
    magic = read_exact(f, 16)  # IMAGE_MAGIC_SIZE + 1
    assert magic[:15] == b"partclone-image", f"Bad magic: {magic}"
    print(f"Magic: OK")

    ptc_version = read_exact(f, 14)  # PARTCLONE_VERSION_SIZE
    print(f"Partclone version: {ptc_version.decode('ascii', errors='replace').rstrip(chr(0))}")

    version = read_exact(f, 4)  # IMAGE_VERSION_SIZE
    version_str = version.decode("ascii", errors="replace")
    print(f"Image version: {version_str}")

    endianess = struct.unpack("<H", read_exact(f, 2))[0]
    is_le = endianess == 0xC0DE
    print(f"Endianness: 0x{endianess:04X} ({'LE' if is_le else 'BE'})")
    assert is_le, "Only little-endian images supported"

    # === file_system_info_v2 (52 bytes) ===
    fs_type = read_exact(f, 16)  # FS_MAGIC_SIZE + 1
    print(f"File system: {fs_type.decode('ascii', errors='replace').rstrip(chr(0))}")

    device_size = struct.unpack("<Q", read_exact(f, 8))[0]
    print(f"Device size: {device_size} bytes ({device_size / (1024**3):.2f} GiB)")

    total_blocks = struct.unpack("<Q", read_exact(f, 8))[0]
    print(f"Total blocks: {total_blocks}")

    super_used = struct.unpack("<Q", read_exact(f, 8))[0]
    print(f"Superblock used blocks: {super_used}")

    used_blocks = struct.unpack("<Q", read_exact(f, 8))[0]
    print(f"Used blocks (bitmap): {used_blocks}")

    block_size = struct.unpack("<I", read_exact(f, 4))[0]
    print(f"Block size: {block_size}")

    # === image_options_v2 (18 bytes) ===
    feature_size = struct.unpack("<I", read_exact(f, 4))[0]
    print(f"Feature size: {feature_size}")

    image_version = struct.unpack("<H", read_exact(f, 2))[0]
    cpu_bits = struct.unpack("<H", read_exact(f, 2))[0]
    checksum_mode = struct.unpack("<H", read_exact(f, 2))[0]
    checksum_size = struct.unpack("<H", read_exact(f, 2))[0]
    blocks_per_checksum = struct.unpack("<I", read_exact(f, 4))[0]
    reseed_checksum = struct.unpack("<B", read_exact(f, 1))[0]
    bitmap_mode = struct.unpack("<B", read_exact(f, 1))[0]
    print(f"Image version (opts): {image_version}")
    print(f"CPU bits: {cpu_bits}")
    print(f"Checksum mode: {checksum_mode}")
    print(f"Checksum size: {checksum_size} bytes")
    print(f"Blocks per checksum: {blocks_per_checksum}")
    print(f"Reseed checksum: {reseed_checksum}")
    print(f"Bitmap mode: {bitmap_mode} ({'BM_BIT' if bitmap_mode == 1 else 'BM_BYTE' if bitmap_mode == 2 else 'BM_NONE'})")

    # === CRC of descriptor (4 bytes) ===
    desc_crc = struct.unpack("<I", read_exact(f, 4))[0]
    print(f"Descriptor CRC: 0x{desc_crc:08X}")

    # === Bitmap ===
    if bitmap_mode == 1:  # BM_BIT
        bitmap_bytes = math.ceil(total_blocks / 8)
    elif bitmap_mode == 2:  # BM_BYTE
        bitmap_bytes = total_blocks
    else:
        raise ValueError(f"Unsupported bitmap mode: {bitmap_mode}")

    print(f"\nReading bitmap ({bitmap_bytes} bytes)...")
    bitmap = read_exact(f, bitmap_bytes)

    # Bitmap checksum
    if checksum_size > 0:
        bitmap_crc = read_exact(f, checksum_size)
        print(f"Bitmap checksum: {bitmap_crc.hex()}")

    # Count used blocks in bitmap
    if bitmap_mode == 1:
        set_bits = sum(bin(b).count("1") for b in bitmap)
    else:
        set_bits = sum(1 for b in bitmap if b)
    print(f"Bitmap used blocks: {set_bits} (header says: {used_blocks})")

    # === Write raw image ===
    raw_size = total_blocks * block_size
    print(f"\nWriting raw image to {output_path}...")
    print(f"Raw image size will be: {raw_size} bytes ({raw_size / (1024**3):.2f} GiB)")

    zero_block = b"\x00" * block_size
    data_blocks_read = 0

    with open(output_path, "wb") as out:
        for block_idx in range(total_blocks):
            # Check bitmap
            if bitmap_mode == 1:
                byte_idx = block_idx // 8
                bit_idx = block_idx % 8
                is_used = (bitmap[byte_idx] >> bit_idx) & 1
            else:
                is_used = bitmap[block_idx]

            if is_used:
                block_data = read_exact(f, block_size)
                out.write(block_data)
                data_blocks_read += 1

                # Read checksum after every blocks_per_checksum data blocks
                if checksum_size > 0 and blocks_per_checksum > 0:
                    if data_blocks_read % blocks_per_checksum == 0:
                        read_exact(f, checksum_size)  # skip checksum
            else:
                out.write(zero_block)

            if (block_idx + 1) % 100000 == 0:
                pct = (block_idx + 1) / total_blocks * 100
                print(f"  Progress: {pct:.1f}% ({block_idx + 1}/{total_blocks}, {data_blocks_read} data blocks read)", flush=True)

    print(f"\nDone! Read {data_blocks_read} data blocks (expected {used_blocks}).")
    print(f"Output size: {os.path.getsize(output_path)} bytes")

    f.close()
    multi.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <output_raw_image> <input_part1> [input_part2] ...")
        sys.exit(1)

    output = sys.argv[1]
    parts = sys.argv[2:]
    convert_partclone_to_raw(parts, output)
