"""A dm-crypt mapping made with the kernel's device-mapper ioctls alone
(PAD-1186): what ``cryptsetup open`` does for a LUKS volume whose key and
data segment are already known, without cryptsetup or dmsetup.

WHY.  A Stern Spike 3 card's games partition is LUKS2 (``aes-xts-plain64``).
A Write that grows a file there mounts the plaintext through the Linux
kernel's ext4 driver (core/ext4_grow.py), which needs the volume mapped.
The app's own WSL distro (PAD Runtime, core/runtime.py) is a pinned image
without cryptsetup or dmsetup, but the WSL kernel carries dm-crypt and the
image carries python3, so the mapping is made here with ``fcntl.ioctl`` on
``/dev/mapper/control``: DM_DEV_CREATE, DM_TABLE_LOAD (one ``crypt`` target)
and DM_DEV_SUSPEND to resume it.  The block node is made with mknod (no udev
in WSL), the mapping removed with DM_DEV_REMOVE.

This file is ALSO a script: ext4_grow ships its source inside the grow
script and runs it with python3 in the Linux, so it is stdlib only and has
no package imports.

    python3 dmcrypt.py open  NAME DEVICE OFFSET_SECTORS LENGTH_SECTORS KEYFILE [SECTOR_SIZE]
        prints the block node of the plaintext (and nothing else)
    python3 dmcrypt.py close NAME
"""

import os
import stat
import struct
import sys

#: struct dm_ioctl (linux/dm-ioctl.h): version[3], data_size, data_start,
#: target_count, open_count, flags, event_nr, padding, dev, name[128],
#: uuid[129], data[7] - 312 bytes
_DM_FMT = "=3IIIIiIIIQ128s129s7s"
_DM_SIZE = struct.calcsize(_DM_FMT)
#: struct dm_target_spec: sector_start, length, status, next, target_type[16]
_SPEC_FMT = "=QQiI16s"
_SPEC_SIZE = struct.calcsize(_SPEC_FMT)
_VERSION = (4, 0, 0)

_DEV_CREATE, _DEV_REMOVE, _DEV_SUSPEND, _TABLE_LOAD = 3, 4, 6, 9
_EXISTS_FLAG = 1 << 2
#: DM_READONLY_FLAG: the table maps a read-only device (a ``losetup -r`` loop)
_READONLY_FLAG = 1 << 0

CONTROL = "/dev/mapper/control"


def _ioc(nr):
    """_IOWR(0xfd, nr, struct dm_ioctl)."""
    return (3 << 30) | (_DM_SIZE << 16) | (0xFD << 8) | nr


def _header(name, data_size, target_count=0, flags=0, data_start=_DM_SIZE):
    return struct.pack(_DM_FMT, _VERSION[0], _VERSION[1], _VERSION[2],
                       data_size, data_start, target_count, 0, flags, 0, 0, 0,
                       name.encode()[:127], b"", b"")


def _call(nr, buf):
    import fcntl                     # Linux only (the module loads anywhere)
    buf = bytearray(buf)
    fd = os.open(CONTROL, os.O_RDWR)
    try:
        fcntl.ioctl(fd, _ioc(nr), buf)
    finally:
        os.close(fd)
    return bytes(buf)


def crypt_table(device, offset_sectors, length_sectors, key, cipher="aes-xts-plain64",
                sector_size=512, iv_offset=0):
    """The DM_TABLE_LOAD payload: one ``crypt`` target over *device*."""
    params = "%s %s %d %s %d" % (cipher, bytes(key).hex(), iv_offset, device,
                                 offset_sectors)
    if sector_size and sector_size != 512:
        params += " 1 sector_size:%d" % sector_size
    p = params.encode() + b"\0"
    p += b"\0" * (-(_SPEC_SIZE + len(p)) % 8)
    spec = struct.pack(_SPEC_FMT, 0, length_sectors, 0, _SPEC_SIZE + len(p),
                       b"crypt")
    return spec + p


def _decode_dev(dev):
    """The kernel's huge_encode_dev: (major, minor)."""
    major = (dev >> 8) & 0xFFF
    minor = (dev & 0xFF) | ((dev >> 12) & 0xFFF00)
    return major, minor


def open_crypt(name, device, offset_sectors, length_sectors, key,
               sector_size=512, node_dir="/dev/mapper", readonly=False):
    """Map *device* through dm-crypt as *name*; returns the block node path.
    *readonly*: a read-only mapping (needed over a ``losetup -r`` loop, which
    the kernel will not open for writing; PAD-1263 reads source cards so)."""
    out = _call(_DEV_CREATE, _header(name, _DM_SIZE))
    dev = struct.unpack(_DM_FMT, out)[10]
    try:
        table = crypt_table(device, offset_sectors, length_sectors, key,
                            sector_size=sector_size)
        _call(_TABLE_LOAD, _header(name, _DM_SIZE + len(table), 1,
                                   flags=_READONLY_FLAG if readonly else 0) + table)
        _call(_DEV_SUSPEND, _header(name, _DM_SIZE))           # resume
    except BaseException:
        close_crypt(name)
        raise
    major, minor = _decode_dev(dev)
    os.makedirs(node_dir, exist_ok=True)
    node = os.path.join(node_dir, name)
    try:
        os.unlink(node)
    except OSError:
        pass
    os.mknod(node, 0o600 | stat.S_IFBLK, os.makedev(major, minor))
    return node


def close_crypt(name, node_dir="/dev/mapper"):
    """Remove the mapping *name* (and its node); quiet when it is gone."""
    try:
        os.unlink(os.path.join(node_dir, name))
    except OSError:
        pass
    try:
        _call(_DEV_REMOVE, _header(name, _DM_SIZE))
        return True
    except OSError:
        return False


def main(argv):
    if len(argv) >= 6 and argv[0] == "open":
        name, device, off, length, keyfile = argv[1:6]
        sector = int(argv[6]) if len(argv) > 6 else 512
        with open(keyfile, "rb") as f:
            key = f.read()
        print(open_crypt(name, device, int(off), int(length), key,
                         sector_size=sector))
        return 0
    if len(argv) == 2 and argv[0] == "close":
        return 0 if close_crypt(argv[1]) else 1
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
