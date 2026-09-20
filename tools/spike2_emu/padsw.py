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
SIZE = OFF_SCR_CAB + CAB_N           # 1084, in a 4096-byte block


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
