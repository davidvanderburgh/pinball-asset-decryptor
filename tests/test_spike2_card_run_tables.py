"""A card run rebuilds a stale device table on its FIRST start (PAD-551).

peanuts' synthesis of 25 titles found speaker rings missing on Godzilla, D&D,
Bond, Jaws, John Wick, King Kong, Metallica and Star Wars - eight of the titles
whose device tables gained their SPEAKER rows with devicexy reader 3 (PAD-517).
The tables were the old reader's: watch.sh builds them BEFORE run_game.sh
publishes dump/title, so gameinfo named the PREVIOUS run's title, fell back to
the empty games/<title> stub, found no game binary, and mktables printed
"devices (cached)" over a table two reader revisions old. Only a second run of
the same title in a row ever rebuilt it; Venom's on the rig here dated from
2026-09-06. watch.sh now says which title and where its files are.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

#: a table cached by reader 1: no `# reader:` line at all
OLD_TABLE = """# venom_le device positions, from the game binary.
# binary: game 7195548 bytes
# 1 records (coil=1), 0 on the playfield image.
# playfield image: (not found) (313x710)
coil      SHAKER MOTOR                           0     0    0    0    5     0  -      -
"""


@pytest.fixture()
def card_run(monkeypatch, tmp_path):
    """A rig whose last run was another title, and a card for venom_le."""
    import devicexy
    import gameinfo
    import mktables
    monkeypatch.setenv("PAD_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("PAD_TABLES", str(tmp_path / "tables"))
    monkeypatch.delenv("PAD_GAME", raising=False)
    dump = tmp_path / "root" / "dump"
    dump.mkdir(parents=True)
    (dump / "title").write_text("name=godzilla_le\ndir=/nowhere/godzilla_le\n")
    card = tmp_path / "card" / "venom_le"
    card.mkdir(parents=True)
    (card / "game").write_bytes(b"\x7fELF" + b"\0" * 60)
    tdir = tmp_path / "tables" / "venom_le"
    tdir.mkdir(parents=True)
    (tdir / "device_xy.txt").write_text(OLD_TABLE)
    built = []

    def fake_build(game=None, elf_path=None):
        built.append((game, gameinfo.elf(game)))
        return [{"kind": "coil", "name": "SHAKER MOTOR", "x": 0, "y": 0, "w": 0,
                 "h": 0, "group": 5, "index": 0, "conn": "", "image": "",
                 "va": 1}]
    monkeypatch.setattr(devicexy, "build", fake_build)
    monkeypatch.setattr(gameinfo, "_GIVEN_DIRS", {})
    return mktables, gameinfo, card, tdir, built


def test_without_the_title_dir_the_stale_table_was_kept(card_run):
    mktables, _gi, _card, tdir, built = card_run
    mktables.build("venom_le", say=lambda s: None)
    assert built == []
    assert "# reader:" not in (tdir / "device_xy.txt").read_text()


def test_with_the_title_dir_the_first_start_rebuilds_it(card_run):
    mktables, gameinfo, card, tdir, built = card_run
    gameinfo.set_game_dir("venom_le", str(card))
    mktables.build("venom_le", say=lambda s: None)
    assert built == [("venom_le", os.path.join(str(card), "game"))]
    text = (tdir / "device_xy.txt").read_text()
    import devicexy
    assert "%s%d" % (devicexy.READER_TAG, devicexy.READER_REV) in text


def test_the_given_dir_is_only_that_titles(card_run):
    _m, gameinfo, card, _t, _b = card_run
    gameinfo.set_game_dir("venom_le", str(card))
    assert gameinfo.game_dir("venom_le") == str(card)
    assert gameinfo.game_dir("rush_le") != str(card)


def test_watch_sh_passes_the_title_and_its_dir_to_every_tables_pass():
    sh = open(os.path.join(RIG, "watch.sh"), encoding="utf-8").read()
    assert 'MKT_ARGS=(--game "$GAME")' in sh
    assert '[ -f "$GAME_ELF" ] && MKT_ARGS+=(--dir "${GAME_ELF%/*}")' in sh
    calls = [ln for ln in sh.splitlines()
             if '"$RIG/mktables.py"' in ln and "--current" not in ln
             and not ln.lstrip().startswith("#")]
    assert len(calls) == 4 and all('"${MKT_ARGS[@]}"' in ln for ln in calls)
    # GAME_ELF is the card's own (read for the node directory) long before
    assert sh.index('GAME_ELF="$CARD_PATH/game"') < sh.index("MKT_ARGS=(")
