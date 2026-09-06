#!/usr/bin/env python3
"""display2.py [--shell] <game-elf> - a title's PANEL TIMINGS, read out of the game.

    python3 display2.py game            -> fb0 1360x768  fb2 1280x800
    python3 display2.py --shell game    -> PAD_GL2_W=1280 PAD_GL2_H=800

WHERE THE NUMBERS COME FROM, because item 65 forbids the alternative. The
second display's size used to be nowhere: eglshim answered every display with
the backbox's 1360x768 unless PAD_GL2_W/H were set by hand, and a hand-typed
per-title table is the "a wrong table is worse than none" trap items 55, 57
and 61 each fell into once. The game itself knows both sizes - it drives the
panels. Its display setup (mando_le 1.44.0: 0x3ddf24) calls FB_SetTiming twice,
once for `/dev/fb0` (the LVDS backbox) and once for `/dev/fb2` (the HDMI
second display - the holographic topper on mando_le), and each call takes a
static 44-byte timing record from rodata:

    u32 pixclock, right_margin, hsync_len, left_margin, XRES,
        lower_margin, vsync_len, upper_margin, YRES, bits_per_pixel, sync

(the field order is FB_SetTiming's own, 0x52e030, read off how it fills the
fb_var_screeninfo before FBIOPUT_VSCREENINFO: [r4+16] -> xres, [r4+32] ->
yres). Read 2026-09-05 off the mando_le binary: fb0 = 1360x768 @16bpp, fb2 =
1280x800 @16bpp - the topper's real panel, and the size every topper clip on
the card is encoded at.

HOW THEY ARE FOUND, generically. String references in this binary exist only
as movw/movt pairs (findref.sh's standing note). The path string `/dev/fbN` is
built into r0 and the record's address into r1 within a few instructions of
each other, so: locate the string, find the movw/movt pair that builds its
address, and take the r1 pair beside it. Nothing here is a per-title number.
A title whose binary has no `/dev/fb2` reference (a single-display game) yields
no fb2 line and watch.sh leaves PAD_GL2_W/H alone - which is the old behaviour.

WHAT THESE ARE NOT (settled 2026-09-05, the same day): the geometry the game
gets back from EGL. watch.sh exported the fb2 record as PAD_GL2_W/H for one
run and the topper came out cropped, because the game presents display 2
through a viewport of DISPLAY 0's size (its render thread, 0x4519f4) while
sizing display 2's FBO and presenter from display 2's own geometry - a
present that is only whole when the two geometries are EQUAL. Told the
backbox's 1360x768 the picture was complete. So on the machine the topper
HDMI runs at the backbox's mode and this 1280x800 is the panel's timing
request; eglshim's default answer (every display = the backbox) is the
game's own assumption, and this tool is the reader of the panel timings,
printed beside it on the pane. (The empty topper scene that first sent this
file looking here was the node-12 part number, item 67's real gate.)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nbdir import load_segments, va_to_off  # noqa: E402

#: The record FB_SetTiming consumes (see the module docstring).
RECORD_BYTES = 44
XRES_OFF = 16
YRES_OFF = 32
BPP_OFF = 36

#: How far apart the path pair (r0) and the record pair (r1) may sit, in
#: instructions. mando_le interleaves them (movw r0, movw r1, movt r0, movt
#: r1); ten covers a register spill or two on either side.
PAIR_WINDOW = 10

DEVICES = (("fb0", b"/dev/fb0\0"), ("fb2", b"/dev/fb2\0"))


def movw_movt_pairs(code, base_va, window=16):
    """Every (movt_index, reg, value) a movw/movt pair builds in `code`.

    ARM A32 encodings, condition AL: movw = 0xE30xxxxx, movt = 0xE34xxxxx,
    imm16 = imm4<<12 | imm12, Rd in bits 15..12. A movt completes the most
    recent movw on the same register if that movw is within `window`
    instructions - the compiler schedules other work in between.
    """
    n = len(code) // 4
    words = struct.unpack_from("<%dI" % n, code, 0)
    last_movw = {}                      # reg -> (index, imm16)
    for i, w in enumerate(words):
        if (w & 0xFFF00000) == 0xE3000000:          # movw
            reg = (w >> 12) & 0xF
            last_movw[reg] = (i, ((w >> 4) & 0xF000) | (w & 0xFFF))
        elif (w & 0xFFF00000) == 0xE3400000:        # movt
            reg = (w >> 12) & 0xF
            lo = last_movw.get(reg)
            if lo and i - lo[0] <= window:
                hi = ((w >> 4) & 0xF000) | (w & 0xFFF)
                yield i, reg, (hi << 16) | lo[1]
                del last_movw[reg]
    return


def find_records(rx_bytes, rx_va, read_va):
    """{name: (xres, yres, bpp, record_va)} for each device string present.

    `read_va(va, n)` returns `n` bytes at a virtual address, or None. Pure so
    the test can feed it a synthetic code blob and a dict-backed reader.
    """
    pairs = list(movw_movt_pairs(rx_bytes, rx_va))
    by_index = {}
    for idx, reg, val in pairs:
        by_index.setdefault(idx, []).append((reg, val))
    out = {}
    for name, needle in DEVICES:
        off = rx_bytes.find(needle)
        if off < 0:
            continue
        str_va = rx_va + off
        sites = [idx for idx, reg, val in pairs if val == str_va and reg == 0]
        for site in sites:
            # THE NEAREST r1 pair, not the last one in the window: the two
            # FB_SetTiming call sites sit back to back (mando_le: fb2 at
            # 0x3ddfb8, fb0 at 0x3ddfcc), so a window around one site also
            # holds the other site's record, and "last seen" handed fb2 the
            # backbox record - measured, the first version of this did.
            rec_va, best = None, None
            for j in range(site - PAIR_WINDOW, site + PAIR_WINDOW + 1):
                for reg, val in by_index.get(j, ()):
                    if reg == 1 and (best is None or abs(j - site) < best):
                        rec_va, best = val, abs(j - site)
            if rec_va is None:
                continue
            rec = read_va(rec_va, RECORD_BYTES)
            if not rec or len(rec) < RECORD_BYTES:
                continue
            xres, = struct.unpack_from("<I", rec, XRES_OFF)
            yres, = struct.unpack_from("<I", rec, YRES_OFF)
            bpp, = struct.unpack_from("<I", rec, BPP_OFF)
            if 100 <= xres <= 8192 and 100 <= yres <= 8192:
                out[name] = (xres, yres, bpp, rec_va)
                break
    return out


def fb_geometry(elf_path):
    """{name: (xres, yres, bpp, record_va)} read out of a game ELF."""
    with open(elf_path, "rb") as f:
        elf = f.read()
    rx, rw = load_segments(elf)
    rx_off, rx_size, rx_va = rx

    def read_va(va, n):
        for seg in (rx, rw):
            off = va_to_off(va, seg)
            if off is not None:
                return elf[off:off + n]
        return None

    return find_records(elf[rx_off:rx_off + rx_size], rx_va, read_va)


def main(argv):
    shell = "--shell" in argv
    args = [a for a in argv[1:] if a != "--shell"]
    if not args:
        raise SystemExit(__doc__)
    geo = fb_geometry(args[0])
    if shell:
        if "fb2" in geo:
            print("PAD_GL2_W=%d PAD_GL2_H=%d" % geo["fb2"][:2])
        return 0 if "fb2" in geo else 1
    if not geo:
        print("no framebuffer timing records found")
        return 1
    print("  ".join("%s %dx%d @%dbpp (record 0x%x)" % (k, v[0], v[1], v[2], v[3])
                    for k, v in sorted(geo.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
