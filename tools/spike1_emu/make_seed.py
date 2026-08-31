"""Seed a 64KB board EEPROM with a valid NVRG section so the firmware stops
re-formatting. Layout decoded from nv_section_eeprom_read / nv_block_eeprom_read:
  0x2000: 'NVRG' (u32 magic) + active_block (u32, 0)
  0x2008: block0 header: 'NVBL' (u32) + len (u32) + crc32 (u32, standard)
  0x2014: block0 data (len bytes)
  0x3004/0x3010: block1 header/data (mirror)
CRC32 = standard (init ~0, reflected, final xor) = zlib.crc32.
"""
import struct
import sys
import zlib

size = 0x10000
ee = bytearray(b"\xff" * size)


def region_header(value):
    """persistent-storage region header (validate_region): {u32 value,
    u32 ~sum32(value)} — for a 4-byte value sum32 == value, so checksum =
    ~value. Read from (region_base - 8)."""
    return struct.pack("<II", value & 0xffffffff, (~value) & 0xffffffff)


# The two persistent-storage regions' headers sit just below their bases:
# region A base 0x6000 -> header 0x5ff8; region B base 0x8000 -> header 0x7ff8
# (validate_region reads base-8; read_bytes adds the region's own base
# offset, so the real EEPROM offsets are 0x5ff8 / 0x7ff8 — confirmed from the
# i2c transaction log). Higher value = active (ping-pong).
ee[0x5ff8:0x6000] = region_header(2)
ee[0x7ff8:0x8000] = region_header(1)

data = bytes(2048)                          # empty section (zeros), valid CRC
crc = zlib.crc32(data) & 0xffffffff

# section header @0x2000
ee[0x2000:0x2004] = b"NVRG"
ee[0x2004:0x2008] = struct.pack("<I", 0)    # active block 0

# block 0 header @0x2008 + data @0x2014
ee[0x2008:0x200c] = b"NVBL"
ee[0x200c:0x2010] = struct.pack("<I", len(data))
ee[0x2010:0x2014] = struct.pack("<I", crc)
ee[0x2014:0x2014 + len(data)] = data

# block 1 (mirror) header @0x3004 + data @0x3010
ee[0x3004:0x3008] = b"NVBL"
ee[0x3008:0x300c] = struct.pack("<I", len(data))
ee[0x300c:0x3010] = struct.pack("<I", crc)
ee[0x3010:0x3010 + len(data)] = data

open(sys.argv[1], "wb").write(ee)
print("seeded %s: NVRG@0x2000 block0/1 len=%d crc=0x%08x" %
      (sys.argv[1], len(data), crc))
