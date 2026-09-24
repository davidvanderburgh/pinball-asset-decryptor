"""Tests for reading any Spike 2 build's own modes off its game program (stock_scan*, stock_reader).

A synthetic plain-C title (an ELF built here: operator settings, audits, the functions that
read them and their callers) runs everywhere, CI included: the reader finds get_adjustment and
the audit counter by what they do, lists the modes the audits name with their settings, the
table is cached and indexed, stock_modes.tables() / table_for / identify see it, and a staged
timer reaches the Write overlay with no caller passing a table. The tracker's shapes (a mov +
movt pair, a conditional value, a strd into a field, a virtual call on a field) and the
grammar's new forms (one number at several sites, ``uncertain`` rows, a mode's own name) are
checked on synthetic words.

Against the real game programs of the latest builds (outside the repo; skipped without them):
the Godzilla tables regenerate the hand table's player-facing rows, Beatles lists its six modes
with the Drive My Car timer as an operator setting, TMNT's Episode One has its timer and start
award as instruction words, Munsters' duration is one row over two words, and a card this app
already wrote keeps the table of its original. Every editable number on eight C++ builds is
checked independently of the reader (capstone, straight-line): its call is inside the function
it names, its register is read once, words two modes hold say so, and an unnamed timer number
is read-only. A written card read before its original is refused, never read as stock. Desk
only.
"""
import hashlib
import os
import struct

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import stock_modes as SM          # noqa: E402
from pinball_decryptor.plugins.stern import stock_reader as R          # noqa: E402
from pinball_decryptor.plugins.stern import stock_scan as SS           # noqa: E402
from pinball_decryptor.plugins.stern import title_reader as TR         # noqa: E402
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable  # noqa: E402

pytestmark = pytest.mark.usefixtures("preview_modes_on")

#: folders of <game>-<version>.elf game programs, from PAD_GAME_ELFS (several joined with
#: os.pathsep); the tests that need one skip without it
ELF_DIRS = [d for d in (os.environ.get("PAD_GAME_ELFS") or "").split(os.pathsep) if d]


def real_elf(name):
    """The game program ``<game>-<version>.elf`` (e.g. ``beatles-1.29.0``), or a skip."""
    for d in ELF_DIRS:
        p = os.path.join(d, name + ".elf")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    pytest.skip("no %s game program on this machine (set PAD_GAME_ELFS to a folder of "
                "<game>-<version>.elf files)" % name)


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    """Generated tables go to a folder of this test's own."""
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(R, "_CACHE", {"index_key": None, "builds": [], "parsed": {}})
    return tmp_path / "cache"


# ---- a synthetic ARM program ---------------------------------------------------------------------
TEXT_VA, TEXT_OFF = 0x10000, 0x1000
DATA_VA = 0x200000


def movw(rd, v):
    return 0xE3000000 | rd << 12 | ((v >> 12) & 0xF) << 16 | (v & 0xFFF)


def movt(rd, v):
    return 0xE3400000 | rd << 12 | ((v >> 12) & 0xF) << 16 | (v & 0xFFF)


def mov(rd, v):
    assert v < 256
    return 0xE3A00000 | rd << 12 | v


PUSH, POP = 0xE92D4010, 0xE8BD8010             # push {r4, lr} / pop {r4, pc}


def bl(site, target):
    return 0xEB000000 | (((target - site - 8) >> 2) & 0xFFFFFF)


def elf(text_words, data=b"", data_va=DATA_VA):
    """A little-endian ELF32: an R+X load of *text_words* at TEXT_VA and an R+W load of
    *data* at *data_va*."""
    code = struct.pack("<%dI" % len(text_words), *text_words)
    data_off = TEXT_OFF + len(code) + (-len(code) % 0x1000)
    hdr = bytearray(52)
    hdr[0:4] = b"\x7fELF"
    hdr[4], hdr[5], hdr[6] = 1, 1, 1
    struct.pack_into("<HHIIIIIHHHHHH", hdr, 16, 2, 40, 1, TEXT_VA, 52, 0, 0, 52, 32, 2, 40, 0, 0)
    ph = struct.pack("<8I", 1, TEXT_OFF, TEXT_VA, TEXT_VA, len(code), len(code), 5, 0x1000)
    ph += struct.pack("<8I", 1, data_off, data_va, data_va, len(data), len(data), 6, 0x1000)
    b = bytes(hdr) + ph
    b += b"\0" * (TEXT_OFF - len(b)) + code
    b += b"\0" * (data_off - len(b)) + data
    return b


AD_SPECS = [("AD_INVALID", 0, 0, 0), ("AD_BALLS_PER_GAME", 3, 1, 10),
            ("AD_MODE_ALPHA_TIMER", 30, 20, 60), ("AD_MODE_ALPHA_SHOTS", 4, 2, 8),
            ("AD_BRAVO_MULTIBALL_BALL_SAVE_SECONDS", 15, 0, 30), ("AD_FREE_PLAY", 0, 0, 1)]
AUD_NAMES = ["AUD_INVALID", "AUD_TOTAL_PLAYS", "AUD_MODE_ALPHA_STARTED", "AUD_MODE_ALPHA_COMPLETED",
             "AUD_BRAVO_MULTIBALLS", "AUD_BRAVO_MULTIBALL_JACKPOTS", "AUD_TOTAL_BALL_SEARCH_STARTS",
             "AUD_EXTRA_1", "AUD_EXTRA_2", "AUD_EXTRA_3", "AUD_EXTRA_4", "AUD_EXTRA_5",
             "AUD_EXTRA_6", "AUD_EXTRA_7"]
AUD_ID_BASE = 100                               # the id the code passes = 100 + the name's place


def c_title(ad_specs=AD_SPECS, aud_names=AUD_NAMES):
    """A plain-C title: settings and audits tables in the shapes the game uses, get_adjustment
    and the audit counter, and a caller per setting (``get_adjustment(id)``) and per audit
    (``audit_add(id, 1)``). Returns ``(elf bytes, {name: VA})``."""
    data = bytearray()

    def put(b):
        va = DATA_VA + len(data)
        data.extend(b)
        return va

    def align():
        data.extend(b"\0" * (-len(data) % 4))

    ad_name_va = [put(n.encode() + b"\0") for n, *_r in ad_specs]
    node_va = put(b"SYS\0")
    aud_name_va = [put(n.encode() + b"\0") for n in aud_names]
    align()
    put(b"".join(struct.pack("<I", v) for v in ad_name_va))
    ad_table = put(b"".join(struct.pack("<iiiii", 0, d, mn, mx, 1) + b"\0" * 24
                            for _n, d, mn, mx in ad_specs))
    put(struct.pack("<IIIII", 0, ad_table, len(ad_specs), 44, node_va))
    put(b"".join(struct.pack("<I", v) for v in aud_name_va))
    aud_table = put(b"".join(b"\0" * 0x12 + struct.pack("<H", AUD_ID_BASE + i) + b"\0" * 8
                             for i in range(len(aud_names))))
    put(struct.pack("<IIII", 0, aud_table, len(aud_names), 28))
    counters = put(b"\0" * 64)

    words = []
    get_adj = TEXT_VA
    words += [PUSH, movw(3, ad_table & 0xFFFF), movt(3, ad_table >> 16), POP]
    audit_add = TEXT_VA + 4 * len(words)
    words += [PUSH, movw(3, counters & 0xFFFF), movt(3, counters >> 16), POP]
    sites = {}
    for i in range(1, len(ad_specs)):
        f = TEXT_VA + 4 * len(words)
        words += [PUSH, mov(0, i), 0, POP]
        words[-2] = bl(f + 8, get_adj)
        sites[ad_specs[i][0]] = f + 8
    for i in range(1, len(aud_names)):
        f = TEXT_VA + 4 * len(words)
        words += [PUSH, mov(0, AUD_ID_BASE + i), mov(1, 1), 0, POP]
        words[-2] = bl(f + 12, audit_add)
        sites[aud_names[i]] = f + 12
    sites.update(get_adjustment=get_adj, audit_add=audit_add)
    return elf(words, bytes(data)), sites


# ---- the synthetic plain-C title ------------------------------------------------------------------
def test_the_plain_c_reader_finds_the_engine_the_modes_and_their_settings():
    data, sites = c_title()
    prog = SS.Program(data)
    from pinball_decryptor.plugins.stern import stock_scan_c as SC
    r = SC.read(prog)
    assert r.engine == {"get_adjustment": sites["get_adjustment"], "audit_add": sites["audit_add"]}
    assert [(m.id, m.cls, m.name) for m in r.modes] == [
        (1, "alpha", "Alpha"), (2, "bravo_multiball", "Bravo Multiball")]
    alpha, bravo = r.modes
    assert [(row.key, row.value, row.kind, row.klass) for row in alpha.rows] == [
        ("timer.adjustment", 30, ("adj", "AD_MODE_ALPHA_TIMER", 2), "adjustment"),
        ("shots.adjustment", 4, ("adj", "AD_MODE_ALPHA_SHOTS", 3), "adjustment")]
    assert [(row.key, row.kind[1]) for row in bravo.rows] == [
        ("ball_save.adjustment", "AD_BRAVO_MULTIBALL_BALL_SAVE_SECONDS")]
    assert any("counted at 0x%x" % sites["AUD_MODE_ALPHA_STARTED"] in f for f in alpha.facts)


def test_a_generated_table_parses_and_every_setting_is_editable():
    data, _sites = c_title()
    text, info = R.generate(data, "synthc", "1.00")
    assert info["family"] == "c" and info["modes"] == 2
    b = SM.parse(text)[0]
    assert b.id == "synthc 1.00" and b.sha1 == hashlib.sha1(data).hexdigest()
    assert b.mode_name(1) == "Alpha"
    n = b.number("1.timer.adjustment")
    assert n.editable and n.adj_range == (20, 60) and b.row_label(n) == "Timer"
    assert all(x.editable for x in b.numbers)


def test_the_table_is_cached_indexed_and_seen_by_every_table_lookup(cache):
    data, _sites = c_title()
    seen = []
    res = R.ensure_table(data, "synthc", "1.00", progress=lambda f, t="": seen.append((f, t)))
    assert res.origin == "generated" and res.build.id == "synthc 1.00"
    assert any("unknown" in n or "isn't one the app has seen" in n for n in res.notes)
    fr = [f for f, _t in seen]
    assert fr == sorted(fr) and fr[-1] == 1.0 and any("Mode 1 of 2" in t for _f, t in seen)
    assert os.path.isfile(R.table_path(res.build.sha1))
    rec = R.load_index()[res.build.sha1]
    assert (rec["game"], rec["version"], rec["stock"]) == ("synthc", "1.00", "unknown")
    # every caller of the tables sees it: tables(), table_for, identify
    assert any(b.sha1 == res.build.sha1 for b in SM.tables())
    assert SM.table_for("synthc", "1.0.0").sha1 == res.build.sha1
    assert SM.identify(SM.ElfImage(data), SM.tables())[1] == "sha1"
    # the second look is the cache, not a new read
    again = R.ensure_table(data, "synthc", "1.00",
                           cancel=lambda: pytest.fail("a cached table was read again"))
    assert again.origin == "generated" and again.build.sha1 == res.build.sha1
    # ... and it keeps the caveat of a program the app has not seen from Stern
    assert again.notes == (R.UNKNOWN_BUILD,)


def test_a_table_of_an_older_reader_is_not_listed(cache):
    data, _sites = c_title()
    res = R.ensure_table(data, "synthc", "1.00")
    import json
    idx = R.load_index()
    idx[res.build.sha1]["rev"] = R.READER_REV - 1
    with open(os.path.join(R.user_tables_dir(), R.INDEX), "w", encoding="utf-8") as f:
        json.dump({"format": R.INDEX_FORMAT, "builds": idx}, f)
    assert not any(b.sha1 == res.build.sha1 for b in R.cached_builds())


def test_a_hand_table_wins_for_its_program(monkeypatch):
    data, _sites = c_title()
    text, _info = R.generate(data, "synthc", "1.00")
    hand = SM.parse(text.replace("name Alpha", "name Hand_Alpha"))[0]
    monkeypatch.setattr(SM, "_TABLES", [hand])
    res = R.ensure_table(data, "synthc", "1.00")
    assert res.origin == "hand" and res.build is hand
    assert not os.path.exists(R.table_path(hand.sha1))


def test_a_staged_timer_reaches_the_write_with_no_table_passed(tmp_path):
    data, _sites = c_title()
    res = R.ensure_table(data, "synthc", "1.00")
    project = _project(tmp_path, "synthc-1_00_0.Release.8G.sdcard.raw")
    build = SM.table_for_project(project)
    assert build is not None and build.sha1 == res.build.sha1
    SM.stage(project, build, build.number("1.timer.adjustment"), 45)
    rdr = _Reader(data)
    writes, overlay, n = SM.compute_writes(rdr, rdr.fw_node, project, None)
    off = AdjustmentTable(data).default_file_offset("AD_MODE_ALPHA_TIMER")
    assert n == 1 and overlay == {off: struct.pack("<i", 45)}
    assert writes == [(off, struct.pack("<i", 45))]
    assert SM.pending_count(project) == 1


def _forget_tables():
    """What an app update that raises READER_REV, a cleared cache or a project opened on
    another PC leaves: no generated table of the build on this computer."""
    import shutil
    shutil.rmtree(R.user_tables_dir(), ignore_errors=True)
    R._CACHE.update({"index_key": None, "builds": [], "parsed": {}})


def test_a_staged_timer_is_written_when_its_table_was_lost(tmp_path):
    """Review M4: numbers staged while the table was here are not dropped when it is gone. The
    Write list shows them as not read yet, the engine's guard counts them (no "Nothing to
    write"), and the Write reads the table again from the card's own game program."""
    from pinball_decryptor.webui import write_scan as WS
    data, _sites = c_title()
    R.ensure_table(data, "synthc", "1.00")
    project = _project(tmp_path, "synthc-1_00_0.Release.8G.sdcard.raw")
    build = SM.table_for_project(project)
    SM.stage(project, build, build.number("1.timer.adjustment"), 45)
    _forget_tables()
    assert SM.table_for_project(project) is None and SM.staged_edits(project) == []
    assert SM.unread_staged(project) == 1 and SM.pending_count(project) == 1
    mfr = type("M", (), {"capabilities": type("C", (), {"modes": True})()})()
    rows = WS.stock_mode_rows(mfr, project)
    assert len(rows) == 1 and "1 staged change(s), not read yet" in rows[0][0]
    said = []
    rdr = _Reader(data)
    writes, overlay, n = SM.compute_writes(rdr, rdr.fw_node, project,
                                           lambda m, lvl="info": said.append(m))
    off = AdjustmentTable(data).default_file_offset("AD_MODE_ALPHA_TIMER")
    assert n == 1 and overlay == {off: struct.pack("<i", 45)}
    assert any("read their table from this card's game program" in m for m in said)
    assert SM.table_for_project(project) is not None and SM.unread_staged(project) == 0


WORD_TABLE = """build synthw 1.00 sha1 %s
mode 1 cmode_alpha obj 0x0 vtable 0x0 title_msg ? name Alpha
number 1 %s 3000000 lit 0x10010 002dc6c0 word
number 1 start.caward_add 500000 lit 0x10020 0007a120 word
"""


def test_staged_keys_follow_a_new_reader_revision(tmp_path, monkeypatch):
    """Review M4: a row an older reader keyed one way and a newer reader another (the same
    instruction words, the same setting) keeps its staged value: the key is read through the
    table the older reader kept for the program, and staging again moves it to the new key."""
    sha1 = "ab" * 20
    old = SM.parse(WORD_TABLE % (sha1, "shot.caward_add"))[0]
    new = SM.parse(WORD_TABLE % (sha1, "shot.award_value"))[0]
    monkeypatch.setattr(R, "older_tables", lambda s: [old] if s == sha1 else [])
    staged = {"1.shot.caward_add": 4000000, "1.nowhere": 7}
    got = SM.resolve_keys(staged, new)
    assert got == {"1.shot.award_value": 4000000, "1.nowhere": 7}
    # a key the new table has wins over a mapped one
    assert SM.resolve_keys({"1.shot.caward_add": 1, "1.shot.award_value": 2}, new) == \
        {"1.shot.award_value": 2}
    # staging in the new table moves the old key, so it can't come back after a revert
    project = _project(tmp_path, "synthw-1_00_0.raw")
    from pinball_decryptor.core import staged_changes
    staged_changes.save(project, {SM.STAGE_KEY: {"build": new.id, "values": {
        "1.shot.caward_add": 4000000}, "touched": ["1.shot.caward_add"]}})
    assert SM.staged_for(project, new)["values"] == {"1.shot.award_value": 4000000}
    assert [e["new"] for e in SM.staged_edits(project, new)] == [4000000]
    SM.unstage(project, new, new.number("1.shot.award_value"))
    rec = staged_changes.load(project)[SM.STAGE_KEY]
    assert rec["values"] == {} and rec["touched"] == ["1.shot.award_value"]
    # the files an older reader kept are found by revision
    monkeypatch.undo()
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache2"))
    monkeypatch.setattr(R, "_CACHE", {"index_key": None, "builds": [], "parsed": {}})
    import os as _os
    _os.makedirs(R.user_tables_dir(), exist_ok=True)
    with open(R.table_path(sha1, R.READER_REV - 1), "w", encoding="utf-8") as f:
        f.write(WORD_TABLE % (sha1, "shot.caward_add"))
    assert [b.number("1.shot.caward_add") is not None for b in R.older_tables(sha1)] == [True]


def test_a_kept_table_of_a_changed_program_is_not_served_as_stock(synthc_known):
    """Review: a table kept for a program that isn't Stern's (one generated before its build
    was known) is not served from the cache as the game's own numbers once the build is
    known: the original's table, or the refusal, decides."""
    ours = _written(synthc_known)
    text, _info = R.generate(ours, "synthc", "1.00")
    R.save_table(text, "synthc", "1.00", hashlib.sha1(ours).hexdigest(), "unknown")
    res = R.ensure_table(ours, "synthc", "1.00")
    assert res.build is None and "isn't the one Stern shipped as synthc 1.00" in res.notes[0]
    orig = R.ensure_table(synthc_known, "synthc", "1.00")
    again = R.ensure_table(ours, "synthc", "1.00")
    assert again.build.sha1 == orig.build.sha1 and "original synthc 1.00" in again.notes[0]


def test_the_operator_menus_words_are_read_once_and_kept(tmp_path):
    data, _sites = c_title()
    res = R.ensure_table(data, "synthc", "1.00")
    caps = R.captions_for(data, res.build)
    assert set(caps) <= set(res.build.adjustment_numbers()) and caps
    assert os.path.isfile(os.path.join(R.user_tables_dir(), "%s.captions.json" % res.build.sha1))
    assert R.captions_for(b"not a program", res.build, sha1=res.build.sha1) == caps  # the kept file


def test_a_card_this_app_wrote_keeps_its_originals_table(tmp_path):
    data, _sites = c_title()
    first = R.ensure_table(data, "synthc", "1.00")
    ours = bytearray(data)
    off = AdjustmentTable(data).default_file_offset("AD_MODE_ALPHA_TIMER")
    struct.pack_into("<i", ours, off, 45)                  # what a Write of 45 leaves
    res = R.ensure_table(bytes(ours), "synthc", "1.00")
    assert res.build.sha1 == first.build.sha1 and res.origin == "generated"
    assert "the table read from the original synthc 1.00" in res.notes[0]
    assert not os.path.exists(R.table_path(hashlib.sha1(bytes(ours)).hexdigest()))
    # and a second Write to that card still finds it (the settings route)
    assert SM.identify(SM.ElfImage(bytes(ours)), SM.tables(), "synthc", "1.00")[1] == "settings"


def test_a_program_holding_this_apps_text_segment_is_not_read_as_stock():
    from pinball_decryptor.plugins.stern.progreloc import EXT_MAGIC
    data, _sites = c_title()
    ours = data + EXT_MAGIC + b"\0" * 8
    assert R.stock_state(ours)[0] == "ours"
    res = R.ensure_table(ours, "synthc", "1.00")
    assert res.build is None and "changed by this app" in res.notes[0]


def test_cancel_stops_before_the_read_and_saves_nothing():
    data, _sites = c_title()
    with pytest.raises(TR.Cancelled):
        R.ensure_table(data, "synthc", "1.00", cancel=lambda: True)
    assert not os.path.exists(R.table_path(hashlib.sha1(data).hexdigest()))


def test_something_that_isnt_a_game_program_says_so():
    res = R.ensure_table(b"not an elf at all", "x", "1.0")
    assert res.build is None and res.notes


class _Reader:
    """The slice of Ext4Reader compute_writes touches: one file on a flat disk."""

    def __init__(self, data):
        self.data = data
        self.fw_node = {"size": len(data)}

    def read_file_bytes(self, node):
        return self.data

    def disk_ranges(self, node, off, length):
        return [(off, length)]


def _project(tmp_path, card_name):
    import json
    p = tmp_path / "proj"
    p.mkdir()
    (p / ".extract_source.json").write_text(json.dumps({
        "input_path": "D:\\x\\" + card_name, "input_name": card_name, "size": 1, "mtime": 1}),
        encoding="utf-8")
    return str(p)


# ---- the tracker and the grammar --------------------------------------------------------------------
def test_the_tracker_reads_a_mov_movt_award_a_conditional_and_field_facts():
    callee = TEXT_VA + 0x100
    w = [PUSH,                                   # 00
         0xE1A04000,                             # 04 mov r4, r0             (this)
         0xE3A02D35,                             # 08 mov r2, #0xd40
         0xE3A03000,                             # 0c mov r3, #0
         0xE3402003,                             # 10 movt r2, #3            -> 200,000
         0xE5940030,                             # 14 ldr r0, [r4, #0x30]    (a field)
         0,                                      # 18 bl callee
         0xE3A0501E,                             # 1c mov r5, #30
         0xE5845080,                             # 20 str r5, [r4, #0x80]    (this->+0x80 = 30)
         0x83A01064,                             # 24 movhi r1, #100         (one path only)
         0xE1A00004,                             # 28 mov r0, r4
         0,                                      # 2c bl callee
         0xE5943078,                             # 30 ldr r3, [r4, #0x78]    (the timer object)
         0xE5932000,                             # 34 ldr r2, [r3]           (its vtable)
         0xE1A00003,                             # 38 mov r0, r3
         0xE3A0102D,                             # 3c mov r1, #45
         0xE592C03C,                             # 40 ldr ip, [r2, #0x3c]    (slot 15)
         0xE12FFF3C,                             # 44 blx ip
         POP]                                    # 48
    w[6] = bl(TEXT_VA + 0x18, callee)
    w[11] = bl(TEXT_VA + 0x2C, callee)
    w += [0xE320F000] * ((0x100 - 4 * len(w)) // 4) + [0xE12FFF1E]
    prog = SS.Program(elf(w))
    t = SS.track(prog, TEXT_VA)
    c1, c2 = t.calls[0], t.calls[1]
    assert c1["args"]["r0"] == SS.Sym("field", 0x30)
    kind, words = SS.kind_of(c1["args"]["r2"])
    assert c1["args"]["r2"].v == 200000 and kind == ("movwt", TEXT_VA + 8, TEXT_VA + 0x10)
    assert SM.decode("movwt", tuple(int(x, 16) for x in words)) == 200000
    assert c2["args"]["r1"].cond and c2["args"]["r1"].v == 100
    assert t.stores[0x80].v == 30
    (vc,) = t.vcalls
    assert vc["obj"] == SS.Sym("field", 0x78) and vc["slot"] == 15 and vc["args"]["r1"].v == 45


def test_a_strd_of_a_constant_pair_is_recorded_unconditional():
    w = [PUSH, 0xE30866A0, 0xE3A07000, 0xE3406001,   # movw r6 / mov r7, #0 / movt r6 -> 100,000
         0xE1C068F0,                                 # strd r6, r7, [r0, #0x80]
         POP]
    prog = SS.Program(elf(w))
    (va, lo, hi, base, off), = SS.track(prog, TEXT_VA).strd64
    assert (va, lo.v, hi.v, base, off) == (TEXT_VA + 0x10, 100000, 0, SS.THIS, 0x80)


def _two_site_table(data, va1, va2, klass="word"):
    return ("build two 1.0 sha1 %s\nmode 5 ctwo obj 0x0 vtable 0x0 title_msg ? name Two_Sites\n"
            "number 5 timer.seconds 16 imm 0x%x 0x%x e3a01010,e3a01010 %s  # two words\n"
            % (hashlib.sha1(data).hexdigest(), va1, va2, klass))


def test_one_number_at_two_sites_is_one_row_written_together(tmp_path):
    w = [0xE3A01010, 0xE320F000, 0xE3A01010, 0xE12FFF1E]       # mov r1,#16 at two sites
    data = elf(w)
    b = SM.parse(_two_site_table(data, TEXT_VA, TEXT_VA + 8))[0]
    n = b.number("5.timer.seconds")
    assert b.mode_name(5) == "Two Sites"
    assert n.vas == (TEXT_VA, TEXT_VA + 8) and n.editable and n.value == 16
    assert SM.encode("imm", n.words, 20) == (0xE3A01014, 0xE3A01014)
    assert SM.site_state(SM.ElfImage(data), n)[0] == "stock"
    project = _project(tmp_path, "two-1_0_0.raw")
    SM.stage(project, b, n, 20)
    overlay, count, _b = SM.plan_overlay(data, project, None, builds=[b])
    assert count == 1 and overlay == {TEXT_OFF: struct.pack("<I", 0xE3A01014),
                                      TEXT_OFF + 8: struct.pack("<I", 0xE3A01014)}
    # two sites that disagree don't read as one number
    assert SM.decode("imm", (0xE3A01010, 0xE3A01014)) is None


def test_an_uncertain_row_is_read_only_and_says_why():
    data = elf([0xE3A01010, 0xE12FFF1E])
    text = ("build u 1.0 sha1 %s\nmode 1 cu obj 0x0 vtable 0x0 title_msg ?\n"
            "number 1 reset.award_value 16 imm 0x%x e3a01010 uncertain  # which part of the award "
            "record this is isn't decoded; v[20] stores it\n" % (hashlib.sha1(data).hexdigest(),
                                                                 TEXT_VA))
    n = SM.parse(text)[0].number("1.reset.award_value")
    assert not n.editable
    assert "can't be sure" in n.why_read_only() and "isn't decoded" in n.why_read_only()
    with pytest.raises(SM.StockModeError):
        SM.check_value(n, 20)


def test_a_slot_the_reader_didnt_name_reads_as_other():
    n = SM.Number(1, "v41.caward_add@3", 5, "imm", (1,), (0xE3A00005,), "word")
    assert n.label == "Other award (3)"


# ---- the real game programs --------------------------------------------------------------------------
# Rows of the hand tables the structural reader reads differently, each checked by hand:
#  * Godzilla's battle vs Ebirah shot awards: `mov r2, #0xd40; movt r2, #3` is 200,000 in two
#    words; item 144's reader took a movt after a mov for a computed value (code);
#  * the scaled-award multiplier and the constructor's start value were added to the hand table
#    by hand (item 144/145), not by its reader.
KNOWN_HAND_ONLY = {"shot.caward_add_scaled.mult", "timer.seconds.ctor"}


@pytest.mark.parametrize("name,build_id", [("godzilla_pro-1.15.0", "godzilla_pro 1.15"),
                                           ("godzilla_le-1.16.0", "godzilla_le 1.16")])
def test_the_godzilla_tables_regenerate_the_hand_tables_rows(name, build_id):
    data = real_elf(name)
    hand = next(b for b in SM.hand_tables() if b.id == build_id)
    text, info = R.generate(data, hand.game, hand.version)
    gen = SM.parse(text)[0]
    assert info["family"] == "cmode" and sorted(gen.modes) == sorted(hand.modes)

    def sig(n):
        return (n.mode_id, n.value, n.kind, tuple(n.args))
    got = {sig(n): n for n in gen.numbers}
    missing = [n for n in hand.numbers if n.is_player_facing and sig(n) not in got]
    unexplained = [n.row_key for n in missing
                   if n.key.split("@")[0] not in KNOWN_HAND_ONLY
                   and not (n.mode_id == 12 and n.kind == "code" and "caward_add" in n.key)]
    assert not unexplained
    reproduced = sum(1 for n in hand.numbers if n.is_player_facing and sig(n) in got)
    assert reproduced >= 82
    # the rows it reads where item 144 saw code are the movwt the instructions hold
    shot = [n for n in gen.numbers if n.mode_id == 12 and n.key.startswith("v")
            and "caward_add" in n.key and n.value == 200000]
    assert len(shot) == 6 and all(n.kind == "movwt" and n.editable for n in shot)


def test_beatles_lists_its_modes_with_the_timers_as_settings(tmp_path):
    data = real_elf("beatles-1.29.0")
    res = R.ensure_table(data, "beatles", "1.29.0")
    b = res.build
    assert res.origin == "generated" and b.id == "beatles 1.29.0"
    assert [b.mode_name(i) for i in sorted(b.modes)] == [
        "All My Loving", "Drive My Car", "Should Have Known Better", "Ticket to Ride",
        "It Won't Be Long", "Main Multiball"]                  # the apostrophe the audit lost
    dmc = b.number("2.timer.adjustment")
    assert (dmc.adj_name, dmc.value, dmc.adj_range, dmc.editable) == (
        "AD_MODE_DRIVE_MY_CAR_TIMER", 30, (20, 60), True)
    assert all(n.editable for n in b.numbers)
    # the end-to-end Write: the Drive My Car timer at 45 is its compiled default
    project = _project(tmp_path, "beatles-1_29_0.Release.8G.sdcard.raw")
    build = SM.table_for_project(project)
    SM.stage(project, build, build.number("2.timer.adjustment"), 45)
    rdr = _Reader(data)
    _w, overlay, n = SM.compute_writes(rdr, rdr.fw_node, project, None)
    off = AdjustmentTable(data).default_file_offset("AD_MODE_DRIVE_MY_CAR_TIMER")
    assert n == 1 and overlay == {off: struct.pack("<i", 45)}


def test_tmnt_episode_one_has_its_timer_and_start_award_as_words(tmp_path):
    data = real_elf("turtles_pro-1.59.0")
    res = R.ensure_table(data, "turtles_pro", "1.59.0")
    b = res.build
    assert b.mode_name(28) == "Episode One"
    t = b.number("28.timer.seconds")
    a = b.number("28.start.caward_add")
    assert (t.value, t.kind, t.args, t.editable) == (30, "imm", (0x61DB0,), True)
    assert (a.value, a.kind, a.args, a.editable) == (250000, "movwt", (0x65014, 0x65024), True)
    assert not b.number("28.reset.award_value").editable       # an undecoded award field
    project = _project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw")
    build = SM.table_for_project(project)
    SM.stage(project, build, t, 45)
    SM.stage(project, build, a, 500000)
    rdr = _Reader(data)
    _w, overlay, n = SM.compute_writes(rdr, rdr.fw_node, project, None)
    img = SM.ElfImage(data)
    want = {img.va_to_off(0x61DB0): struct.pack("<I", SM.encode("imm", t.words, 45)[0])}
    lo, hi = SM.encode("movwt", a.words, 500000)
    want[img.va_to_off(0x65014)] = struct.pack("<I", lo)
    want[img.va_to_off(0x65024)] = struct.pack("<I", hi)
    assert n == 2 and overlay == want
    assert SM.encode("imm", t.words, 45)[0] == 0xE3A0702D
    # the card that Write makes keeps this table (the instruction route), never read as stock
    ours = bytearray(data)
    for o, w in overlay.items():
        ours[o:o + 4] = w
    again = R.ensure_table(bytes(ours), "turtles_pro", "1.59.0")
    assert again.build.sha1 == b.sha1 and "original" in again.notes[0]
    assert not os.path.exists(R.table_path(hashlib.sha1(bytes(ours)).hexdigest()))


def test_munsters_duration_is_one_row_over_two_words():
    data = real_elf("munsters_le-1.28.0")
    text, _info = R.generate(data, "munsters_le", "1.28.0")
    b = SM.parse(text)[0]
    n = b.number("3.timer.seconds")
    assert n.kind == "imm" and len(n.args) == 2 and n.value == 30 and n.editable
    img = SM.ElfImage(data)
    assert SM.site_state(img, n)[0] == "stock"


@pytest.mark.parametrize("name", ["king_kong_le-0.97.0", "rush_le-1.18.0", "jaws_le-1.02.0",
                                  "stranger_things_le-1.12.0"])
def test_other_builds_read_and_every_word_row_is_the_programs_own(name):
    data = real_elf(name)
    text, info = R.generate(data, *name.rsplit("-", 1))
    b = SM.parse(text)[0]
    assert b.modes and info["seconds"] < 30
    img = SM.ElfImage(data)
    for n in b.numbers:
        if n.klass in ("word", "uncertain") and n.kind in SM.WORD_KINDS:
            assert SM.site_state(img, n)[0] == "stock" and n.words_agree, n.row_key


@pytest.mark.parametrize("name", [None, "rush_le-1.18.0", "beatles-1.29.0"])
def test_the_fast_settings_table_reads_what_the_class_reads(name):
    data = c_title()[0] if name is None else real_elf(name)
    a, f = AdjustmentTable(data), SS.settings_table(SS.Program(data))
    assert (f.names, f.table_va, f.count, f.elem, f.node, f.record_va) == (
        a.names, a.table_va, a.count, a.elem, a.node, a.record_va)


def test_the_class_scans_skip_a_big_asset_blob_and_keep_the_real_classes():
    data = real_elf("led_zeppelin_le-1.22.0")
    prog = SS.Program(data)
    assert prog.asset_blob() is not None
    model = SS.class_model(prog)
    # a coincidental word in the assets used to stand for this mode class's typeinfo
    m = model["cthe_song_remains_the_same"]
    assert m["base"] == "cmode" and m["vtable"]


def test_the_tabs_dialog_and_the_write_scan_see_a_generated_table(tmp_path):
    """The callers of the tables need no change: once a card's table is generated, the Modes
    tab's dialog lists its numbers, a value staged there is a Write-scan row and the engine's
    guard counts it."""
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import write_scan as WS
    from pinball_decryptor.plugins.stern import engine
    data, _sites = c_title()
    R.ensure_table(data, "synthc", "1.00")
    project = _project(tmp_path, "synthc-1_00_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("modes")

        def go():
            svc._project_var().set(project)
            svc.refresh_stock_modes()
        w.run(go)
        st = w.state("modes")["stock"]
        assert st["on"] and st["msg"].lower().startswith("synthc 1.00: 3 number(s)")
        assert [(r["mode"], r["number"], r["value"]) for r in st["rows"]] == [
            ("Alpha", "Timer", "30"), ("Alpha", "Shots", "4"),
            ("Bravo Multiball", "Ball Save Seconds", "15")]
        w.run(svc.stage_stock_value, "1.timer.adjustment", 45)
    mfr = type("M", (), {"capabilities": type("C", (), {"modes": True})()})()
    rows = WS.stock_mode_rows(mfr, project)
    assert len(rows) == 1 and "Alpha timer: 30 -> 45" in rows[0][0]
    assert SM.pending_count(project) == 1 and engine._stock_mode_pending(project) == 1


# ---- where a function ends, and who else reads a constant ----------------------------------------
def b_(site, target, cond=0xE):
    return cond << 28 | 0x0A000000 | (((target - site - 8) >> 2) & 0xFFFFFF)


def str_(rt, rn, imm):
    return 0xE5800000 | rn << 16 | rt << 12 | imm


CMP_R0_0, MOV_R4_R0, POP_R4_LR = 0xE3500000, 0xE1A04000, 0xE8BD4010
NOP, BXLR = 0xE320F000, 0xE12FFF1E


def test_a_tail_call_ends_the_function_and_the_next_function_is_not_its_code():
    """A thunk (``b`` as the first instruction) and a function ending ``pop; b other`` are
    one-branch tail calls: the award-like call in the function after them is not theirs."""
    callee = TEXT_VA + 0x100
    w = [0] * 16
    w[0] = b_(TEXT_VA, TEXT_VA + 0x20)                   # 00 thunk: b 0x20
    w[1:5] = [PUSH, MOV_R4_R0, POP_R4_LR, 0]             # 04 push; mov r4,r0; pop {r4,lr}
    w[4] = b_(TEXT_VA + 0x10, TEXT_VA + 0x20)            # 10 b 0x20 (a tail call)
    w[8:13] = [PUSH, 0xE3A02D35, 0xE3A03000, 0, POP]     # 20 push; mov r2,#0xd40; mov r3,#0
    w[11] = bl(TEXT_VA + 0x2C, callee)                   # 2c bl callee
    w += [NOP] * ((0x100 - 4 * len(w)) // 4) + [BXLR]
    prog = SS.Program(elf(w))
    thunk, tail = SS.track(prog, TEXT_VA), SS.track(prog, TEXT_VA + 4)
    assert thunk.end == TEXT_VA + 4 and tail.end == TEXT_VA + 0x14
    for t in (thunk, tail):
        assert [(c["target"], c["tail"]) for c in t.calls] == [(TEXT_VA + 0x20, True)]
    (own,) = SS.track(prog, TEXT_VA + 0x20).calls
    assert own["target"] == callee and own["args"]["r2"].v == 0xD40


def test_code_nothing_branches_to_starts_with_no_constants():
    callee = TEXT_VA + 0x100
    w = [PUSH, CMP_R0_0, b_(TEXT_VA + 8, TEXT_VA + 0x18, cond=0x0),   # beq 0x18
         0xE3A02033, POP, 0, POP]                                     # mov r2,#0x33 / pop
    w[5] = bl(TEXT_VA + 0x14, callee)                                 # 14: after a return
    w += [NOP] * ((0x100 - 4 * len(w)) // 4) + [BXLR]
    prog = SS.Program(elf(w))
    (call,) = SS.track(prog, TEXT_VA).calls
    assert call["va"] == TEXT_VA + 0x14 and "r2" not in call["args"]


@pytest.fixture
def need_capstone():
    pytest.importorskip("capstone")


def test_other_uses_finds_a_second_store_of_the_same_register(need_capstone):
    w = [PUSH, MOV_R4_R0, 0xE3A02014,                       # mov r2, #20
         str_(2, 4, 0xA4), str_(2, 4, 0xCC), POP]           # str r2,[r4,#0xa4] / [r4,#0xcc]
    prog = SS.Program(elf(w))
    t = SS.track(prog, TEXT_VA)
    v = t.stores[0xA4]
    assert t.store_at[0xA4] == TEXT_VA + 0xC
    assert SS.other_uses(prog, v, t, t.store_at[0xA4]) == [TEXT_VA + 0x10]
    one = SS.Program(elf(w[:4] + [POP]))
    t1 = SS.track(one, TEXT_VA)
    assert SS.other_uses(one, t1.stores[0xA4], t1, t1.store_at[0xA4]) == []


def test_other_uses_follows_a_branch_and_stops_where_the_register_is_replaced(need_capstone):
    callee = TEXT_VA + 0x100
    w = [0xE92D4030, MOV_R4_R0, 0xE3A05007,                 # push {r4,r5,lr}; mov r5, #7
         CMP_R0_0, b_(TEXT_VA + 0x10, TEXT_VA + 0x1C, cond=0x0),   # beq 0x1c
         str_(5, 4, 0x10), 0xE8BD8030,                      # 14 str r5,[r4,#0x10]; pop
         str_(5, 4, 0x20), 0xE3A05000, str_(5, 4, 0x24),    # 1c str r5,[r4,#0x20]; mov r5,#0; str
         0xE3A02C7D, 0xE3A03000, 0, 0xE8BD8030]             # 28 mov r2,#0x7d00; mov r3,#0; bl
    w[12] = bl(TEXT_VA + 0x30, callee)
    w += [NOP] * ((0x100 - 4 * len(w)) // 4) + [BXLR]
    prog = SS.Program(elf(w))
    t = SS.track(prog, TEXT_VA)
    five = SS.Val(7, [(TEXT_VA + 8, w[2], "imm")])
    # read at 0x14 on one path and at 0x1c on the other; the store at 0x24 is of the new r5
    assert SS.other_uses(prog, five, t, TEXT_VA + 0x14) == [TEXT_VA + 0x1C]
    (call,) = t.calls
    assert SS.other_uses(prog, call["args"]["r2"], t, call["va"]) == []


def test_rows_at_the_same_words_are_one_row_and_carry_the_modes_sharing_them():
    r = SS.Reading("crule")
    a, b = SS.ModeRead(1, "ca", "A"), SS.ModeRead(2, "cb", "B")
    a.add("timer.v17", 40, ("imm", 0x100), ["e3a02028"], "uncertain", "slot 17")
    a.add("timer.seconds", 40, ("imm", 0x100), ["e3a02028"], "word", "the duration")
    a.add("title_msg", 7, ("movw", 0x200), ["e3000007"], "word", "v[57] returns it")
    b.add("title_msg", 7, ("movw", 0x200), ["e3000007"], "word", "v[57] returns it")
    r.modes += [a, b]
    SS.settle_shared(r)
    (timer,) = [x for x in a.rows if x.vas == (0x100,)]
    assert timer.key == "timer.seconds" and timer.klass == "uncertain"
    assert "timer.v17" in timer.comment
    assert [x.shared for x in a.rows + b.rows if x.key == "title_msg"] == [2, 2]


# ---- a card this app wrote, opened before its original -------------------------------------------
@pytest.fixture
def synthc_known(monkeypatch):
    """The synthetic title's program as a build Stern shipped (KNOWN_STOCK)."""
    data, _sites = c_title()
    monkeypatch.setitem(R.KNOWN_STOCK, hashlib.sha1(data).hexdigest(), "synthc 1.00")
    return data


def _written(data):
    ours = bytearray(data)
    off = AdjustmentTable(data).default_file_offset("AD_MODE_ALPHA_TIMER")
    struct.pack_into("<i", ours, off, 45)                  # what a Write of 45 leaves
    return bytes(ours)


def test_a_written_card_read_before_its_original_is_refused_not_taken_as_stock(synthc_known):
    ours = _written(synthc_known)
    res = R.ensure_table(ours, "synthc", "1.0")
    assert res.build is None and "isn't the one Stern shipped as synthc 1.00" in res.notes[0]
    assert R.load_index() == {} and not os.path.exists(
        R.table_path(hashlib.sha1(ours).hexdigest()))
    # the original is then read from itself, with its own numbers
    orig = R.ensure_table(synthc_known, "synthc", "1.00")
    assert orig.origin == "generated" and orig.build.sha1 == hashlib.sha1(synthc_known).hexdigest()
    assert orig.build.number("1.timer.adjustment").value == 30
    assert R.load_index()[orig.build.sha1]["stock"] == "known"
    # and the written card now gets the original's table
    again = R.ensure_table(ours, "synthc", "1.00")
    assert again.build.sha1 == orig.build.sha1 and "original synthc 1.00" in again.notes[0]


def test_a_stock_program_is_read_from_itself_even_when_a_written_card_matches(synthc_known):
    """A table kept for a written copy never stands in for a program KNOWN_STOCK names: the
    known program is read from itself, and both tables stay listed (the index is by SHA-1)."""
    ours = _written(synthc_known)
    text, _info = R.generate(ours, "synthc", "1.00")
    R.save_table(text, "synthc", "1.00", hashlib.sha1(ours).hexdigest(), "unknown")
    res = R.ensure_table(synthc_known, "synthc", "1.00")
    assert res.build.sha1 == hashlib.sha1(synthc_known).hexdigest()
    assert res.build.number("1.timer.adjustment").value == 30
    assert set(R.load_index()) == {hashlib.sha1(ours).hexdigest(), res.build.sha1}
    # the stock program's table is the one a title lookup finds first
    assert SM.table_for("synthc", "1.00").sha1 == res.build.sha1


def test_a_table_that_cannot_be_kept_is_still_returned(monkeypatch):
    data, _sites = c_title()

    def refuse(*_a, **_k):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(R, "save_table", refuse)
    res = R.ensure_table(data, "synthc", "1.00")
    assert res.build is not None and res.build.mode_name(1) == "Alpha"
    assert any("couldn't be kept" in n for n in res.notes)


def test_a_cut_off_game_program_says_so():
    data, _sites = c_title()
    res = R.ensure_table(data[:TEXT_OFF + 16], "synthc", "1.00")
    assert res.build is None and res.notes


# ---- the real game programs: every editable number is its own ------------------------------------
def _real_table(name):
    data = real_elf(name)
    text, _info = R.generate(data, *name.rsplit("-", 1))
    return data, text, SM.parse(text)[0]


def _overrides(text):
    out, cur = {}, None
    import re
    for line in text.splitlines():
        m = re.match(r"mode (\d+) ", line)
        if m:
            cur = int(m.group(1))
        if line.startswith("# overrides:"):
            out[cur] = {int(k): int(f, 16)
                        for k, f in re.findall(r"v\[(\d+)\]=0x([0-9a-f]+)", line)}
    return out


def _linear_reads(prog, cs, va_def, limit=400):
    """An independent count (capstone, straight-line) of reads of the register the
    instruction at *va_def* writes, until it is written again, a call, a branch or a return."""
    def ins(va):
        return next(cs.disasm(struct.pack("<I", prog.word(va)), va), None)
    i = ins(va_def)
    regs = {cs.reg_name(x) for x in i.regs_access()[1]} - {"pc"}
    reads = []
    for va in range(va_def + 4, va_def + 4 * limit, 4):
        j = ins(va)
        if j is None:
            continue
        r, w = ({cs.reg_name(x) for x in s} for s in j.regs_access())
        if r & regs:
            reads.append(va)
        if j.mnemonic in ("bl", "blx") or (j.mnemonic.startswith(("b", "bx")) and
                                           j.mnemonic in ("b", "bx")):
            if j.mnemonic in ("bl", "blx") and regs & {"r0", "r1", "r2", "r3"}:
                reads.append(va)
            if j.mnemonic in ("b", "bx") or regs & {"r0", "r1", "r2", "r3", "ip"}:
                break
        if j.mnemonic.startswith("pop") and "pc" in j.op_str:
            break
        if (w & regs) and j.mnemonic != "movt" and not (r & regs):
            break
    return sorted(set(reads))


@pytest.mark.parametrize("name", ["avengers_infinity_le-1.09.0", "dungeons_and_dragons_le-1.00.0",
                                  "led_zeppelin_le-1.22.0", "john_wick_le-1.01.0",
                                  "turtles_pro-1.59.0", "star_wars_le-1.30.0",
                                  "sword_of_rage_le-1.18.0", "iron_maiden_le-1.16.0"])
def test_every_editable_word_is_that_numbers_own(name, need_capstone):
    """Checks independent of the reader's own code: an editable call row's
    call is inside the function it names, an editable instruction's register is read once,
    rows sharing words across modes say so, one mode never lists one word twice, and a timer
    number the reader couldn't name is never editable."""
    import collections
    import re
    import capstone
    data, text, b = _real_table(name)
    prog = SS.Program(data)
    cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    cs.detail = True
    over = _overrides(text)
    for n in b.numbers:
        if not (n.is_word and n.editable):
            continue
        assert not re.match(r"timer\.v\d", n.key), n.row_key
        m = re.search(r"v\[(\d+)\] call 0x([0-9a-f]+)", n.comment)
        if m and int(m.group(1)) in over.get(n.mode_id, {}):
            fn, call = over[n.mode_id][int(m.group(1))], int(m.group(2), 16)
            assert fn <= call and prog.func_start(call) <= fn, n.row_key
        if n.kind in ("imm", "movw", "movwt"):
            for d in ([n.vas[1]] if n.kind == "movwt" else n.vas):
                assert len(_linear_reads(prog, cs, d)) <= 1, (n.row_key, hex(d))
    by = collections.defaultdict(list)
    for n in b.numbers:
        if n.is_word and n.klass in ("word", "uncertain"):
            for va in n.vas:
                by[va].append(n)
    for va, ns in by.items():
        modes = collections.Counter(x.mode_id for x in ns)
        assert max(modes.values()) == 1, [x.row_key for x in ns]
        for x in ns:
            assert not x.editable or len(modes) == 1 or x.shared >= len(modes), x.row_key


def test_words_read_twice_or_held_by_two_modes_on_real_builds(need_capstone):
    _d, _t, dnd = _real_table("dungeons_and_dragons_le-1.00.0")
    t = dnd.number("39.timer.seconds")
    assert not t.editable and "also feeds 0x1ec63c" in t.comment
    _d, _t, sw = _real_table("star_wars_le-1.30.0")
    assert [sw.number("%d.title_msg" % i).shared for i in (19, 20)] == [2, 2]
    _d, _t, av = _real_table("avengers_infinity_le-1.09.0")
    assert not [n.row_key for n in av.numbers if 0xCEC74 in n.vas and n.mode_id != 19]
    _d, _t, jw = _real_table("john_wick_le-1.01.0")
    assert not jw.number("23.timer.v16").editable


def test_a_written_tmnt_card_read_first_is_refused_and_the_original_reads_itself():
    data = real_elf("turtles_pro-1.59.0")
    res = R.ensure_table(data, "turtles_pro", "1.59.0")
    ep = res.build.number("28.timer.seconds")
    ours = bytearray(data)
    img = SM.ElfImage(data)
    ours[img.va_to_off(0x61DB0):img.va_to_off(0x61DB0) + 4] = struct.pack(
        "<I", SM.encode("imm", ep.words, 45)[0])
    ours = bytes(ours)
    # a fresh machine: nothing cached
    os.remove(R.table_path(res.build.sha1))
    os.remove(os.path.join(R.user_tables_dir(), R.INDEX))
    R._CACHE.update({"index_key": None, "builds": [], "parsed": {}})
    first = R.ensure_table(ours, "turtles_pro", "1.59")
    assert first.build is None and "Stern shipped as turtles_pro 1.59.0" in first.notes[0]
    orig = R.ensure_table(data, "turtles_pro", "1.59.0")
    assert orig.build.sha1 == res.build.sha1 and orig.build.number("28.timer.seconds").value == 30
    again = R.ensure_table(ours, "turtles_pro", "1.59.0")
    assert again.build.sha1 == res.build.sha1
