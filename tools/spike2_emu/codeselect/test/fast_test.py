#!/usr/bin/env python3
"""fast_test.py BIN T [FONT] - drives bofselect --input fast (PAD-342) against
the Barrels of Fun emulator's own FAST board model, and one stand-in board.

The board side is tools/bof_emu/bofhw.py with Labyrinth's profile: the same
three USB serial ports a Labyrinth has (the Neuron's NET and expansion ports
and the FAST Audio Controller), its fake sysfs naming them, and the replies
the game's own fast_stem.gd parses - ID:NET, SA: physical levels.  bofselect
is pointed at that rig with PAD_SELECT_FAST_ROOT, so its port search runs as
it does on a machine; the display is a fake framebuffer file.

  1. the search: the NET port is found (ID:NET) and the Audio Controller is
     skipped by its USB product name, without being opened.
  2. buttons: RIGHT flipper (22) -> highlight 1, START (14) -> chose 1, the
     choice file holds 1, exit 0, and nothing but ID:, SA: (and no CH:, the
     board answered) was ever sent: no switch or driver config, so no coil.
  3. the second START: LAUNCH (20, switch_start=14,20) confirms too; LEFT
     (15) wraps 0 -> 1 on a two-image menu.
  4. no board at all: the menu still runs, times out and boots the default -
     a dead button never keeps a machine from booting.
  5. a board that answers SA: only after CH: (a stand-in on a pty): one
     CH:2000,01 is sent after SA: goes unanswered, then the buttons work;
     and a REVERSED button (reads 1 at rest, 0 pressed) still presses,
     because pressed = different from the first reading.
  6. --learn names an unmapped switch (39, the shooter lane) in the log.
  7. the framebuffer: the last frame (LOADING ...) is in the fake fb file,
     centred 1:1 on 1366x768 with the 3-pixel black borders.
"""
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tty

HERE = os.path.dirname(os.path.abspath(__file__))
BOFEMU = os.path.normpath(os.path.join(HERE, "..", "..", "..", "bof_emu"))
PROFILE = os.path.join(BOFEMU, "profiles", "labyrinth.json")

CONF = """image=GDCraze.x86_64|LABYRINTH|Stock code
image=pad_image1.bin|SARAH CODE|A mod
default=0
timeout={timeout}
switch_left=15
switch_right=22
switch_start=14,20
"""


RIGS = []


def fail(msg):
    print("FAIL: " + msg)
    for r in RIGS:
        try:
            print("--- %s/bofhw.log (tail)" % r.root)
            print("".join(open(os.path.join(r.root, "bofhw.log")).readlines()[-25:]))
        except OSError:
            pass
    sys.exit(1)


class Rig:
    """bofhw.py in a rig directory, and its control socket."""

    def __init__(self, root):
        self.root = root
        self.proc = subprocess.Popen([sys.executable, os.path.join(BOFEMU, "bofhw.py"),
                                      "--dir", root, "--profile", PROFILE],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        sock = os.path.join(root, "ctl.sock")
        for _ in range(100):
            if os.path.exists(sock):
                break
            time.sleep(0.05)
        else:
            fail("bofhw.py made no ctl.sock")

    def ctl(self, line):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(os.path.join(self.root, "ctl.sock"))
        s.sendall((line + "\n").encode())
        out = s.recv(65536).decode()
        s.close()
        return out

    def log(self):
        with open(os.path.join(self.root, "bofhw.log")) as f:
            return f.read()

    def stop(self):
        try:
            self.ctl("quit")
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def start_menu(binary, t, name, timeout, font, env_extra, extra=()):
    conf = os.path.join(t, name + ".conf")
    with open(conf, "w") as f:
        f.write(CONF.format(timeout=timeout))
    out = os.path.join(t, name + ".choice")
    log = os.path.join(t, name + ".log")
    fb = os.path.join(t, name + ".fb")
    last = os.path.join(t, name + ".last")      # the menu remembers: every run starts fresh
    for p in (out, log, fb, last):
        if os.path.exists(p):
            os.unlink(p)
    env = dict(os.environ, PAD_SELECT_FAKEFB="1366x768x32:" + fb)
    env.update(env_extra)
    args = [binary, "--input", "fast", "--conf", conf, "--out", out,
            "--last", os.path.join(t, name + ".last"), "--log", log,
            "--audio", "none", "--no-invert"] + list(extra)
    if font:
        args += ["--font", font]
    p = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p, out, log, fb


def wait_log(log, pattern, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if os.path.exists(log):
            with open(log, errors="replace") as f:
                text = f.read()
            if re.search(pattern, text):
                return text
        time.sleep(0.05)
    fail("no %r in %s within %ss:\n%s" % (pattern, log, secs,
                                         open(log).read() if os.path.exists(log) else "(no log)"))


def settled(log):
    """the first reading is the rest level, and the debouncer settles on the
    two after it (input.c): a press inside that first ~75 ms reads as a
    button held at power-up and is not an edge, by design"""
    text = wait_log(log, r"fast: \d+ switches read")
    time.sleep(0.4)
    return text


def finish(p, secs=30):
    try:
        out, _ = p.communicate(timeout=secs)
    except subprocess.TimeoutExpired:
        p.kill()
        fail("the menu did not exit")
    return p.returncode, out


def read_choice(path):
    with open(path) as f:
        return f.read().strip()


class StandIn(threading.Thread):
    """A FAST NET port on a pty that answers SA: only once CH: has come, with
    the START button wired reversed (1 at rest)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.master, self.slave = os.openpty()
        tty.setraw(self.master)
        tty.setraw(self.slave)
        self.path = os.ttyname(self.slave)
        self.levels = [0] * 16
        self.levels[14 // 8] |= 1 << (14 % 8)          # START reversed: 1 at rest
        self.configured = False
        self.got = []
        self.stop = False

    def run(self):
        buf = b""
        while not self.stop:
            try:
                data = os.read(self.master, 4096)
            except OSError:
                time.sleep(0.01)
                continue
            buf += data
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                line = line.decode(errors="replace")
                self.got.append(line)
                if line.startswith("ID:"):
                    os.write(self.master, b"ID:NET FP-CPU-2000  02.25\r")
                elif line.startswith("CH:"):
                    self.configured = True
                    os.write(self.master, b"CH:P\r")
                elif line.startswith("SA:") and self.configured:
                    os.write(self.master, ("SA:80,%s\r" % "".join("%02X" % b for b in self.levels)).encode())

    def press(self, sw, secs=0.2):
        self.levels[sw // 8] ^= 1 << (sw % 8)
        time.sleep(secs)
        self.levels[sw // 8] ^= 1 << (sw % 8)


def main():
    binary, t = sys.argv[1], sys.argv[2]
    font = sys.argv[3] if len(sys.argv) > 3 and os.path.exists(sys.argv[3]) else ""
    os.makedirs(t, exist_ok=True)
    rigdir = tempfile.mkdtemp(prefix="fastrig.", dir=t)
    rig = Rig(rigdir)
    RIGS.append(rig)
    env = {"PAD_SELECT_FAST_ROOT": rigdir}
    try:
        # 1 + 2: the search, RIGHT, START
        p, out, log, fb = start_menu(binary, t, "fast1", 30, font, env)
        text = wait_log(log, r"fast: \d+ switches read")
        time.sleep(0.4)
        if not re.search(r"ttyACM0 is the NET port \(ID:NET", text):
            fail("the NET port was not found as ttyACM0:\n" + text)
        if not re.search(r"ttyACM2 is the Audio Controller, skipped", text):
            fail("the Audio Controller was not skipped by name:\n" + text)
        rig.ctl("tap 22 200")
        wait_log(log, r"key: right")
        rig.ctl("tap 14 200")
        rc, so = finish(p)
        if rc != 0 or read_choice(out) != "1" or "chose 1 SARAH CODE" not in so:
            fail("RIGHT, START: rc %s, choice %r\n%s" % (rc, read_choice(out), so))
        sent = [ln for ln in rig.log().splitlines() if "NET <- " in ln]
        cmds = sorted(set(re.sub(r".*NET <- ([A-Z]+):.*", r"\1", ln) for ln in sent))
        if cmds != ["ID", "SA"]:
            fail("the menu sent more than ID: and SA:: %r" % cmds)
        print("ok 1-2: NET port found, Audio Controller skipped, RIGHT+START chose 1, only ID:/SA: sent")
        # 7: the glass
        with open(fb, "rb") as f:
            glass = f.read()
        if len(glass) != 1366 * 768 * 4:
            fail("the fake framebuffer is %d bytes" % len(glass))
        row = 400 * 1366 * 4
        if any(glass[row:row + 3 * 4][i] for i in range(12) if i % 4 != 3):
            fail("the 3-pixel left border is not black")
        if not any(glass[row + 3 * 4:row + 1363 * 4]):
            fail("nothing drawn on row 400")
        print("ok 7: the canvas is on the fake framebuffer, 1:1 with black borders")
        time.sleep(0.5)                 # run 1's START tap is over before the next run looks

        # 3: LAUNCH is a second START; LEFT wraps
        p, out, log, fb = start_menu(binary, t, "fast3", 30, font, env)
        settled(log)
        rig.ctl("tap 15 200")
        wait_log(log, r"key: left")
        rig.ctl("tap 20 200")
        rc, so = finish(p)
        if rc != 0 or read_choice(out) != "1":
            fail("LEFT, LAUNCH: rc %s, choice %r\n%s" % (rc, read_choice(out), so))
        print("ok 3: LEFT wrapped to 1, LAUNCH confirmed it")
        time.sleep(0.5)

        # 8: a flipper HELD when the menu starts: letting go is one press, and
        # after RELEARN_MS of reading "pressed" its level is taken as rest, so
        # the button works again (without that it would read pressed for good)
        rig.ctl("sw 15 1")
        p, out, log, fb = start_menu(binary, t, "fast8", 30, font, env)
        text = settled(log) or open(log).read()
        if "at rest LEFT 1" not in text:
            fail("held LEFT: the first reading did not see it held:\n" + text)
        rig.ctl("sw 15 0")
        wait_log(log, r"key: left")
        wait_log(log, r"switch 15 read 0 for 3 s without a break - taken as its rest level", 6)
        time.sleep(0.3)                 # two agreeing samples settle it (input.c)
        rig.ctl("tap 15 200")
        wait_log(log, r"(?s)key: left.*key: left")
        rig.ctl("tap 14 200")
        rc, so = finish(p)
        if rc != 0 or read_choice(out) != "0":
            fail("held LEFT: rc %s, choice %r\n%s" % (rc, read_choice(out), so))
        print("ok 8: a LEFT held at start - released = one press, re-learnt after 3 s, then works")
        time.sleep(0.5)

        # 6: --learn
        p, out, log, fb = start_menu(binary, t, "fast6", 30, font, env, ["--learn"])
        settled(log)
        rig.ctl("tap 39 200")
        wait_log(log, r"fast: learn: switch 39 -> 1 \(pressed\)")
        rig.ctl("tap 14 200")
        rc, so = finish(p)
        if rc != 0 or read_choice(out) != "0":
            fail("--learn run: rc %s, choice %r" % (rc, read_choice(out)))
        print("ok 6: --learn logged switch 39")
    finally:
        rig.stop()

    # 4: no board
    p, out, log, fb = start_menu(binary, t, "fast4", 2, font,
                                 {"PAD_SELECT_FAST_ROOT": os.path.join(t, "no-such-rig")})
    rc, so = finish(p)
    if rc != 0 or read_choice(out) != "0":
        fail("no board: rc %s, choice %r\n%s" % (rc, read_choice(out), so))
    with open(log) as f:
        if f.read().count("no FAST NET port answered") != 1:
            fail("no board: the 'no FAST NET port' line is not there exactly once")
    print("ok 4: no board - timed out to the default, said so once")

    # 5: CH: first, and a reversed START
    s = StandIn()
    s.start()
    p, out, log, fb = start_menu(binary, t, "fast5", 30, font, {}, ["--fast", s.path])
    wait_log(log, r"sending CH:2000,01")
    settled(log)
    s.press(22)
    wait_log(log, r"key: right")
    s.press(14)
    rc, so = finish(p)
    s.stop = True
    if rc != 0 or read_choice(out) != "1":
        fail("stand-in: rc %s, choice %r\n%s" % (rc, read_choice(out), so))
    if sum(1 for ln in s.got if ln.startswith("CH:")) != 1:
        fail("CH: was not sent exactly once: %r" % [ln for ln in s.got if not ln.startswith("SA:")])
    print("ok 5: CH:2000,01 sent once after SA: went unanswered; a reversed START pressed")
    print("fast_test: OK")


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    main()
