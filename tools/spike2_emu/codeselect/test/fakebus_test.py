#!/usr/bin/env python3
"""QEMU=qemu-arm-static fakebus_test.py ROOT BIN T [FONT]

Runs fakebus.py (a pty node bus) and codeselect --input hw --nodebus <pty>
--spi none --default 1 under qemu and presses buttons through the control
file.

  1. LEFT then START -> choice 0, '[select] key: left', '[select] key: start',
     '[select] chose 0', the exact scan frames '88 02 11 65 0c' /
     '81 02 11 6c 0c', the identity reads '88 02 fe 78 0d' / '81 02 fe 7f 0d',
     the 0a 00 -> 03 00 exchange, and no 'BAD CK' in the bus log.
  2. ACTION alone -> choice 1 (the default, untouched), '[select] key: action'
     and never '[select] key: start'. The lockdown-bar button is node 1 bit 2,
     another bit of the SAME 0x11 reply that carries START at bit 11, so this
     case must not add a single extra frame kind to the bus log.

The emulator comes from the environment ($QEMU, exported by the Makefile),
not argv: the rig's teardown does pkill -f 'arm-binfmt|qemu-arm' and this
script's own command line must not match it."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def one_run(qemu, root, binp, t, font, conf, tag, steps):
    """Start fakebus.py on a pty and codeselect against it, then apply steps
    [(wait_s, control-file text), ...]. Returns (rc, out, err, buslog, choice,
    seconds)."""
    ctl = os.path.join(t, "fakebus_%s.ctl" % tag)
    fblog = os.path.join(t, "fakebus_%s.log" % tag)
    choice = os.path.join(t, "hw_%s.choice" % tag)
    last = os.path.join(t, "hw_%s.last" % tag)
    for p in (ctl, fblog, choice, last):
        if os.path.exists(p):
            os.unlink(p)
    open(ctl, "w").close()

    fb = subprocess.Popen([sys.executable, os.path.join(HERE, "..", "fakebus.py"),
                           "--control", ctl, "--log", fblog, "--idle", "4", "--max", "60"],
                          stdout=subprocess.PIPE, text=True)
    slave = fb.stdout.readline().strip()
    if not slave.startswith("/dev/"):
        fb.kill()
        raise SystemExit("fakebus_test: fakebus.py printed %r" % slave)
    print("fakebus_test: [%s] bus on %s" % (tag, slave))

    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "hw_%s.ppm" % tag),
           "--conf", conf, "--input", "hw", "--nodebus", slave, "--spi", "none",
           "--timeout", "6", "--default", "1", "--out", choice, "--last", last,
           "--log", os.path.join(t, "hw_%s.log" % tag), "--font", font, "--no-invert"]
    t0 = time.monotonic()
    sel = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for wait, text in steps:
        time.sleep(wait)
        with open(ctl, "w") as f:
            f.write(text + "\n")
    try:
        out, err = sel.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        sel.kill()
        out, err = sel.communicate()
        fb.kill()
        raise SystemExit("fakebus_test: FAIL [%s] codeselect did not exit\n%s\n%s" % (tag, out, err))
    dt = time.monotonic() - t0
    try:
        fb.wait(timeout=10)
    except subprocess.TimeoutExpired:
        fb.kill()
    sys.stdout.write(out)
    log = open(fblog).read() if os.path.exists(fblog) else ""
    got = open(choice).read().strip() if os.path.exists(choice) else None
    return sel.returncode, out, err, log, got, dt


def main():
    root, binp, t = sys.argv[1:4]
    qemu = os.environ.get("QEMU", "qemu-arm-static")
    font = sys.argv[4] if len(sys.argv) > 4 and os.path.isfile(sys.argv[4]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    os.makedirs(t, exist_ok=True)
    conf = os.path.join(t, "hw.conf")
    with open(conf, "w") as f:
        f.write("image=/dev/mmcblk0p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code\n"
                "image=/dev/mmcblk0p7|TMNT 1987|1.59.0 - upscaled cartoon retheme\n"
                "default=0\ntimeout=10\n")

    # --- 1. LEFT moves the highlight off the default, START confirms ---
    rc, out, err, log, got, dt = one_run(qemu, root, binp, t, font, conf, "start",
                                         [(2.0, "left"), (0.3, ""), (0.3, "start")])
    ok = True
    if rc != 0:
        print("fakebus_test: FAIL exit %d" % rc)
        ok = False
    if got != "0":
        print("fakebus_test: FAIL choice file holds %r, expected '0'" % got)
        ok = False
    for want in ("[select] key: left", "[select] key: start", "[select] chose 0"):
        if want not in out:
            print("fakebus_test: FAIL stdout lacks %r" % want)
            ok = False
    for want in ("TX 88 02 11 65 0c", "TX 81 02 11 6c 0c", "TX 88 02 fe 78 0d", "TX 81 02 fe 7f 0d",
                 "TX 0a 00", "RX 03 00", "TX 80 02 f1 8d 00", "TX 80 03 f0 22 6b 00",
                 "TX 80 03 f0 11 7c 00", "TX 88 03 f0 10 75 00", "TX 88 03 f0 20 65 00",
                 "RX 00 ff 1f f9 40 00 00 00 00 00 a9 00"):
        if want not in log:
            print("fakebus_test: FAIL bus log lacks %r" % want)
            ok = False
    if "BAD CK" in log:
        print("fakebus_test: FAIL bus log has BAD CK")
        ok = False
    n11 = log.count("TX 88 02 11 65 0c") + log.count("TX 81 02 11 6c 0c")
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("fakebus_test: OK (left -> highlight 0, start -> chose 0, %d scans, %.1f s, exit 0)" % (n11, dt))

    # --- 2. the ACTION button (node 1 bit 2) confirms just like START ---
    # Nothing moves the highlight, so the default (1) is what gets booted; the
    # bus sees the same 0x11 scan of node 1 that already carried START.
    rc, out, err, log, got, dt = one_run(qemu, root, binp, t, font, conf, "action",
                                         [(2.0, "action")])
    ok = True
    if rc != 0:
        print("fakebus_test: FAIL (action) exit %d" % rc)
        ok = False
    if got != "1":
        print("fakebus_test: FAIL (action) choice file holds %r, expected '1'" % got)
        ok = False
    for want in ("[select] key: action", "[select] chose 1"):
        if want not in out:
            print("fakebus_test: FAIL (action) stdout lacks %r" % want)
            ok = False
    for unwanted in ("[select] key: start", "[select] key: left", "[select] key: right"):
        if unwanted in out:
            print("fakebus_test: FAIL (action) a spurious %r" % unwanted)
            ok = False
    if "countdown expired" in err:
        print("fakebus_test: FAIL (action) the countdown chose the image, not the button")
        ok = False
    # Node 1 idles at 04 59 7f 00 00 00 00 00 - fakebus.py records where that
    # word comes from and why ff x8 was wrong. Both halves are checked here:
    # the at-rest reply, and the one with the action button down, where bit 2
    # clears byte 0 to 00. The trailing bytes are the u16 0, the checksum and
    # STATUS 0.
    if "RX 04 59 7f 00 00 00 00 00 00 00 24 00" not in log:
        print("fakebus_test: FAIL (action) the bus never replied with node 1 at rest")
        ok = False
    if "RX 00 59 7f 00 00 00 00 00 00 00 28 00" not in log:
        print("fakebus_test: FAIL (action) the bus never replied with node 1 bit 2 low")
        ok = False
    if "BAD CK" in log:
        print("fakebus_test: FAIL (action) bus log has BAD CK")
        ok = False
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    n11 = log.count("TX 88 02 11 65 0c") + log.count("TX 81 02 11 6c 0c")
    print("fakebus_test: OK (action -> chose 1 (the default), %d scans, %.1f s, exit 0)" % (n11, dt))


if __name__ == "__main__":
    main()
