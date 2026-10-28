"""PAD-798 (an owner asked to change TMNT's scoring): the game's own modes' AWARD numbers on the Modes tab.

A crule title's mode keeps its points in a caward record: per level, the value it pays, how much it grows a shot and
the most it grows to (plus the growth's own step and ceiling). stock_scan_cpp reads which table and level each
number a mode's reset stores fills, off the record's own code, and a number whose words are its own is editable.
The emulator proof is the ticket's: a Write-built TMNT LE 1.59 card's running game held Turtle Power's level 1 at
the staged 1,000,000 / 60,000 / 2,000,000 (stock 100,000 / 25,000 / 250,000), the other levels untouched.
The tests on real game programs skip without them (PAD_GAME_ELFS, as test_stern_stock_reader's)."""

import os

import pytest

from pinball_decryptor.plugins.stern import stock_modes as SM
from pinball_decryptor.plugins.stern import stock_reader as R
from pinball_decryptor.plugins.stern import stock_scan as SS
from pinball_decryptor.plugins.stern import stock_scan_cpp as C

ELF_DIRS = [d for d in (os.environ.get("PAD_GAME_ELFS") or "").split(os.pathsep) if d]


def real_elf(name):
    for d in ELF_DIRS:
        p = os.path.join(d, name + ".elf")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    pytest.skip("no %s game program on this machine (set PAD_GAME_ELFS)" % name)


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(R, "_CACHE", {"index_key": None, "builds": [], "parsed": {}})


def _number(key, value=100000, kind="movwt", klass="word"):
    return SM.Number(mode_id=39, key=key, value=value, kind=kind, args=(0x1000, 0x1004),
                     words=(0xE3082000, 0xE3402001), klass=klass)


# ---- the rows in words ---------------------------------------------------------------------------
@pytest.mark.parametrize("key,label", [
    ("reset.award_value_1", "Award level 1 value"),
    ("reset.award_grows_2", "Award level 2 grows by"),
    ("reset.award_cap_3", "Award level 3 grows to at most"),
    ("reset.award_step_1", "Award level 1 growth steps up by"),
    ("reset.award_stepcap_4", "Award level 4 growth tops out at"),
    ("start.award_value_now", "Award (the level it is on) value"),
])
def test_an_award_row_says_its_level_and_what_it_is(key, label):
    n = _number(key)
    assert n.label == label
    assert n.is_player_facing


def test_other_award_named_rows_keep_what_they_were():
    """``award_screen.type`` (Godzilla's award screen) is no award number: not on the tab, as before."""
    assert not _number("19.start_display.award_screen.type".split(".", 1)[1]).is_player_facing
    old = _number("reset.award_value", klass="uncertain")
    assert old.is_player_facing and old.label == "Reset award value"


def test_the_reader_revision_moved_on():
    assert R.READER_REV >= 4                     # tables generated before PAD-798 are read again


# ---- the record's layout, off its own code --------------------------------------------------------
CRULE = ["turtles_le-1.59.0", "turtles_pro-1.58.0", "dungeons_and_dragons_le-1.00.0", "john_wick_le-1.01.0",
         "led_zeppelin_le-1.22.0", "mando_le-1.44.0", "munsters_le-1.28.0", "rush_le-1.18.0",
         "sword_of_rage_le-1.18.0", "venom_le-1.07.0", "foo_fighters_le-1.04.0"]


@pytest.mark.parametrize("name", CRULE)
def test_every_crule_build_keeps_the_same_award_tables(name):
    """Found by the two functions' exact shapes, or by their use where the shapes differ (TMNT Pro 1.58)."""
    prog = SS.Program(real_elf(name))
    lay = C.award_layout(prog, SS.class_model(prog))
    assert lay is not None
    parts = {v: k for k, v in lay.items() if v != "record"}
    assert parts == {"value": 0x10, "grows": 0x1c, "cap": 0x28, "step": 0x34, "stepcap": 0x40}
    rec = sorted(k for k, v in lay.items() if v == "record")
    assert len(rec) == 2 and rec[1] == rec[0] + 0x20 and rec[0] in (0x80, 0x90)


@pytest.mark.parametrize("name", CRULE)
def test_every_crule_build_has_award_numbers_to_change(name):
    prog = SS.Program(real_elf(name))
    r = C.read(prog)
    rows = [row for m in r.modes for row in m.rows if ".award_" in row.key]
    assert sum(1 for row in rows if row.klass == "word") >= 3, name


def test_turtle_power_s_levels_are_read_as_the_game_keeps_them():
    """TMNT LE 1.59's Turtle Power, as its running game holds it (the emulator read, stock card): level 1 worth
    100,000, growing 25,000, up to 250,000; level 2 350,000 growing 50,000. Level 1's value is kept in three
    places (the table and the record's own two copies), edited together; level 3's value shares its words with
    level 2's cap, so neither is editable alone."""
    b = R.ensure_table(real_elf("turtles_le-1.59.0"), "turtles_le", "1.59.0").build
    assert b.mode_name(39) == "Turtle Power"
    want = {"39.reset.award_value_1": 100000, "39.reset.award_grows_1": 25000, "39.reset.award_cap_1": 250000,
            "39.reset.award_value_2": 350000, "39.reset.award_grows_2": 50000}
    for key, v in want.items():
        n = b.number(key)
        assert n is not None and n.value == v and n.editable, key
    v1 = b.number("39.reset.award_value_1")
    assert v1.kind == "movwt" and len(v1.args) == 6
    assert SM.decode(v1.kind, SM.encode(v1.kind, v1.words, 1000000)) == 1000000
    grows = b.number("39.reset.award_grows_1")
    with pytest.raises(SM.StockModeError):
        SM.check_value(grows, 250000)           # one movw: at most 65,535
    assert not any(n.editable for n in b.numbers
                   if n.mode_id == 39 and n.key in ("reset.award_value_3", "reset.award_cap_2"))


def test_a_level_picked_as_the_mode_plays_is_the_current_level_s():
    """John Wick's modes hand their level check a field of the mode, not a constant."""
    prog = SS.Program(real_elf("john_wick_le-1.01.0"))
    r = C.read(prog)
    keys = [row.key for m in r.modes for row in m.rows if row.key.endswith("_now")]
    assert keys and all(".award_" in k for k in keys)
