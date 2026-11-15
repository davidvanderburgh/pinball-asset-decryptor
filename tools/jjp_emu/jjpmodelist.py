#!/usr/bin/env python3
"""List every game mode living in a running JJP game (PAD-1335).

A JJP mode is a C++ object derived from the engine's `Mode`: a global such as
`slash_solo` or `song_mode`, built by Mode::Mode(name, id, ModeManager*, Lamp*,
run_id, grace_id, grace_grace_id, Audit*, Audit*).  This finds them generically
on any title that shares the engine: every vtable in the game's .dynsym that
carries Mode::is_running is a Mode class, and every object in the game's
writable memory whose first word points into one of those vtables is a mode.

Read-only, through /proc/<pid>/mem, which never trips the Sentinel envelope's
anti-debug gate (do NOT use gdb/strace on the game).  Run as root in WSL:

    python3 jjpmodelist.py [--elf PATH] [--pid PID]
"""
import argparse
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jjpelf import GameElf  # noqa: E402
import swdump  # noqa: E402  (find_pid keeps to the JJP jail)

# Mode layout, read off GnR 3.03's live objects and Mode::Mode / start / run_proc.
OFF_NAME, OFF_ID, OFF_MGR, OFF_RUN_ID = 0x08, 0x10, 0x18, 0x28


def demangle(names):
    out = subprocess.run(['c++filt'], input='\n'.join(names), capture_output=True, text=True)
    return out.stdout.split('\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description='List the live Mode objects of a JJP game.')
    ap.add_argument('--elf', default=None, help='the game binary (default: the mounted title)')
    ap.add_argument('--pid', type=int, default=None)
    a = ap.parse_args(argv)
    pid = a.pid or swdump.find_pid()
    if not pid:
        print('jjpmodelist: no JJP game running', file=sys.stderr)
        return 3
    elf = a.elf or os.readlink(f'/proc/{pid}/exe')
    if not elf.startswith('/var/tmp') and os.path.exists(f'/proc/{pid}/root' + elf):
        elf = f'/proc/{pid}/root' + elf
    g = GameElf(elf)
    mem = open(f'/proc/{pid}/mem', 'rb', buffering=0)

    def rd(addr, n):
        mem.seek(addr)
        return mem.read(n)

    is_running = g.addr('_ZN4Mode10is_runningEv')
    vts = {}
    for n in g.names_matching('_ZTV'):
        try:
            a0, sz = g.addr(n), g.size(n)
            data = rd(a0, sz)
        except Exception:
            continue
        slots = struct.unpack_from(f'<{sz // 8}Q', data)
        if is_running in slots:
            vts[a0 + 16] = n
    cls = dict(zip(vts.keys(), demangle([n[4:] and '_Z' + n[4:] for n in vts.values()])))
    cls = {k: v.replace('vtable for ', '') for k, v in cls.items()}
    syms = {}
    for n in g.names_matching(''):
        try:
            a0 = g.addr(n)
        except Exception:
            continue
        if a0:          # imports carry address 0
            syms[a0] = n
    rows = []
    for line in open(f'/proc/{pid}/maps'):
        parts = line.split()
        lo, hi = (int(x, 16) for x in parts[0].split('-'))
        path = parts[5] if len(parts) > 5 else ''
        if 'w' not in parts[1] or not path.endswith('/game'):
            continue
        buf = rd(lo, hi - lo)
        for off in range(0, len(buf) - 0x30, 8):
            v = struct.unpack_from('<Q', buf, off)[0]
            if v not in vts:
                continue
            obj = lo + off
            name_p, mode_id, mgr, run_id = (struct.unpack_from('<Q', buf, off + OFF_NAME)[0],
                                            struct.unpack_from('<i', buf, off + OFF_ID)[0],
                                            struct.unpack_from('<Q', buf, off + OFF_MGR)[0],
                                            struct.unpack_from('<I', buf, off + OFF_RUN_ID)[0])
            try:
                name = rd(name_p, 48).split(b'\0')[0].decode('latin1')
            except OSError:
                name = '?'
            rows.append((obj, syms.get(obj, ''), cls.get(v, vts[v]), name, mode_id, mgr, run_id))
    print(f'{len(rows)} modes in pid {pid} ({os.path.basename(os.path.dirname(elf))})')
    print(f"{'object':12s} {'symbol':28s} {'class':34s} {'name':26s} {'id':>4s} {'proc':>6s} manager")
    for obj, sym, c, name, mid, mgr, rid in rows:
        manager = (syms.get(mgr) or hex(mgr)) if mgr else '-'
        print(f'{obj:#012x} {sym:28s} {c:34s} {name:26s} {mid:4d} {rid:#6x} {manager}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
