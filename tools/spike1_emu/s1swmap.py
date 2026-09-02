#!/usr/bin/env python3
"""Build a switch map for a Spike 1 title by walking the LIVE runtime switch
registry in guest memory — the WWE method (see the WWE boot-gate work),
generalised so ANY title gets a real map instead of the broken static decode.

Usage (the rig UP; the game past node registration):

    python3 s1swmap.py [--work /home/david/s1emu] [--out <file>] [--wait 240]

``--wait N`` retries for N seconds instead of failing on the first look, which
is how ``start.sh`` runs it: launched with the game, it sits there until the
registry is populated and then writes ``$S1_WORK/s1switches.json``.  That is
what gives an UNCURATED title a correct map — see "why this runs by itself"
below.

Everything is derived from the game ELF's own symbols (Spike 1 game ELFs ship
symbols), so nothing here is per-title:

  * the REGISTRY is found from the ``[pc, #imm]`` literal in the first
    instructions of ``sys_node_board_device_switch_update_inputs`` — the same
    anchor on every framework era met so far (WWE's 0.18, GOT LE's 0.49,
    GBLE-class 0.52, Whoa Nellie's).  The literal is NOT always the registry
    itself: on GOT LE it points 0xC in front of it (the anchor loads an
    enclosing struct and indexes into it), which read a count of 0 and made
    this tool refuse the title outright.  So the literal is a STARTING POINT:
    :func:`find_registry` scans a small window of offsets from it for the
    shape (a node count 1..64 at +0x100 whose entry pointers all land in the
    guest's data range) and takes the first that fits.  Guarded — a window
    with no such shape raises instead of walking garbage.
  * switch NAMES come from ``switch_table_data`` (ids < 129) and
    ``switch_dedicated_table_data`` (ids >= 129), which are RUNTIME-populated
    — read from guest memory, never from the file, whose copies are zeros.

Guest memory is ``/proc/<pid>/mem`` at guest address + 0x10000 (qemu-user
guest_base).  Node 0's chain is the CPU-SPI cluster (dips/service/interlock)
and is excluded — the map covers the node-bus matrix the viewer and keeper
inject into.

WHY THIS RUNS BY ITSELF (PAD-101).  The rig used to write s1switches.json from
the STATIC decode (``s1elf --switches``) and only overwrite it when a curated
``switchmaps/<CARD>.json`` existed — 7 files, matched on the card's FILENAME.
The static decode's names are right and its (node,index) attribution is wrong,
so on every other card — including the Pro/base build of a title whose LE is
curated — every click, every play key and the ball keeper's trough all
addressed the wrong slots: "switches not working on any spike 1 game".  This
walk reproduces the curated map (measured on GOT LE: 67 of 72 entries
identical, and NO position disagreed — the 5 were hand-edited names), so it is
the general answer, and start.sh now runs it on any title without a curated
map.

The output is the ``switchmaps/<TITLE>.json`` shape MINUS ``_trough_coils``:
the eject coils are observed live (press START and watch the retrying 0x40
coil frames in ttyS4.cap), not walked.  The keeper handles a map without them
(it holds the trough full and serves on plunge instead of on the eject coil).
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s1elf import _Elf  # noqa: E402  same dir: minimal ELF reader, no binutils

GUEST_BASE = 0x10000
ANCHOR = "sys_node_board_device_switch_update_inputs"
#: how far past the anchor's literal to look for the registry (see the module
#: docstring: GOT LE's literal sits 0xC in front of it).  Small on purpose —
#: a wide scan would eventually find SOME word that passes the shape test.
_REGISTRY_SCAN = 0x40
_MAX_NODES = 64
#: a populated registry's entry pointers point into the guest's own data; the
#: guest is a static ARM binary loaded low, so anything outside this is noise.
_PLAUSIBLE_PTR = (0x8000, 0x4000000)


class NotReady(Exception):
    """The guest is up but has not populated the registry yet (or is not up).

    Separate from a hard failure so ``--wait`` knows to look again."""


PROC = "/proc"          # overridden in tests


def _owns(pid, work):
    """True if *pid* is THIS rig's guest.  Both rigs name their guest ``game``
    (see s1own.sh) — the Spike 2 one is on this machine too and walking ITS
    memory with a Spike 1 ELF's symbols would yield confident nonsense.  Same
    test s1own.sh uses: our work dir appears in the process's mountinfo."""
    try:
        with open(os.path.join(PROC, str(pid), "mountinfo"), "r") as f:
            return (work.rstrip("/") + "/") in f.read()
    except OSError:
        return True     # unreadable: ambiguous, never worse than the old code


def game_pid(work):
    out = subprocess.run(["ps", "-eo", "pid,comm,pcpu", "--sort=-pcpu"],
                         stdout=subprocess.PIPE, check=True).stdout.decode()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "game" and _owns(int(parts[0]), work):
            return int(parts[0])
    raise NotReady("no guest (comm=game) for %s — is the rig running?" % work)


def elf_symbols(elf):
    """``(_Elf, {symbol: vaddr})`` for the game ELF.

    Read with the rig's own ELF reader rather than shelling out to ``nm``:
    one less thing that has to be installed in the user's WSL distro, and it
    resolves a vaddr through the section table instead of assuming the whole
    image is mapped at 0x8000."""
    with open(elf, "rb") as f:
        e = _Elf(f.read())
    return e, e.syms


def find_anchor(syms):
    for name, addr in syms.items():
        if ANCHOR in name:
            return addr
    raise SystemExit("s1swmap: no %s symbol in the ELF" % ANCHOR)


def registry_literal(elf, syms):
    """The [pc, #imm] literal loaded in the anchor's first instructions."""
    func = find_anchor(syms)
    code = elf.read_vaddr(func, 64)
    for i in range(0, 60, 4):
        (ins,) = struct.unpack_from("<I", code, i)
        # ldr rX, [pc, #imm]  (cond=AL, P=1 U=1 W=0 L=1, Rn=pc)
        if (ins & 0x0FFF0000) == 0x059F0000:
            imm = ins & 0xFFF
            lit = func + i + 8 + imm
            return struct.unpack("<I", elf.read_vaddr(lit, 4))[0]
    raise SystemExit("s1swmap: no [pc,#imm] literal in the anchor's head")


def registry_shape(g, base):
    """The node count at *base* if it looks like a populated registry, else None.

    The shape: a count of 1..64 at +0x100, and that many 8-byte entries whose
    record pointer lands in the guest's data range.  Both halves matter — a
    count alone matches any small integer in .data."""
    try:
        count = g.u32(base + 0x100)
    except OSError:
        return None
    if not 0 < count <= _MAX_NODES:
        return None
    lo, hi = _PLAUSIBLE_PTR
    try:
        for i in range(count):
            rec = g.u32(base + i * 8)
            if not lo <= rec < hi:
                return None
    except OSError:
        return None
    return count


def find_registry(g, lit):
    """The registry base at or just past the anchor's literal *lit*.

    The literal is the anchor's own load, which on some titles is an enclosing
    struct rather than the registry (GOT LE: +0xC).  Scan forward a little for
    the shape and take the first match; refuse rather than guess."""
    for delta in range(0, _REGISTRY_SCAN, 4):
        count = registry_shape(g, lit + delta)
        if count:
            return lit + delta, count
    raise NotReady("no populated switch registry at 0x%x..0x%x — booted far "
                   "enough?" % (lit, lit + _REGISTRY_SCAN))


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


#: characters a real switch name is made of.  The name is reached through two
#: pointer hops, and a hop that lands on live data reads as a short printable
#: string ("X{'" on GOT LE's 11,1) which would then be shown as a switch's
#: name and searched by the keeper.  Anything outside this alphabet, or with
#: fewer than two letters, is treated as a miss so the caller falls back to
#: "SW <id>" — honest, and it keeps the name-matched rows (TROUGH…, SHOOTER…,
#: START BUTTON) trustworthy.
_NAME_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
               "0123456789 .,#()-/&'+*:!?")


def plausible_name(name):
    if not name or len(name) < 3:
        return False
    if any(c not in _NAME_OK for c in name):
        return False
    return sum(c.isalpha() for c in name) >= 2


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
        if plausible_name(name):
            return name
        p2 = g.u32(p1)
        name = g.cstr(p2) if p2 else None
        return name if plausible_name(name) else None
    except OSError:
        return None


def walk(g, base, syms, count=None):
    """``{"node,index": name}`` for every switch the running game registered."""
    if count is None:
        count = registry_shape(g, base)
    if not count:
        raise NotReady("registry at 0x%x is not populated" % base)
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


def build_map(work):
    """``{"node,index": name}`` walked out of the running game.

    Raises :class:`NotReady` while the rig is not up / not booted far enough."""
    elf_path = os.path.realpath(os.path.join(work, "game", "game"))
    elf, syms = elf_symbols(elf_path)
    lit = registry_literal(elf, syms)
    g = Guest(game_pid(work))
    base, count = find_registry(g, lit)
    print("[swmap] elf %s  registry 0x%x (%d nodes)" % (elf_path, base, count),
          file=sys.stderr)
    return walk(g, base, syms, count)


def write_map(m, out):
    blob = json.dumps(dict(sorted(
        m.items(), key=lambda kv: tuple(map(int, kv[0].split(","))))), indent=1)
    if out == "-":
        print(blob)
        return
    tmp = out + ".tmp"          # the switch window and the keeper poll this
    with open(tmp, "w") as f:   # file, so it must never be seen half-written
        f.write(blob + "\n")
    os.replace(tmp, out)
    print("[swmap] wrote %s" % out, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/home/david/s1emu")
    ap.add_argument("--out", default="-")
    ap.add_argument("--wait", type=float, default=0, metavar="SECONDS",
                    help="keep retrying for this long while the game boots")
    ap.add_argument("--every", type=float, default=5.0, metavar="SECONDS",
                    help="retry interval under --wait")
    args = ap.parse_args()

    deadline = time.monotonic() + args.wait
    while True:
        try:
            m = build_map(args.work)
        except NotReady as exc:
            if time.monotonic() >= deadline:
                print("s1swmap: %s" % exc, file=sys.stderr)
                return 1
            time.sleep(args.every)
            continue
        break
    print("[swmap] %d switches on %d nodes" % (
        len(m), len({k.split(",")[0] for k in m})), file=sys.stderr)
    write_map(m, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
