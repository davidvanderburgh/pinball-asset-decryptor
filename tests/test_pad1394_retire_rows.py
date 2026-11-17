"""PAD-1394: a card written again from a card the app wrote before kept the menu rows of settings now switched off
(EDITION, HANDICAP, the shared MORE SETTINGS rows) listed on their page with nothing reading them: the planner only ever
added records to the menu's table. Now every Write takes off the rows of ours it no longer wants - out of the table it
grows, else by a same-size shrink in place - and a Write that wants none of our settings does it too."""
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label

from tests.test_pad1382_more_settings import LE116, PRO116, _program, _wanted
from tests.test_pad724_menu_every_title import AERO

MUSIC = (MS.MUSIC_MODE, 3, ["Standard", "Orchestral", "Stoner"])
EDITION = (MS.EDITION, 2, ["One", "Two"])
IMAGE = (MS.IMAGE_SET, 2, ["Standard", "Kaiju"])
HANDI = (MS.HANDICAP, 2, ["Off", "On"], {"onoff": True})
OURS = {v[1] for v in MS.SETTINGS.values()}
CARDS = pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])


def _write(raw, tmp, wanted):
    """*raw* after a Write of *wanted* (``plan_many``): the same-size writes, and the grown table placed in the program's
    text extension segment the way the engine places it. ``(program, settings)``."""
    from pinball_decryptor.plugins.stern import engine as E
    t = AdjustmentTable(raw)
    settings, writes, cat, refused = MS.plan_many(t, wanted)
    assert refused == {}
    if cat is None:
        b = bytearray(raw)
        for off, data in writes.items():
            b[off:off + len(data)] = data
        return bytes(b), settings
    reloc, why = E._text_reloc_plan(raw)
    assert reloc, why
    va = reloc["base_va"] + reloc["used"]
    fw = list(writes.items()) + list(MS.table_writes(t, cat, va, *settings).items())
    os.makedirs(str(tmp), exist_ok=True)
    grown = E._grow_program_text(raw, fw, MS.table_blob(cat, *settings), reloc, None, str(tmp), None,
                                 lambda *a, **k: None)
    with open(grown["path"], "rb") as f:
        return f.read(), settings


def _ours_listed(raw):
    t = AdjustmentTable(raw)
    cat = MS.menu_table(t)
    return sorted(menu_label(t, i) for _c, i in MS.listed_rows(cat) if menu_label(t, i) in OURS), cat


@CARDS
def test_rows_switched_off_leave_the_menu(card, tmp_path):
    stock = _program(card)
    n_stock = len(MS.menu_table(AdjustmentTable(stock)).records)
    earlier, _s = _write(stock, tmp_path / "a", [MUSIC, EDITION, HANDI])
    assert _ours_listed(earlier)[0] == ["EDITION", "HANDICAP", "MUSIC MODE"]   # the card the app wrote before
    again, settings = _write(earlier, tmp_path / "b", [MUSIC])
    listed, cat = _ours_listed(again)
    assert listed == ["MUSIC MODE"] and len(cat.records) == n_stock + 1
    assert MS.check(again, settings[0]) == []
    # the menu re-reads at the shorter size (the copy's constants say it), and a third Write changes nothing
    assert MS.category_table(AdjustmentTable(again)) == cat
    _s, writes, cat3, refused = MS.plan_many(AdjustmentTable(again), [MUSIC])
    assert refused == {} and cat3 is None
    assert MS.stale_rows(AdjustmentTable(again), cat, _s) == []


@CARDS
def test_a_row_reused_for_another_setting_stays_and_the_rest_go(card, tmp_path):
    earlier, _s = _write(_program(card), tmp_path / "a", [MUSIC, EDITION, HANDI])
    again, settings = _write(earlier, tmp_path / "b", [MUSIC, IMAGE])
    assert _ours_listed(again)[0] == ["IMAGE SET", "MUSIC MODE"]
    assert [MS.check(again, s) for s in settings] == [[], []]


@CARDS
def test_a_write_wanting_none_takes_every_row_of_ours_off(card, tmp_path):
    stock = _program(card)
    stock_cat = MS.menu_table(AdjustmentTable(stock))
    earlier, _s = _write(stock, tmp_path / "a", [MUSIC, EDITION, HANDI])
    writes, gone = MS.retire(AdjustmentTable(earlier))
    assert sorted(gone) == ["EDITION", "HANDICAP", "MUSIC MODE"]
    b = bytearray(earlier)
    for off, data in writes.items():
        b[off:off + len(data)] = data
    listed, cat = _ours_listed(bytes(b))
    assert listed == [] and cat.records == stock_cat.records         # the game's own menu again
    assert MS.retire(AdjustmentTable(bytes(b))) == ({}, [])
    assert MS.retire(AdjustmentTable(stock)) == ({}, [])             # a stock program has nothing to retire
    # and a later Write can put a row back on the shrunk table
    back, settings = _write(bytes(b), tmp_path / "c", [EDITION])
    assert _ours_listed(back)[0] == ["EDITION"] and MS.check(back, settings[0]) == []


@CARDS
def test_the_shared_rows_go_when_the_settings_fit_rows_of_their_own(card, tmp_path):
    earlier, settings = _write(_program(card), tmp_path / "a", _wanted(music=True))
    assert any(MS.is_shared(s) for s in settings)
    assert {"MORE SETTINGS", "SETTING VALUE"} <= set(_ours_listed(earlier)[0])
    again, _s = _write(earlier, tmp_path / "b", [MUSIC])
    assert _ours_listed(again)[0] == ["MUSIC MODE"]


def test_the_standard_adjustments_list_drops_them_too(tmp_path):
    stock = _program(AERO)
    ids = MS.menu_table(AdjustmentTable(stock)).ids
    earlier, _s = _write(stock, tmp_path / "a", [MUSIC, EDITION])
    assert MS.menu_table(AdjustmentTable(earlier)).ids == ids + (31, 33)
    again, settings = _write(earlier, tmp_path / "b", [MUSIC])
    assert MS.menu_table(AdjustmentTable(again)).ids == ids + (31,)
    assert MS.check(again, settings[0]) == []
    writes, gone = MS.retire(AdjustmentTable(again))
    b = bytearray(again)
    for off, data in writes.items():
        b[off:off + len(data)] = data
    assert gone == ["MUSIC MODE"] and MS.menu_table(AdjustmentTable(bytes(b))).ids == ids


class _Reader:
    """A card reader over one file's bytes (the engine's ext4 reader's calls), counting whole-file reads."""

    def __init__(self, data):
        self.data, self.whole = data, 0

    def read_range(self, _node, off, n):
        return self.data[off:off + n]

    def read_file_bytes(self, _node):
        self.whole += 1
        return self.data

    def disk_ranges(self, _node, off, n):
        return [(1000000 + off, n)]


@CARDS
def test_the_engine_step_for_a_write_wanting_none(card, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    said = []
    log = lambda m, *a: said.append(m)                                # noqa: E731
    stock = _program(card)
    r = _Reader(stock)
    assert E._retire_menu_rows(r, {}, log) == ([], {}, 0) and r.whole == 0   # its header alone said no
    earlier, _s = _write(stock, tmp_path / "a", [MUSIC, EDITION])
    r = _Reader(earlier)
    writes, ov, n = E._retire_menu_rows(r, {}, log)
    assert n == 2 and writes == [(1000000 + o, b) for o, b in sorted(ov.items())]
    assert "EDITION" in said[-1] and "MUSIC MODE" in said[-1] and "taken off the menu" in said[-1]
    b = bytearray(earlier)
    for off, data in ov.items():
        b[off:off + len(data)] = data
    assert _ours_listed(bytes(b))[0] == []
    # a staged whole-file program takes them in the file, with no in-place write
    staged = tmp_path / "game"
    staged.write_bytes(earlier)
    assert E._retire_menu_rows(_Reader(b""), {}, log, patched_fw=str(staged))[:2] == ([], {})
    assert _ours_listed(staged.read_bytes())[0] == []


def test_a_spike3_program_drops_them_too():
    from pinball_decryptor.plugins.stern import spike3_menu as S3
    from tests.test_pad1321_spike3_menu_rows import program
    _g, _v, elf = program("star_wars_elg")
    n_stock = len(MS.menu_table(AdjustmentTable(elf, wide_ok=True)).records)
    earlier, placed, refused = S3.grow(elf, [MUSIC, EDITION])
    assert refused == {} and len(placed) == 2
    t = AdjustmentTable(earlier, wide_ok=True)
    assert len(MS.menu_table(t).records) == n_stock + 2
    again, placed, refused = S3.grow(earlier, [MUSIC])           # in place: nothing new to list
    nt = AdjustmentTable(again, wide_ok=True)
    cat = MS.menu_table(nt)
    assert refused == {} and len(cat.records) == n_stock + 1
    assert sorted(menu_label(nt, i) for _c, i in MS.listed_rows(cat) if menu_label(nt, i) in OURS) == ["MUSIC MODE"]
    MS.wide_copy_sites(nt, cat)                                      # the copy reads at the shorter size
    back, placed, refused = S3.grow(again, [MUSIC, EDITION])     # and grows again from it
    assert refused == {} and len(MS.menu_table(AdjustmentTable(back, wide_ok=True)).records) == n_stock + 2
