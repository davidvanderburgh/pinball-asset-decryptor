"""A cabinet without its topper has no topper boards on the bus (PAD-498).

"Venom: node 12 present with Topper toggle off" (peanuts, 2026-10-10). The
Emulate tab's Topper box (PAD_TOPPER=0) only ever shut the second display's
window; the shim kept answering for the topper's own boards, so the game drove
a topper the cabinet was not meant to have and the virtual playfield showed
node 12 with its 75 lights. Unticked now means the title's own topper boards
are silenced the way any board a machine does not have is, through the node
census watch.sh already asks.

The node names below are the titles' own, read off the Stern cards on David's
disk (latest build of each title, 2026-10-10).
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.join(HERE, "..", "tools", "spike2_emu")
sys.path.insert(0, RIG)


@pytest.fixture(scope="module")
def nodecensus():
    import nodecensus as mod
    return mod


def _rec(node, name, flags=0x0c, typ="ws2812node"):
    return dict(node=node, name=name, flags=flags, type=typ)


#: venom_le 1.07's directory, the title in the report.
VENOM = [
    _rec(1, "CABINET", 0x08, "pinnode"),
    _rec(2, "Cabinet Lights"),
    _rec(4, "QR Scanner", 0x04, "node4"),
    _rec(8, "LOWER PLAYFIELD", 0x08, "pinnode"),
    _rec(9, "UPPER PLAYFIELD", 0x08, "pinnode"),
    _rec(12, "TOPPER"),
    _rec(14, "Topper Lights"),
]

#: foo_fighters_le 1.04's: the "and perhaps others" - a third topper board.
FOO = [
    _rec(1, "CABINET", 0x08, "pinnode"),
    _rec(12, "TOPPER (OPTIONAL)", 0x0c, "coil4node"),
    _rec(13, "TOPPER WS2812 (OPTIONAL)"),
    _rec(14, "Topper Lights"),
]


def test_the_title_names_its_own_topper_boards(nodecensus):
    assert nodecensus.topper_nodes(VENOM) == {12: "TOPPER",
                                              14: "Topper Lights"}
    assert sorted(nodecensus.topper_nodes(FOO)) == [12, 13, 14]


def test_the_name_is_matched_whatever_its_spelling(nodecensus):
    """Not a node number and not one spelling: batman's 12 and 13 are
    "Accessory Topper (Optional)" and "LE/SLE Topper (Optional)", john_wick's
    12 is "Topper Lights" and its 13 a stepper board."""
    recs = [_rec(12, "Accessory Topper (Optional)", 0x04, "pinnode"),
            _rec(13, "Topper Stepper Motor Board", 0x0c, "tmc5041node"),
            _rec(15, "Topper 2 Lights", 0x04),
            _rec(9, "PLAYFIELD", 0x08, "pinnode")]
    assert sorted(nodecensus.topper_nodes(recs)) == [12, 13, 15]


def test_a_required_board_is_never_unplugged_by_a_tick_box(nodecensus):
    """Optionality is the guard, as for the node4 silence: an absent REQUIRED
    board wedges the locate step. Every topper board on every card carries the
    optional bit today; this keeps a future one from stalling a boot."""
    assert nodecensus.topper_nodes([_rec(12, "TOPPER", 0x08, "pinnode")]) == {}
    assert nodecensus.topper_nodes([]) == {}


def test_one_directory_read_serves_both_rules(nodecensus):
    """optional_node4_nodes() and topper_nodes() read the same directory; on
    rush_le a read is a 184.6 MB walk, so it is done once."""
    assert nodecensus.optional_node4_in(VENOM) == {4}
    assert nodecensus.node_directory(None) == []
    assert nodecensus.node_directory(os.path.join(HERE, "no-such-game")) == []


class _Args(object):
    def __init__(self, elf, no_topper=False):
        self.elf = str(elf)
        self.switches = self.nodedir = None
        self.nodedir_fresh = "1"
        if no_topper:
            self.no_topper = True


def test_topper_off_is_its_own_verdict_and_old_caches_still_serve(
        nodecensus, tmp_path):
    """The key names the topper only when it is off, so every verdict cached
    before PAD-498 (all of them topper-on) still serves its own start."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 200)
    on = nodecensus.cache_key(_Args(elf))
    off = nodecensus.cache_key(_Args(elf, no_topper=True))
    assert on and off and on != off
    assert "topper" not in on


def _run(nodecensus, monkeypatch, capsys, tmp_path, *extra):
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 200)
    # Godzilla's real shape: node 2 has no devices and is already silenced;
    # node 4 is an optional node4 whose identity cannot be answered.
    monkeypatch.setattr(nodecensus, "census", lambda *a, **k: (
        {8: {"total": 9}, 9: {"total": 1}}, {}, 10))
    monkeypatch.setattr(nodecensus, "node_directory",
                        lambda p: VENOM if p else [])
    monkeypatch.setattr(sys, "argv",
                        ["nodecensus.py", "--elf", str(elf), "--values"]
                        + list(extra))
    nodecensus.main()
    return dict(ln.split("=", 1)
                for ln in capsys.readouterr().out.splitlines())


def test_topper_off_silences_the_topper_boards(nodecensus, monkeypatch,
                                               capsys, tmp_path):
    got = _run(nodecensus, monkeypatch, capsys, tmp_path, "--no-topper")
    assert got["silent"] == "2,4,12,14"
    # never `ff`: a status answer reads as alive-but-unidentified, and the
    # game re-probes it (godzilla_le's node 2, 2026-08-22)
    assert got["silent-ff"] == "4"
    assert "node 12 (TOPPER)" in got["because"]
    assert "node 14 (Topper Lights)" in got["because"]
    # and which of them went with the topper, for the playfield
    assert got["topper"] == "12,14"


def test_topper_on_is_exactly_what_it_was(nodecensus, monkeypatch, capsys,
                                          tmp_path):
    got = _run(nodecensus, monkeypatch, capsys, tmp_path)
    assert got["silent"] == "2,4"
    assert got["silent-ff"] == "4"
    assert "opper" not in got["because"]
    assert got["topper"] == ""


def test_the_topper_list_is_cached_with_the_verdict(nodecensus, monkeypatch,
                                                    capsys, tmp_path):
    """A second topper-off start is served from the cache, and must hand the
    playfield the same boards the scan named."""
    dest = tmp_path / "node_census.notopper.txt"
    first = _run(nodecensus, monkeypatch, capsys, tmp_path, "--no-topper",
                 "--cache", str(dest))
    assert dest.exists()

    def never(*a, **k):
        raise AssertionError("the binary was read again")
    monkeypatch.setattr(nodecensus, "census", never)
    monkeypatch.setattr(nodecensus, "node_directory", never)
    monkeypatch.setattr(sys, "argv",
                        ["nodecensus.py", "--elf", str(tmp_path / "game"),
                         "--values", "--no-topper", "--cache", str(dest)])
    nodecensus.main()
    again = dict(ln.split("=", 1)
                 for ln in capsys.readouterr().out.splitlines())
    assert again == first


def test_a_verdict_cached_before_pad498_still_serves(nodecensus, tmp_path):
    """Those caches have no `topper=` line, and they were all topper-on."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 200)
    key = nodecensus.cache_key(_Args(elf))
    dest = tmp_path / "node_census.txt"
    dest.write_text("inputs=%s\nsilent=2\nsilent-ff=\nbecause=why\n" % key)
    assert nodecensus.cache_read(str(dest), key) == ([2], [], "why", [])


def test_watch_sh_asks_for_it_only_when_the_box_is_off():
    """The shell half: PAD_TOPPER=0 is what the Emulate tab sends, and the
    topper-off verdict is cached beside the topper-on one rather than over
    it, so flipping the box does not re-read rush_le's binary every start."""
    with open(os.path.join(RIG, "watch.sh"), encoding="utf-8",
              errors="replace") as f:
        watch = f.read()
    gate = watch.index('if [ "${PAD_TOPPER:-1}" = 0 ]; then')
    assert watch.index("NB_TOPPER_ARG=\n") < gate
    assert "NB_TOPPER_ARG=--no-topper" in watch[gate:gate + 300]
    census = watch.index('NB_VALUES=$(python3 "$RIG/nodecensus.py"')
    assert gate < census
    call = watch[census:watch.index("2>/dev/null)", census)]
    assert "--values $NB_TOPPER_ARG" in call
    assert "node_census${NB_TOPPER_ARG:+.notopper}.txt" in call
    # and the playfield is told, through the file it reads
    tell = watch.index("s/^topper=//p", census)
    block = watch[tell:tell + 400]
    assert '> "$ROOT/dump/topper_off"' in block
    assert 'rm -f "$ROOT/dump/topper_off"' in block


# ------------------------------------------------- the virtual playfield ----

@pytest.fixture
def pf(monkeypatch, tmp_path):
    """playfield.py reading a run's dump folder in tmp_path."""
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf.padpath, "dump", lambda: str(tmp_path))
    monkeypatch.setattr(pf, "TOPPER_OFF_PATH", str(tmp_path / "topper_off"))
    tdir = tmp_path / "tables"
    tdir.mkdir()
    # id num node bit NAME - Foo Fighters' two topper switches on node 12
    (tdir / "switch_list.txt").write_text(
        "36 11 1 2 START BUTTON\n"
        "60 31 9 0 LEFT ORBIT\n"
        "70 90 12 0 TOPPER HOME 1\n"
        "71 91 12 1 TOPPER HOME 2\n")
    monkeypatch.setattr(pf, "TDIR", str(tdir))
    return pf


def test_with_the_topper_on_nothing_is_hidden(pf):
    assert pf.topper_off_nodes() == set()
    assert [r["node"] for r in pf.load_switch_list()] == [1, 9, 12, 12]


def test_topper_off_takes_its_switches_out_of_the_list(pf, tmp_path):
    (tmp_path / "topper_off").write_text("12,13,14\n")
    assert pf.topper_off_nodes() == {12, 13, 14}
    assert [r["name"] for r in pf.load_switch_list()] == ["START BUTTON",
                                                          "LEFT ORBIT"]


def _block(pf, lit):
    """A padled block with one written channel per (node, index) in `lit`."""
    d = bytearray(pf.PADLED_READ)
    for node, idx in lit:
        d[pf.LED_HDR + node * pf.LED_IDX + idx] = 0xff
    return bytes(d)


def test_topper_off_earns_its_lights_no_block_in_the_grid(pf, tmp_path):
    """The report itself: Venom's grid showed `node 12 (75)` with the box
    unticked. Whatever the wire carries for a board the cabinet does not
    have, the grid gives it no block."""
    d = _block(pf, [(7, 0), (7, 1), (12, 0), (12, 74), (14, 3)])
    on = pf.LedGrid({})
    assert on._discover(d)
    assert {n for n, _i in on.seen} == {7, 12, 14}

    (tmp_path / "topper_off").write_text("12,14\n")
    off = pf.LedGrid({})
    assert off._discover(d)
    assert {n for n, _i in off.seen} == {7}
