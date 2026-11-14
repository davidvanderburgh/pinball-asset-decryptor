#!/usr/bin/env python3
"""Keep a Spike 2 game's mechs switched on in the emulator (PAD-1225).

A real machine has operator settings that switch a mech off for good when it
is broken: batman 66's AD_TURNTABLE_MOTOR_DISABLED, AD_PENGUIN_MOTOR_DISABLED,
AD_TURNTABLE_DIVERTER_DISABLED, ... With one of them On the game never moves
that mech - no boot test, no ball search, no turn for a hurry-up - and plays
on as if it were broken. A player's batman did exactly that: his crane moved
and his turntable was never sent anywhere, so every Bat Phone hurry-up faced
the TV. On the rig, setting AD_TURNTABLE_MOTOR_DISABLED gave that same log.

The emulator's mechs cannot break, so such a setting only ever spoils play.
This watches the running game's own values and sets any that is On back to
Off, saying so once in the run log ("[mechguard] ..."), which a problem report
carries. Each setting is the game's live adjustment: the descriptor at
table + id * elem holds a pointer to a u32 value and a check byte, the ones'
complement of the value's four bytes (PAD-615). The table is found in the
game's own ELF by the app's adjustment decoder.

    mechguard.py <pid of the launch that starts the game>
    PAD_MECHGUARD=0   leaves the settings alone
"""
import json
import os
import re
import struct
import sys
import time

RIG = os.path.dirname(os.path.abspath(__file__))
# installed: {app}/tools/spike2_emu next to {app}/pinball_decryptor; in the repo the same
sys.path.insert(0, os.path.dirname(os.path.dirname(RIG)))

# a switch that takes a mech out: a motor, a diverter, a magnet, a gate
GUARDED = re.compile(r"^AD_[A-Z0-9_]*(MOTOR|DIVERTER|MAGNET|GATE)[A-Z0-9_]*_DISABLED$")
POLL_S = 0.5
FIND_S = 180


def say(msg):
    print("[mechguard] %s" % msg, flush=True)


def _children(pid):
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            stat = open("/proc/%s/stat" % p).read()
        except OSError:
            continue
        # the ppid follows the ')' that closes the command name
        if int(stat.rsplit(")", 1)[1].split()[1]) == pid:
            out.append(int(p))
    return out


def _is_game(pid):
    try:
        return os.path.basename(os.readlink("/proc/%d/exe" % pid)) == "game" or \
            any(ln.rstrip().endswith("/game") for ln in open("/proc/%d/maps" % pid))
    except OSError:
        return False


def find_game(root):
    """The game process under *root* (run_game.sh), or None."""
    todo, seen = [root], set()
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        if p != root and _is_game(p):
            return p
        todo.extend(_children(p))
    return None


def game_base(pid):
    """Where the guest's address 0 sits in this process (qemu-user maps the
    ELF's first page, VA 0x8000, at file offset 0)."""
    for line in open("/proc/%d/maps" % pid):
        q = line.split()
        if len(q) >= 6 and q[2] == "00000000" and os.path.basename(q[5]) == "game":
            return int(q[0].split("-")[0], 16) - 0x8000
    return None


def game_elf(pid):
    """The game's program as the process mapped it. The path in maps is the
    one inside the game's own mount namespace (the card mount, under qemu), so
    it is opened through the process: map_files names the very file mapped,
    root/<path> the same path as the game sees it. /proc/<pid>/exe is qemu."""
    for line in open("/proc/%d/maps" % pid):
        q = line.split()
        if len(q) >= 6 and q[2] == "00000000" and os.path.basename(q[5]) == "game":
            lo, hi = (int(x, 16) for x in q[0].split("-"))     # map_files: no leading zeros
            for p in ("/proc/%d/map_files/%x-%x" % (pid, lo, hi), "/proc/%d/root%s" % (pid, q[5])):
                try:
                    with open(p, "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                if data[:4] == b"\x7fELF":
                    return data
            break
    raise OSError("the game's program could not be read")


def _pure_name_run(table, va_set):
    """AdjustmentTable._longest_name_run without numpy, for a distro that has none."""
    best = []
    lo, hi = min(va_set), max(va_set)
    for po, pv, fsz in table._loads:
        base, words = table._words(po, fsz)
        run = []
        for j, w in enumerate(words):
            if lo <= w <= hi and w in va_set:
                v = pv + (base - po) + 4 * j
                if run and v != run[-1] + 4:
                    if len(run) > len(best):
                        best = run
                    run = []
                run.append(v)
        if len(run) > len(best):
            best = run
    return best


def guarded(elf):
    """{id: name} of the mech-off settings and (table_va, elem), from the ELF -
    or ({}, None) when its adjustment table cannot be read."""
    from pinball_decryptor.plugins.stern import adjustments
    try:
        import numpy  # noqa: F401
    except ImportError:
        adjustments.AdjustmentTable._longest_name_run = _pure_name_run
    t = adjustments.AdjustmentTable(elf)
    ids = {}
    for i, n in enumerate(t.names):
        if not n or not GUARDED.match(n):
            continue
        o = t._off(t.table_va + i * t.elem)
        default, lo, hi = struct.unpack_from("<3i", t.data, o + 4)
        if default == 0 and lo == 0 and hi == 1:     # an off/on switch that ships off
            ids[i] = n
    return ids, (t.table_va, t.elem)


def cached(elf, game):
    """guarded() once per build: the decode reads the whole program."""
    key = "%s-%d-%08x" % (game or "game", len(elf), sum(elf[:4096:16]) & 0xffffffff)
    path = os.path.join(os.environ.get("TMPDIR") or "/tmp", "padmechguard-%s.json" % key)
    try:
        d = json.load(open(path))
        return {int(k): v for k, v in d["ids"].items()}, tuple(d["table"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    ids, table = guarded(elf)
    try:
        json.dump({"ids": ids, "table": table}, open(path, "w"))
    except OSError:
        pass
    return ids, table


class Live:
    """The running game's adjustment values, through /proc/<pid>/mem."""

    def __init__(self, pid, table, elem, base):
        self.f = open("/proc/%d/mem" % pid, "r+b", buffering=0)
        self.table, self.elem, self.base = table, elem, base

    def _rd(self, va, n):
        self.f.seek(va + self.base)
        return self.f.read(n)

    def _slot(self, i):
        return struct.unpack("<I", self._rd(self.table + i * self.elem, 4))[0]

    def get(self, i):
        raw = self._rd(self._slot(i), 5)
        return struct.unpack("<i", raw[:4])[0], raw[4]

    def set(self, i, v):
        b = struct.pack("<i", v)
        self.f.seek(self._slot(i) + self.base)
        self.f.write(b + bytes([~sum(b) & 0xff]))


def label(name):
    return name[3:].replace("_", " ")


def guard(live, ids, done):
    """One look: every guarded setting that reads On is set Off. Returns the
    names it changed this time."""
    changed = []
    for i, name in ids.items():
        v, ck = live.get(i)
        if v == 1 and ck == (~sum(struct.pack("<i", 1)) & 0xff):
            live.set(i, 0)
            changed.append(name)
            if name not in done:
                done.add(name)
                say("%s was On in the game's settings, which keeps that mech still "
                    "for good; set Off (the emulator's mechs cannot break)" % label(name))
    return changed


def main(argv):
    if os.environ.get("PAD_MECHGUARD", "1") == "0":
        return 0
    root = int(argv[1]) if len(argv) > 1 else 0
    t0 = time.time()
    pid = None
    while time.time() - t0 < FIND_S:
        pid = find_game(root) if root else None
        if pid and game_base(pid) is not None:
            break
        if root and not os.path.exists("/proc/%d" % root):
            return 0
        time.sleep(0.5)
    else:
        return 0
    try:
        ids, table = cached(game_elf(pid), os.environ.get("PAD_GAME"))
    except Exception as e:                                  # noqa: BLE001
        say("cannot read this game's settings table (%s); its settings are left alone" % e)
        return 0
    if not ids:
        return 0
    say("watching %d mech-off setting(s): %s" % (len(ids), ", ".join(label(n) for n in ids.values())))
    live, done = Live(pid, table[0], table[1], game_base(pid)), set()
    while os.path.exists("/proc/%d" % pid):
        try:
            guard(live, ids, done)
        except OSError:
            break
        time.sleep(POLL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
