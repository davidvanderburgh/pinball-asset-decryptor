#!/usr/bin/env python3
"""padsw_test.py QEMU ROOT BIN T TABLES [FONT]

Drives codeselect --input padsw the way padglhost does: a 4096-byte padsw
file (magic 'PADS', gen at 4, held[] at 8), RIGHT held for 100 ms then
released, then START held. Expects '[select] key: right', '[select] chose 1'
and a choice file holding 1 (highlight started at 0)."""
import os
import struct
import subprocess
import sys
import time

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


def main():
    qemu, root, binp, t, tables = sys.argv[1:6]
    font = sys.argv[6] if len(sys.argv) > 6 and os.path.isfile(sys.argv[6]) else \
        os.path.join(root, "usr/local/spike/VeraMono.ttf")
    os.makedirs(t, exist_ok=True)
    conf = os.path.join(t, "padsw.conf")
    with open(conf, "w") as f:
        f.write("image=p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code\n"
                "image=p7|TMNT 1987|1.59.0 - upscaled cartoon retheme\n"
                "default=0\ntimeout=10\n")
    ids = table_ids(tables)
    right = ids.get((8, 24))
    start = ids.get((1, 11))
    if right is None or start is None:
        raise SystemExit("padsw_test: %s has no (8,24)/(1,11) rows" % tables)
    print("padsw_test: ids from %s: right %d start %d" % (tables, right, start))

    padsw = os.path.join(t, "padsw")
    with open(padsw, "wb") as f:
        f.write(struct.pack("<II", MAGIC, 1) + bytes(4096 - 8))
    choice = os.path.join(t, "padsw.choice")
    last = os.path.join(t, "padsw.last")
    for p in (choice, last):
        if os.path.exists(p):
            os.unlink(p)

    cmd = [qemu, "-L", root, binp, "--headless", os.path.join(t, "padsw.ppm"), "--conf", conf,
           "--input", "padsw", "--padsw", padsw, "--tables", tables, "--timeout", "4",
           "--out", choice, "--last", last, "--log", os.path.join(t, "padsw.log"),
           "--font", font, "--no-invert"]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    set_held(padsw, right, 1)
    time.sleep(0.1)
    set_held(padsw, right, 0)
    time.sleep(0.2)
    set_held(padsw, start, 1)
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise SystemExit("padsw_test: FAIL codeselect did not exit\n%s\n%s" % (out, err))
    dt = time.monotonic() - t0
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
    if not ok:
        sys.stderr.write(err)
        raise SystemExit(1)
    print("padsw_test: OK (right -> highlight 1, start -> chose 1, %.1f s, exit 0)" % dt)


if __name__ == "__main__":
    main()
