#!/usr/bin/env python3
"""padsw.py - the ONE definition of the switch block's layout, for the scripts.

`padsw.h` is the definition for the two C programs. This is the same struct for
the Python side, in one place, because four scripts had four copies of `OFF_HELD
= 8` and the block just grew two more regions. The rig has been bitten by
duplicated facts twice already (alive.sh vs killgame.sh, autoattract.sh vs
status.sh), and both times the copies drifted rather than broke loudly.

THREE REGIONS, ONE WRITER EACH - read padsw.h for why, but the short version is
that padglhost REBUILDS its whole array on every key event, so when the scripts
shared that array a flipper press erased whatever swpoke.py or plunge.py had
just written:

    held[]      the KEYBOARD's, written only by padglhost
    scr_held[]  the SCRIPTS', written only by the helpers here
    mrg[]       what the GAME IS HANDED, written only by the guest shim

So: WRITE scr_held, READ mrg. Writing held[] from a script puts it back in a
fight it cannot win, and reading held[] answers a question about the keyboard
rather than about the machine.

TAKING OWNERSHIP MATTERS, and it is the one non-obvious part. The shim merges by
LAST EDGE WINS per id, so a write that does not CHANGE scr_held moves nothing.
padglhost latches the coin door and the six trough balls on at window open, so
`mrg[66]` is 1 while `scr_held[66]` is still 0 - and plunge.py writing 0 there
would be a no-op. `take()` first copies the merged value into scr_held (silent,
because it agrees with what the game already sees) so that the write after it is
a real edge. Use it before changing anything the keyboard might also hold.

AND THEN CHECK THAT IT LANDED (`set_confirmed`, PAD-186). take() plus the write
after it is `1 -> 0 -> 1` in scr_held, and the shim only looks between passes:
if no pass lands in the middle the pair collapses and the switch never moves,
with every instrument on this side still saying it did. A helper that means to
change what the GAME sees should write through `set_confirmed` and say so when
the merge did not take it - `set_held` alone is for the script's own bookkeeping.
"""
import mmap
import os
import struct
import time
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

#: PAD_SW_FILE points the helpers at a block that is not a running game's, which
#: is the only way to check any of this without one. The rig never sets it.
#: `dump() or ""` (the same guard playfield.py uses): on a machine with no
#: rig root - a CI runner - dump() is None, and joining None killed this
#: module at IMPORT, which single-process test runs only dodged because an
#: alphabetically earlier test had already imported it under a monkeypatched
#: PAD_ROOT and left it cached in sys.modules.
PATH = (os.environ.get("PAD_SW_FILE")
        or os.path.join(padpath.dump() or "", "padsw"))
MAGIC = 0x53444150
MAX_ID = 256

#: Byte offsets, matching struct padsw_shm in padsw.h field for field.
OFF_MAGIC = 0
OFF_GEN = 4                          # keyboard generation  (padglhost writes)
OFF_HELD = 8                         # keyboard array       (padglhost writes)
OFF_TAP_GEN = OFF_HELD + MAX_ID      # 264
OFF_TAP_ID = OFF_TAP_GEN + 4         # 268
OFF_TAP_READS = OFF_TAP_ID + 4       # 272
OFF_SCR_GEN = OFF_TAP_READS + 4      # 276  script generation (WE write)
OFF_SCR_HELD = OFF_SCR_GEN + 4       # 280  script array      (WE write)
OFF_MRG_GEN = OFF_SCR_HELD + MAX_ID  # 536  merged generation (the shim writes)
OFF_MRG = OFF_MRG_GEN + 4            # 540  merged array      (the shim writes)
OFF_KBD_SRC = OFF_MRG + MAX_ID       # 796  who padglhost was  (it writes)
OFF_SCR_SRC = OFF_KBD_SRC + 4        # 800  who WE are         (WE write)
OFF_GUEST_T0 = OFF_SCR_SRC + 4       # 804  the guest's clock  (the shim writes)
OFF_SPIN_GEN = OFF_GUEST_T0 + 4      # 808  rip generation     (swspin.py writes)
OFF_SPIN = OFF_SPIN_GEN + 4          # 812  rip array          (swspin.py writes)

#: THE CABINET BUTTONS BY NAME, for the boot menu before a title has a switch
#: list (padsw.h says why). Same order as padsw.h's PADSW_CAB_* and the menu's
#: own key order; one byte each, no generation - the menu polls them.
CAB_NAMES = ("left", "right", "start", "action", "select", "plus", "minus", "back")
CAB_N = len(CAB_NAMES)
OFF_CAB = OFF_SPIN + MAX_ID          # 1068 keyboard's cab[]   (padglhost writes)
OFF_SCR_CAB = OFF_CAB + CAB_N        # 1076 scripts' scr_cab[] (WE write)
OFF_PAUSED = OFF_SCR_CAB + CAB_N     # 1084 1 while frozen     (padglhost writes)
OFF_PAUSED_MS = OFF_PAUSED + 4       # 1088 total ms frozen    (padglhost writes)
OFF_PAUSE_REQ = OFF_PAUSED_MS + 4    # 1092 pause presses      (WE write)
OFF_STOP_WANT = OFF_PAUSE_REQ + 4    # 1096 1 = freeze wanted  (padglhost writes)
OFF_STOP_GEN = OFF_STOP_WANT + 4     # 1100 request counter    (padglhost writes)
OFF_STOP_N = OFF_STOP_GEN + 4        # 1104 games signalled    (pausekeep.py writes)
OFF_STOP_ACK = OFF_STOP_N + 4        # 1108 request served     (pausekeep.py writes)
OFF_SPEED_REQ = OFF_STOP_ACK + 4     # 1112 game speed x1000   (padspeed.py writes)
OFF_SPEED_NOW = OFF_SPEED_REQ + 4    # 1116 speed in effect    (the shim writes)
SIZE = OFF_SPEED_NOW + 4             # 1120, in a 4096-byte block


def open_block(path=PATH):
    """The mapped block, or None with a message if the emulator is not up."""
    try:
        f = open(path, "r+b")
    except OSError as exc:
        print("cannot open %s: %s" % (path, exc))
        return None
    m = mmap.mmap(f.fileno(), 4096)
    if struct.unpack_from("<I", m, OFF_MAGIC)[0] != MAGIC:
        print("bad magic - is the emulator running?")
        m.close()
        return None
    return m


def merged(m, sw):
    """What the game is being handed for `sw` right now."""
    return m[OFF_MRG + sw]


#: SAY WHO YOU ARE. Every write from this side lands in one array, so the log
#: cannot tell autoattract's Service Back from a flipper poke unless the writer
#: says - and a replay that re-delivers autoattract fights the next run's own.
#: padsw.h has the alphabet and the one case it cannot resolve. `?` is what an
#: untagged helper gets, which is visible in the log rather than silent.
#:
#: READ AT IMPORT, not only inside set_source(), and that is the fix for a real
#: hole rather than a tidy-up. PAD_SW_SRC used to be consulted only by
#: set_source(), so anything that imported this module and drove a switch
#: directly - a one-off `python3 -c`, a future replay driver - was tagged `?`
#: however carefully its caller had set the variable. Caught on a live run:
#: `PAD_SW_SRC=r` produced `[sw] 105100 ms +59?`.
_src = ord((os.environ.get("PAD_SW_SRC") or "?")[0]) & 0xFF


def set_source(tag):
    """Declare the writer, as a DEFAULT that PAD_SW_SRC still beats.

    The environment winning is how a wrapper retags a helper it shells out to:
    autoattract.sh exports PAD_SW_SRC=a and keeps calling the ordinary
    swpoke.py, so the rig's own boot press is distinguishable from a flipper
    poke without a second copy of swpoke.py existing to drift.
    """
    global _src
    _src = ord((os.environ.get("PAD_SW_SRC") or tag)[0]) & 0xFF


def guest_ms(m):
    """The guest's own millisecond - the number every `[sw]` line is stamped
    with - computed here rather than read from a log.

    The shim publishes its pad_ms() origin, and qemu-user runs on this same
    host, so the guest clock and CLOCK_MONOTONIC here are the SAME counter with
    a different zero. Truncated to 32 bits exactly as the shim's own arithmetic
    is, so the two agree even across the wrap. Returns None before the shim has
    published (the block exists from the moment padglhost opens it, which is
    ahead of the guest's first SPI transfer).
    """
    t0 = struct.unpack_from("<I", m, OFF_GUEST_T0)[0]
    if not t0:
        return None
    return ((time.monotonic_ns() // 1000000) - t0) & 0xFFFFFFFF


def bump(m):
    struct.pack_into("<I", m, OFF_SCR_SRC, _src)   # before the gen, so the
    struct.pack_into("<I", m, OFF_SCR_GEN,         # shim's read order works
                     struct.unpack_from("<I", m, OFF_SCR_GEN)[0] + 1)
    m.flush()


def set_held(m, sw, val):
    """Drive one switch from the script side and publish it."""
    m[OFF_SCR_HELD + sw] = 1 if val else 0
    bump(m)


def take(m, ids):
    """Take ownership of `ids` at their CURRENT merged value, silently.

    Only needed for switches padglhost also holds - the coin door and the
    trough. See the module docstring: without this, writing the value the
    merge already shows produces no edge and therefore no effect.
    """
    changed = False
    for sw in ids:
        want = 1 if m[OFF_MRG + sw] else 0
        if m[OFF_SCR_HELD + sw] != want:
            m[OFF_SCR_HELD + sw] = want
            changed = True
    if changed:
        bump(m)


#: HOW LONG A HELPER WAITS FOR THE GAME TO ACTUALLY BE TOLD, and how long one
#: re-assert gives the shim to run a merge pass. See `set_confirmed`.
CONFIRM_S = float(os.environ.get("PAD_SW_CONFIRM_MS") or 250) / 1000.0
RETRY_S = float(os.environ.get("PAD_SW_RETRY_MS") or 12) / 1000.0


def adopted(m, sw, val):
    """Has the merge taken the level we asked for? The game's own answer."""
    return bool(m[OFF_MRG + sw]) == bool(val)


def merging(m):
    """Is there a guest on the other side that could take a write at all?

    `guest_ms()` is None until the shim has published its clock, which it does
    on the first SPI transfer - so this is "a game is running", and it is the
    difference between a write that was LOST and a write that has nobody to
    read it yet (the window is open, the title has not booted). Only the first
    is worth retrying or reporting.
    """
    return guest_ms(m) is not None


def _wait_adopted(m, sw, want, budget):
    end = time.monotonic() + budget
    while True:
        if adopted(m, sw, want):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.001)


def set_confirmed(m, sw, val, timeout_s=None):
    """Drive one switch AND PROVE THE GAME WAS TOLD. True / False / None.

    ★ PAD-186, DRAGONRR: "if I click Drain with no timer running it allows me
    but the game doesn't end." A click the window ACCEPTS and the game never
    sees looks exactly like that, and until this existed every helper here
    printed its success line from the value it had written rather than from
    the value the game was handed.

    THE FAULT IS `take()` AND THE WRITE AFTER IT COLLAPSING INTO NOTHING.
    The shim merges by LAST EDGE WINS: it diffs scr_held[] against the snapshot
    it took on its own previous pass, so only a CHANGE moves the answer. take()
    exists to make the write after it a change - it copies the merged value
    into scr_held first. But the pair is `1 -> 0 -> 1`, and if no merge pass
    lands in between, the shim compares 1 against a snapshot of 1, finds no
    edge, and the drain is silently gone. padsw.h's own example is the state
    that starts it: padglhost latches the six trough balls on at window open,
    so mrg[] and scr_held[] disagree from the first frame, and a drain that
    collapses leaves them disagreeing - so the NEXT click can collapse too.
    That is the "it doesn't always take the drain click" half of his report.

    THE ANSWER IS TO READ BACK THE MERGE, which is published for exactly this
    kind of question, rather than to invent a handshake the block does not
    have (mrg_gen deliberately does not move for a take). If the level has not
    been adopted, re-assert it as a pair the shim cannot collapse - the
    opposite level, a beat for one merge pass, then the level we meant - and
    try again until the deadline. The opposite level is HARMLESS precisely
    when this is needed: it is what the merge is already showing, so it moves
    nothing the game can see.

    Returns True when the game has it, False when it never took it (the caller
    should say so rather than claim success), and None when there is no guest
    to take it - a dry window, where "unconfirmed" is not a fault.
    """
    want = 1 if val else 0
    set_held(m, sw, want)
    if not merging(m):
        return None
    end = time.monotonic() + (CONFIRM_S if timeout_s is None else timeout_s)
    while True:
        left = end - time.monotonic()
        if _wait_adopted(m, sw, want, max(0.0, min(RETRY_S, left))):
            return True
        if time.monotonic() >= end:
            return False
        set_held(m, sw, 1 - want)    # an edge the shim cannot have snapshotted
        time.sleep(RETRY_S)          # one merge pass later...
        set_held(m, sw, want)        # ...and the level we actually meant


def spinning(m, sw):
    """Is `sw` being ripped right now (item 26)?"""
    return m[OFF_SPIN + sw]


def set_cab(m, name, val):
    """Hold or release one of the boot menu's buttons BY NAME (item: first-run
    keys). Its own byte in the scripts' half of the cabinet region - no take(),
    no generation: the only reader is the menu, which polls it, and nothing
    merges it, so there is no edge to lose and no stuck level to inherit
    except our own, which the callers release on EOF."""
    m[OFF_SCR_CAB + CAB_NAMES.index(name)] = 1 if val else 0
    m.flush()


def speed(m):
    """The game's speed in effect (PAD-484): how many game seconds pass per real
    one. 1.0 until padspeed.py asks for another and the shim takes it up - and
    on a block an older renderer made, where the field reads zero."""
    v = struct.unpack_from("<I", m, OFF_SPEED_NOW)[0]
    return v / 1000.0 if v else 1.0


def game_sleep(m, secs):
    """Sleep `secs` of the GAME's time. Every helper that models a physical
    time - a button held, a ball rolling down a lane, a coil's pulse settling -
    waits through this, so at 4x the game sees the same 150 ms press it sees at
    1x rather than a 600 ms one (which on a service button is an auto-repeat)."""
    time.sleep(secs / speed(m))


class GameClock:
    """Seconds of the GAME's time, for a helper that keeps time across many
    looks at the wire (ballfeed.py). It advances by the speed in effect at each
    look, so at 1x it IS time.monotonic() - it starts there, and a helper's
    zeros and comparisons mean what they always did."""

    def __init__(self, m):
        self.m = m
        self.real = time.monotonic()
        self.game = self.real

    def now(self):
        r = time.monotonic()
        self.game += (r - self.real) * speed(self.m)
        self.real = r
        return self.game


def request_speed(m, k):
    """Ask the shim for game speed `k` (4 = four game seconds a real one; 0.5 is
    slow motion; 1 is real time). It is taken up at the game's next clock read;
    speed() says when it has been."""
    struct.pack_into("<I", m, OFF_SPEED_REQ, max(0, int(round(k * 1000))))
    m.flush()


def request_pause(m):
    """Pause or resume the game, as the game window's Pause key does (PAD-204).
    One press = one step of the counter padglhost polls; it toggles once per
    step it has not seen. Nothing to release: a press is not a hold."""
    struct.pack_into("<I", m, OFF_PAUSE_REQ,
                     (struct.unpack_from("<I", m, OFF_PAUSE_REQ)[0] + 1) & 0xFFFFFFFF)
    m.flush()


def set_spin(m, sw, val):
    """Start or stop RIPPING one switch (item 26).

    Not a hold and not an edge: the shim alternates the level it reports on
    each scan of this switch's node while the flag is set, which is the maximum
    closure rate the diffed 0x11 scan can carry. No take() and no scr_held[] -
    the rip has its own single-writer region and never touches the merge, so
    clearing the flag leaves the switch OPEN by construction.
    """
    m[OFF_SPIN + sw] = 1 if val else 0
    struct.pack_into("<I", m, OFF_SPIN_GEN,
                     struct.unpack_from("<I", m, OFF_SPIN_GEN)[0] + 1)
    m.flush()


class Confirmer:
    """`set_confirmed` for a helper that cannot stop and wait (PAD-1306).

    swkeys.py and padlink.py take a flipper edge down a pipe and must be
    ready for the next one at once, so a 250 ms wait per edge is out. This
    is the same discipline as a state machine: `set()` writes the level
    (take-then-set, as before) and remembers it; `tick()`, called often,
    reads the merge back, and while the game has not taken the level it
    writes the opposite level for one merge pass and then the level again,
    until CONFIRM_S has gone by. A switch lost to a collapsed take, a torn
    read or a write the shim snapshotted as its baseline is put right within
    a few passes instead of leaving the game a ball short of the table.

    BEFORE THE GAME IS UP (no guest clock yet) a write still goes into
    scr_held, as it always did, but its check waits: the deadline starts
    the moment the shim publishes its clock, so a trough a table set at
    Init is checked against the game's first passes rather than given up
    on before the game ran. A PAUSED game (padglhost's `paused`) runs no
    merge pass either: checks wait for it to run again, which is also the
    one case where a take-then-set is lost every time. A NEW guest clock (the game restarted under the
    helper) checks every level held again, for the same reason.

    `lost` counts the levels the game never took by the deadline, `again`
    the re-asserts it took to get the rest; `on_lost(sw, level)` is told of
    each loss so the helper can say so."""

    def __init__(self, m, confirm_s=None, retry_s=None, clock=time.monotonic, on_lost=None):
        self.m = m
        self.confirm_s = CONFIRM_S if confirm_s is None else confirm_s
        self.retry_s = RETRY_S if retry_s is None else retry_s
        self.clock = clock
        self.on_lost = on_lost
        self.held = {}          # sw -> the level this helper means
        self.wait = {}          # sw -> [deadline or None, next look, flipped]
        self.lost = 0
        self.again = 0
        self._t0 = None

    def _guest(self):
        return struct.unpack_from("<I", self.m, OFF_GUEST_T0)[0]

    def set(self, sw, val):
        want = 1 if val else 0
        take(self.m, (sw,))
        set_held(self.m, sw, want)
        self.held[sw] = want
        now = self.clock()
        self.wait[sw] = [now + self.confirm_s if self._guest() else None,
                         now + self.retry_s, False]

    def pending(self):
        return len(self.wait)

    def tick(self):
        t0 = self._guest()
        if not t0:
            return
        now = self.clock()
        if t0 != self._t0:
            if self._t0 is not None:        # the game restarted: check them all again
                for sw in self.held:
                    self.wait.setdefault(sw, [None, now, False])
            self._t0 = t0
        if struct.unpack_from("<I", self.m, OFF_PAUSED)[0]:
            # FROZEN (Pause / F9): no merge pass runs, so nothing can be taken
            # and a re-assert now would collapse like the write it repairs.
            # Each check starts again, deadline and all, once the game runs;
            # any flip in flight is put back to the level meant first.
            for sw, st in self.wait.items():
                if st[2]:
                    set_held(self.m, sw, self.held[sw])
                st[0], st[2] = None, False
            return
        for sw, st in list(self.wait.items()):
            want = self.held[sw]
            if st[0] is None:               # written before the game was up
                st[0], st[1] = now + self.confirm_s, now
            if st[2]:                       # the opposite level had its pass
                if now >= st[1]:
                    set_held(self.m, sw, want)
                    st[1], st[2] = now + self.retry_s, False
                continue
            if adopted(self.m, sw, want):
                del self.wait[sw]
                continue
            if now >= st[0]:
                del self.wait[sw]
                self.lost += 1
                if self.on_lost:
                    self.on_lost(sw, want)
                continue
            if now >= st[1]:
                # what the merge already shows, so the game sees nothing move
                set_held(self.m, sw, 1 - want)
                self.again += 1
                st[1], st[2] = now + self.retry_s, True

    def release(self):
        """Open everything still held closed (the helper's EOF)."""
        for sw, val in self.held.items():
            if val:
                set_held(self.m, sw, 0)
        self.held.clear()
        self.wait.clear()
