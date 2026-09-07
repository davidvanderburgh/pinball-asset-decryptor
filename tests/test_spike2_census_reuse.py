"""Reusing a node-board derivation instead of re-reading a 190 MB binary.

WHAT THIS PROTECTS. `watch.sh` used to ask `nodecensus.py` for its three
values with three separate runs, and each run read the game binary from
scratch - twice, once for the device table and once for the node directory.
On an ordinary title that is a second or two. On `rush_le` 1.18.0, whose
`.data` section is 184.6 MB against `godzilla_le`'s 8.0 MB WHOLE BINARY, it
was 20.4 s a run: 61 s of the 77 s that passed before the game process
started, for three copies of one answer (peanuts' emulation matrix, 2026-09-07:
"much longer than any other game to start").

The fix is `--values` (all three from one reading) plus a cache keyed on the
identity of every input, and `nbdir --reuse` for the same reason. Both are
only safe while the key is: silencing a node that IS populated loses its
devices with no message at all, which is the failure `nodecensus.py`'s header
is mostly about. So what these tests pin is not the speed - it is that a
served answer is an answer for the inputs in front of it, and that anything
unexpected falls back to reading the binary rather than to a stale verdict.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "spike2_emu"))


@pytest.fixture(scope="module")
def nbdir():
    import nbdir as mod
    return mod


@pytest.fixture(scope="module")
def nodecensus():
    import nodecensus as mod
    return mod


class _Args(object):
    """The handful of argparse fields cache_key() reads."""

    def __init__(self, elf, switches, nodedir, fresh="1"):
        self.elf = str(elf)
        self.switches = str(switches)
        self.nodedir = str(nodedir)
        self.nodedir_fresh = fresh


@pytest.fixture
def inputs(tmp_path):
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 200)
    sw = tmp_path / "switch_list.txt"
    sw.write_text("1 11 1 11 START BUTTON\n")
    nd = tmp_path / "node_ident.txt"
    nd.write_text("node=2 type=ws2812node code=5\n")
    return elf, sw, nd


# --------------------------------------------------------------- the key ----

def test_key_covers_every_input_that_moves_the_verdict(nodecensus, inputs):
    """All four inputs are in the key because all four change the answer: the
    binary (device table, node4 flags), the switch list (the fallback branch),
    the node directory (the item 51 guard) and whether it is FRESH (item 82
    answers an optional node4 whose row is fresh, silences it when stale)."""
    elf, sw, nd = inputs
    base = nodecensus.cache_key(_Args(elf, sw, nd))
    assert base

    elf.write_bytes(b"\x7fELF" + b"\0" * 201)          # a different binary
    assert nodecensus.cache_key(_Args(elf, sw, nd)) != base
    elf.write_bytes(b"\x7fELF" + b"\0" * 200)
    assert nodecensus.cache_key(_Args(elf, sw, nd)) == base

    sw.write_text("1 11 2 11 START BUTTON\n")          # same length, node 1->2
    assert nodecensus.cache_key(_Args(elf, sw, nd)) != base

    sw.write_text("1 11 1 11 START BUTTON\n")
    nd.write_text("node=4 type=node4 code=3\n")
    assert nodecensus.cache_key(_Args(elf, sw, nd)) != base

    nd.write_text("node=2 type=ws2812node code=5\n")
    assert nodecensus.cache_key(_Args(elf, sw, nd, fresh="0")) != base


def test_a_same_length_rewrite_is_not_the_same_input(nodecensus, inputs):
    """★ WHY THE SMALL FILES ARE HASHED, NOT STAT'D. Both are rewritten in
    place by the rig itself - switch_list.txt by the shim's dump on every run,
    node_ident.txt by nbdir on every start - so a size would miss exactly the
    kind of rewrite this rig performs."""
    elf, sw, nd = inputs
    before = nodecensus.cache_key(_Args(elf, sw, nd))
    after_text = "1 11 9 11 START BUTTON\n"
    assert len(after_text) == len(sw.read_text())
    sw.write_text(after_text)
    assert nodecensus.cache_key(_Args(elf, sw, nd)) != before


def test_no_binary_named_means_no_caching(nodecensus, tmp_path):
    """`--game` mode and an unreadable path both yield no key, and a verdict
    without a key is never written and never served."""
    assert nodecensus.cache_key(_Args(None, None, None)) is None
    assert nodecensus.cache_key(_Args(tmp_path / "gone", None, None)) is None
    dest = tmp_path / "census.txt"
    nodecensus.cache_write(str(dest), None, [2], [], "why")
    assert not dest.exists()
    assert nodecensus.cache_read(str(dest), None) is None


# ------------------------------------------------------- the census cache ----

def test_verdict_round_trips_and_only_for_its_own_inputs(nodecensus, inputs,
                                                         tmp_path):
    elf, sw, nd = inputs
    dest = tmp_path / "sub" / "node_census.txt"      # the dir need not exist
    key = nodecensus.cache_key(_Args(elf, sw, nd))
    why = "node 4 is an OPTIONAL node4-type board; and node 2 is absent"
    nodecensus.cache_write(str(dest), key, [2, 4], [4], why)

    assert nodecensus.cache_read(str(dest), key) == ([2, 4], [4], why)
    assert nodecensus.cache_read(str(dest), key + " x") is None
    # the empty verdict - "silence nothing" - is a real answer, not a miss
    nodecensus.cache_write(str(dest), key, [], [], "nothing is silenced")
    assert nodecensus.cache_read(str(dest), key) == ([], [], "nothing is silenced")


def test_an_unreadable_or_damaged_cache_reads_the_binary(nodecensus, inputs,
                                                         tmp_path):
    """Every failure answers None, which sends the caller to the scan. A
    re-derivation costs seconds; a wrong verdict costs a board's devices."""
    elf, sw, nd = inputs
    key = nodecensus.cache_key(_Args(elf, sw, nd))
    dest = tmp_path / "node_census.txt"
    assert nodecensus.cache_read(str(dest), key) is None          # absent
    dest.write_text("inputs=%s\nsilent=2\n" % key)                 # truncated
    assert nodecensus.cache_read(str(dest), key) is None
    dest.write_text("inputs=%s\nsilent=two\nsilent-ff=\nbecause=x\n" % key)
    assert nodecensus.cache_read(str(dest), key) is None           # not a node
    dest.write_text("nonsense\n")
    assert nodecensus.cache_read(str(dest), key) is None


def test_because_stays_one_line(nodecensus, inputs, tmp_path):
    """The reason is read back with a line-oriented parse here and with `sed`
    in watch.sh, and it is the only free-form field."""
    elf, sw, nd = inputs
    key = nodecensus.cache_key(_Args(elf, sw, nd))
    dest = tmp_path / "node_census.txt"
    nodecensus.cache_write(str(dest), key, [2], [], "first\nsecond")
    assert nodecensus.cache_read(str(dest), key) == ([2], [], "first second")


def _run_values(nodecensus, elf, sw, nd, dest, monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        ["nodecensus.py", "--elf", str(elf), "--switches", str(sw),
         "--nodedir", str(nd), "--nodedir-fresh", "1",
         "--cache", str(dest), "--values"])
    nodecensus.main()


def test_a_census_that_threw_is_not_kept(nodecensus, inputs, tmp_path,
                                         monkeypatch, capsys):
    """A census that could not read the binary fell back to the switch list.
    That is the right answer for a title whose device table will not parse and
    the wrong one to FREEZE for a card that was briefly not readable - and
    from here the two look the same, so neither is cached."""
    elf, sw, nd = inputs
    dest = tmp_path / "node_census.txt"

    def boom(*a, **k):
        raise SystemExit("devicexy: no game binary")

    monkeypatch.setattr(nodecensus, "census", boom)
    _run_values(nodecensus, elf, sw, nd, dest, monkeypatch)
    assert "silent=" in capsys.readouterr().out      # the run still starts
    assert not dest.exists()


def test_a_binary_that_reads_and_holds_NOTHING_is_kept(nodecensus, inputs,
                                                       tmp_path, monkeypatch,
                                                       capsys):
    """★ THE CASE THE CACHE EXISTS FOR. rush_le's device table yields zero
    records after 9.6 s of scanning - and zero is an ANSWER, returned rather
    than raised. Refusing to keep it would leave the slowest title paying the
    scan on every start, which is the fault being fixed."""
    elf, sw, nd = inputs
    dest = tmp_path / "node_census.txt"
    monkeypatch.setattr(nodecensus, "census", lambda *a, **k: ({}, {}, 0))
    _run_values(nodecensus, elf, sw, nd, dest, monkeypatch)
    first = capsys.readouterr().out
    assert dest.exists()

    # and the kept verdict is the one the scan reached
    monkeypatch.setattr(nodecensus, "census", _never_called)
    _run_values(nodecensus, elf, sw, nd, dest, monkeypatch)
    assert capsys.readouterr().out == first


def _never_called(*a, **k):
    raise AssertionError("the binary was read again despite a current cache")


# -------------------------------------------------- the node directory -------

def test_source_id_names_the_binary_AND_the_hex_beside_it(nbdir, tmp_path):
    """★ HALF OF EVERY ROW COMES FROM THE FIRMWARE IMAGES, not from the ELF -
    variant, fw, hexver, hex - and PAD's own blip-free patch rewrites those.
    A key naming only the binary would serve a table describing firmware that
    is no longer on the card."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    base = nbdir.source_id(str(elf), str(tmp_path))

    hexf = tmp_path / "pinnode-LPC1313-1_19_0.hex"
    hexf.write_text(":00000001FF\n")
    with_hex = nbdir.source_id(str(elf), str(tmp_path))
    assert with_hex != base

    hexf.write_text(":00000001FE\n:00000001FE\n")     # patched, longer
    assert nbdir.source_id(str(elf), str(tmp_path)) != with_hex

    renamed = tmp_path / "pinnode-LPC1313-1_20_0.hex"
    hexf.rename(renamed)
    assert nbdir.source_id(str(elf), str(tmp_path)) != with_hex

    assert nbdir.source_id(str(tmp_path / "gone"), str(tmp_path)) is None
    assert nbdir.source_id(str(elf), str(tmp_path / "gone")) is None


def test_reuse_copies_a_current_table_and_refuses_anything_else(nbdir,
                                                                tmp_path):
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    src = nbdir.source_id(str(elf), str(tmp_path))
    have = tmp_path / "node_ident.txt"
    body = ("# nbdir v1 elf=game nodes=1 src=%s\n"
            "node=2 type=ws2812node code=5\n" % src)
    have.write_text(body)
    out = tmp_path / "out.txt"

    assert nbdir.reuse(str(have), str(out), str(elf), str(tmp_path)) is True
    assert out.read_text() == body

    # a table from a DIFFERENT binary, and one from before src= existed
    have.write_text(body.replace(src, src + " x"))
    assert nbdir.reuse(str(have), str(out), str(elf), str(tmp_path)) is False
    have.write_text("# nbdir v1 elf=game nodes=1\nnode=2 type=ws2812node code=5\n")
    assert nbdir.reuse(str(have), str(out), str(elf), str(tmp_path)) is False

    # a table with no rows proves nothing - derive rather than trust it
    have.write_text("# nbdir v1 elf=game nodes=0 src=%s\n"
                    "# skipped node=2 code=5 reason=unknown\n" % src)
    assert nbdir.reuse(str(have), str(out), str(elf), str(tmp_path)) is False

    assert nbdir.reuse(str(tmp_path / "gone"), str(out), str(elf),
                       str(tmp_path)) is False
    assert nbdir.reuse(None, str(out), str(elf), str(tmp_path)) is False


# ------------------------------------------- the switch-position join -------

DEV_HEADER = ("# t device positions, from the game binary.\n"
              "# binary: %s\n"
              "# %d records (), 0 on the playfield image.\n")
DEV_ROW = ("switch    LEFT RAMP MADE OPTO   153   103   20   20    7"
           "     0  -      playfield\n")
SW_LIST = "67  59  9  0  LEFT RAMP MADE OPTO\n"


def _tables(tmp_path, monkeypatch, rows, game="testtitle"):
    """A cached tables directory whose device table names its own binary, so
    mktables' _built_from() is satisfied and the derive branch stays shut."""
    import devicexy
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_TABLES", str(tmp_path / "tables"))
    monkeypatch.setenv("PAD_GAME", game)
    tdir = tmp_path / "tables" / game
    tdir.mkdir(parents=True)
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    (tdir / "device_xy.txt").write_text(
        DEV_HEADER % (devicexy.binary_id(str(elf)), rows) + DEV_ROW * rows)
    (tdir / "switch_list.txt").write_text(SW_LIST)
    for nm in ("led_io.txt", "group_node.txt"):
        (tdir / nm).write_text("# cached\n")
    assert not (tdir / "switch_xy.txt").exists()
    return tdir


@pytest.mark.parametrize("rows, expect_scan", [(0, False), (1, True)])
def test_an_empty_device_table_is_not_asked_for_again(tmp_path, monkeypatch,
                                                      rows, expect_scan):
    """★ THE GATE ON THIS BRANCH IS `switch_xy.txt does not exist`, AND A
    TITLE WITH NO DEVICES CAN NEVER WRITE ONE - so before this it re-read the
    game binary on every start, for ever, to be told the same nothing. On
    rush_le that is 9.6 s a pass and two passes a start, because its `.data`
    is 184.6 MB against godzilla_le's 8.0 MB whole binary.

    A title that HAS devices must still derive them: the text file is a lossy
    copy (whitespace-joined names) and can predate a parser improvement, so it
    is only ever consulted for whether there is anything to look for.
    """
    import devicexy
    import mktables
    _tables(tmp_path, monkeypatch, rows)

    calls = []
    monkeypatch.setattr(devicexy, "build",
                        lambda *a, **k: calls.append(a) or [])
    mktables.build(game="testtitle", say=lambda *a: None)
    assert bool(calls) is expect_scan


#: hwshim.c nb_fident_load() reads node_ident.txt through `char line[256]`.
#: A longer line is handed to it by fgets IN PIECES, and only the first piece
#: carries the `#` that makes the parser skip a comment.
HWSHIM_LINE_BUF = 256


def test_the_header_stays_inside_hwshims_line_buffer(nbdir, tmp_path):
    """★ THE FIRST VERSION OF src= LISTED EVERY HEX FILE BY NAME and ran to
    604 bytes on rush_le - two and a half of hwshim's line buffers. The two
    continuation pieces do not start with `#`, so they reached the `node=`
    test, and nothing broke only because a hex filename spells `node-` and
    `node4-` and never `node=`. Hashing the listing keeps the key exact and
    the line short; this is the check that keeps it that way.
    """
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    for n in range(20):                       # rush_le ships 15
        (tmp_path / ("some_long_board_type_name-LPC1313-1_19_%d.hex" % n)
         ).write_text(":00000001FF\n")
    src = nbdir.source_id(str(elf), str(tmp_path))
    out = tmp_path / "node_ident.txt"
    nbdir.emit([], [], str(elf), str(out), src)
    header = out.read_text().splitlines()[0]
    assert header.startswith("#")
    assert len(header) + 1 < HWSHIM_LINE_BUF, header    # +1 for the newline


def test_emit_writes_a_src_the_reuse_can_read_back(nbdir, tmp_path):
    """`src=` carries spaces, so it must stay LAST on the header line - and
    the pair has to agree, which is what this checks rather than the text."""
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    (tmp_path / "pinnode-LPC1313-1_19_0.hex").write_text(":00000001FF\n")
    src = nbdir.source_id(str(elf), str(tmp_path))
    have = tmp_path / "node_ident.txt"
    rows = [(2, "ws2812node", 5, 0x2C40102B, 5, 0x05, 0x012300, "1.35.0",
             "ws2812node-LPC1313-1_19_0.hex", False, 5205319)]
    nbdir.emit(rows, [], str(elf), str(have), src)
    assert have.read_text().splitlines()[0].endswith(" src=" + src)
    out = tmp_path / "out.txt"
    assert nbdir.reuse(str(have), str(out), str(elf), str(tmp_path)) is True
    assert out.read_text() == have.read_text()


# ------------------------------------------------ the playfield drawing ------

@pytest.fixture(scope="module")
def gameinfo():
    import gameinfo as mod
    return mod


def _title(tmp_path, monkeypatch, title, *names):
    """A title laid out where gameinfo.game_dir() falls back to looking:
    $PAD_ROOT/games/<title>/assets/nuk/images/TestMode."""
    d = tmp_path / "games" / title / "assets" / "nuk" / "images" / "TestMode"
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_bytes(b"\x89PNG\r\n\x1a\x08")
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_GAME", title)
    return title


def _pick(gameinfo, title):
    got = gameinfo.find_playfield_art(title)
    return os.path.basename(got) if got else None


def test_an_le_takes_the_premium_playfield_not_the_alphabet(gameinfo, tmp_path,
                                                            monkeypatch):
    """uncanny_xmen_le 0.98 ships `xmen_pre_...` and `xmen_pro_...` and names
    neither of them `le`. The right answer is the Premium drawing - one
    playfield serves LE and Premium - and before this it was reached only by
    found[0] happening to sort `pre` before `pro`. peanuts' matrix had this
    title down as "playfield artwork: No"."""
    t = _title(tmp_path, monkeypatch, "uncanny_xmen_le",
               "xmen_pre_playfield_scaled.png", "xmen_pro_playfield_scaled.png")
    assert _pick(gameinfo, t) == "xmen_pre_playfield_scaled.png"


def test_the_alphabet_no_longer_decides_it(gameinfo, tmp_path, monkeypatch):
    """The same two drawings with the Pro sorting FIRST - the case
    find_playfield_art's own docstring says it must not lose: "It would have
    picked the Pro drawing for an LE machine as soon as the alphabetical
    order changed"."""
    t = _title(tmp_path, monkeypatch, "uncanny_xmen_le",
               "a_pro_playfield.png", "z_premium_playfield.png")
    assert _pick(gameinfo, t) == "z_premium_playfield.png"


def test_a_pro_title_never_takes_a_premium_drawing(gameinfo, tmp_path,
                                                   monkeypatch):
    """One way only: Pro has its own playfield and must not borrow."""
    t = _title(tmp_path, monkeypatch, "uncanny_xmen_pro",
               "xmen_pre_playfield_scaled.png", "xmen_pro_playfield_scaled.png")
    assert _pick(gameinfo, t) == "xmen_pro_playfield_scaled.png"


def test_an_explicit_le_drawing_still_wins(gameinfo, tmp_path, monkeypatch):
    """jaws_le's own spelling keeps first claim over the premium fallback, so
    no title measured before this changes its pick."""
    t = _title(tmp_path, monkeypatch, "jaws_le",
               "jaws_le_playfield_scaled.png",
               "jaws_premium_playfield_scaled.png",
               "jaws_pro_playfield_scaled.png")
    assert _pick(gameinfo, t) == "jaws_le_playfield_scaled.png"


def test_the_2025_generation_names_both_models_in_one_file(gameinfo, tmp_path,
                                                           monkeypatch):
    """dungeons_and_dragons_le's own spelling is the evidence that LE and
    Premium share one playfield - and it carries `le`, so it matches earlier
    and never reaches the new branch."""
    t = _title(tmp_path, monkeypatch, "dungeons_and_dragons_le",
               "Rope_LE-Premium-X8-X9_TOP_playfield.png",
               "Rope_PRO-X7_TOP_playfield.png")
    assert _pick(gameinfo, t) == "Rope_LE-Premium-X8-X9_TOP_playfield.png"
