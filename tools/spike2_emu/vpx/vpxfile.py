#!/usr/bin/env python3
"""vpxfile.py - read, patch and re-sign a Visual Pinball X table (.vpx).

A .vpx is an OLE compound document: `GameStg/GameData` (the table's own
fields, BIFF records, the script under tag CODE), `GameStg/GameItem<n>` (one
stream per playfield object), `GameStg/Collection<n>`, images, sounds,
`TableInfo/*` strings, and `GameStg/MAC`, a 16-byte MD2 digest VPX recomputes
on load and REFUSES the file over when it does not match ("refuse it rather
than load it and hope", pintable.cpp). So any edit made outside the VPX
editor - the script, a new light, one more trigger - has to be followed by
the same digest VPX would have written, and this module is that digest.

WHAT VPX HASHES (file version >= 1000; read from pintable.cpp's
LoadGameFromStorage, BiffReader.cpp and BiffWriter.cpp on 2026-10-27):

    "Visual Pinball"                       the 14-byte key, first
    GameStg/Version                        4 bytes
    TableInfo/TableName, AuthorName, TableVersion, ReleaseDate, AuthorEmail,
      AuthorWebSite, TableBlurb, TableDescription, TableRules
                                           raw UTF-16 bytes, each only if present
    TableInfo/Screenshot                   raw bytes, if present
    GameStg/CustomInfoTags                 BIFF records (rule below)
    TableInfo/<each custom tag>            raw bytes
    GameStg/GameData                       BIFF records (rule below)
    GameStg/Collection0..n-1               BIFF records (rule below)

BIFF record rule: each record is [u32 size][4-char tag][payload]. The SIZE
is never hashed at the top level (GetIntNoHash); the TAG is; the PAYLOAD is,
with one exception: CODE's payload is [u32 len][script text] and only the
TEXT feeds the hash ("Only the script text feeds the hash, not the length").
ENDB's tag is hashed and ends the object. Font descriptors (textbox/decal
FONT records) are skipped too, but those live in GameItems, which do not
feed the hash at all from file version 1000 on (nor do images, sounds or
fonts). TableSaveDate and TableSaveRev are written with a null hash: not
hashed.

`verify()` on an untouched table proves the rule: its digest equals the
file's MAC. That is the test to run first on any new VPX release.

WRITING. olefile reads compound files but cannot add streams, so writes go
through the Windows structured-storage API (pywin32's pythoncom.StgOpenStorage):
one transaction that replaces GameData, adds GameItem streams and rewrites MAC.
Windows only, like VPX itself.
"""
import os
import shutil
import struct
import sys

import olefile

TABLE_KEY = b"Visual Pinball"
INFO_HASHED = ("TableName", "AuthorName", "TableVersion", "ReleaseDate", "AuthorEmail",
               "AuthorWebSite", "TableBlurb", "TableDescription", "TableRules")

ITEM_TYPES = {0: "Wall", 1: "Flipper", 2: "Timer", 3: "Plunger", 4: "Textbox", 5: "Bumper",
              6: "Trigger", 7: "Light", 8: "Kicker", 9: "Decal", 10: "Gate", 11: "Spinner",
              12: "Ramp", 13: "Table", 14: "LightCenter", 15: "DragPoint", 16: "Collection",
              17: "DispReel", 18: "LightSeq", 19: "Primitive", 20: "Flasher", 21: "Rubber",
              22: "HitTarget", 23: "Light2", 24: "PartGroup"}


# ---------------------------------------------------------------- BIFF ----

def biff_records(data, start=0):
    """Yield (tag, payload, offset) for a BIFF stream; stops after ENDB.

    CODE IS THE ODD ONE. Its record is [u32 4]["CODE"] and the script follows
    OUTSIDE the record as [u32 len][text] (BiffWriter writes the size over the
    tag alone; BiffReader::AsScript reads the length and text straight off the
    stream). It is yielded here as one record whose payload is that
    [len][text], so a caller sees the script whole and biff_record() writes it
    back the same way. Read it as a plain record and the script's first four
    characters parse as the next tag - which, as it happens, hashes to the same
    bytes VPX hashes, so a digest cannot tell the two readings apart; script()
    and replace_field() can."""
    i = start
    n = len(data)
    while i + 8 <= n:
        size = struct.unpack_from("<I", data, i)[0]
        tag = data[i + 4:i + 8].decode("latin1")
        if tag == "CODE" and size == 4 and i + 12 <= n:
            clen = struct.unpack_from("<I", data, i + 8)[0]
            yield tag, data[i + 8:i + 12 + clen], i
            i += 12 + clen
            continue
        payload = data[i + 8:i + 4 + size]
        yield tag, payload, i
        i += 4 + size
        if tag == "ENDB":
            return


def biff_record(tag, payload):
    if tag == "CODE":
        return struct.pack("<I", 4) + b"CODE" + payload
    return struct.pack("<I", 4 + len(payload)) + tag.encode("latin1") + payload


def biff_hash_update(md2, data, start=0):
    """Feed a BIFF object to the digest exactly as BiffReader does."""
    for tag, payload, _ in biff_records(data, start):
        md2.update(tag.encode("latin1"))
        if tag == "ENDB":
            return
        if tag == "CODE":
            md2.update(payload[4:])          # the script text, not its length
        else:
            md2.update(payload)


def wide(s):
    """A BIFF wide string payload: u32 byte length + UTF-16LE."""
    b = s.encode("utf-16le")
    return struct.pack("<I", len(b)) + b


def unwide(payload):
    n = struct.unpack_from("<I", payload, 0)[0]
    return payload[4:4 + n].decode("utf-16le", "replace")


# ---------------------------------------------------------------- read -----

class VpxTable:
    """Everything the digest needs, plus the items, read once with olefile."""

    def __init__(self, path):
        self.path = path
        ole = olefile.OleFileIO(path)
        self.ole = ole
        self.version = struct.unpack("<i", ole.openstream("GameStg/Version").read())[0]
        self.gamedata = ole.openstream("GameStg/GameData").read()
        self.mac = ole.openstream("GameStg/MAC").read() if ole.exists("GameStg/MAC") else None
        self.info = {}
        for e in ole.listdir():
            if e[0] == "TableInfo":
                self.info[e[1]] = ole.openstream("/".join(e)).read()
        self.custom_tags = (ole.openstream("GameStg/CustomInfoTags").read()
                            if ole.exists("GameStg/CustomInfoTags") else None)
        self.collections = []
        i = 0
        while ole.exists("GameStg/Collection%d" % i):
            self.collections.append(ole.openstream("GameStg/Collection%d" % i).read())
            i += 1
        self.items = []
        i = 0
        while ole.exists("GameStg/GameItem%d" % i):
            self.items.append(ole.openstream("GameStg/GameItem%d" % i).read())
            i += 1

    # -- fields of GameData
    def gamedata_field(self, tag):
        for t, payload, _ in biff_records(self.gamedata):
            if t == tag:
                return payload
        return None

    def script(self):
        payload = self.gamedata_field("CODE")
        return payload[4:].decode("utf-8", "replace") if payload else ""

    def item_count(self):
        return struct.unpack("<i", self.gamedata_field("SEDT"))[0]

    @staticmethod
    def item_info(data):
        """(type name, object name, (x, y) or None) of one GameItem stream."""
        t = struct.unpack_from("<i", data, 0)[0]
        name, pos = "", None
        for tag, payload, _ in biff_records(data, 4):
            if tag == "NAME":
                name = unwide(payload).replace("\x00", "").strip()
            elif tag == "VCEN" and pos is None and len(payload) >= 8:
                pos = struct.unpack_from("<ff", payload, 0)
        return ITEM_TYPES.get(t, str(t)), name, pos

    # -- digest
    def digest(self, gamedata=None):
        """The MAC VPX computes for this table (with `gamedata` in place of
        the file's own, when a patched one is being signed)."""
        from Crypto.Hash import MD2
        md2 = MD2.new()
        md2.update(TABLE_KEY)
        md2.update(struct.pack("<i", self.version))
        for name in INFO_HASHED:
            if name in self.info:
                md2.update(self.info[name])
        if "Screenshot" in self.info:
            md2.update(self.info["Screenshot"])
        if self.custom_tags is not None:
            biff_hash_update(md2, self.custom_tags)
            for tag, payload, _ in biff_records(self.custom_tags):
                if tag == "CUST":
                    n = struct.unpack_from("<I", payload, 0)[0]
                    cname = payload[4:4 + n].decode("utf-8", "replace")
                    if cname in self.info:
                        md2.update(self.info[cname])
        biff_hash_update(md2, self.gamedata if gamedata is None else gamedata)
        for col in self.collections:
            biff_hash_update(md2, col)
        return md2.digest()

    def verify(self):
        return self.mac is not None and self.digest() == self.mac


# ---------------------------------------------------------------- patch ----

def replace_field(gamedata, tag, new_payload):
    """GameData with one record's payload replaced (first occurrence)."""
    out = bytearray()
    done = False
    for t, payload, _ in biff_records(gamedata):
        if t == tag and not done:
            out += biff_record(t, new_payload)
            done = True
        else:
            out += biff_record(t, payload)
    if not done:
        raise KeyError(tag)
    return bytes(out)


def with_script(gamedata, text):
    b = text.encode("utf-8")
    return replace_field(gamedata, "CODE", struct.pack("<I", len(b)) + b)


def with_item_count(gamedata, n):
    return replace_field(gamedata, "SEDT", struct.pack("<i", n))


def item_records(data, start=4):
    """Every record of a GameItem stream, NESTED OBJECTS INCLUDED. A light's
    or trigger's shape is a run of drag points, each written as a DPNT tag
    followed by its own records and its own ENDB; only the ENDB at depth zero
    ends the item. biff_records() stops at the first ENDB it meets, which for
    such an item is the first drag point's - a clone built from it carried one
    point and no closing ENDB, and VPX sat in "Loading" for ever on it."""
    depth = 0
    for tag, payload, off in _records_no_stop(data, start):
        yield tag, payload, off
        if tag == "DPNT":
            depth += 1
        elif tag == "ENDB":
            if depth == 0:
                return
            depth -= 1


def _records_no_stop(data, start):
    i, n = start, len(data)
    while i + 8 <= n:
        size = struct.unpack_from("<I", data, i)[0]
        tag = data[i + 4:i + 8].decode("latin1")
        yield tag, data[i + 8:i + 4 + size], i
        i += 4 + size


def clone_item(data, name, x, y):
    """A copy of a GameItem stream renamed and moved: every VCEN in it (the
    centre and each drag point) shifts by the same delta, so a light's shape
    travels with it."""
    t = struct.unpack_from("<i", data, 0)[0]
    out = bytearray(struct.pack("<i", t))
    dx = dy = None
    for tag, payload, _ in item_records(data, 4):
        if tag == "VCEN" and len(payload) >= 8:
            ox, oy = struct.unpack_from("<ff", payload, 0)
            if dx is None:                      # the first VCEN is the centre
                dx, dy = x - ox, y - oy
            payload = struct.pack("<ff", ox + dx, oy + dy) + payload[8:]
        elif tag == "NAME":
            payload = wide(name)
        out += biff_record(tag, payload)
    return bytes(out)


def set_fields(data, fields):
    """A GameItem stream with the first top-level record of each tag in
    `fields` given a new payload (a timer's TMON/TMIN, say)."""
    t = struct.unpack_from("<i", data, 0)[0]
    out = bytearray(struct.pack("<i", t))
    todo = dict(fields)
    depth = 0
    for tag, payload, _ in item_records(data, 4):
        if depth == 0 and tag in todo:
            payload = todo.pop(tag)
        out += biff_record(tag, payload)
        if tag == "DPNT":
            depth += 1
        elif tag == "ENDB" and depth:
            depth -= 1
    if todo:
        raise KeyError("no %s record in the item" % ",".join(todo))
    return bytes(out)


def write_patched(src, dst, gamedata=None, new_items=(), script=None):
    """Copy `src` to `dst`, then replace GameData (optionally with a new
    script), append `new_items` (GameItem streams) and re-sign."""
    import pythoncom
    from win32com import storagecon as sc
    table = VpxTable(src)
    gd = table.gamedata if gamedata is None else gamedata
    if script is not None:
        gd = with_script(gd, script)
    n0 = table.item_count()
    if new_items:
        gd = with_item_count(gd, n0 + len(new_items))
    mac = table.digest(gd)
    table.ole.close()
    shutil.copyfile(src, dst)
    mode = sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE | sc.STGM_TRANSACTED
    root = pythoncom.StgOpenStorage(dst, None, mode, None, 0)
    stg = root.OpenStorage("GameStg", None, mode, None, 0)
    cmode = sc.STGM_CREATE | sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE
    for name, data in [("GameData", gd), ("MAC", mac)] + \
            [("GameItem%d" % (n0 + i), item) for i, item in enumerate(new_items)]:
        stm = stg.CreateStream(name, cmode, 0, 0)
        stm.Write(data)
        stm.Commit(0)
    stg.Commit(0)
    root.Commit(0)
    return mac


# ---------------------------------------------------------------- CLI ------

def main(argv):
    if len(argv) < 3 or argv[1] not in ("verify", "script", "items", "mac"):
        print("usage: vpxfile.py verify|mac|script|items <table.vpx> [out]", file=sys.stderr)
        return 2
    cmd, path = argv[1], argv[2]
    t = VpxTable(path)
    if cmd == "verify":
        ok = t.verify()
        print("version %d  file MAC %s  computed %s  -> %s"
              % (t.version, t.mac.hex() if t.mac else "-", t.digest().hex(),
                 "OK" if ok else "MISMATCH"))
        return 0 if ok else 1
    if cmd == "mac":
        print(t.digest().hex())
        return 0
    if cmd == "script":
        out = argv[3] if len(argv) > 3 else None
        if out:
            open(out, "w", encoding="utf-8", newline="").write(t.script())
            print("%d chars -> %s" % (len(t.script()), out))
        else:
            sys.stdout.write(t.script())
        return 0
    if cmd == "items":
        print("%d items (SEDT says %d)" % (len(t.items), t.item_count()))
        for i, d in enumerate(t.items):
            kind, name, pos = t.item_info(d)
            print("%4d %-10s %-24s %s" % (i, kind, name, "@(%.0f,%.0f)" % pos if pos else ""))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
