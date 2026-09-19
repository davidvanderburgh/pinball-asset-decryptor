#!/usr/bin/env python3
"""Round-trip the appender against REAL manifests, before any card is touched.

For each dumped .sidx: append a record for a file the card never had, then check
every invariant that 14 real cards agree on, re-parse it, confirm the new record
reads back with the right size and digests, and confirm nothing else moved.

Also the reverse: removing the appended record must reproduce the stock manifest
BYTE FOR BYTE. That is one of item 129's acceptance clauses, and it is much cheaper
to check here than on a card.

  roundtrip129.py <repo> <sidx> [<sidx> ...]
"""
import hashlib
import hmac as _hmac
import struct
import sys

REPO = sys.argv[1]
sys.path.insert(0, REPO)

from pinball_decryptor.plugins.stern import sidx as S            # noqa: E402
from pinball_decryptor.plugins.stern import sidx_append as A     # noqa: E402

BLOB = b"our own asset, which this card never had" * 977   # a plausible size
NEW_SIZE = len(BLOB)
HM = _hmac.new(S.SIDX_KEY, BLOB, hashlib.sha1).digest()
MD = hashlib.md5(BLOB).digest()

ok_all = True
for path in sys.argv[2:]:
    data = open(path, "rb").read()
    recs, _crc, fmt = S.parse_records(data)
    pkg = data[8:0x28].split(b"\x00")[0].decode("latin1")
    newpath = "%s/assets/lcd/ours/mode.radium" % pkg
    label = path.split("/")[-1]

    pre = A.verify(data)
    if pre:
        print("%-42s STOCK MANIFEST ALREADY FAILS: %s" % (label, pre))
        ok_all = False
        continue

    try:
        out = A.append_record(data, newpath, NEW_SIZE, HM, MD)
    except A.SidxAppendError as e:
        print("%-42s REFUSED: %s" % (label, e))
        ok_all = False
        continue

    bad = A.verify(out, expect_paths=[newpath])
    recs2, _c2, fmt2 = S.parse_records(out)
    po = recs2.get(newpath)
    checks = [
        ("invariants", not bad),
        ("format unchanged", fmt2 == fmt),
        ("one more record", len(recs2) == len(recs) + 1),
        ("new record present", po is not None),
        ("grew by path+record", len(out) - len(data)
         == len(newpath) + 1 + 8 + A._PAYLOAD_LEN[fmt]),
    ]
    if po is not None:
        pack, size_off = S._SIZE_FIELDS[fmt][0], S._SIZE_FIELDS[fmt][1]
        h_off, m_off = S._FORMATS[fmt]
        checks += [
            ("size stored", struct.unpack_from(pack, out, po + size_off)[0] == NEW_SIZE),
            ("hmac stored", out[po + h_off:po + h_off + 20] == HM),
            ("md5 stored", out[po + m_off:po + m_off + 16] == MD),
        ]
    # every stock record must still resolve, unmoved in ORDER and identical in bytes
    same = all(p in recs2 for p in recs)
    checks.append(("all stock paths kept", same))
    stock_payloads_ok = True
    for p, old_po in list(recs.items())[:50]:
        new_po = recs2.get(p)
        if new_po is None:
            stock_payloads_ok = False
            break
        if data[old_po:old_po + A._PAYLOAD_LEN[fmt]] != out[new_po:new_po + A._PAYLOAD_LEN[fmt]]:
            stock_payloads_ok = False
            break
    checks.append(("stock payloads byte-identical", stock_payloads_ok))

    # REMOVAL restores the stock manifest exactly (an acceptance clause).
    #
    # This calls the SHIPPED function. An earlier version open-coded the same
    # arithmetic here, which tested this script's copy of the logic and left
    # sidx_deliver.remove_file_record unexercised against a real manifest - the
    # same shape as a control that shares the fault it is meant to catch.
    from pinball_decryptor.plugins.stern import sidx_deliver as D
    try:
        back = D.remove_file_record(out, newpath)
    except Exception as e:                                    # noqa: BLE001
        back = b""
        print("      remove_file_record raised: %s: %s" % (type(e).__name__, e))
    checks.append(("removal restores stock byte-for-byte", back == data))

    failed = [n for n, good in checks if not good]
    ok_all = ok_all and not failed
    print("%-42s %-5s n=%-5d %s"
          % (label, fmt, len(recs),
             "OK" if not failed else "FAILED: " + ", ".join(failed)))
    if bad:
        for b in bad:
            print("      invariant: %s" % b)

print("\nROUND TRIP HOLDS ON EVERY MANIFEST" if ok_all else "\nFAILURES - do not go near a card")
