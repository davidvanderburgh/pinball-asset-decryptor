"""PAD-619: a switch list read out of the BINARY gives way to the run's own dump.

star_wars_le 1.30: pass one (no run) wrote the list from the static reader,
which numbers that build's switches in another order than the game's own table
(LEFT FLIPPER BUTTON 55 on disk, 59 in the game). Pass two found the list
"(cached)" and never compared it with the dump the same run printed - so Start,
both flipper buttons and the trough feeder poked the wrong switches for good.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import mktables  # noqa: E402
import swnames  # noqa: E402
import swtable  # noqa: E402

#: the binary's numbering (static reader) and the game's own, same wires
BINARY_ROWS = [(36, 0, 1, 11, "START BUTTON"), (55, 0, 8, 25, "LEFT FLIPPER BUTTON"),
               (54, 0, 8, 24, "RIGHT FLIPPER BUTTON"), (67, 0, 8, 37, "TROUGH 1")]
DUMP = """[sw] --- switches: count=72 entry[]=0x0084e530 raw[]=0x00000000 ---
[sw] id=36  num=73   node=1  bit=11 raw=? logical=1 flags=0x0020 START BUTTON
[sw] id=58  num=10   node=8  bit=24 raw=? logical=1 flags=0x0020 RIGHT FLIPPER BUTTON
[sw] id=59  num=9    node=8  bit=25 raw=? logical=1 flags=0x0020 LEFT FLIPPER BUTTON
[sw] id=71  num=20   node=8  bit=37 raw=? logical=1 flags=0x0020 TROUGH 1
[dev] --- ball devices: 0 ---
"""


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(swnames, "fill", lambda rows, *a, **k: (rows, []))
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    lst = tmp_path / "switch_list.txt"
    lst.write_text(swtable.text("star_wars_le", BINARY_ROWS, str(elf), static_asked=True,
                                source=swtable.SOURCE_BINARY))
    return tmp_path, str(elf), str(lst)


def _ids(path):
    return {r[4]: r[0] for r in mktables._read_list(path)}


def _log(tmp_path, text):
    p = tmp_path / "run.log"
    p.write_text(text)
    return str(p)


def test_the_dump_replaces_a_list_read_out_of_the_binary(rig):
    tmp_path, elf, lst = rig
    assert mktables.switch_dump_complete(_log(tmp_path, DUMP))
    said = []
    assert mktables._dump_over_binary(lst, "star_wars_le", elf, str(tmp_path / "run.log"), 0,
                                      said.append)
    assert _ids(lst)["LEFT FLIPPER BUTTON"] == 59 and _ids(lst)["TROUGH 1"] == 71
    assert mktables._recorded_source(lst) == swtable.SOURCE_DUMP
    assert any("3 of 4 ids moved" in s for s in said), said


def test_a_list_from_the_dump_is_not_asked_again(rig):
    tmp_path, elf, lst = rig
    log = _log(tmp_path, DUMP)
    open(lst, "w").write(swtable.text("star_wars_le", BINARY_ROWS, elf, source=swtable.SOURCE_DUMP))
    assert not mktables._dump_over_binary(lst, "star_wars_le", elf, log, 0, lambda m: None)
    assert _ids(lst)["LEFT FLIPPER BUTTON"] == 55


def test_no_dump_marks_the_list_and_later_runs_stop_waiting(rig, monkeypatch):
    tmp_path, elf, lst = rig
    log = _log(tmp_path, "[run] no switch table found\n")
    assert not mktables._dump_over_binary(lst, "star_wars_le", elf, log, 0, lambda m: None)
    assert mktables._recorded_source(lst) == swtable.SOURCE_BINARY_NO_DUMP
    assert _ids(lst)["LEFT FLIPPER BUTTON"] == 55, "the binary's list is kept, not dropped"
    waited = []
    monkeypatch.setattr(mktables, "wait_for_switches", lambda *a, **k: waited.append(a))
    mktables._dump_over_binary(lst, "star_wars_le", elf, log, 60, lambda m: None)
    assert not waited, "a title whose run never dumped waited again"


def test_a_list_from_before_the_source_line_is_checked_like_a_binary_one(rig):
    tmp_path, elf, lst = rig
    log = _log(tmp_path, DUMP)
    text = "".join(l for l in open(lst) if not l.startswith(swtable.SOURCE_TAG))
    open(lst, "w").write(text)
    assert mktables._recorded_source(lst) is None
    assert mktables._dump_over_binary(lst, "star_wars_le", elf, log, 0, lambda m: None)
    assert _ids(lst)["LEFT FLIPPER BUTTON"] == 59


#: PAD-654, munsters_le 1.28: the shim's dump names nothing on node 8 (item 29's message-table address)
DUMP_UNNAMED = DUMP.replace("LEFT FLIPPER BUTTON", "?").replace("TROUGH 1", "?")


def test_the_dumps_unnamed_rows_keep_the_replaced_lists_names_by_the_wire(rig):
    """The list being replaced was named by the static table and memoed as asked; the dump's `?` rows used to
    inherit the memo and never be asked, so the trough stayed `?` and the ball tools used Godzilla's ids."""
    tmp_path, elf, lst = rig
    assert mktables._dump_over_binary(lst, "star_wars_le", elf, _log(tmp_path, DUMP_UNNAMED), 0,
                                      lambda m: None)
    ids = _ids(lst)
    assert ids["LEFT FLIPPER BUTTON"] == 59 and ids["TROUGH 1"] == 71, ids
    assert "?" not in ids


def test_a_memo_from_before_pad654_is_asked_again(rig, monkeypatch):
    """A list PAD-619's dump path already wrote with `?` rows and the old memo heals on its next run."""
    tmp_path, elf, lst = rig
    monkeypatch.setattr(mktables.devicexy, "binary_id", lambda p: "game 68 bytes")
    open(lst, "w").write("# static-names: game 68 bytes\n1 0 8 3 ?\n")
    assert not mktables._static_names_asked(lst, elf)
    open(lst, "w").write("# static-names: %s\n1 0 8 3 ?\n" % swtable.static_memo("game 68 bytes"))
    assert mktables._static_names_asked(lst, elf)
