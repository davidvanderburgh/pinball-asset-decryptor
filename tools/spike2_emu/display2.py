#!/usr/bin/env python3
"""display2.py [--shell] <game-elf> - a title's PANEL TIMINGS, read out of the game.

    python3 display2.py game            -> fb0 1360x768  fb2 1280x800
    python3 display2.py --shell game    -> PAD_GL2_WIN_W=1280 PAD_GL2_WIN_H=800

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


#: ★ WHAT THE BINARY CANNOT TELL US, REPORTED FROM REAL MACHINES.
#:
#: Everything else in this file is DERIVED, and that is the point of it - a
#: hand-typed per-title table is the trap items 55, 57 and 61 each fell into
#: once. These facts are here because they are not in the binary AT ALL, which
#: was established rather than assumed (2026-09-07): the small-cabinet builds
#: reference no `/dev/fb*` string of any kind and carry no 800x480 anywhere -
#: and neither does a FULL cabinet carry its own 1360x768, which came from
#: watching the game's post-boot scissor rect at RUNTIME. A panel's mounting
#: angle is not in there either; the game renders the same landscape frame
#: whichever way round the glass is screwed on.
#:
#: WHAT MAKES THEM SAFE TO KEEP. A wrong entry is visible the instant anyone
#: looks - the opposite of the silent-missing-devices failure the no-tables
#: rule exists to prevent. And each is a measurement from a machine someone
#: owns, not a guess:
#:
#:   * the 800x480 single screen - three separate cabinets, three separate
#:     reports, the same number (James Bond 60th, Star Wars Home Edition,
#:     Jurassic Park The Pin, all one-screen models).
#:   * venom_le's quarter turn - the report said "90 degrees clockwise", and a
#:     photograph of that machine shows its topper carrying the same service
#:     screen as the backbox, a quarter turn from it.
#:
#: ★ ONE OF THEM REACHES THE GUEST, AND THAT IS THE POINT OF IT (2026-09-08).
#: `rot2` and the second display's size are host-only, and must stay that way -
#: item 67 proved that telling the GAME display 2's panel size crops the
#: topper, because the game presents display 2 through display 0's viewport.
#: `screen` is not that. A one-screen cabinet has no second display and no
#: viewport indirection, and these games do not scale their scene to the size
#: they are handed: told 1360x768, star_wars_elg draws its 800x480 service
#: screen in the top-left corner and leaves the rest black, and
#: jurassic_park_the_pin puts its bottom-right Insider badge at 0.57 across
#: (800/1360). Sizing only the WINDOW therefore shrank the same wrong picture
#: and the report came back unchanged. So `screen` sizes the guest's render
#: target, which is what the machine's own panel does; watch.sh sets
#: PAD_GL_W/H from it, and a caller that names those by hand still wins.
#: The check on that is the same as every other line here: it is wrong in a
#: way anybody can see.
#:
#: A title that grows a real timing record later needs no entry: the derived
#: reading is what sizes the second display, and this only fills the gap.
REPORTED_PANELS = {
    "james_bond_60th_le":    {"screen": (800, 480)},
    "star_wars_elg":         {"screen": (800, 480)},
    "jurassic_park_the_pin": {"screen": (800, 480)},
    "venom_le":              {"rot2": 90},
}


def reported(title):
    """The reported facts for `title`, or {} - keyed on the title the card
    names itself, which is what watch.sh already has."""
    return dict(REPORTED_PANELS.get(title or "", {}))


def reported_exports(title):
    """["NAME=value", ...] - `title`'s reported facts as watch.sh wants them.

    The translation from a fact to the knobs that carry it lives HERE and not
    in the shell, because it is the part with a decision in it: a reported
    screen sets the guest's render size AND the window, a reported rotation
    sets neither. That was got wrong once in the other direction - the panel
    was made a window size alone, which shrank the wrong picture instead of
    fixing it - so it is somewhere a test can reach.

    watch.sh still decides who WINS: a caller that named any of these by hand
    keeps its own value. This only says what the machine was reported to be.
    """
    r = reported(title)
    out = []
    if r.get("screen"):
        w, h = r["screen"]
        # Both, and in this order. PAD_GL_W/H is what the game is told, which
        # is the half that makes the picture right; PAD_GL_WIN_W/H is the
        # window, which is normally the same number and is also padglhost's
        # signal that this run's size is a reported panel rather than the
        # rig's default (it will not replay a window size remembered from
        # before that was known).
        out += ["PAD_GL_W=%d" % w, "PAD_GL_H=%d" % h,
                "PAD_GL_WIN_W=%d" % w, "PAD_GL_WIN_H=%d" % h]
    if r.get("rot2"):
        # Host side only, and it must stay that way - a rotation the guest
        # knew about would be a rotation applied twice.
        out.append("PAD_GL2_ROT=%d" % r["rot2"])
    return out


def main(argv):
    shell = "--shell" in argv
    if "--reported" in argv:
        args = [a for a in argv[1:] if a != "--reported"]
        if not args:
            raise SystemExit(__doc__)
        for line in reported_exports(args[0]):
            print(line)
        return 0
    args = [a for a in argv[1:] if a != "--shell"]
    if not args:
        raise SystemExit(__doc__)
    geo = fb_geometry(args[0])
    if shell:
        # ★ PAD_GL2_WIN_W/H, NOT PAD_GL2_W/H. This printed the render-size
        # names until 2026-09-07, and they are the one thing this record is
        # NOT - exporting them as the render size is precisely what cropped
        # mando_le's topper, and the paragraph above exists because of it.
        # The record is the PANEL, so it names the window, which is the
        # separate knob padglhost grew for it (item 65, peanuts' matrix).
        if "fb2" in geo:
            print("PAD_GL2_WIN_W=%d PAD_GL2_WIN_H=%d" % geo["fb2"][:2])
        return 0 if "fb2" in geo else 1
    if not geo:
        print("no framebuffer timing records found")
        return 1
    print("  ".join("%s %dx%d @%dbpp (record 0x%x)" % (k, v[0], v[1], v[2], v[3])
                    for k, v in sorted(geo.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
