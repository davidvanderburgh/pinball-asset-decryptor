#!/usr/bin/env python3
"""QEMU=qemu-arm-static padsw_test.py ROOT BIN T TABLES [FONT]

Drives codeselect --input padsw the way padglhost does: a 4096-byte padsw
file (magic 'PADS', gen at 4, held[] at 8), RIGHT held for 100 ms then
released, then START held. Expects '[select] key: right', '[select] chose 1'
and a choice file holding 1 (highlight started at 0).

A second, silent run presses the ACTION button (the one on the lockdown bar,
node 1 bit 2 - Space in the rig) instead of START and must reach the same
place: RIGHT moves the highlight to 1, ACTION confirms it, the log line reads
'[select] key: action' (never 'key: start'), and the choice file holds 1.

Then the two ways the Action button can be ABSENT, which is where a menu can
confirm itself. With no switch table the selector has only the platform ids,
and platform id 34 is COIN DOOR INTERLOCK - a switch a shut door holds MADE -
on seven of the 31 cached lists. So: a table-less run with id 34 made, and
then re-made mid-run, must NOT confirm and must sit out its whole countdown,
while the same edge on id 36 (START's platform id) still does confirm - the
positive control that keeps the first check from passing vacuously. And the
footer, which both the live menu and --snapshot now log verbatim, must name
START alone wherever no Action button is resolved.

The sound path is exercised the way the rig's player would see it: the test
creates the FIFO and holds its read end open (non-blocking) before the
selector starts, and the selector runs with --audio fifo:<that> and
--audio-fmt. Checks: the fmt file says '44100 2'; nothing but silence flows
before RIGHT; the move sound follows RIGHT; the confirm sound follows START
and the program only exits once it has played (>= 0.9 s for a 1.0 s WAV);
the --audio-dump holds the same non-silent mix. A second run with a FIFO
that does not exist still exits 0 in the countdown time. A third run loses
its reader mid-way (the read end is closed, as the rig's relay does when its
Windows player dies, and the fmt file is removed, as a restarted playaudio.sh
does) and gets it back 4 s later: the loss and the 3 s gap are logged, the
fmt file is rewritten, the selector reconnects and drops only the gap.

The emulator comes from the environment ($QEMU, exported by the Makefile),
not argv: the rig's teardown does pkill -f 'arm-binfmt|qemu-arm' and this
script's own command line must not match it."""
import os
import re
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkmedia  # noqa: E402

MAGIC = 0x53444150
OFF_GEN = 4
OFF_HELD = 8


def table_ids(path):
    ids = {}
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split(None, 4)
            if len(parts) < 4:
                continue
            sid, _num, node, bit = (int(x) for x in parts[:4])
            ids[(node, bit)] = sid
    return ids


def set_held(path, sid, value):
    with open(path, "r+b") as f:
        f.seek(OFF_HELD + sid)
        f.write(bytes([value]))
        f.seek(OFF_GEN)
        gen = struct.unpack("<I", f.read(4))[0]
        f.seek(OFF_GEN)
        f.write(struct.pack("<I", gen + 1))


class FifoReader(threading.Thread):
    """Drains the FIFO like padrelay would and keeps every chunk with the time
    it arrived, so the test can ask 'was there sound after t?'. drop_end()
    closes the read end (the selector's next write gets EPIPE, as when the
    rig's relay loses its player); take_end() opens it again."""

    def __init__(self, fd):
        super().__init__(daemon=True)
        self.fd = fd
        self.chunks = []          # (monotonic time, bytes)
        self.stop = False

    def run(self):
        while not self.stop:
            fd = self.fd
            if fd < 0:
                time.sleep(0.005)
                continue
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                time.sleep(0.005)
                continue
            except OSError:         # the end was dropped under this read
                time.sleep(0.005)
                continue
            if data:
                self.chunks.append((time.monotonic(), data))
            else:
                time.sleep(0.005)   # no writer yet / writer gone: EOF-ish

    def drop_end(self):
        fd, self.fd = self.fd, -1
        time.sleep(0.02)            # a read in flight returns first
        os.close(fd)

    def take_end(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    def loud_since(self, t):
        """True when a chunk that arrived after t holds a non-zero sample."""
        return any(any(d) for (ts, d) in self.chunks if ts >= t)

    def total(self):
        return sum(len(d) for _, d in self.chunks)

    def total_since(self, t):
        return sum(len(d) for (ts, d) in self.chunks if ts >= t)


def main():
    root, binp, t, tables = sys.argv[1:5]
    qemu = os.environ.get("QEMU", "qemu-arm-static")
    font = sys.argv[5] if len(sys.argv) > 5 and os.path.isfile(sys.argv[5]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    os.makedirs(t, exist_ok=True)
    media = os.path.join(t, "padsw_media")
    mkmedia.make(media)
    conf = os.path.join(t, "padsw.conf")
    with open(conf, "w") as f:
        f.write("image=p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code|art0.png||\n"
                "image=p7|TMNT 1987|1.59.0 - upscaled cartoon retheme|art1.png|anim1.gif|\n"
                "sound_move=move.wav\nsound_confirm=confirm.wav\nvolume=60\n"
                "default=0\ntimeout=10\n")
    ids = table_ids(tables)
    right = ids.get((8, 24))
    start = ids.get((1, 11))
    action = ids.get((1, 2))            # the lockdown-bar button, whatever it is named
    if right is None or start is None or action is None:
        raise SystemExit("padsw_test: %s has no (8,24)/(1,11)/(1,2) rows" % tables)
    print("padsw_test: ids from %s: right %d start %d action %d" % (tables, right, start, action))

    padsw = os.path.join(t, "padsw")
    with open(padsw, "wb") as f:
        f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
    choice = os.path.join(t, "padsw.choice")
    last = os.path.join(t, "padsw.last")
    fifo = os.path.join(t, "audio.fifo")
    fmt = os.path.join(t, "audio.fmt")
    dump = os.path.join(t, "padsw_mix.raw")
    for p in (choice, last, fifo, fmt, dump):
        if os.path.exists(p):
            os.unlink(p)
    os.mkfifo(fifo)
    rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    reader = FifoReader(rfd)
    reader.start()

    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw.ppm"), "--conf", conf,
           "--input", "padsw", "--padsw", padsw, "--tables", tables, "--timeout", "4",
           "--out", choice, "--last", last, "--log", os.path.join(t, "padsw.log"),
           "--font", font, "--no-invert", "--media", media,
           "--audio", "fifo:" + fifo, "--audio-fmt", fmt, "--audio-dump", dump]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    quiet_before = reader.total()
    quiet_loud = reader.loud_since(0)
    t_right = time.monotonic()
    set_held(padsw, right, 1)
    time.sleep(0.1)
    set_held(padsw, right, 0)
    time.sleep(0.5)
    loud_after_right = reader.loud_since(t_right)
    t_start = time.monotonic()
    set_held(padsw, start, 1)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL codeselect did not exit\n%s\n%s" % (out, err))
    t_exit = time.monotonic()
    time.sleep(0.3)                     # let the reader drain the tail
    reader.stop = True
    reader.join(timeout=2)
    os.close(rfd)
    dt = t_exit - t0
    confirm_wait = t_exit - t_start
    sys.stdout.write(out)
    ok = True
    if proc.returncode != 0:
        print("padsw_test: FAIL exit %d" % proc.returncode)
        ok = False
    got = open(choice).read().strip() if os.path.exists(choice) else None
    if got != "1":
        print("padsw_test: FAIL choice file holds %r, expected '1'" % got)
        ok = False
    for want in ("[select] key: right", "[select] key: start", "[select] chose 1"):
        if want not in out:
            print("padsw_test: FAIL stdout lacks %r" % want)
            ok = False
    if "[select] key: left" in out:
        print("padsw_test: FAIL a spurious left key")
        ok = False
    # --- sound ---
    fmt_got = open(fmt).read().strip() if os.path.exists(fmt) else None
    if fmt_got != "44100 2":
        print("padsw_test: FAIL audio.fmt holds %r, expected '44100 2'" % fmt_got)
        ok = False
    if quiet_before == 0:
        print("padsw_test: FAIL nothing reached the FIFO before RIGHT (silence should stream)")
        ok = False
    if quiet_loud:
        print("padsw_test: FAIL the FIFO was not silent before the first key")
        ok = False
    if not loud_after_right:
        print("padsw_test: FAIL no move sound after RIGHT (%d bytes drained)" % reader.total())
        ok = False
    if not reader.loud_since(t_start):
        print("padsw_test: FAIL no confirm sound after START")
        ok = False
    if confirm_wait < 0.9:
        print("padsw_test: FAIL exited %.2f s after START; the 1.0 s confirm sound must finish first" % confirm_wait)
        ok = False
    if confirm_wait > 4.0:
        print("padsw_test: FAIL exited %.2f s after START (cap is 8 s, expected ~1.2 s)" % confirm_wait)
        ok = False
    mix = open(dump, "rb").read() if os.path.exists(dump) else b""
    if len(mix) < 4 * 44100 or not any(mix):
        print("padsw_test: FAIL the mix dump is missing, short or silent (%d bytes)" % len(mix))
        ok = False
    for want in ("audio: fifo %s open" % fifo, "media: 2 art, 1 anim (4 frames), 0 music, move=y confirm=y",
                 " frames written, ", "start %d action %d" % (start, action)):
        if want not in err:
            print("padsw_test: FAIL log lacks %r" % want)
            ok = False
    if " 0 dropped" not in err:
        print("padsw_test: note: some frames were dropped (the reader thread was slow):",
              [l for l in err.splitlines() if "dropped" in l])
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("padsw_test: OK (right -> highlight 1, start -> chose 1, confirm held exit %.2f s, "
          "%d FIFO bytes, %.1f s, exit 0)" % (confirm_wait, reader.total(), dt))

    # --- the ACTION button confirms exactly as START does ---
    # The lockdown-bar button (node 1 bit 2, Space in the rig). Same move, same
    # confirm, a different name in the log: RIGHT then ACTION must land on
    # image 1, and 'key: start' must never appear.
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)
    with open(padsw, "wb") as f:
        f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw_action.ppm"), "--conf", conf,
           "--input", "padsw", "--padsw", padsw, "--tables", tables, "--timeout", "8",
           "--out", choice, "--last", last, "--log", os.path.join(t, "padsw_action.log"),
           "--font", font, "--no-invert", "--media", media, "--audio", "none", "--default", "0"]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    set_held(padsw, right, 1)
    time.sleep(0.1)
    set_held(padsw, right, 0)
    time.sleep(0.4)
    set_held(padsw, action, 1)          # press and hold, as a thumb does
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL (action) codeselect did not exit\n%s\n%s" % (out, err))
    dt = time.monotonic() - t0
    sys.stdout.write(out)
    ok = True
    if proc.returncode != 0:
        print("padsw_test: FAIL (action) exit %d" % proc.returncode)
        ok = False
    got = open(choice).read().strip() if os.path.exists(choice) else None
    if got != "1":
        print("padsw_test: FAIL (action) choice file holds %r, expected '1'" % got)
        ok = False
    for want in ("[select] key: right", "[select] key: action", "[select] chose 1"):
        if want not in out:
            print("padsw_test: FAIL (action) stdout lacks %r" % want)
            ok = False
    if "[select] key: start" in out:
        print("padsw_test: FAIL (action) the action press was reported as start")
        ok = False
    if dt > 7.0:
        print("padsw_test: FAIL (action) took %.1f s: the countdown expired instead of the button" % dt)
        ok = False
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("padsw_test: OK (action id %d: right -> highlight 1, action -> chose 1, %.1f s, exit 0)"
          % (action, dt))

    # --- how the action id is resolved when the wire is not in the list ---
    # Every switch list on this disk puts the button on node 1 bit 2, so these
    # two are synthetic. First: the wire is absent but the NAME is there, in a
    # spelling no list uses (lower case, collapsed blanks, an '(OPTIONAL)'
    # suffix) - it must resolve, and be marked '(by name)'. The decoys must NOT
    # win: 'TOURNAMENT START BUTTON' (26 real lists carry one) must not become
    # START, and 'ACTION BUTTON TARGET' must not become ACTION - both would
    # match a substring rule. Second: no wire and no name at all (the beatles
    # case) leaves the id at -1 rather than at the platform 34, which on that
    # very title is the START button.
    def ids_line(name, rows, timeout="1"):
        path = os.path.join(t, name)
        with open(path, "w") as f:
            f.write("# id   num   node  bit  name\n" + rows)
        p = subprocess.Popen([qemu, "-L", root, binp, "--headless", os.path.join(t, name + ".ppm"),
                              "--conf", conf, "--input", "padsw",
                              "--padsw", os.path.join(t, "no_such_padsw"), "--tables", path,
                              "--timeout", timeout, "--out", choice, "--last", last,
                              "--log", os.path.join(t, name + ".log"), "--font", font,
                              "--no-invert", "--media", media, "--audio", "none"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        o, e = p.communicate(timeout=20)
        marker = "padsw: ids from %s:" % path
        for line in e.splitlines():
            i = line.find(marker)
            if i >= 0:
                return line[i + len(marker):].strip()
        raise SystemExit("padsw_test: FAIL (%s) no ids line\n%s" % (name, e))

    got = ids_line("byname.txt",
                   "1    0    8   25   LEFT FLIPPER BUTTON\n"
                   "2    0    8   24   RIGHT FLIPPER BUTTON\n"
                   "3    0    1   11   START BUTTON\n"
                   "4    0    1   12   TOURNAMENT START BUTTON\n"
                   "5    0    1   13   ACTION BUTTON TARGET\n"
                   "7    0    1   30   lockdown   button   (OPTIONAL)\n"
                   "8    0    0    8   SERVICE SELECT\n")
    want = "left 1 right 2 start 3 action 7 (by name) select 8 plus 26 minus 27 back 28"
    if got != want:
        raise SystemExit("padsw_test: FAIL (by name) ids line is %r,\n"
                         "                              expected %r" % (got, want))
    print("padsw_test: OK (a list without the wire resolves the action button by name: %s)" % got)

    got = ids_line("noaction.txt",
                   "1    0    8   25   LEFT FLIPPER BUTTON\n"
                   "3    0    1   11   START BUTTON\n"
                   "4    0    1   12   TOURNAMENT START BUTTON\n")
    if " action -1 " not in got + " ":
        raise SystemExit("padsw_test: FAIL (no action) ids line is %r; a list with no lockdown "
                         "row must leave the action id unset, not at the platform 34" % got)
    if "start 3" not in got:
        raise SystemExit("padsw_test: FAIL (no action) START was lost: %r" % got)
    print("padsw_test: OK (a list with no lockdown row leaves it unset: %s)" % got)

    # --- THE PHANTOM ACTION: a table-less menu must not confirm itself ---
    # Platform id 34 - what padglhost publishes for the Action button before any
    # switch list resolves - is COIN DOOR INTERLOCK (node 0 bit 23) on seven of
    # the 31 cached lists: aerosmith_le, avengers_infinity_le, foo_fighters_le,
    # guardians_le, iron_maiden_le, mando_le, rush_le. A shut coin door holds
    # that switch MADE and padglhost latches it at window open, so a menu that
    # read id 34 with no table read a switch nobody touched as an ACTION press.
    #
    # Both ways it can present are driven here: held from before the selector
    # starts (the latch), and 0 -> 1 while it runs (padglhost re-resolving the
    # door from platform id 33 onto this title's id 34 mid-menu, which is what
    # actually fired - a switch already made when the first sample lands sets
    # the debouncer's first settled level and raises no edge).
    #
    # The POSITIVE CONTROL is the same scenario on id 36, START's platform id,
    # which must still confirm: without it a run that simply ignores the padsw
    # file would pass this test.
    def phantom_run(name, sid, timeout="4"):
        for p in (choice, last):
            if os.path.exists(p):
                os.unlink(p)
        sw = os.path.join(t, name + ".padsw")
        with open(sw, "wb") as f:
            f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
        with open(sw, "r+b") as f:            # made before the selector starts
            f.seek(OFF_HELD + sid)
            f.write(b"\x01")
        missing = os.path.join(t, "no_such_table_dir", "switch_list.txt")
        p = subprocess.Popen([qemu, "-L", root, binp, "--headless",
                              os.path.join(t, name + ".ppm"), "--conf", conf,
                              "--input", "padsw", "--padsw", sw, "--tables", missing,
                              "--timeout", timeout, "--out", choice, "--last", last,
                              "--log", os.path.join(t, name + ".log"), "--font", font,
                              "--no-invert", "--media", media, "--audio", "none",
                              "--default", "0"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        t0 = time.monotonic()
        time.sleep(1.2)                       # past the first settled samples
        set_held(sw, sid, 0)                  # ...and now a rising edge on it
        time.sleep(0.3)
        set_held(sw, sid, 1)
        try:
            o, e = p.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            p.kill()
            o, e = p.communicate()
            raise SystemExit("padsw_test: FAIL (%s) codeselect did not exit\n%s\n%s" % (name, o, e))
        return p.returncode, o, e, time.monotonic() - t0

    rc, o, e, dt = phantom_run("phantom34", 34)
    if "no switch table" not in e:
        raise SystemExit("padsw_test: FAIL (phantom) the run found a table after all:\n%s" % e)
    if "[select] key: action" in o:
        raise SystemExit("padsw_test: FAIL (phantom) a coin door held closed was read as an "
                         "ACTION press with no switch table:\n%s" % o)
    if "[select] key:" in o:
        raise SystemExit("padsw_test: FAIL (phantom) some key fired off id 34:\n%s" % o)
    if "countdown expired" not in e:
        raise SystemExit("padsw_test: FAIL (phantom) the menu ended before its countdown "
                         "(%.1f s), so something confirmed it:\n%s" % (dt, e))
    if rc != 0 or "[select] chose 0" not in o:
        raise SystemExit("padsw_test: FAIL (phantom) exit %d\n%s" % (rc, o))
    if dt < 3.5:
        raise SystemExit("padsw_test: FAIL (phantom) exited after only %.1f s of a 4 s "
                         "countdown" % dt)
    print("padsw_test: OK (no table + id 34 made and then re-made: no action, the countdown "
          "chose 0 after %.1f s)" % dt)

    rc, o, e, dt = phantom_run("control36", 36)
    if "[select] key: start" not in o or "[select] chose 0" not in o:
        raise SystemExit("padsw_test: FAIL (control) id 36 did NOT confirm with no table, so "
                         "the phantom test above proves nothing:\n%s\n%s" % (o, e))
    if "countdown expired" in e:
        raise SystemExit("padsw_test: FAIL (control) the countdown chose it, not the key:\n%s" % e)
    print("padsw_test: OK (positive control: the same edge on id 36 DOES confirm, %.1f s)" % dt)

    # --- the footer names only the buttons that exist ---
    # Both the live menu and --snapshot log the footer they drew, so the string
    # is checkable without reading pixels. With the Action button unresolved the
    # footer must say START alone: naming a button nothing is wired to is the
    # defect, whether it comes from a list that has no lockdown row (beatles) or
    # from a menu that has no list at all.
    FOOT_ACTION = "LEFT / RIGHT FLIPPER: choose      START or ACTION: boot"
    FOOT_START = "LEFT / RIGHT FLIPPER: choose      START: boot"

    def footer_of(name, table, input_="padsw"):
        p = subprocess.Popen([qemu, "-L", root, binp, "--snapshot",
                              os.path.join(t, name + ".ppm"), "--conf", conf,
                              "--input", input_, "--tables", table, "--timeout", "1",
                              "--log", os.path.join(t, name + ".log"), "--font", font,
                              "--no-invert", "--media", media],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        o, e = p.communicate(timeout=25)
        m = re.search(r'footer "([^"]*)"', o + e)
        if not m:
            raise SystemExit("padsw_test: FAIL (%s) no footer in the log\n%s\n%s" % (name, o, e))
        return m.group(1)

    got = footer_of("foot_yes", tables)
    if got != FOOT_ACTION:
        raise SystemExit("padsw_test: FAIL (footer) a list WITH a lockdown row drew %r,\n"
                         "                          expected %r" % (got, FOOT_ACTION))
    got = footer_of("foot_no", os.path.join(t, "noaction.txt"))
    if got != FOOT_START:
        raise SystemExit("padsw_test: FAIL (footer) a list with NO lockdown row drew %r,\n"
                         "                          expected %r" % (got, FOOT_START))
    got = footer_of("foot_none", os.path.join(t, "no_such_table_dir", "switch_list.txt"))
    if got != FOOT_START:
        raise SystemExit("padsw_test: FAIL (footer) a menu with NO list at all drew %r,\n"
                         "                          expected %r" % (got, FOOT_START))
    got = footer_of("foot_hw", os.path.join(t, "no_such_table_dir", "switch_list.txt"), "hw")
    if got != FOOT_ACTION:
        raise SystemExit("padsw_test: FAIL (footer) --input hw reads node 1 bit 2 off the wire, "
                         "so it must still promise ACTION; drew %r" % got)
    print("padsw_test: OK (footer: named ACTION only where one is resolved, START alone "
          "otherwise, and always on --input hw)")

    # the LIVE menu logs it too (the '[select] menu: ...' line, on stdout), so
    # the table-less control run above drew the honest footer as well
    if 'footer "%s"' % FOOT_START not in o + e:
        raise SystemExit("padsw_test: FAIL (footer) the live table-less run drew %r" %
                         (re.search(r'footer "([^"]*)"', o + e),))

    # --- a switch list that CHANGES on disk is re-read ---
    # The list used to be latched on the first successful parse and never looked
    # at again, which loses the race padglhost already handles: mktables repairs
    # a partly-derived list about a second into a run. Here the list starts with
    # no lockdown row (so the Action button is unresolved and the footer says
    # START alone) and gains one mid-menu. The selector must notice the new
    # mtime, re-resolve, repaint the footer - and then actually accept a press
    # on the id it just learned.
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)
    live = os.path.join(t, "live_table.txt")
    with open(live, "w") as f:
        f.write("# id   num   node  bit  name\n"
                "1    0    8   25   LEFT FLIPPER BUTTON\n"
                "2    0    8   24   RIGHT FLIPPER BUTTON\n"
                "3    0    1   11   START BUTTON\n")
    sw = os.path.join(t, "live.padsw")
    with open(sw, "wb") as f:
        f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
    proc = subprocess.Popen([qemu, "-L", root, binp, "--headless",
                             os.path.join(t, "live.ppm"), "--conf", conf, "--input", "padsw",
                             "--padsw", sw, "--tables", live, "--timeout", "12",
                             "--out", choice, "--last", last,
                             "--log", os.path.join(t, "live.log"), "--font", font,
                             "--no-invert", "--media", media, "--audio", "none", "--default", "0"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t0 = time.monotonic()
    time.sleep(1.5)
    with open(live, "a") as f:          # mktables filling in what it now knows
        f.write("9    0    1    2   Action Button\n")
    time.sleep(3.0)                     # the re-stat runs every 2 s
    set_held(sw, 9, 1)
    try:
        o, e = proc.communicate(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        o, e = proc.communicate()
        raise SystemExit("padsw_test: FAIL (reread) codeselect did not exit\n%s\n%s" % (o, e))
    dt = time.monotonic() - t0
    if "changed on disk; ids re-resolved" not in e:
        raise SystemExit("padsw_test: FAIL (reread) the list grew a lockdown row and the "
                         "selector never re-read it:\n%s" % e)
    if "action 9" not in e:
        raise SystemExit("padsw_test: FAIL (reread) the re-read did not pick up action 9:\n%s" % e)
    if "footer: ACTION button resolved" not in e:
        raise SystemExit("padsw_test: FAIL (reread) the footer was not repainted:\n%s" % e)
    if 'footer "%s"' % FOOT_START not in o + e:
        raise SystemExit("padsw_test: FAIL (reread) the menu opened promising an ACTION button "
                         "it had not resolved:\n%s" % o)
    if "[select] key: action" not in o or "[select] chose 0" not in o:
        raise SystemExit("padsw_test: FAIL (reread) the re-resolved id did not confirm:\n%s" % o)
    if "countdown expired" in e:
        raise SystemExit("padsw_test: FAIL (reread) the countdown chose it, not the button:\n%s" % e)
    print("padsw_test: OK (a list that gains a lockdown row mid-run is re-read: action 9 "
          "resolved, footer repainted, press accepted, %.1f s)" % dt)

    # --- a FIFO that does not exist: still exits 0 on the countdown ---
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)
    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw2.ppm"), "--conf", conf,
           "--input", "none", "--timeout", "1", "--out", choice, "--last", last,
           "--log", os.path.join(t, "padsw2.log"), "--font", font, "--no-invert", "--media", media,
           "--audio", "fifo:/nonexistent/dir/audio.fifo", "--audio-fmt", os.path.join(t, "audio2.fmt")]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL (no fifo) codeselect did not exit")
    dt = time.monotonic() - t0
    if proc.returncode != 0 or "[select] chose 0" not in out:
        sys.stderr.write(err)
        raise SystemExit("padsw_test: FAIL (no fifo) exit %d\n%s" % (proc.returncode, out))
    if "audio: fifo /nonexistent/dir/audio.fifo: " not in err:
        sys.stderr.write(err)
        raise SystemExit("padsw_test: FAIL (no fifo) the missing FIFO was not logged")
    print("padsw_test: OK (missing fifo: chose 0 on the countdown, %.1f s, exit 0)" % dt)

    # --- the reader goes away and comes back: EPIPE, ENXIO retries, reopen ---
    # What happened in the rig on 2026-09-02: the relay closed the read end
    # when its Windows player died 31 s in (and there, nothing ever reopened
    # it). Here it comes back after 4 s. The selector must log the loss once,
    # name the 3 s gap, keep the fmt file alive (a restarted playaudio.sh
    # removes it and waits for a fresh one), reconnect within its 100 ms
    # retry, and drop only the gap.
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)
    fifo3 = os.path.join(t, "audio3.fifo")
    fmt3 = os.path.join(t, "audio3.fmt")
    for p in (fifo3, fmt3):
        if os.path.exists(p):
            os.unlink(p)
    os.mkfifo(fifo3)
    reader = FifoReader(os.open(fifo3, os.O_RDONLY | os.O_NONBLOCK))
    reader.start()
    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw3.ppm"), "--conf", conf,
           "--input", "none", "--timeout", "7", "--out", choice, "--last", last,
           "--log", os.path.join(t, "padsw3.log"), "--font", font, "--no-invert", "--media", media,
           "--audio", "fifo:" + fifo3, "--audio-fmt", fmt3]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    had_before = reader.total()
    reader.drop_end()                   # the relay's player died
    t_lost = time.monotonic()
    time.sleep(0.3)
    os.unlink(fmt3)                     # a restarted playaudio.sh's rm -f
    time.sleep(3.7)                     # 4 s without a reader in all
    fmt_back = open(fmt3).read().strip() if os.path.exists(fmt3) else None
    reader.take_end(fifo3)              # a fresh player attached: the relay reopened
    t_back = time.monotonic()
    try:
        out, err = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL (reader loss) codeselect did not exit\n%s\n%s" % (out, err))
    time.sleep(0.3)
    reader.stop = True
    reader.join(timeout=2)
    os.close(reader.fd)
    gap = t_back - t_lost
    ok = True
    if proc.returncode != 0 or "[select] chose 0" not in out:
        print("padsw_test: FAIL (reader loss) exit %d\n%s" % (proc.returncode, out))
        ok = False
    if had_before == 0:
        print("padsw_test: FAIL (reader loss) nothing flowed before the drop")
        ok = False
    if err.count("audio: fifo reader went away, reopening") != 1:
        print("padsw_test: FAIL (reader loss) the loss was not logged exactly once")
        ok = False
    if err.count("audio: fifo %s open" % fifo3) != 2:
        print("padsw_test: FAIL (reader loss) expected two opens (start, and after the reader came back)")
        ok = False
    if "audio: fifo %s open again after" % fifo3 not in err:
        print("padsw_test: FAIL (reader loss) the reopen was not logged as one")
        ok = False
    if "audio: no fifo reader for 3 s (it went away" not in err:
        print("padsw_test: FAIL (reader loss) the 3 s gap was not named")
        ok = False
    if fmt_back != "44100 2":
        print("padsw_test: FAIL (reader loss) the removed fmt file was not rewritten (holds %r)" % fmt_back)
        ok = False
    if "(rewritten: it had been removed)" not in err:
        print("padsw_test: FAIL (reader loss) the fmt rewrite was not logged")
        ok = False
    after = reader.total_since(t_back)
    if after < 4 * 44100:               # >= 1 s of audio once the reader was back
        print("padsw_test: FAIL (reader loss) only %d bytes reached the reader after it came back" % after)
        ok = False
    if not reader.loud_since(t_back):
        print("padsw_test: FAIL (reader loss) no confirm sound after the reader came back")
        ok = False
    m = re.search(r"audio: (\d+) frames written, (\d+) dropped", err)
    written, dropped = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
    lo, hi = int(gap * 44100 * 0.8), int((gap + 1.0) * 44100)
    if not lo <= dropped <= hi:
        print("padsw_test: FAIL (reader loss) %d frames dropped for a %.1f s gap (expected %d..%d)"
              % (dropped, gap, lo, hi))
        ok = False
    if written < 3 * 44100:
        print("padsw_test: FAIL (reader loss) only %d frames written" % written)
        ok = False
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("padsw_test: OK (reader loss: EPIPE at %.1f s, %.1f s without a reader, reconnected, "
          "%d frames dropped = %.2f s, %d bytes after, %.1f s, exit 0)"
          % (t_lost - t0, gap, dropped, dropped / 44100.0, after, time.monotonic() - t0))


if __name__ == "__main__":
    main()
