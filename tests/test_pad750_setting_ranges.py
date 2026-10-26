"""PAD-750: a setting's lowest / highest value (the range the machine's menu
offers) can be changed on the Defaults tab and is written into the card
beside the default, on Spike 2 and Spike 1 alike."""

import json
import os
import shutil

import pytest

from pinball_decryptor.plugins.stern.adjustments import (
    PRESET_RANGES_KEY, AdjustmentTable, clean_ranges, range_editable,
    resolve_overrides)
from pinball_decryptor.plugins.stern.spike1_adjustments import (
    Spike1AdjustmentError, Spike1Adjustments)
from tests.test_spike1_adjustments import _build_elf
from tests.test_stern_adjustments import make_elf
from tests.test_webui_defaults import _load, _staged
from tests.webui_harness import web_app

SPECS = [("AD_INVALID", 0, 0, 0), ("AD_FREE_PLAY", 0, 0, 1),
         ("AD_BALLS_PER_GAME", 3, 1, 10), ("AD_TILT_WARNINGS", 2, 0, 3),
         ("AD_LANGUAGE", 0, 0, 4),
         ("AD_SOUND_MASTER_VOLUME_SETTING", 64, 0, 64)]


@pytest.fixture
def table():
    return AdjustmentTable(make_elf(SPECS))


# ------------------------------------------------------------ the firmware
def test_a_changed_range_is_written_beside_the_default(table):
    with pytest.raises(ValueError):
        table.patched_bytes({"AD_BALLS_PER_GAME": 12})
    out = table.patched_bytes({"AD_BALLS_PER_GAME": 12},
                              ranges={"AD_BALLS_PER_GAME": (1, 15)})
    assert len(out) == len(table.data)
    e = AdjustmentTable(out).get("AD_BALLS_PER_GAME")
    assert (e["default"], e["min"], e["max"]) == (12, 1, 15)
    # nothing else moved: three 4-byte fields at most
    diff = [i for i, (a, b) in enumerate(zip(table.data, out)) if a != b]
    assert diff and diff[-1] - diff[0] < 12
    # a range alone, and a default checked against the range it will have
    e = AdjustmentTable(table.patched_bytes(
        {}, ranges={"AD_TILT_WARNINGS": (1, 2)})).get("AD_TILT_WARNINGS")
    assert (e["default"], e["min"], e["max"]) == (2, 1, 2)
    with pytest.raises(ValueError):
        table.patched_bytes({"AD_TILT_WARNINGS": 3},
                            ranges={"AD_TILT_WARNINGS": (1, 2)})
    with pytest.raises(ValueError):
        table.patched_bytes({}, ranges={"AD_TILT_WARNINGS": (5, 2)})
    with pytest.raises(ValueError):
        table.patched_bytes({}, ranges={"AD_NOPE": (1, 2)})


def test_spike1_range_is_written_beside_the_default():
    adj = Spike1Adjustments(_build_elf())
    with pytest.raises(Spike1AdjustmentError):
        adj.patched_bytes({3: 150})
    out = Spike1Adjustments(adj.patched_bytes({3: 150},
                                              ranges={3: (25, 200)}))
    e = out.entry(3)
    assert (e["default"], e["min"], e["max"]) == (150, 25, 200)
    with pytest.raises(Spike1AdjustmentError):
        adj.patched_bytes({}, ranges={3: (9, 2)})


def test_clean_ranges_drops_what_is_not_a_range():
    got = clean_ranges({"AD_A": [1, 15], "AD_B": [5, 2], "AD_C": "x",
                        "AD_D": [1], "AD_E": ["2", "7"], 7: (0, 9),
                        "AD_F": [0, 2 ** 31], True: (0, 1)})
    assert got == {"AD_A": (1, 15), "AD_E": (2, 7), 7: (0, 9)}
    assert clean_ranges(None) == {} and clean_ranges([1, 2]) == {}


def test_which_ranges_can_change(table):
    assert range_editable("AD_BALLS_PER_GAME", table.get("AD_BALLS_PER_GAME"))
    # on/off, named choices the app knows, the master volume: no
    assert not range_editable("AD_FREE_PLAY", table.get("AD_FREE_PLAY"))
    assert not range_editable("AD_LANGUAGE", table.get("AD_LANGUAGE"))
    assert not range_editable("AD_SOUND_MASTER_VOLUME_SETTING",
                              table.get("AD_SOUND_MASTER_VOLUME_SETTING"))


def test_what_a_build_writes(table):
    def entry_of(n):
        return table.get(n) if n in table.by_name else None
    vals, rngs = resolve_overrides(
        entry_of,
        {"AD_BALLS_PER_GAME": 20, "AD_NOT_HERE": 1, "AD_FREE_PLAY": 1},
        {"AD_BALLS_PER_GAME": [1, 15], "AD_NOT_HERE": [0, 5],
         "AD_FREE_PLAY": [0, 3],                      # not a range to change
         "AD_TILT_WARNINGS": [0, 3]})                 # the card's own
    # the value is pulled into the NEW range, not the card's
    assert vals == {"AD_BALLS_PER_GAME": 15, "AD_FREE_PLAY": 1}
    assert rngs == {"AD_BALLS_PER_GAME": (1, 15)}
    # a narrowed range that leaves out the card's default moves the default
    vals, rngs = resolve_overrides(entry_of, {},
                                   {"AD_BALLS_PER_GAME": [5, 8]})
    assert vals == {"AD_BALLS_PER_GAME": 5}
    assert rngs == {"AD_BALLS_PER_GAME": (5, 8)}
    # and the result patches cleanly
    e = AdjustmentTable(table.patched_bytes(vals, ranges=rngs)).get(
        "AD_BALLS_PER_GAME")
    assert (e["default"], e["min"], e["max"]) == (5, 5, 8)


# Spike 1 on a real card: the write path that patches the card in place
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CARDS = [os.path.join(_REPO, "images", "Stern", "spike1",
                       "ghostbusters_le-1_17.iso"),
          os.path.join(os.environ.get("PAD_SPIKE1_CARDS", ""),
                       "ghostbusters_le-1_17.iso")]
_CARD = next((c for c in _CARDS if os.path.isfile(c)), None)


@pytest.mark.skipif(_CARD is None, reason="Spike 1 sample card not present")
def test_spike1_card_takes_a_range(tmp_path):
    from pinball_decryptor.plugins.stern import spike1
    from pinball_decryptor.plugins.stern.formats import spike1_linux_partitions
    card = str(tmp_path / "card.iso")
    shutil.copy(_CARD, card)
    parts = spike1_linux_partitions(card)
    before = Spike1Adjustments(spike1.read_game_elf(card, parts))
    idx = next(r["id"] for r in before.rows()
               if r["max"] - r["min"] >= 2 and r["min"] >= 0
               and r["max"] < 1000)
    e = before.entry(idx)
    hi = e["max"] + 5
    n = spike1.write_game_elf_defaults(card, {idx: hi},
                                       ranges_by_id={idx: (e["min"], hi)})
    assert n == 1
    after = Spike1Adjustments(spike1.read_game_elf(card, parts)).entry(idx)
    assert (after["default"], after["min"], after["max"]) == (
        hi, e["min"], hi)


# ------------------------------------------------------------ the tab
EVERY = [
    {"id": 0x50, "name": "AD_BALLS_PER_GAME", "label": "BALLS PER GAME",
     "default": 3, "min": 1, "max": 10, "step": 1, "labels": None,
     "status": ""},
    {"id": 0x55, "name": "AD_FREE_PLAY", "label": "FREE PLAY",
     "default": 0, "min": 0, "max": 1, "step": 1, "labels": None,
     "status": ""},
]
ROWS = [{"name": "AD_BALLS_PER_GAME", "label": "Balls Per Game",
         "kind": "number", "help": "", "scale": 1, "labels": None,
         "group": "Game", "status": "", "default": 3, "min": 1, "max": 10,
         "step": 1},
        {"name": "AD_FREE_PLAY", "label": "Free Play", "kind": "toggle",
         "help": "", "scale": 1, "labels": None, "group": "Game",
         "status": "", "default": 0, "min": 0, "max": 1, "step": 1}]


def _form_row(w, name):
    return next(it for it in w.state("defaults")["form"]
                if it.get("name") == name)


def test_the_editor_changes_a_range_and_stages_it(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, rows=ROWS, every=EVERY, plan=None, hstd=None, project=proj)
        assert _form_row(w, "AD_BALLS_PER_GAME")["range_edit"] is True
        assert _form_row(w, "AD_FREE_PLAY")["range_edit"] is False
        info = w.call("defaults.edit_info", "AD_BALLS_PER_GAME")
        assert info["range_edit"] is True
        assert (info["min"], info["max"]) == (1, 10)
        assert (info["card_min"], info["card_max"]) == (1, 10)
        assert info["range_warn"]
        assert w.call("defaults.edit_info", "AD_FREE_PLAY")[
            "range_edit"] is False
        # past the card's range: the value needs the new range to stick
        assert w.call("defaults.edit_apply", "AD_BALLS_PER_GAME", 12,
                      False, 1, 15) is True
        st = _staged(proj)
        assert st["settings"] == {"AD_BALLS_PER_GAME": 12}
        assert st["setting_ranges"] == {"AD_BALLS_PER_GAME": [1, 15]}
        assert w.window.staged_setting_ranges(str(proj)) == {
            "AD_BALLS_PER_GAME": (1, 15)}
        row = _form_row(w, "AD_BALLS_PER_GAME")
        assert row["range"] == "1 - 15  (card 1 - 10)"
        assert row["range_chg"] is True and row["hi"] == 15
        lst = next(r for r in w.state("defaults")["all"]
                   if r["name"] == "AD_BALLS_PER_GAME")
        assert lst["rchg"] is True and lst["new"] == "12"
        # a range that is not one, or on an on/off setting, is refused
        assert w.call("defaults.edit_apply", "AD_BALLS_PER_GAME", 3,
                      False, 9, 2) == "range"
        assert w.call("defaults.edit_apply", "AD_FREE_PLAY", 1,
                      False, 0, 3) == "range"
        assert _staged(proj)["setting_ranges"] == {
            "AD_BALLS_PER_GAME": [1, 15]}
        # narrowing it so it leaves out the value pulls the value in
        assert w.call("defaults.edit_apply", "AD_BALLS_PER_GAME", 12,
                      False, 1, 5)
        assert _staged(proj)["settings"] == {"AD_BALLS_PER_GAME": 5}
        # Back to card value: the card's value AND range
        assert w.call("defaults.edit_apply", "AD_BALLS_PER_GAME", None, True)
        st = _staged(proj)
        assert "settings" not in st and "setting_ranges" not in st
        assert _form_row(w, "AD_BALLS_PER_GAME")["range"] == "1 - 10"


def test_staged_ranges_come_back_and_reset_clears_them(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(proj), {
        "settings": {"AD_BALLS_PER_GAME": 14},
        "setting_ranges": {"AD_BALLS_PER_GAME": [1, 15]}})
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, rows=ROWS, every=EVERY, plan=None, hstd=None, project=proj)
        # the value past the card's own max survives the overlay
        assert w.state("defaults")["values"]["AD_BALLS_PER_GAME"] == 14
        assert _form_row(w, "AD_BALLS_PER_GAME")["range_chg"] is True
        w.call("defaults.reset")
        st = _staged(proj)
        assert "settings" not in st and "setting_ranges" not in st
        assert _form_row(w, "AD_BALLS_PER_GAME")["range"] == "1 - 10"


def test_a_preset_keeps_its_ranges(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, rows=ROWS, every=EVERY, plan=None, hstd=None, project=proj)
        w.call("defaults.edit_apply", "AD_BALLS_PER_GAME", 12, False, 1, 15)
        w.answers.append("Long games")
        assert w.call("defaults.save_preset")["ok"]
        blob = w.app._settings["default_settings_presets"]
        saved = blob["presets"]["Long games"]
        assert saved[PRESET_RANGES_KEY] == {"AD_BALLS_PER_GAME": [1, 15]}
        assert saved["AD_BALLS_PER_GAME"] == 12
        assert w.state("defaults")["status"] == (
            "Saved preset \"Long games\" (2 settings).")
        w.call("defaults.reset")
        assert w.state("defaults")["values"]["AD_BALLS_PER_GAME"] == 3
        w.call("defaults.pick_preset", "Long games")
        assert w.state("defaults")["values"]["AD_BALLS_PER_GAME"] == 12
        assert _form_row(w, "AD_BALLS_PER_GAME")["range_chg"] is True
        # what the build reads off it: the range key is not a setting
        json.dumps(blob)


def test_mod_packs_and_transfers_carry_ranges():
    from pinball_decryptor.core import mod_transfer, modpack
    assert "setting_ranges" in mod_transfer._MERGE_KEYS
    assert "setting_ranges" in modpack._EXTRA_MAPS
