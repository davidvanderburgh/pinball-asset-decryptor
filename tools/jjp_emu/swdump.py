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
different space entirely.
"""

import argparse
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jjpelf import GameElf                                       # noqa: E402

DEFAULT_ELF = '/var/tmp/jjp_run/jjpe/gen1/Wonka/game'

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
            rec['group'] = struct.unpack_from('<I', b, 32)[0]
        else:
            # Coil and lamp layouts are not decoded yet; carry the raw bytes so
            # a later pass can work them out without needing another live run.
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


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Dump live JJP switch/coil/lamp tables.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--elf', default=DEFAULT_ELF)
    ap.add_argument('--pid', type=int, default=None)
    ap.add_argument('--out', default=None, help='write JSON here')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

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
    for sym, osize, kind in (('hook_coil_override_table', COIL_SIZE, 'coil'),
                             ('hook_lamp_table', LAMP_SIZE, 'lamp')):
        if sym in elf.syms:
            try:
                out[kind + 's'] = dump_table(
                    elf, mem, sym, osize, kind,
                    size_sym='hook_lamp_table_size' if kind == 'lamp' else None)
            except Exception as exc:                            # noqa: BLE001
                out[kind + 's'] = []
                out[kind + 's_error'] = str(exc)

    checked, bad = verify_matrix(switches)
    out['matrix']['verified'] = checked
    out['matrix']['mismatches'] = bad

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
                print(f"{k}: {len(out[k])}")
        print(f"matrix rule checked on {checked} switch_NNN symbols, "
              f"{len(bad)} mismatches")
        for m in bad[:10]:
            print(f"  MISMATCH {m[0]}: got byte {m[1]:#04x} bit {m[2]:#04x}, "
                  f"expected byte {m[3]:#04x} bit {m[4]:#04x}")
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
