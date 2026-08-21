#!/usr/bin/env python3
"""Dump the LIVE switch / coil / lamp tables out of a running JJP game.

WHY LIVE, AND WHY THIS IS SAFE
------------------------------
Every device object in the ELF is all zeroes on disk - they are C++ statics
filled in by constructors at startup - so the file gives you the roster and the
ordering but none of the numbers.  The numbers exist only in a running process.

Reading /proc/<pid>/mem does NOT attach a debugger and does not make us the
tracer, so it never trips the Sentinel envelope's anti-debug gate (which reads
TracerPid and answers a debugger with "Debugger detected (E2011)" followed by a
deliberate self-SIGSEGV).  Note the game already reports a NON-ZERO TracerPid:
it ptraces itself from a child process precisely so nothing else can attach.
Plain memory reads as root are unaffected.  NEVER run gdb or strace on it.

THE Switch STRUCT (104 bytes), decoded from live objects on 2026-08-19
----------------------------------------------------------------------
Offsets confirmed by cross-checking three trough switches against each other
and against switch_068 / switch_128, whose matrix positions are known by name:

    off  type   meaning
      0  u32    index into switch_table
      8  ptr    -> name string (ASCII, in .rodata)
     16  ptr    -> shared handler/group (identical across the trough family)
     24  u32    2   (constant on every switch seen)
     28  u32    2   (ditto)
     32  u32    group/kind - 0x13 on troughs, 0 on plain matrix switches
     36  u32    6 on troughs, 0 otherwise
     40  u32    3 on troughs, 0 otherwise
     48  u32    0x3c3c everywhere - a default, not a position
     52  i32    X in playfield-image pixels, or -1 if unpositioned
     56  i32    Y in playfield-image pixels, or -1 if unpositioned
     60  u8     frame byte index within the 64-byte I/O frame
     61  u8     bit mask within that byte
     62  u8     LIVE STATE - 1 while the game considers the switch closed
     63  u8     debounced/previous state
     64  u32    tick at which the state last changed
     68  u32    counter since last change (resets on an edge)

Offsets 62-68 were confirmed by INJECTING: driving the six trough switches
through the CUSE device and re-reading the objects showed 62 and 63 go 0 -> 1,
64 take a timestamp, and 68 reset.  That is the whole loop - UI to shared
memory to the character device to the game - verified end to end.

THE Coil STRUCT (80 bytes), decoded from live objects on 2026-08-20
-------------------------------------------------------------------
The same shape as Switch, one table over:

    off  type   meaning
      0  u32    index into hook_coil_override_table
      8  ptr    -> name string ("Trough VUK", "Right Slingshot")
     16  u32    pulse duration in MILLISECONDS (32 for a kicker, 200 for a
                flipper hold, 500 for the topper LEDs, 1000 for a motor)
     24  i32    X in playfield-image pixels, or -1
     28  i32    Y in playfield-image pixels, or -1
     36  u8     frame byte index within the 64-byte OUT frame
     37  u8     bit mask within that byte

Offsets 36/37 are the coil's twin of the switch's 60/61, and they decode
cleanly: all 45 coils have DISTINCT (byte, bit) pairs, offset 37 holds only
powers of two, and the grouping is what a driver board looks like (flippers
together on byte 1, steppers on 5, topper on 6).

CONFIRMED AGAINST THE LIVE OUT FRAME, so this is a reading and not a guess:
coil_lamp_start_button is byte 9 bit 0x40, and during attract IO OUT byte 9 bit
6 toggles at 2 Hz - the start button blinking, which is what attract does.  The
offset between struct byte and frame byte is therefore ZERO, and all coils are
on the IO board.

This is what lets anything answer the game: coil_vuk_trough (byte 1 bit 0x10,
32 ms) is the trough eject the ball feeder waits for.

THE MATRIX LAYOUT THIS REVEALS
------------------------------
switch_NNN maps into the I/O frame as:

    byte = 4 + (N - 1) // 8
    bit  = 1 << ((N - 1) % 8)

Checked against live objects: switch_068 -> byte 0x0c bit 0x08, switch_128 ->
byte 0x13 bit 0x80.  So the 128-switch matrix occupies bytes 4..19 of the
64-byte IN frame, LSB first.  That is the frame layout the project plan
expected would need a real cabinet and a driver capture to learn.

THE COORDINATES ARE ALREADY IN PLAYFIELD-IMAGE SPACE
----------------------------------------------------
switch_trough_5 is (221, 733) and the game's own
graphics/Game Tests/pf_image.png is 385x768, so X/Y drop straight onto the
playfield photograph with no calibration step.  Do not confuse this with
hook_playfield_width / _height, which are 20.25 x 46.0 - those are INCHES and a
different space entirely - but DO use them: they are what proves a candidate
calibration scale impossible (see ``_square_pixels``).

A LAMP AND A SWITCH THAT SHARE A NAME ARE NOT ALWAYS THE SAME SPOT
------------------------------------------------------------------
``calibrate()`` pairs lp_<x> with switch_<x> and treats the pair as one
physical point.  For the jets that is exact - the lamp sits under the jet, and
measured on Wonka the two agree to about a pixel.  For the lanes it is FALSE:
lp_inlane_left_1 is the arrow INSERT and switch_inlane_left_1 is the ROLLOVER,
and the rollover is ~2.3 inches DOWN-LANE of the insert (measured: 31-40 px on
Wonka, and 3.85 in for outlane_left).

That is a systematic error, along the lane, in the direction of travel - so it
lands almost entirely in Y and cancels in X, which is why X was right all
along.  And because the usable pairs bunch into just two clusters (jets around
y=10-14 in, lanes around y=31-33 in), a constant offset in the lower cluster
does not average out: it TILTS the fit.  On Wonka it dragged the Y scale from
a true 17.09 px/in to 18.88, so every LED drifted progressively downward -
55 px by the SHOOT AGAIN insert between the flipper tips.  The cure is in
``_square_pixels``: the photo has SQUARE PIXELS, so one scale must serve both
axes, and the axis the lane offset cannot corrupt is the one to keep.
"""

import argparse
import itertools
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jjpelf import GameElf                                       # noqa: E402

#: Where the game binary lives inside the jail, MINUS the title.
JAIL_GAMES = '/var/tmp/jjp_run/jjpe/gen1'


def default_elf(base=JAIL_GAMES):
    """The mounted title's game binary, found rather than assumed.

    This used to be the literal path ``.../gen1/Wonka/game``, which is the one
    thing padpath.sh says must never happen: "nothing downstream should contain
    the word Wonka".  It cost more than tidiness.  Running Guns N' Roses, swdump
    died with FileNotFoundError on Wonka's path, so no dump was written - and
    jjpsw_launch.sh, finding a perfectly valid dump already on disk from the last
    Wonka run, opened the matrix onto it.  The panel then showed gobstopper
    targets and a 6-ball trough over a GnR playfield, every name and frame
    address a confident lie about the machine that was running.

    The same discovery jjp_title() and pfimage.find_game_dir() use: the title
    directory is the one with an executable ``game`` in it.
    """
    try:
        for name in sorted(os.listdir(base)):
            cand = os.path.join(base, name, 'game')
            if os.access(cand, os.X_OK):
                return cand
    except OSError:
        pass
    # Nothing mounted.  Return the path we would have used so the error names
    # the directory rather than dying on a None.
    return os.path.join(base, '<no title mounted>', 'game')

SWITCH_SIZE = 104
COIL_SIZE = 80
LAMP_SIZE = 88

#: Where the 128-switch matrix starts inside the 64-byte IN frame.  Derived,
#: not guessed - see the module docstring.
MATRIX_FIRST_BYTE = 4
MATRIX_SWITCHES = 128


def matrix_addr(n):
    """switch_NNN (1-based) -> (frame byte, bit mask)."""
    if not 1 <= n <= MATRIX_SWITCHES:
        raise ValueError(f"switch number {n} outside 1..{MATRIX_SWITCHES}")
    return MATRIX_FIRST_BYTE + (n - 1) // 8, 1 << ((n - 1) % 8)


class LiveMem:
    """Read-only view of another process's memory."""

    def __init__(self, pid):
        self.pid = pid
        self.fh = open(f'/proc/{pid}/mem', 'rb', 0)

    def read(self, addr, n):
        self.fh.seek(addr)
        return self.fh.read(n)

    def cstr(self, addr, limit=128):
        if not addr:
            return ''
        b = self.read(addr, limit)
        z = b.find(b'\0')
        return b[:z if z >= 0 else limit].decode('latin1', 'replace')


def find_pid():
    """The renderer process - a JJP launch is three, and only one is fat."""
    out = subprocess.run(['pgrep', '-x', 'game'], capture_output=True, text=True)
    best, best_rss = None, -1
    for tok in out.stdout.split():
        p = int(tok)
        try:
            rss = int(open(f'/proc/{p}/statm').read().split()[1])
        except OSError:
            continue
        if rss > best_rss:
            best, best_rss = p, rss
    return best


def decode_lamp(mem, elf, pv):
    """Decode one 88-byte Lamp object.

    Offsets, read off live objects on 2026-08-19:

        off  type   meaning
          0  ptr    vtable (identical across every lamp)
          8  f32    X in INCHES
         12  f32    Y in INCHES
         32  f32    X again (a second copy; same value)
         36  f32    Y again
         40  u32    lamp index (matches the game's own numbering)
         48  ptr    -> name string ("Gobstopper", "Camera Spotlight")
         56  u32    kind - 4 and 7 dominate, 8199 appears a few times
         60  u32    unknown a
         64  u32    unknown b
         68  u32    sequence within hook_lamp_table
         80  ptr    -> per-lamp heap block (NOT animation state: sampled over
                    3 s of attract, neither the object nor that block changed)

    NOTE THE UNITS.  Lamps are in INCHES; switches are in playfield-image
    PIXELS.  Mixing them silently puts every lamp in the top-left corner.
    calibrate() below solves the inches->pixels mapping.
    """
    b = mem.read(pv, LAMP_SIZE)
    if len(b) < LAMP_SIZE:
        return None
    x, y = struct.unpack_from('<ff', b, 8)
    return {
        'symbol': elf.by_addr.get(pv, ''),
        'name': mem.cstr(struct.unpack_from('<Q', b, 48)[0]),
        'addr': pv,
        'kind': 'lamp',
        'index': struct.unpack_from('<I', b, 40)[0],
        'x_in': round(x, 4),
        'y_in': round(y, 4),
        'lamp_kind': struct.unpack_from('<I', b, 56)[0],
        'seq': struct.unpack_from('<I', b, 68)[0],
        # A lamp at exactly (0,0) is unplaced, the same convention switches use
        # with -1.  Do not draw these.
        'placed': not (x == 0.0 and y == 0.0),
    }


def dump_lamps(elf, mem):
    addr = elf.addr('hook_lamp_table')
    nbytes = elf.size('hook_lamp_table')
    if 'hook_lamp_table_size' in elf.syms:
        n = struct.unpack('<I', mem.read(elf.addr('hook_lamp_table_size'), 4))[0]
        if 0 < n * 8 <= nbytes:
            nbytes = n * 8
    raw = mem.read(addr, nbytes)
    out = []
    for pv in struct.unpack('<%dQ' % (len(raw) // 8), raw):
        if not pv:
            continue
        try:
            rec = decode_lamp(mem, elf, pv)
        except OSError:
            # One unreadable object must not lose the other 215.  An EIO here
            # took the whole lamp table to zero once.
            continue
        if rec:
            out.append(rec)
    return out


def calibrate(switches, lamps, playfield=None, image_size=None):
    """Solve inches -> playfield-image pixels, and say how well it fits.

    ``playfield`` is the game's own ``{'width': in, 'height': in}`` and
    ``image_size`` the photograph's ``(w, h)`` in pixels.  Both are optional and
    are used only by :func:`_square_pixels`, which needs them to tell an
    impossible scale from a possible one.

    Switches carry pixel coordinates, lamps carry inches, and nothing in the
    game states the relationship.  Devices that share an exact name suffix
    (switch_jet_left / lp_jet_left) are the same physical spot, so each such
    pair is one observation.

    Matching on keyword OVERLAP instead was tried first and is a trap: it
    paired switch_spinner with lp_factory_tour_1 and produced a fit with 51 px
    mean error.  Exact suffix only, then RANSAC to drop the pairs where the
    lamp genuinely is not co-located with the switch.
    """
    sw = {s['symbol'][7:]: (s['x'], s['y'])
          for s in switches
          if s.get('x') is not None and s.get('symbol', '').startswith('switch_')}
    lp = {l['symbol'][3:]: (l['x_in'], l['y_in'])
          for l in lamps
          if l.get('placed') and l.get('symbol', '').startswith('lp_')}
    pairs = [(k, sw[k], lp[k]) for k in sw if k in lp]
    if len(pairs) < 2:
        return {'ok': False, 'pairs': len(pairs),
                'why': 'need at least two exact-suffix switch/lamp pairs'}

    def solve(axis):
        i = 0 if axis == 'x' else 1
        best = None
        for a_, b_ in itertools.combinations(pairs, 2):
            d = a_[2][i] - b_[2][i]
            if abs(d) < 0.5:
                continue
            m = (a_[1][i] - b_[1][i]) / d
            c = a_[1][i] - m * a_[2][i]
            inl = [p for p in pairs if abs(m * p[2][i] + c - p[1][i]) <= 12]
            if not best or len(inl) > len(best[2]):
                best = (m, c, inl)
        if not best:
            return None
        inl = best[2]
        n = len(inl)
        sx = sum(p[2][i] for p in inl); sy = sum(p[1][i] for p in inl)
        sxx = sum(p[2][i] ** 2 for p in inl); sxy = sum(p[2][i] * p[1][i] for p in inl)
        den = n * sxx - sx * sx
        if abs(den) < 1e-9:
            return None
        m = (n * sxy - sx * sy) / den
        c = (sy - m * sx) / n
        res = [abs(m * p[2][i] + c - p[1][i]) for p in inl]
        return {'scale': m, 'offset': c, 'inliers': n, 'pairs': len(pairs),
                'max_px': max(res), 'mean_px': sum(res) / n,
                'outliers': [p[0] for p in pairs
                             if abs(m * p[2][i] + c - p[1][i]) > 12]}

    fx, fy = solve('x'), solve('y')
    out = {'ok': bool(fx and fy), 'x': fx, 'y': fy, 'pairs': len(pairs),
           'pair_names': sorted(p[0] for p in pairs)}
    if fx and fy:
        out['square_pixels'] = _square_pixels(fx, fy, pairs, playfield,
                                              image_size)
    return out


def png_size(path):
    """(width, height) from a PNG's IHDR, or None.

    Header-only on purpose: this runs next to a live game and must not pull a
    multi-megabyte photograph into memory to read two integers.
    """
    try:
        with open(path, 'rb') as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or not head.startswith(b'\x89PNG'):
        return None
    return (int.from_bytes(head[16:20], 'big'),
            int.from_bytes(head[20:24], 'big'))


def _square_pixels(fx, fy, pairs, playfield=None, image_size=None):
    """Force ONE scale onto both axes, and say why it was needed.

    THE BUG THIS FIXES.  ``solve()`` fits X and Y independently, which quietly
    allows a mapping that no photograph can have: different inches-per-pixel
    horizontally and vertically.  The playfield photo has square pixels, so the
    two scales must be equal.  On Wonka they came out 17.06 and 18.88 - a 10.7%
    disagreement - because the lane pairs put the arrow insert and its rollover
    switch ~2.3 in apart along the lane (see the module docstring), which tilts
    the Y fit and leaves X alone.  The result was an LED error that GREW with Y:
    nothing at the top, ~27 px by the mid-playfield inserts, 55 px by SHOOT
    AGAIN - which reads as "the LEDs drift downward toward the bottom".

    WHICH SCALE IS THE HONEST ONE is decided by the game's own numbers, not by
    a preference: ``hook_playfield_width/height`` say the playfield is
    20.25 x 46.0 inches, so a scale implies a playfield of a certain pixel size,
    and a scale whose playfield does not FIT the photograph is impossible.  On
    Wonka that is decisive - 17.06 gives 345x785 px (fits a 385x768 photo),
    18.88 gives 382x868, i.e. a playfield 100 px taller than the picture of it.
    With no photo to check against we fall back to X, which is the axis a
    down-lane offset cannot corrupt (it is a Y error by construction) and the
    better-conditioned fit besides: the X pairs span the full width, while the
    Y pairs bunch into two bands.

    THE OFFSET IS PINNED AT THE TOPMOST ANCHOR.  Correcting a scale pivots
    everything about some point, and the top is the right one to keep still:
    the topmost anchors are the JETS, whose lamp and switch really are the same
    spot (they agree to ~1 px), while it is the lower, lane pairs that are
    offset.  Pinning there also means this only moves what was wrong.  Verified
    against six inserts measured by eye off Wonka's photo (SUPER SPINNER,
    SUPERX 2X/3X/4X/5X, SHOOT AGAIN): 28-55 px of error before, 2-6 px after.

    Returns a dict describing what was done (recorded in the dump so a bad
    correction announces itself), or None when nothing needed changing.
    """
    sx, sy = fx['scale'], fy['scale']
    if not sx or not sy:
        return None

    def fits(s):
        """Does a playfield at this scale fit inside the photograph?"""
        if not playfield or not image_size:
            return None
        w = s * playfield.get('width', 0)
        h = s * playfield.get('height', 0)
        # 5% of slack: the photo is framed to the playfield but need not
        # include every last millimetre of it (Wonka's crops ~2% off the top).
        return w <= image_size[0] * 1.05 and h <= image_size[1] * 1.05

    fit_x, fit_y = fits(sx), fits(sy)
    if fit_y and not fit_x:
        keep, drop, axis = fy, fx, 'x'          # Y is the credible one
    else:
        keep, drop, axis = fx, fy, 'y'          # X by default and by evidence
    s = keep['scale']

    if abs(drop['scale'] - s) <= 0.005 * s:
        # Already isotropic to within half a percent - nothing to correct, and
        # rewriting the fit would only add noise.
        return None

    # Pin the corrected axis at its topmost anchor so the good end stays put.
    i = 0 if axis == 'x' else 1
    top = min(p[2][i] for p in pairs)
    raw_scale, raw_offset = drop['scale'], drop['offset']
    drop['scale'] = s
    drop['offset'] = (raw_scale * top + raw_offset) - s * top
    drop['raw_scale'] = raw_scale
    drop['raw_offset'] = raw_offset
    drop['squared_from'] = axis_other = 'x' if axis == 'y' else 'y'
    return {
        'corrected': axis, 'took_scale_from': axis_other, 'scale': s,
        'raw_scale': raw_scale, 'pinned_at_in': top,
        'disagreement_pct': round(100.0 * abs(raw_scale - s) / s, 1),
        'playfield_fits': {'x': fit_x, 'y': fit_y},
    }


def dump_table(elf, mem, table_sym, obj_size, kind, size_sym=None):
    addr = elf.addr(table_sym)
    nbytes = elf.size(table_sym)
    if size_sym and size_sym in elf.syms:
        n = struct.unpack('<I', mem.read(elf.addr(size_sym), 4))[0]
        nbytes = min(nbytes, n * 8)

    raw = mem.read(addr, nbytes)
    ptrs = struct.unpack('<%dQ' % (len(raw) // 8), raw)

    items = []
    for pv in ptrs:
        if not pv:
            continue
        b = mem.read(pv, obj_size)
        if len(b) < obj_size:
            continue
        rec = {
            'index': struct.unpack_from('<I', b, 0)[0],
            'symbol': elf.by_addr.get(pv, ''),
            'name': mem.cstr(struct.unpack_from('<Q', b, 8)[0]),
            'addr': pv,
            'kind': kind,
        }
        if kind == 'switch':
            x, y = struct.unpack_from('<ii', b, 52)
            rec['x'] = x if x >= 0 else None
            rec['y'] = y if y >= 0 else None
            rec['frame_byte'] = b[60]
            rec['frame_bit'] = b[61]
            # The game's OWN view of the switch, not ours - useful for
            # confirming that an injected switch actually landed.
            rec['live_closed'] = bool(b[62])
            rec['group'] = struct.unpack_from('<I', b, 32)[0]
            # INVERTED OPTO flag (offset 0x24 bit 0x2).  MultiballDevice::
            # update_ball_count reads the live state and, when this bit is set,
            # INVERTS it: for the trough these are optos, so a ball BREAKS the
            # beam -> reads OPEN, and empty -> CLOSED.  Seating such a switch
            # "closed" for a present ball reads to the game as ABSENT, which is
            # why a full trough looked empty and the game never started.  The
            # feeder/UI flip these at the switch layer (see jjpsw.SwitchShm).
            rec['inverted'] = bool(struct.unpack_from('<I', b, 0x24)[0] & 0x2)
        elif kind == 'coil':
            x, y = struct.unpack_from('<ii', b, 24)
            rec['x'] = x if x >= 0 else None
            rec['y'] = y if y >= 0 else None
            # Where this coil lives in the OUT frame - see the module docstring.
            # Everything that has to notice a coil FIRE (the ball feeder) reads
            # these, so they are decoded here, once, rather than in each caller.
            rec['frame_byte'] = b[36]
            rec['frame_bit'] = b[37]
            rec['pulse_ms'] = struct.unpack_from('<I', b, 16)[0]
            rec['raw'] = b.hex()
        else:
            # The lamp override layout is not decoded here; carry the raw bytes
            # so a later pass can work it out without another live run.
            rec['raw'] = b.hex()
        items.append(rec)
    return items


def verify_matrix(switches):
    """Cross-check the derived byte/bit rule against what the game actually holds.

    This is the one claim everything downstream rests on, so it is checked on
    every dump rather than trusted.  Returns (checked, mismatches).
    """
    checked = 0
    bad = []
    for s in switches:
        sym = s.get('symbol', '')
        if not (sym.startswith('switch_') and sym[7:].isdigit()):
            continue
        n = int(sym[7:])
        try:
            want_byte, want_bit = matrix_addr(n)
        except ValueError:
            continue
        checked += 1
        if (s['frame_byte'], s['frame_bit']) != (want_byte, want_bit):
            bad.append((sym, s['frame_byte'], s['frame_bit'], want_byte, want_bit))
    return checked, bad


def verify_coils(coils):
    """Coil (frame byte, bit) pairs must be DISTINCT, the way switch ones are.

    A collision would mean offsets 36/37 are not the OUT address after all, and
    the ball feeder would then be watching the wrong bit for the trough eject -
    which fails as "the game ball-searches for ever", the least diagnosable
    failure this rig has.  Cheap to check, so check it every dump.
    """
    seen = {}
    bad = []
    for c in coils:
        fb, bit = c.get('frame_byte'), c.get('frame_bit')
        if fb is None or not bit:
            continue
        if bit & (bit - 1):
            bad.append((c['symbol'], f'bit {bit:#04x} is not a single bit'))
            continue
        key = (fb, bit)
        if key in seen:
            bad.append((c['symbol'], f'shares byte {fb} bit {bit:#04x} '
                                     f'with {seen[key]}'))
        seen[key] = c['symbol']
    return len(seen), bad


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Dump live JJP switch/coil/lamp tables.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # Resolved at CALL time, not import time: the mounted title changes between
    # runs and a module-level default would freeze whichever was up first.
    ap.add_argument('--elf', default=None,
                    help='the game binary (default: the mounted title\'s)')
    ap.add_argument('--pid', type=int, default=None)
    ap.add_argument('--out', default=None, help='write JSON here')
    ap.add_argument('--pf', default=None,
                    help='the playfield photo, read for its size only - it is '
                         'what proves an impossible calibration scale')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)
    if not args.elf:
        args.elf = default_elf()

    pid = args.pid or find_pid()
    if not pid:
        print('swdump: no running game (start one with run_game.sh --detach)',
              file=sys.stderr)
        return 3

    elf = GameElf(args.elf)
    mem = LiveMem(pid)

    switches = dump_table(elf, mem, 'switch_table', SWITCH_SIZE, 'switch')
    out = {
        'pid': pid,
        'elf': args.elf,
        'playfield_inches': {
            'width': struct.unpack('<f', elf.read(elf.addr('hook_playfield_width'), 4))[0],
            'height': struct.unpack('<f', elf.read(elf.addr('hook_playfield_height'), 4))[0],
        },
        'matrix': {'first_byte': MATRIX_FIRST_BYTE, 'count': MATRIX_SWITCHES},
        'switches': switches,
    }
    if 'hook_coil_override_table' in elf.syms:
        try:
            out['coils'] = dump_table(elf, mem, 'hook_coil_override_table',
                                      COIL_SIZE, 'coil')
        except Exception as exc:                                # noqa: BLE001
            out['coils'], out['coils_error'] = [], str(exc)

    if 'hook_lamp_table' in elf.syms:
        try:
            out['lamps'] = dump_lamps(elf, mem)
        except Exception as exc:                                # noqa: BLE001
            out['lamps'], out['lamps_error'] = [], str(exc)

    # The photograph's size is what makes an impossible scale detectable, so
    # pass it when we have been told where the photo is.
    out['calibration'] = calibrate(switches, out.get('lamps', []),
                                   playfield=out['playfield_inches'],
                                   image_size=png_size(args.pf) if args.pf
                                   else None)

    checked, bad = verify_matrix(switches)
    out['matrix']['verified'] = checked
    out['matrix']['mismatches'] = bad

    n_coil, coil_bad = verify_coils(out.get('coils', []))
    out['coil_addressing'] = {'distinct': n_coil, 'problems': coil_bad}

    if args.out:
        with open(args.out, 'w') as fh:
            json.dump(out, fh, indent=1)

    if not args.quiet:
        positioned = [s for s in switches if s.get('x') is not None]
        print(f"pid {pid}: {len(switches)} switches, {len(positioned)} positioned")
        pf = out['playfield_inches']
        print(f"playfield: {pf['width']} x {pf['height']} inches")
        for k in ('coils', 'lamps'):
            if k in out:
                extra = ''
                if k == 'lamps':
                    extra = f", {sum(1 for l in out[k] if l['placed'])} placed"
                print(f"{k}: {len(out[k])}{extra}")
        cal = out['calibration']
        if cal.get('ok'):
            for ax in ('x', 'y'):
                f = cal[ax]
                print(f"calib {ax}: px = {f['scale']:.3f}*in + {f['offset']:.2f}  "
                      f"inliers {f['inliers']}/{f['pairs']}  mean {f['mean_px']:.1f}px"
                      + (f"  outliers {f['outliers']}" if f['outliers'] else ''))
            sq = cal.get('square_pixels')
            if sq:
                print(f"calib: forced SQUARE PIXELS - {sq['corrected']} scale "
                      f"{sq['raw_scale']:.3f} was {sq['disagreement_pct']}% off "
                      f"the {sq['took_scale_from']} scale {sq['scale']:.3f}; "
                      f"the photo cannot have two scales, so "
                      f"{sq['corrected']} was rescaled (pinned at "
                      f"{sq['pinned_at_in']:.1f} in)")
        else:
            print("calibration FAILED:", cal.get('why', ''))
        print(f"matrix rule checked on {checked} switch_NNN symbols, "
              f"{len(bad)} mismatches")
        for m in bad[:10]:
            print(f"  MISMATCH {m[0]}: got byte {m[1]:#04x} bit {m[2]:#04x}, "
                  f"expected byte {m[3]:#04x} bit {m[4]:#04x}")
        if 'coils' in out:
            print(f"coil OUT addressing: {n_coil} distinct byte/bit pairs, "
                  f"{len(coil_bad)} problems")
            for sym, why in coil_bad[:10]:
                print(f"  PROBLEM {sym}: {why}")
        print()
        print(f"{'idx':>4} {'symbol':<30} {'name':<26} {'x':>5} {'y':>5}  frame")
        for s in switches:
            if s.get('x') is None:
                continue
            print(f"{s['index']:>4} {s['symbol'][:30]:<30} {s['name'][:26]:<26} "
                  f"{s['x']:>5} {s['y']:>5}  "
                  f"byte {s['frame_byte']:#04x} bit {s['frame_bit']:#04x}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
