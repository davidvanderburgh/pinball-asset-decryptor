#!/usr/bin/env python3
"""Build a curated switch map for a Spike 1 title by walking the LIVE runtime
switch registry in guest memory — the WWE method (see the WWE boot-gate work),
generalised so any title gets a real map instead of the broken static decode.

Usage (the rig UP and the game at attract or later):

    python3 s1swmap.py [--work /home/david/s1emu] [--out <file>]

Everything is derived from the game ELF's own symbols (Spike 1 game ELFs ship
symbols), so nothing here is per-title:

  * the REGISTRY BASE is the ``[pc, #imm]`` literal in the first instructions
    of ``sys_node_board_device_switch_update_inputs`` (matched by its mangled
    name in ``nm``) — the same anchor on every framework era met so far
    (WWE's 0.18, GBLE-class 0.52, Whoa Nellie's);
  * switch NAMES come from ``switch_table_data`` (ids < 129) and
    ``switch_dedicated_table_data`` (ids >= 129), which are RUNTIME-populated
    — read from guest memory, never from the file, whose copies are zeros.

Guest memory is ``/proc/<pid>/mem`` at guest address + 0x10000 (qemu-user
guest_base).  Node 0's chain is the CPU-SPI cluster (dips/service/interlock)
and is excluded — the map covers the node-bus matrix the viewer and keeper
inject into.

The output is the ``switchmaps/<TITLE>.json`` shape MINUS ``_trough_coils``:
the eject coils are observed live (press START and watch the retrying 0x40
coil frames in ttyS4.cap), not walked.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys

GUEST_BASE = 0x10000
ANCHOR = "sys_node_board_device_switch_update_inputs"


def game_pid():
    out = subprocess.run(["ps", "-eo", "pid,comm,pcpu", "--sort=-pcpu"],
                         stdout=subprocess.PIPE, check=True).stdout.decode()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "game":
            return int(parts[0])
    raise SystemExit("s1swmap: no guest (comm=game) — start the rig first")


def elf_symbols(elf):
    syms = {}
    out = subprocess.run(["nm", elf], stdout=subprocess.PIPE,
                         check=True).stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return syms


def find_anchor(syms):
    for name, addr in syms.items():
        if ANCHOR in name:
            return addr
    raise SystemExit("s1swmap: no %s symbol in the ELF" % ANCHOR)


def registry_base(elf, syms):
    """The [pc, #imm] literal loaded in the anchor's first instructions."""
    func = find_anchor(syms)
    with open(elf, "rb") as f:
        f.seek(func - 0x8000)
        code = f.read(64)
        for i in range(0, 60, 4):
            (ins,) = struct.unpack_from("<I", code, i)
            # ldr rX, [pc, #imm]  (cond=AL, P=1 U=1 W=0 L=1, Rn=pc)
            if (ins & 0x0FFF0000) == 0x059F0000:
                imm = ins & 0xFFF
                lit = func + i + 8 + imm
                f.seek(lit - 0x8000)
                (base,) = struct.unpack("<I", f.read(4))
                return base
    raise SystemExit("s1swmap: no [pc,#imm] literal in the anchor's head")


class Guest:
    def __init__(self, pid):
        self.f = open("/proc/%d/mem" % pid, "rb")

    def read(self, addr, n):
        self.f.seek(addr + GUEST_BASE)
        return self.f.read(n)

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def u8(self, addr):
        return self.read(addr, 1)[0]

    def cstr(self, addr, cap=48):
        raw = self.read(addr, cap)
        s = raw.split(b"\0")[0]
        try:
            t = s.decode("ascii")
        except UnicodeDecodeError:
            return None
        if t and all(31 < ord(c) < 127 for c in t):
            return t
        return None


def switch_name(g, syms, sid):
    if sid >= 129:
        base = syms.get("switch_dedicated_table_data")
        entry = base + (sid - 129) * 32 if base else None
    else:
        base = syms.get("switch_table_data")
        entry = base + sid * 32 if base else None
    if not entry:
        return None
    try:
        p1 = g.u32(entry + 8)
        if not p1:
            return None
        name = g.cstr(p1)
        if name:
            return name
        p2 = g.u32(p1)
        return g.cstr(p2) if p2 else None
    except OSError:
        return None


def walk(g, base, syms):
    count = g.u32(base + 0x100)
    if not 0 < count <= 64:
        raise SystemExit("s1swmap: registry count %d looks wrong at 0x%x "
                         "(booted far enough?)" % (count, base))
    out = {}
    for i in range(count):
        rec = g.u32(base + i * 8)
        chain = g.u32(base + i * 8 + 4)
        if not rec:
            continue
        node = g.u8(rec)
        if node == 0:
            continue                     # the CPU-SPI cluster
        hops = 0
        while chain and hops < 512:
            hops += 1
            dev = g.u32(chain + 20)
            if dev:
                sid = g.u32(dev + 8)
                pos = g.u8(dev + 22)
                name = switch_name(g, syms, sid) or ("SW %d" % sid)
                key = "%d,%d" % (node, pos)
                if key not in out:
                    out[key] = name
            chain = g.u32(chain + 24)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/home/david/s1emu")
    ap.add_argument("--out", default="-")
    args = ap.parse_args()

    elf = os.path.realpath(os.path.join(args.work, "game", "game"))
    syms = elf_symbols(elf)
    base = registry_base(elf, syms)
    pid = game_pid()
    print("[swmap] elf %s  registry 0x%x  pid %d" % (elf, base, pid),
          file=sys.stderr)
    g = Guest(pid)
    m = walk(g, base, syms)
    print("[swmap] %d switches on %d nodes" % (
        len(m), len({k.split(",")[0] for k in m})), file=sys.stderr)
    blob = json.dumps(dict(sorted(
        m.items(), key=lambda kv: tuple(map(int, kv[0].split(","))))),
        indent=1)
    if args.out == "-":
        print(blob)
    else:
        with open(args.out, "w") as f:
            f.write(blob + "\n")
        print("[swmap] wrote %s" % args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
