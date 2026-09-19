#!/usr/bin/env python3
"""Confirm the .sidx invariants across MANY cards before writing a single byte.

Established on three cards so far, and two of them is a coincidence risk - tonight's
_DESC_KEY2_MASK was "verified" on one title and wrong on the next.

  * 0x04            = filesize - 8
  * 0x30            = path count = record count
  * trailer         = 'FEND' + 4 zero bytes, last in the file
  * payload length  = 80 (FI64) / 60 (FINF), uniform within a manifest
  * THE SIZE TOTAL, stored differently per format:
        FI64  -> an SZ64 block, u64 = sum of every record's size
        FINF  -> header word 0x34,  u32 = the same sum
    (Deadpool 0x34 = 0xb000af2b = 2,952,834,859 = its 420 record sizes summed.
     No CRC candidate matched it. On FI64 cards 0x34 is 0xffffffff and the total
     lives in SZ64 - Godzilla's is 6.23 GB, which would not fit in a u32 at all.)

Also checks what an appender must not get wrong: that paths and records are in the
same order, and how close a FINF total is to the u32 ceiling.

  sidxrule129.py <repo> <card.raw> [<card.raw> ...]
"""
import struct
import sys

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from pinball_decryptor.plugins.stern import engine as E   # noqa: E402
from pinball_decryptor.plugins.stern import sidx as S     # noqa: E402

U32_MAX = 0xFFFFFFFF
ok_all = True


def check(card):
    global ok_all
    parts = E._linux_partitions(card)
    with open(E._lp(card), "rb") as f:
        reader, _fw, _img = E._locate(f, parts)
        path, node = S.find_sidx(reader)
        if node is None:
            print("%-42s no .sidx" % card.split("/")[-1])
            return
        d = reader.read_file_bytes(node)

    name = path.split("/")[-1]
    si = d.find(b"STRS")
    strs_len = struct.unpack_from("<I", d, si + 4)[0]
    paths = [p.decode("latin1") for p in d[si + 8:si + 8 + strs_len].split(b"\x00") if p]
    pos = si + 8 + strs_len
    tag = d[pos:pos + 4]
    lens, sizes = set(), []
    while pos + 8 <= len(d) and d[pos:pos + 4] == tag:
        rl = struct.unpack_from("<I", d, pos + 4)[0]
        po = pos + 8
        lens.add(rl)
        if tag == b"FI64":
            sizes.append(struct.unpack_from("<Q", d, po + 8)[0])
        else:
            sizes.append(struct.unpack_from("<I", d, po + 4)[0])
        pos += 8 + rl
    total = sum(sizes)
    fmt = tag.decode("latin1")

    w04 = struct.unpack_from("<I", d, 4)[0]
    w30 = struct.unpack_from("<I", d, 0x30)[0]
    w34 = struct.unpack_from("<I", d, 0x34)[0]
    sz = d.find(b"SZ64")
    sz_val = struct.unpack_from("<Q", d, sz + 8)[0] if sz >= 0 else None

    checks = [
        ("0x04 == filesize-8", w04 == len(d) - 8),
        ("0x30 == paths", w30 == len(paths)),
        ("0x30 == records", w30 == len(sizes)),
        ("FEND trailer last", d[pos:] == b"FEND\x00\x00\x00\x00"),
        ("payload len uniform", len(lens) == 1),
    ]
    if fmt == "FI64":
        checks.append(("SZ64 == size total", sz_val == total))
        checks.append(("0x34 == 0xffffffff", w34 == U32_MAX))
    else:
        checks.append(("0x34 == size total", w34 == total))
        checks.append(("no SZ64 block", sz < 0))

    bad = [n for n, good in checks if not good]
    ok_all = ok_all and not bad
    print("%-40s %-5s n=%-5d total=%-13d %s"
          % (name, fmt, len(sizes), total,
             "OK" if not bad else "FAILED: " + ", ".join(bad)))
    if fmt == "FINF":
        head = U32_MAX - total
        print("      u32 headroom for an appended file: %d bytes (%.2f GB)"
              % (head, head / 1e9))


for card in sys.argv[2:]:
    try:
        check(card)
    except Exception as e:                                  # noqa: BLE001
        print("%-40s FAILED: %s: %s" % (card.split("/")[-1], type(e).__name__, e))
        ok_all = False

print("\nALL INVARIANTS HOLD" if ok_all else "\nSOMETHING DISAGREES - do not write yet")
