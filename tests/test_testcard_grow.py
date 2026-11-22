"""Simon (2026-11-22): a PAD test card grown over the network to fill its SD card.

"when updating on the network ... the user can grow their write as much as they want (or should be able to) within
the limits of their SD card", and it "can be grown remotely but will require reboots".  core/testcard_grow.py: the
new table written on the running machine (p1/p2 untouched, p3 to the end, p5/p6 moved to the very end), /data and
/dump saved on the system partition, and a start-up script that - only under exactly that table - makes the new
file systems and puts /data and /dump back.  Proven on a copy of a test card in WSL with the card's own BusyBox,
mke2fs and tar (8 GB card: p3 2 GiB -> 7.4 GB, the remote access host key the same after)."""

import os
import struct
import types

import pytest

from pinball_decryptor.core import remote_send as rs
from pinball_decryptor.core import testcard_grow as tg
from pinball_decryptor.plugins.stern import spike3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# the network test card built from the stock Godzilla 1.16 card with 2 GB of room, on an 8 GB SD card
LAYOUT = {1: (8192, 16384), 2: (24576, 688128), 3: (712704, 4194304), 4: (4907008, 2), 5: (4909056, 262144),
          6: (5173248, 262144)}
CARD = 16777216
GROWN = {3: (712704, 15536128), 5: (16250880, 262144), 6: (16515072, 262144)}


def _mbr():
    m = bytearray(512)
    m[:4] = b"BOOT"
    m[0x1B8:0x1BC] = b"DSID"
    m[0x1BE:0x1FE] = (tg._entry(0x0C, 8192, 16384) + tg._entry(0x83, 24576, 688128)
                      + tg._entry(0x83, 712704, 4194304) + tg._entry(0x0F, 4907008, 528384))
    m[510:512] = b"\x55\xaa"
    return bytes(m)


# ---- the table -------------------------------------------------------------------------------------------------
def test_the_grown_table(tmp_path):
    p = tg.plan(LAYOUT, CARD, _mbr())
    assert p.expect == GROWN
    assert p.gain > 5.8e9
    assert [lba for lba, _d in p.sectors] == [16248832, 16513024, 0], "the EBRs first, the MBR - the switch - last"
    mbr = p.sectors[-1][1]
    assert mbr[:0x1BE] == _mbr()[:0x1BE], "the boot code and disk id are kept"
    assert mbr[0x1BE:0x1DE] == _mbr()[0x1BE:0x1DE], "p1 and p2 are untouched"
    # the table reads back as the kernel will see it
    img = tmp_path / "card.raw"
    with open(img, "wb") as f:
        f.truncate(CARD * 512)
        for lba, data in p.sectors:
            f.seek(lba * 512)
            f.write(data)
    parts = {r["index"]: (r["start_lba"], r["sectors"]) for r in spike3.parse_partitions_path(str(img))}
    assert parts[1] == LAYOUT[1] and parts[2] == LAYOUT[2]
    assert {n: parts[n] for n in (3, 5, 6)} == GROWN
    assert parts[6][0] + parts[6][1] <= CARD
    assert all(s % tg.ALIGN == 0 for s, _c in parts.values())
    assert p.conf() == ("P3_START=712704\nP3_SIZE=15536128\nP5_START=16250880\nP5_SIZE=262144\n"
                        "P6_START=16515072\nP6_SIZE=262144\n")


def test_a_card_that_cannot_grow_is_refused():
    with pytest.raises(tg.GrowError, match="already fills"):
        tg.plan(LAYOUT, 5173248 + 262144 + 4096, _mbr())
    with pytest.raises(tg.GrowError, match="isn't laid out as a PAD test card"):
        tg.plan({**LAYOUT, 7: (9000000, 100)}, CARD, _mbr())
    with pytest.raises(tg.GrowError, match="no partition table"):
        tg.plan(LAYOUT, CARD, bytes(512))


# ---- the start-up script ---------------------------------------------------------------------------------------
def test_the_startup_script_formats_only_under_the_grown_table():
    s = tg.startup_script()
    assert s.startswith("#!/bin/sh\n") and "@" not in s
    check = s.index("nothing changed\"\n    exit 0")
    for word in ("mke2fs", "mount -o remount,rw /", "tar -xf"):
        assert s.index(word) > check, word
    for n in ("3", "5", "6"):
        assert '[ "$(part %s start)" != "$P%s_START" ]' % (n, n) in s
        assert '[ "$(part %s size)" != "$P%s_SIZE" ]' % (n, n) in s
    # it removes itself and the saved copies only when all of it worked
    done = s.index('if [ $ok = 1 ]; then')
    assert s.index("rm -rf $D", done) and s.index("rm -f $0", done)
    assert "rm -f /data/pad/hash_cache.json /data/pad/remote_send.json" in s


def test_the_startup_script_runs_at_the_right_moment():
    name = os.path.basename(tg.BOOT_SCRIPT_PATH)
    assert not name.endswith(".sh"), "the card's rc sources *.sh scripts: this one runs as a program"
    order = sorted(["S02banner.sh", "S02sysfs.sh", "S02zzz_checkfs.sh", "S03mountall.sh", name])
    assert order.index("S02sysfs.sh") < order.index(name) < order.index("S02zzz_checkfs.sh"), \
        "after /sys is up, before the partitions are checked and mounted"


# ---- on the machine --------------------------------------------------------------------------------------------
class _Card(object):
    """The machine's card as sectors, and the commands the grow sends."""

    def __init__(self, testcard=True, layout=LAYOUT, refuse_table=False, left=""):
        self.sectors = {0: _mbr()}
        self.testcard, self._layout, self.refuse_table, self.left = testcard, dict(layout), refuse_table, left
        self.scripts, self.files = [], {}

    def layout(self):
        return dict(self._layout)

    def free(self, mount):
        return 180 << 20

    def close(self):
        pass

    def sh(self, script, stdin=b"", timeout=600, check=True):
        self.scripts.append(script)
        if "PAD_TESTCARD" in script:
            return 0, "PAD_TESTCARD\n" if self.testcard else ""
        if "UNFINISHED" in script:
            return 0, self.left
        if script == "cat /sys/block/mmcblk0/size":
            return 0, "%d\n" % CARD
        if script.startswith("du -sk"):
            return 0, "300\n"
        if "hexdump" in script:
            lbas = [int(ln.split("skip=")[1].split()[0]) for ln in script.splitlines()]
            return 0, "".join(self.sectors.get(n, bytes(512)).hex() + "\n" for n in lbas)
        if script.startswith("cat > /run/padgrow.tbl"):
            if not self.refuse_table:
                for ln in script.splitlines()[1:]:
                    if ln.startswith("dd "):
                        i, lba = int(ln.split("skip=")[1].split()[0]), int(ln.split("seek=")[1].split()[0])
                        self.sectors[lba] = stdin[i * 512:(i + 1) * 512]
            return 0, ""
        if script.startswith("cat > "):
            self.files[script.split()[2]] = stdin
            return 0, ""
        return 0, ""


def test_survey_and_prepare_write_the_table_and_the_startup():
    m = _Card()
    p, need, free = tg.survey(m)
    assert p.expect == GROWN and need == 300 * 1024 + tg.SPARE and free == 180 << 20
    said = []
    tg.prepare(m, p, lambda t, lv="info": said.append(t))
    assert m.sectors[0] == p.sectors[-1][1] and m.sectors[16248832] == p.sectors[0][1]
    assert m.files[tg.GROW_DIR + "/grow.conf"] == p.conf().encode()
    assert m.files[tg.BOOT_SCRIPT_PATH] == tg.startup_script().encode()
    joined = "\n".join(m.scripts)
    assert "tar -cf %s/data.tar -C /data ." % tg.GROW_DIR in joined and "tar -cf %s/dump.tar -C /dump ." % tg.GROW_DIR
    assert "conv=" not in joined, "the card's BusyBox 1.23 dd has no conv="
    # the saved copies are on the card before the table changes
    assert joined.index("data.tar") < joined.index("cat > /run/padgrow.tbl")


def test_a_table_the_card_does_not_take_is_put_back():
    m = _Card(refuse_table=True)
    p, _need, _free = tg.survey(m)
    with pytest.raises(tg.GrowError, match="the old one is back"):
        tg.prepare(m, p, lambda *a: None)
    assert m.sectors[0] == _mbr()
    assert any(s.startswith("rm -rf %s; rm -f %s" % (tg.GROW_DIR, tg.BOOT_SCRIPT_PATH)) for s in m.scripts)


def test_only_a_test_card_is_grown_and_an_unfinished_grow_is_said():
    with pytest.raises(tg.GrowError, match="isn't running a PAD test card"):
        tg.survey(_Card(testcard=False))
    with pytest.raises(tg.GrowError, match="still under way.*p3 /games made"):
        tg.survey(_Card(left="UNFINISHED\np3 /games made\n"))
    grown = _Card(layout={**LAYOUT, **GROWN, 4: (16248832, 2)}, left="GROWN\n")
    grown.sectors[0] = tg.plan(LAYOUT, CARD, _mbr()).sectors[-1][1]
    with pytest.raises(tg.GrowError, match="grown already"):
        tg.survey(grown)


def test_the_check_after_the_restart():
    p = tg.plan(LAYOUT, CARD, _mbr())
    m = _Card(layout={**LAYOUT, **GROWN})
    m.sh = lambda script, stdin=b"", timeout=600, check=True: (0, "start-up\np3 /games made\ndone\n")
    m.free = lambda mount: 7 << 30
    assert tg.check_grown(m, p) == 7 << 30
    old = _Card()
    with pytest.raises(tg.GrowError, match="without the grown partitions"):
        tg.check_grown(old, p)
    half = _Card(layout={**LAYOUT, **GROWN})
    half.sh = lambda script, stdin=b"", timeout=600, check=True: (
        0, "" if tg.LOG_ON_DATA in script else "p3 /games made\np5 /data failed\n")
    with pytest.raises(tg.GrowError, match="p5 /data failed"):
        tg.check_grown(half, p)


def test_the_run_restarts_the_machine_and_waits_for_it():
    first = _Card()
    after = _Card(layout={**LAYOUT, **GROWN})
    after.sh = lambda script, stdin=b"", timeout=600, check=True: (0, "done\n")
    after.free = lambda mount: 7 << 30
    tries = iter([first, rs.Unreachable("down"), rs.Unreachable("down"), after])

    def connect(address):
        got = next(tries)
        if isinstance(got, Exception):
            raise got
        return got

    out = {}
    pipe = tg.GrowPipeline("192.168.1.50", lambda *a: None, lambda i: out.setdefault("phases", []).append(i),
                           lambda *a: None, lambda ok, s: out.update(ok=ok, summary=s), connect_fn=connect,
                           sleep=lambda s: None)
    pipe.run()
    assert out["ok"] is True, out
    assert "grown" in out["summary"] and "Send to machine" in out["summary"]
    assert out["phases"] == [0, 1, 2, 3]
    assert any("reboot" in s for s in first.scripts)


# ---- the tab and the app ---------------------------------------------------------------------------------------
def _tab(cb=None, address="192.168.1.50"):
    from pinball_decryptor.webui.tabs.testcard import TestCardTab
    tab = TestCardTab.__new__(TestCardTab)
    tab.window = types.SimpleNamespace(cb={"on_grow_test_card": cb} if cb else {})
    tab._busy = False
    tab._address = lambda: address
    return tab


def test_the_tab_asks_with_the_sizes_then_starts_the_run(monkeypatch):
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui.rpc import RpcError
    started, asked = [], []
    monkeypatch.setattr(rs, "connect", lambda address: _Card())
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    assert _tab(cb=started.append).grow() is True
    assert started == ["192.168.1.50"]
    assert "8.0 GB SD card" in asked[0][1] and "Send to machine afterwards" in asked[0][1]
    with pytest.raises(RpcError, match="Network tab"):
        _tab(cb=started.append, address="").grow()
    monkeypatch.setattr(rs, "connect", lambda address: _Card(testcard=False))
    with pytest.raises(RpcError, match="isn't running a PAD test card"):
        _tab(cb=started.append).grow()
    assert started == ["192.168.1.50"]


def test_the_app_and_the_page_offer_it():
    app = open(os.path.join(ROOT, "pinball_decryptor", "app.py"), encoding="utf-8").read()
    assert "on_grow_test_card=self._start_grow," in app
    assert "testcard_grow.GrowPipeline(address, log_cb, phase_cb, progress_cb, done_cb)" in app
    js = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "testcard.js"),
              encoding="utf-8").read()
    assert 'call("testcard.grow")' in js and "Grow on the machine…" in js
