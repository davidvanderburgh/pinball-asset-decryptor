#!/usr/bin/env python3
"""fakebus_test.py QEMU ROOT BIN T [FONT]

Runs fakebus.py (a pty node bus) and codeselect --input hw --nodebus <pty>
--spi none --default 1 under qemu, presses LEFT then START through the
control file, and expects choice 0, '[select] key: left', '[select] chose 0',
the exact scan frames '88 02 11 65 0c' / '81 02 11 6c 0c', the identity reads
'88 02 fe 78 0d' / '81 02 fe 7f 0d', the 0a 00 -> 03 00 exchange, and no
'BAD CK' in the bus log."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    qemu, root, binp, t = sys.argv[1:5]
    font = sys.argv[5] if len(sys.argv) > 5 and os.path.isfile(sys.argv[5]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    os.makedirs(t, exist_ok=True)
    conf = os.path.join(t, "hw.conf")
    with open(conf, "w") as f:
        f.write("image=/dev/mmcblk0p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code\n"
                "image=/dev/mmcblk0p7|TMNT 1987|1.59.0 - upscaled cartoon retheme\n"
                "default=0\ntimeout=10\n")
    ctl = os.path.join(t, "fakebus.ctl")
    fblog = os.path.join(t, "fakebus.log")
    choice = os.path.join(t, "hw.choice")
    last = os.path.join(t, "hw.last")
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
    print("fakebus_test: bus on %s" % slave)

    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "hw.ppm"), "--conf", conf,
           "--input", "hw", "--nodebus", slave, "--spi", "none", "--timeout", "6", "--default", "1",
           "--out", choice, "--last", last, "--log", os.path.join(t, "hw.log"),
           "--font", font, "--no-invert"]
    t0 = time.monotonic()
    sel = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2.0)
    with open(ctl, "w") as f:
        f.write("left\n")
    time.sleep(0.3)
    with open(ctl, "w") as f:
        f.write("\n")
    time.sleep(0.3)
    with open(ctl, "w") as f:
        f.write("start\n")
    try:
        out, err = sel.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        sel.kill()
        out, err = sel.communicate()
        fb.kill()
        raise SystemExit("fakebus_test: FAIL codeselect did not exit\n%s\n%s" % (out, err))
    dt = time.monotonic() - t0
    try:
        fb.wait(timeout=10)
    except subprocess.TimeoutExpired:
        fb.kill()
    sys.stdout.write(out)
    log = open(fblog).read() if os.path.exists(fblog) else ""
    ok = True
    if sel.returncode != 0:
        print("fakebus_test: FAIL exit %d" % sel.returncode)
        ok = False
    got = open(choice).read().strip() if os.path.exists(choice) else None
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


if __name__ == "__main__":
    main()
