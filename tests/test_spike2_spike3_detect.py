"""PAD-367 - a Stern Spike 3 card is recognised and refused UP FRONT.

Merlin1896, Emulate tab: a walking_dead_remastered_le-0_93_0 ...sdcard-secure
card was copied to the local cache WHOLE - 62 GB - and only then did the mount
fail with "could not mount", because Spike 3 is a different animal from Spike 2.
Its FAT boot partition is labelled SPIKE3 and every Linux partition is a LUKS2 /
AES-XTS volume whose key lives in the machine's CM4 fuses, not on the card, so
there is nothing on the image to mount or decrypt with.

He asked two things: can it be supported (no - the key is not in the image), and
could PAD say so up front instead of copying 62 GB first. This is the second:
``parts.py --spike3`` recognises one from the MBR and a few partition magics -
cheap enough to run before any copy - and cardmount.sh and watch.sh refuse it
there, with a clear message.
"""

import os
import struct
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import parts                                                       # noqa: E402

SECTOR = 512


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf8", newline="") as f:
        return f.read()


def _mbr(entries):
    b = bytearray(512)
    for i, (t, s, c) in enumerate(entries):
        o = 0x1BE + i * 16
        b[o + 4] = t
        struct.pack_into("<II", b, o + 8, s, c)
    b[510:512] = b"\x55\xaa"
    return b


def _fat_boot(label, fat32=False):
    b = bytearray(512)
    if fat32:
        b[66] = 0x29
        b[71:71 + len(label)] = label
    else:
        b[38] = 0x29
        b[43:43 + len(label)] = label
    b[510:512] = b"\x55\xaa"
    return b


def _luks(ver=2):
    b = bytearray(512)
    b[:6] = parts.LUKS_MAGIC
    struct.pack_into(">H", b, 6, ver)
    return b


def _ext4():
    b = bytearray(0x440)
    struct.pack_into("<H", b, 0x438, 0xEF53)       # the ext superblock magic
    return b


def _write(path, entries, *, boot_label, encrypted, chain=()):
    """A card image: primaries in the MBR, a FAT boot sector with *boot_label*,
    and each 0x83 partition filled with LUKS or ext4. *chain* is a list of
    (ptype, rel_start, sectors) logicals written into an EBR chain under the
    first extended primary."""
    end = max(s + c for _t, s, c in entries) + 2
    for _t, rs, c in chain:
        end = max(end, 0)                          # EBRs are written explicitly
    with open(path, "wb") as f:
        f.truncate(end * SECTOR)
        f.write(_mbr(entries))
        f.seek(entries[0][1] * SECTOR)
        f.write(_fat_boot(boot_label))
        for t, s, _c in entries[1:]:
            if t == 0x83:
                f.seek(s * SECTOR)
                f.write(_luks() if encrypted else _ext4())
    return str(path)


def _spike3_card(tmp_path, name="wdr.raw"):
    """Merlin's layout: FAT SPIKE3 boot, two primary LUKS, an extended holding
    two more LUKS logicals."""
    ext_base = 1409024
    p = _write(tmp_path / name,
               [(0x0C, 1, 131072), (0x83, 131073, 1228800),
                (0x83, 1359873, 49152), (0x0F, ext_base, 400000)],
               boot_label=b"SPIKE3", encrypted=True)
    with open(p, "r+b") as f:
        ebr = bytearray(512)
        struct.pack_into("<II", ebr, 0x1BE + 8, 2, 100000)
        ebr[0x1BE + 4] = 0x83
        struct.pack_into("<II", ebr, 0x1CE + 8, 150000, 100000)
        ebr[0x1CE + 4] = 0x0F
        ebr[510:512] = b"\x55\xaa"
        f.seek(ext_base * SECTOR)
        f.write(ebr)
        f.seek((ext_base + 2) * SECTOR)
        f.write(_luks())
        ebr2 = bytearray(512)
        struct.pack_into("<II", ebr2, 0x1BE + 8, 2, 100000)
        ebr2[0x1BE + 4] = 0x83
        ebr2[510:512] = b"\x55\xaa"
        f.seek((ext_base + 150000) * SECTOR)
        f.write(ebr2)
        f.seek((ext_base + 150000 + 2) * SECTOR)
        f.write(_luks())
    return p


def _spike2_card(tmp_path, name="jaws.raw"):
    return _write(tmp_path / name,
                  [(0x0C, 1, 131072), (0x83, 131073, 1228800),
                   (0x83, 1359873, 2000000)],
                  boot_label=b"PADBOOT  ", encrypted=False)


# ---------------------------------------------------------------------------
# the detector
# ---------------------------------------------------------------------------

def test_a_spike3_card_is_recognised_by_its_luks_partitions(tmp_path):
    is3, why = parts.spike3(_spike3_card(tmp_path))
    assert is3
    # every data partition, primary and logical, named
    for p in ("p2", "p3", "p5", "p6"):
        assert p in why
    assert "LUKS" in why and "SPIKE3" in why


def test_a_spike3_card_is_recognised_by_the_label_alone(tmp_path):
    """The LUKS magic is the signal that matters, but a SPIKE3-labelled boot
    partition is enough on its own - a Spike 2 card's is not labelled SPIKE3."""
    p = _write(tmp_path / "lbl.raw",
               [(0x0C, 1, 60), (0x83, 62, 4)],
               boot_label=b"SPIKE3", encrypted=False)
    is3, why = parts.spike3(p)
    assert is3 and "SPIKE3" in why and "LUKS" not in why


def test_a_spike2_card_is_not_a_spike3_card(tmp_path):
    assert parts.spike3(_spike2_card(tmp_path)) == (False, "")


def test_a_non_card_file_is_not_a_spike3_card(tmp_path):
    junk = tmp_path / "junk.raw"
    junk.write_bytes(os.urandom(4096))
    assert parts.spike3(str(junk)) == (False, "")


def test_a_luks1_partition_counts_too(tmp_path):
    """The magic is shared; only the version byte differs. A LUKS1 volume is
    just as unmountable, so it is recognised as well."""
    p = _write(tmp_path / "l1.raw", [(0x0C, 1, 60), (0x83, 62, 4)],
               boot_label=b"PADBOOT  ", encrypted=False)
    with open(p, "r+b") as f:
        f.seek(62 * SECTOR)
        f.write(_luks(ver=1))
    assert parts.spike3(p)[0]


# ---------------------------------------------------------------------------
# the CLI contract cardmount.sh / watch.sh depend on
# ---------------------------------------------------------------------------

def _cli(path):
    r = subprocess.run([sys.executable, os.path.join(RIG, "parts.py"),
                        "--spike3", path],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def test_the_cli_exits_zero_and_says_yes_for_a_spike3_card(tmp_path):
    rc, out = _cli(_spike3_card(tmp_path))
    assert rc == 0 and out.startswith("spike3: yes - ")


def test_the_cli_exits_nonzero_and_says_no_for_a_spike2_card(tmp_path):
    rc, out = _cli(_spike2_card(tmp_path))
    assert rc == 1 and out == "spike3: no"


def test_the_cli_says_no_for_a_missing_image(tmp_path):
    rc, out = _cli(str(tmp_path / "nope.raw"))
    assert rc == 1 and out.startswith("spike3: no")


# ---------------------------------------------------------------------------
# the two refusals, read out of the scripts (they run only inside WSL)
# ---------------------------------------------------------------------------

def test_cardmount_refuses_a_spike3_card_before_the_copy():
    sh = _text("cardmount.sh")
    guard = sh.index('parts.py" --spike3')
    # before cache_pick is ever CALLED - the whole point is no 60 GB copy
    assert guard < sh.index('cache_pick "$IMG"')
    # after the image-exists check, so a missing file is still "no image"
    assert sh.index('die "no image at $IMG"') < guard
    assert "Spike 3 card" in sh and "cannot mount or emulate it" in sh


def test_watch_names_a_spike3_card_instead_of_could_not_mount():
    sh = _text("watch.sh")
    guard = sh.index('parts.py" --spike3')
    # before the cardmount.sh call that would otherwise fail with the generic
    # "could not mount"
    assert guard < sh.index('CARD_OUT=$(bash "$S/cardmount.sh"')
    assert "is a Stern Spike 3 card" in sh
    # exit 1 means watch.sh does not then also print could-not-mount
    tail = sh[guard:sh.index('CARD_OUT=$(bash "$S/cardmount.sh"')]
    assert "exit 1" in tail
