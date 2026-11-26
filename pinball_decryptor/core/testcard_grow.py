"""Grow a PAD test card or multi-boot card over the network to fill its SD card, keeping its files.

Simon (2026-11-22): "when updating on the network ... the user can grow their write as much as they want (or should
be able to) within the limits of their SD card", and the card "can be grown remotely but will require reboots".

A test card and a multi-boot card are both p1 boot, p2 system, p3 /games (the test files, or the games), then the
extended p4 holding p5 (/data) and p6 (/dump), all packed at the front of the SD card.  Growing it:

1. Over the network (this module, on the running machine): /data and /dump are saved onto the system partition, a
   start-up script and its expected layout go beside them, and the new partition table is written - p1 and p2
   untouched, p3 from where it starts to near the card's end, p5 and p6 (their own sizes) moved to the very end.
   The running kernel keeps the old table until the machine restarts, which it then does.
2. At the next start-up, before the card's partitions are checked or mounted (``S02zz_padgrow``, after S02sysfs
   and before S02zzz_checkfs): only when the kernel shows the grown table, p3's file system is checked and enlarged
   to fill its partition (its files stay), p5 and p6 get fresh file systems and /data and /dump their files back;
   the script, the tools and the saved copies go.

Simon (2026-11-26): "all tests should be done via network updates" - so a card keeps its games and test files
while it grows, and a multi-boot card can grow too.  The machine has no resize2fs and an e2fsck from 2013, so PAD
carries both (resources/remote/padgrow, built by installer/build_machine_e2fsprogs.sh); they go onto the machine
for the one start-up and are removed with the rest.

/data holds the machine's remote access identity (/data/dropbear), so it must come back whole, or the next
connection would find a different machine.  The Send's own records of /games (/data/pad) stay true: its files
are the same.
"""

import contextlib
import os
import struct
import time

from . import remote_send as rs

SECTOR = 512
ALIGN = 2048                    # 1 MiB, as every partition of a test card starts (mkmulticard ALIGN)
HEADS, SPT = 4, 32              # the CHS geometry mkmulticard writes the table with
GROW_DIR = "/usr/local/padgrow"
BOOT_SCRIPT_PATH = "/etc/rcS.d/S02zz_padgrow"
LOG_ON_DATA = "/data/pad/padgrow.log"
#: what has to be on the system partition beside the saved /data and /dump
SPARE = 16 << 20
#: a grow worth a restart: less than this and the card already fills its SD card
MIN_GAIN = 256 << 20
#: how long the machine may take to come back after its restart (enlarging a 6 GB /games to 230 GB, the check
#: included, is a few minutes on the machine's SD card)
BACK_WITHIN = 1500
#: the tools the start-up uses, shipped with PAD (static ARM builds of e2fsprogs)
TOOLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "remote", "padgrow")
TOOLS = ("resize2fs", "e2fsck")


class GrowError(rs.SendError):
    pass


# ---- the new table ---------------------------------------------------------------------------------------------
def _chs(lba):
    c, r = divmod(lba, HEADS * SPT)
    h, s = divmod(r, SPT)
    s += 1
    if c > 1023:
        c, h, s = 1023, HEADS - 1, SPT
    return bytes((h, (s & 0x3f) | ((c >> 2) & 0xc0), c & 0xff))


def _entry(ptype, start, count, chs_base=0):
    a = chs_base + start
    return bytes((0,)) + _chs(a) + bytes((ptype,)) + _chs(a + count - 1) + struct.pack("<II", start, count)


def _down(x):
    return x // ALIGN * ALIGN


class Plan(object):
    """The grown layout: ``sectors`` = [(LBA, 512 bytes)] to write (the EBRs first, the MBR last), ``expect`` =
    {partition: (start, sectors)} the machine shows after its restart."""

    def __init__(self, old, card, p3, ext, logs, sectors):
        self.old, self.card, self.p3, self.ext, self.logs, self.sectors = old, card, p3, ext, logs, sectors
        self.expect = {3: p3}
        for n, (_ebr, start, count) in zip((5, 6), logs):
            self.expect[n] = (start, count)

    @property
    def gain(self):
        return (self.p3[1] - self.old[3][1]) * SECTOR

    def conf(self):
        """The start-up script's own check: the table it may format under."""
        return ("P3_START=%d\nP3_SIZE=%d\nP5_START=%d\nP5_SIZE=%d\nP6_START=%d\nP6_SIZE=%d\n"
                % (self.expect[3] + self.expect[5] + self.expect[6]))


def plan(layout, card_sectors, mbr):
    """The grown table for a test card or multi-boot card whose partitions are *layout* (``{n: (start, sectors)}``,
    the machine's own) on an SD card of *card_sectors*, from its current MBR sector *mbr*."""
    mbr = bytes(mbr)
    if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
        raise GrowError("The machine's card has no partition table PAD can read.")
    if sorted(layout) != [1, 2, 3, 4, 5, 6]:
        raise GrowError("The machine's card isn't laid out as a PAD test card or multi-boot card (partitions %s)."
                        % ", ".join(map(str, sorted(layout))))
    types = [mbr[0x1BE + 16 * i + 4] for i in range(4)]
    if types[2] != 0x83 or types[3] not in (0x05, 0x0F):
        raise GrowError("The machine's card isn't laid out as a PAD test card or multi-boot card.")
    p3s, p3c = layout[3]
    p5s, p5c = layout[5]
    p6s, p6c = layout[6]
    if not (layout[2][0] + layout[2][1] <= p3s and p3s + p3c <= p5s < p6s):
        raise GrowError("The machine's card isn't laid out as a PAD test card or multi-boot card.")
    n6 = _down(card_sectors - p6c)
    ebr6 = n6 - ALIGN
    n5 = _down(ebr6 - p5c)
    ext = n5 - ALIGN
    if ext < p6s + p6c or (ext - p3s - p3c) * SECTOR < MIN_GAIN:
        raise GrowError("The card already fills the machine's SD card (%s): there is no room to grow it."
                        % rs._human(card_sectors * SECTOR))
    logs = [(ext, n5, p5c), (ebr6, n6, p6c)]
    new = bytearray(mbr)
    new[0x1BE + 32:0x1FE] = _entry(0x83, p3s, ext - p3s) + _entry(0x0F, ext, n6 + p6c - ext)
    sectors = []
    for i, (ebr, start, count) in enumerate(logs):
        eb = bytearray(SECTOR)
        eb[0x1BE:0x1CE] = _entry(0x83, start - ebr, count, chs_base=ebr)
        if i + 1 < len(logs):
            nebr, nstart, ncount = logs[i + 1]
            eb[0x1CE:0x1DE] = _entry(0x05, nebr - ext, nstart + ncount - nebr, chs_base=ext)
        eb[510:512] = b"\x55\xaa"
        sectors.append((ebr, bytes(eb)))
    sectors.append((0, bytes(new)))
    return Plan(dict(layout), card_sectors, (p3s, ext - p3s), ext, logs, sectors)


# ---- the start-up script ---------------------------------------------------------------------------------------
#: Runs as a program (not sourced: the card's rc sources *.sh), once, early in start-up.  It formats only when the
#: kernel shows exactly the table PAD wrote; a start-up that finds anything else changes nothing.  A failure keeps
#: the script and the saved copies, so the next start-up tries again.
STARTUP = r"""#!/bin/sh
# PAD: the second half of growing this card over the network (Simon, 2026-11-22).  Runs once, before the card's
# partitions are checked and mounted; PAD's Grow wrote it and removes nothing else.
D=@DIR@
[ -f $D/grow.conf ] || exit 0
. $D/grow.conf
part() { cat /sys/block/mmcblk0/mmcblk0p$1/$2 2>/dev/null; }
if [ "$(part 3 start)" != "$P3_START" ] || [ "$(part 3 size)" != "$P3_SIZE" ] || \
   [ "$(part 5 start)" != "$P5_START" ] || [ "$(part 5 size)" != "$P5_SIZE" ] || \
   [ "$(part 6 start)" != "$P6_START" ] || [ "$(part 6 size)" != "$P6_SIZE" ]; then
    echo "padgrow: the card's partitions are not the grown ones: nothing changed"
    exit 0
fi
mount -o remount,rw / || { echo "padgrow: the system partition can't be written: nothing changed"; exit 0; }
say() { echo "padgrow: $*"; echo "$*" >> $D/grow.log; }
say "start-up $(date) - p3 $P3_SIZE sectors"
for n in 3 5 6; do
    if [ ! -b /dev/mmcblk0p$n ]; then
        mm=$(part $n dev)
        mknod /dev/mmcblk0p$n b ${mm%%:*} ${mm##*:} || say "no device for p$n"
    fi
done
ok=1
# /games keeps its files: checked, then enlarged to fill its partition (PAD's own e2fsck and resize2fs; e2fsck
# exit 1 = it fixed something, still fine to enlarge).  Done again at a later start-up it changes nothing.
$D/e2fsck -fy /dev/mmcblk0p3 >> $D/grow.log 2>&1
rc=$?
if [ $rc -le 1 ] && RESIZE2FS_FORCE_LAZY_ITABLE_INIT=1 $D/resize2fs /dev/mmcblk0p3 >> $D/grow.log 2>&1; then
    say "p3 /games enlarged"
else
    ok=0
    say "p3 /games not enlarged (e2fsck $rc)"
fi
for p in "5 /data data" "6 /dump dump"; do
    set -- $p
    if mke2fs -q -F -t ext4 -L $3 /dev/mmcblk0p$1 >> $D/grow.log 2>&1 && mount -t ext4 /dev/mmcblk0p$1 $2; then
        tar -xf $D/$3.tar -C $2 >> $D/grow.log 2>&1 && say "$2 back" || { ok=0; say "$2 not restored"; }
        umount $2
    else
        ok=0
        say "p$1 $2 failed"
    fi
done
if [ $ok = 1 ]; then
    say "done"
    if mount -t ext4 /dev/mmcblk0p5 /data; then
        mkdir -p /data/pad && cp $D/grow.log @LOG@
        umount /data
    fi
    rm -rf $D
    rm -f $0
else
    say "not finished: tried again at the next start-up"
fi
sync
mount -o remount,ro / 2>/dev/null
exit 0
"""


def startup_script():
    return STARTUP.replace("@DIR@", GROW_DIR).replace("@LOG@", LOG_ON_DATA)


# ---- on the machine --------------------------------------------------------------------------------------------
def _is_pad_card(machine):
    """A PAD test card or multi-boot card: its system partition has the boot menu's list (images.conf).  A one-game
    card's partitions are the game's own (Stern's layout), and are left alone."""
    _rc, text = machine.sh("[ -f %s ] && echo PAD_MENU_CARD" % rs.TESTCARD_CONF, check=False)
    return "PAD_MENU_CARD" in (text or "")


def tools():
    """{name: bytes} of the tools the start-up uses; a PAD without them can't grow a card."""
    out = {}
    for name in TOOLS:
        try:
            with open(os.path.join(TOOLS_DIR, name), "rb") as f:
                out[name] = f.read()
        except OSError:
            raise GrowError("This PAD is missing its card-growing tool %s." % name) from None
    return out


def _int(text, what):
    try:
        return int(text.strip().split()[0])
    except (IndexError, ValueError):
        raise GrowError("Couldn't read %s from the machine." % what) from None


def _sectors_hex(machine, lbas):
    _rc, out = machine.sh("\n".join("dd if=/dev/mmcblk0 bs=512 skip=%d count=1 2>/dev/null | "
                                    "hexdump -v -e '/1 \"%%02x\"'; echo" % int(n) for n in lbas))
    lines = [ln.strip() for ln in out.splitlines()]
    if len(lines) < len(lbas):
        raise GrowError("Couldn't read the machine's partition table.")
    try:
        return [bytes.fromhex(ln) for ln in lines[:len(lbas)]]
    except ValueError:
        raise GrowError("Couldn't read the machine's partition table.") from None


def survey(machine):
    """-> (plan, bytes /data and /dump need on the system partition, its free bytes).  Changes nothing."""
    if not _is_pad_card(machine):
        raise GrowError("The machine isn't running a PAD test card or multi-boot card: only those can be grown (a "
                        "one-game card's partitions are the game's).")
    _rc, left = machine.sh("[ -f %s/grow.conf ] && { echo UNFINISHED; tail -n 1 %s/grow.log 2>/dev/null; }; "
                           "[ -f %s ] && echo GROWN" % (GROW_DIR, GROW_DIR, LOG_ON_DATA), check=False)
    if "UNFINISHED" in (left or ""):
        last = [ln for ln in left.splitlines() if ln and ln not in ("UNFINISHED", "GROWN")]
        raise GrowError("A grow of this card is still under way on the machine (%s): restart the machine to "
                        "let its start-up finish it." % (last[0] if last else "its start-up hasn't run yet"))
    _rc, out = machine.sh("cat /sys/block/mmcblk0/size")
    card = _int(out, "the SD card's size")
    try:
        p = plan(machine.layout(), card, _sectors_hex(machine, [0])[0])
    except GrowError as e:
        if "already fills" in str(e) and "GROWN" in (left or ""):
            raise GrowError("This card has been grown already: it fills the machine's SD card.") from None
        raise
    _rc, out = machine.sh("du -sk /data /dump | awk '{s += $1} END {print s}'")
    need = _int(out, "how much /data and /dump hold") * 1024 + SPARE + sum(map(len, tools().values()))
    return p, need, machine.free(rs.ROOT)


def _write_table(machine, sectors):
    blob = b"".join(data for _lba, data in sectors)
    script = ["cat > /run/padgrow.tbl"]
    # the card's BusyBox 1.23 dd has no conv= (a block device is never truncated anyway)
    script += ["dd if=/run/padgrow.tbl of=/dev/mmcblk0 bs=512 skip=%d seek=%d count=1 2>/dev/null || exit 1"
               % (i, lba) for i, (lba, _d) in enumerate(sectors)]
    script += ["sync", "rm -f /run/padgrow.tbl"]
    machine.sh("\n".join(script), stdin=blob)


def prepare(machine, p, log):
    """Step 1 on the running machine: the saved copies and the start-up script, then the table.  A failure before
    the table is written takes everything back off; a table that does not read back as written is put back."""
    log("Saving /data and /dump onto the machine's system partition...", "info")
    files = " ".join(["%s/grow.conf %s/data.tar %s/dump.tar %s" % (GROW_DIR, GROW_DIR, GROW_DIR, BOOT_SCRIPT_PATH)]
                     + ["%s/%s" % (GROW_DIR, name) for name in TOOLS])
    kit = tools()
    try:
        machine.sh("mount -o remount,rw / && rm -rf %s && mkdir -p %s && tar -cf %s/data.tar -C /data . && "
                   "tar -cf %s/dump.tar -C /dump ." % (GROW_DIR, GROW_DIR, GROW_DIR, GROW_DIR), timeout=900)
        machine.sh("cat > %s/grow.conf" % GROW_DIR, stdin=p.conf().encode("ascii"))
        for name in TOOLS:
            machine.sh("cat > %s/%s && chmod 755 %s/%s" % (GROW_DIR, name, GROW_DIR, name), stdin=kit[name],
                       timeout=300)
        machine.sh("cat > %s && chmod 755 %s" % (BOOT_SCRIPT_PATH, BOOT_SCRIPT_PATH),
                   stdin=startup_script().encode("ascii"))
        _rc, out = machine.sh("for f in %s; do [ -s $f ] || echo MISSING $f; done; sync" % files)
        if "MISSING" in out:
            raise GrowError("The machine didn't keep the grow's files (%s)." % out.strip())
    except BaseException:
        machine.sh("rm -rf %s; rm -f %s; sync" % (GROW_DIR, BOOT_SCRIPT_PATH), check=False)
        raise
    log("Writing the grown partition table...", "info")
    lbas = [lba for lba, _d in p.sectors]
    old = _sectors_hex(machine, lbas)
    try:
        _write_table(machine, p.sectors)
        if _sectors_hex(machine, lbas) != [d for _lba, d in p.sectors]:
            raise GrowError("The machine's card didn't take the new partition table; the old one is back and "
                            "nothing else changed.")
    except BaseException:
        # the old table back (only these sectors were touched), then the grow's files off
        with contextlib.suppress(Exception):
            _write_table(machine, list(zip(lbas, old)))
        machine.sh("rm -rf %s; rm -f %s; sync" % (GROW_DIR, BOOT_SCRIPT_PATH), check=False)
        raise
    machine.sh("mount -o remount,ro / 2>/dev/null; sync", check=False)


def check_grown(machine, p):
    """After the restart: the table the machine shows, the start-up's own log, and /games' room now."""
    got = machine.layout()
    wrong = [n for n, want in sorted(p.expect.items()) if tuple(got.get(n, ())[:2]) != tuple(want)]
    if wrong:
        raise GrowError("The machine came back without the grown partitions (p%s); nothing was formatted."
                        % ", p".join(map(str, wrong)))
    _rc, done = machine.sh("cat %s 2>/dev/null" % LOG_ON_DATA, check=False)
    if "done" not in (done or "").split():
        _rc, why = machine.sh("cat %s/grow.log 2>/dev/null" % GROW_DIR, check=False)
        raise GrowError("The machine's start-up didn't finish the grow: %s"
                        % ((why or "").strip().splitlines()[-1:] or ["its start-up script did not run"])[0])
    return machine.free(rs.GAMES)


# ---- the app's run ---------------------------------------------------------------------------------------------
from .pipeline_base import BasePipeline, PipelineError  # noqa: E402

GROW_PHASES = ("Connect", "Prepare", "Restart", "Check")


class GrowPipeline(BasePipeline):
    """Grow the card on the machine at *address*, as one of the app's runs (the Send's log, bar and chips)."""

    def __init__(self, address, log_cb, phase_cb, progress_cb, done_cb, connect_fn=None, sleep=time.sleep,
                 clock=time.monotonic):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.address = address
        self._connect = connect_fn or rs.connect
        self._sleep, self._clock = sleep, clock

    def _run(self):
        self._set_phase(0)
        self._log("Growing the card on the machine at %s..." % self.address, "info")
        try:
            machine = self._connect(self.address)
        except rs.SendError as e:
            raise PipelineError("Connect", str(e)) from None
        try:
            self._set_phase(1)
            p, need, free = survey(machine)
            if need > free:
                raise GrowError("The machine's system partition has %s free, and /data and /dump need %s to be "
                                "kept safe while the card grows." % (rs._human(free), rs._human(need)))
            self._log("The games partition grows from %s to %s (the SD card is %s); its files stay."
                      % (rs._human(p.old[3][1] * SECTOR), rs._human(p.p3[1] * SECTOR),
                         rs._human(p.card * SECTOR)), "info")
            self._check_cancel()
            # PAD-1427 as a Send (David: "a clean isolated update path"): the game is held, its screen saying PAD
            # is updating it, before /data is saved - a game writing its settings meanwhile would be lost
            self._log("Holding the machine's game for the grow (a game being played ends).", "info")
            machine.pause_game()
            try:
                prepare(machine, p, self._log)
            except BaseException:
                # the table is as it was (prepare puts it back): the game back
                with contextlib.suppress(Exception):
                    machine.screen_stopped(False)
                raise
            machine.screen_changing()
            self._set_phase(2)
            self._log("Restarting the machine: its start-up enlarges the games partition and moves /data and "
                      "/dump (a few minutes).", "info")
            machine.reboot()
        except rs.SendError as e:
            raise PipelineError("Grow", str(e)) from None
        finally:
            machine.close()
        machine = self._back()
        try:
            self._set_phase(3)
            room = check_grown(machine, p)
        except rs.SendError as e:
            raise PipelineError("Check", str(e)) from None
        finally:
            machine.close()
        summary = ("The card on the machine is grown: its games partition has %s free, its files as they were."
                   % rs._human(room))
        self._log(summary, "success")
        self._done(True, summary)

    def _back(self):
        self._sleep(20)
        until = self._clock() + BACK_WITHIN
        while True:
            try:
                return self._connect(self.address)
            except rs.SendError:
                if self._cancelled:
                    # the table is written: the machine finishes the grow at its start-up whether PAD waits or not
                    raise PipelineError("Canceled", "Stopped waiting for the machine; it finishes the grow as it "
                                                    "starts up. Grow again later to see that it is done.") from None
                if self._clock() > until:
                    raise PipelineError("Check", "The machine didn't come back on the network after its restart. "
                                                 "Check its screen; once it is up, Grow again: it says whether the "
                                                 "grow finished.") from None
                self._progress(0, 0, "Waiting for the machine to come back")
                self._sleep(10)
