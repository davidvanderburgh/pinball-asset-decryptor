#!/usr/bin/env python3
"""paddelta_test.py PADDELTA T - the install step's program rebuilder (PAD-342) against
deltas written by mkbofmulti.py's own writer, so the two cannot drift apart.

  1. a target rebuilt from a source and a delta of copies and data is the target, byte for
     byte, written to OUT and nothing left as OUT.part;
  2. a delta made against ANOTHER source (its size differs) is refused, exit 4, no OUT;
  3. a delta cut short is refused, exit 4, no OUT and no OUT.part;
  4. a copy reaching past the source is refused, exit 4;
  5. mkbofmulti.delta_ops on two files that share most of their bytes copies the shared
     ones, and apply_delta_md5 (the builder's check) agrees with what paddelta wrote.
"""
import hashlib
import os
import random
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "bof_emu")))
import mkbofmulti as mb  # noqa: E402


def fail(msg):
    print("FAIL: " + msg)
    sys.exit(1)


def run(paddelta, src, dlt, out):
    return subprocess.run([paddelta, src, dlt, out], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main():
    paddelta, t = sys.argv[1], sys.argv[2]
    os.makedirs(t, exist_ok=True)
    rnd = random.Random(342)
    src = os.path.join(t, "pd_src.bin")
    tgt = os.path.join(t, "pd_tgt.bin")
    dlt = os.path.join(t, "pd.delta")
    out = os.path.join(t, "pd_out.bin")
    a = bytes(rnd.getrandbits(8) for _ in range(3 << 20))
    # the target: the source with 100 KB of its second MiB changed in place, and a tail -
    # without a Godot pack directory in either, delta_ops compares at the same offset
    # (moved data is found through the pack's own entries, which these files have not got)
    b = a[:1 << 20] + bytes(rnd.getrandbits(8) for _ in range(100_000)) + a[(1 << 20) + 100_000:] + b"tail"
    with open(src, "wb") as f:
        f.write(a)
    with open(tgt, "wb") as f:
        f.write(b)

    # 5 first: the builder's own ops and writer
    ops = mb.delta_ops(src, tgt)
    copied = sum(n for op, _o, n in ops if op == "C")
    if copied < (2 << 20):
        fail("delta_ops copied only %d bytes of the 2 MiB the files share" % copied)
    mb.write_delta(ops, src, tgt, dlt)
    want = hashlib.md5(b).hexdigest()
    got, size = mb.apply_delta_md5(src, dlt)
    if (got, size) != (want, len(b)):
        fail("apply_delta_md5 says %s %d, the target is %s %d" % (got, size, want, len(b)))

    # 1
    for p in (out, out + ".part"):
        if os.path.exists(p):
            os.unlink(p)
    r = run(paddelta, src, dlt, out)
    if r.returncode != 0:
        fail("paddelta exit %d: %s" % (r.returncode, r.stdout.decode()))
    with open(out, "rb") as f:
        if f.read() != b:
            fail("paddelta's output is not the target")
    if os.path.exists(out + ".part"):
        fail("OUT.part left behind")
    print("ok 1+5: %d ops, %d bytes copied, %d carried; paddelta rebuilt the target byte for byte"
          % (len(ops), copied, mb.delta_data_bytes(ops)))

    # 2: another source
    os.unlink(out)
    other = os.path.join(t, "pd_other.bin")
    with open(other, "wb") as f:
        f.write(a + b"x")
    r = run(paddelta, other, dlt, out)
    if r.returncode != 4 or os.path.exists(out):
        fail("another source: exit %d, out exists %s" % (r.returncode, os.path.exists(out)))
    print("ok 2: a delta made against another source is refused (%s)" % r.stdout.decode().strip())

    # 3: cut short
    cut = os.path.join(t, "pd_cut.delta")
    with open(dlt, "rb") as f:
        data = f.read()
    with open(cut, "wb") as f:
        f.write(data[:len(data) // 2])
    r = run(paddelta, src, cut, out)
    if r.returncode != 4 or os.path.exists(out) or os.path.exists(out + ".part"):
        fail("cut short: exit %d" % r.returncode)
    print("ok 3: a delta cut short is refused, nothing left behind")

    # 4: a copy past the end
    bad = os.path.join(t, "pd_bad.delta")
    with open(bad, "wb") as f:
        f.write(b"PADDLT01" + struct.pack("<QQ", len(a), 10) + b"C" + struct.pack("<QQ", len(a) - 5, 10) + b"E")
    r = run(paddelta, src, bad, out)
    if r.returncode != 4 or os.path.exists(out):
        fail("copy past the end: exit %d" % r.returncode)
    print("ok 4: a copy past the end of the source is refused")
    print("paddelta_test: OK")


if __name__ == "__main__":
    main()
