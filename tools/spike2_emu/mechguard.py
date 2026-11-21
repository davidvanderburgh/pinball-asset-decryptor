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

PAD-1487 (DragonRR): the same watch holds the game's TIMED PLUNGER at Off
when the Emulate tab's "Hold the ball in the shooter lane" is ticked
(PAD_LAUNCH_HOLD=1). TIMED PLUNGER (AD_TIMED_PLUNGER, 0-300 s, shipped 0 =
off) is the operator setting that "autolaunches a ball in the Shooter Lane
after a specified amount of idle time": with it set, ball 1 leaves the lane by
itself however long a tester needs it there. The machine's own value is kept
in PAD_ADJ_KEEP (a file beside the slot's NVRAM) and put back by the first run
without the hold, so a test run never costs the machine its setting.

    mechguard.py <pid of the launch that starts the game>
    PAD_MECHGUARD=0   leaves the mech settings alone
    PAD_LAUNCH_HOLD=1 holds TIMED PLUNGER at Off for this run
    PAD_ADJ_KEEP      where the held setting's own value is kept
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
#: PAD-1487: the setting that launches a waiting ball by itself
TIMED_PLUNGER = "AD_TIMED_PLUNGER"
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


def _program_paths(pid, lo, hi, path, root_link=None):
    """Where the mapped game program can be opened, in the order to try.

    PAD-1487: a rig run as a user (not root) is chrooted into its slot, and
    maps writes the game as /home/<user>/padslots/N/root/games/<title>/game -
    the chroot prefix included, while the card mount it lives on is only in
    the game's own mount namespace. map_files is refused without
    CAP_SYS_ADMIN and root/<that whole path> names nothing, so the guard had
    never read the program on such a run; the file is root/games/<title>/game.
    So: the chroot's own prefix taken off, then each shorter tail."""
    out = ["/proc/%d/map_files/%x-%x" % (pid, lo, hi), "/proc/%d/root%s" % (pid, path)]
    if root_link is None:
        try:
            root_link = os.readlink("/proc/%d/root" % pid)
        except OSError:
            root_link = ""
    root_link = root_link.rstrip("/")
    if root_link and path.startswith(root_link + "/"):
        out.append("/proc/%d/root%s" % (pid, path[len(root_link):]))
    parts = path.strip("/").split("/")
    for i in range(1, len(parts) - 1):
        out.append("/proc/%d/root/%s" % (pid, "/".join(parts[i:])))
    out.append(path)
    seen = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def game_elf(pid):
    """The game's program as the process mapped it. The path in maps is the
    one inside the game's own mount namespace (the card mount, under qemu), so
    it is opened through the process: map_files names the very file mapped,
    root/<path> the same path as the game sees it. /proc/<pid>/exe is qemu."""
    for line in open("/proc/%d/maps" % pid):
        q = line.split()
        if len(q) >= 6 and q[2] == "00000000" and os.path.basename(q[5]) == "game":
            lo, hi = (int(x, 16) for x in q[0].split("-"))     # map_files: no leading zeros
            for p in _program_paths(pid, lo, hi, q[5]):
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
    or ({}, None) when its adjustment table cannot be read. TIMED PLUNGER,
    which is not a mech switch, is launch_setting()'s."""
    ids, _hold, table = _read(elf)
    return ids, table


def launch_setting(elf):
    """PAD-1487: (id, max) of the game's TIMED PLUNGER, or None."""
    return _read(elf)[1]


def _read(elf):
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
    hold = None
    i = t.by_name.get(TIMED_PLUNGER)
    if i is not None:
        o = t._off(t.table_va + i * t.elem)
        default, lo, hi = struct.unpack_from("<3i", t.data, o + 4)
        if lo == 0 and 0 < hi <= 3600 and lo <= default <= hi:   # seconds, 0 = off
            hold = (i, hi)
    return ids, hold, (t.table_va, t.elem)


def cached(elf, game):
    """_read() once per build: the decode reads the whole program. Returns
    (mech ids, TIMED PLUNGER's (id, max) or None, (table_va, elem))."""
    key = "%s-%d-%08x" % (game or "game", len(elf), sum(elf[:4096:16]) & 0xffffffff)
    path = os.path.join(os.environ.get("TMPDIR") or "/tmp", "padmechguard2-%s.json" % key)
    try:
        d = json.load(open(path))
        return ({int(k): v for k, v in d["ids"].items()},
                tuple(d["hold"]) if d["hold"] else None, tuple(d["table"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    ids, hold, table = _read(elf)
    try:
        json.dump({"ids": ids, "hold": hold, "table": table}, open(path, "w"))
    except OSError:
        pass
    return ids, hold, table


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


def _valid(v, ck, hi):
    """A live value the game has loaded: its check byte agrees and it is in range."""
    return ck == (~sum(struct.pack("<i", v)) & 0xff) and 0 <= v <= hi


def load_keep(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_keep(path, d):
    try:
        if d:
            with open(path, "w") as f:
                json.dump(d, f)
            try:
                os.chmod(path, 0o666)          # a root run's file stays writable for the next run
            except OSError:
                pass
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class LaunchHold:
    """PAD-1487: TIMED PLUNGER held at Off for a run (*on*), or the machine's
    own value put back after such a run (*on* False). *keep* is the file the
    value waits in between the two."""

    def __init__(self, live, setting, on, keep):
        self.live, (self.id, self.hi) = live, setting
        self.on, self.keep = on, keep
        self.said = False
        self.finished = False

    def look(self):
        """One look. True once there is nothing more for it to do."""
        if self.finished:
            return True
        v, ck = self.live.get(self.id)
        if not _valid(v, ck, self.hi):
            return False                      # not loaded yet
        kept = load_keep(self.keep) if self.keep else {}
        if self.on:
            if v:
                kept[TIMED_PLUNGER] = v
                if self.keep:
                    save_keep(self.keep, kept)
                self.live.set(self.id, 0)
                say("TIMED PLUNGER was %d s, which launches a waiting ball by itself; held at Off for this run "
                    "(Hold the ball in the shooter lane). The machine keeps its %d s: the next run without "
                    "the hold puts it back" % (v, v))
                self.said = True
            elif not self.said:
                say("holding the ball in the shooter lane: TIMED PLUNGER is Off, so a ball waits there for "
                    "a plunge or the launch button")
                self.said = True
            return False                      # keep holding: the service menu can set it again
        own = kept.pop(TIMED_PLUNGER, None)
        if own is not None:
            if v == 0 and isinstance(own, int) and 0 < own <= self.hi:
                self.live.set(self.id, own)
                say("TIMED PLUNGER put back to the machine's own %d s (an earlier run held it at Off)" % own)
            save_keep(self.keep, kept)
        self.finished = True
        return True


def main(argv):
    mechs_on = os.environ.get("PAD_MECHGUARD", "1") != "0"
    hold_on = os.environ.get("PAD_LAUNCH_HOLD", "0") == "1"
    keep = os.environ.get("PAD_ADJ_KEEP") or ""
    if not mechs_on and not hold_on and not (keep and os.path.exists(keep)):
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
        ids, setting, table = cached(game_elf(pid), os.environ.get("PAD_GAME"))
    except Exception as e:                                  # noqa: BLE001
        say("cannot read this game's settings table (%s); its settings are left alone" % e)
        return 0
    if not mechs_on:
        ids = {}
    if hold_on and not setting:
        say("this game has no TIMED PLUNGER setting: nothing launches a waiting ball by itself to hold off")
    if ids:
        say("watching %d mech-off setting(s): %s" % (len(ids), ", ".join(label(n) for n in ids.values())))
    if not ids and not (setting and (hold_on or keep)):
        return 0
    live, done = Live(pid, table[0], table[1], game_base(pid)), set()
    hold = LaunchHold(live, setting, hold_on, keep) if setting and (hold_on or keep) else None
    while os.path.exists("/proc/%d" % pid):
        try:
            if ids:
                guard(live, ids, done)
            if hold is not None and hold.look() and not ids:
                break
        except OSError:
            break
        time.sleep(POLL_S)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
