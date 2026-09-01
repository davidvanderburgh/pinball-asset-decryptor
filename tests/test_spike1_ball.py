"""The Spike 1 invisible-ball keeper: title-map resolution + input packing.

The daemon itself needs a live rig; these tests pin the pure pieces — how the
keeper resolves its slots from a curated switch map (names + the
``_trough_coils`` meta key) and that its SwitchInput blocks match the format
the responder and viewer share.
"""

import json
import os
import sys

_RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike1_emu")
if _RIG not in sys.path:
    sys.path.insert(0, _RIG)

import s1ball  # noqa: E402
from pinball_decryptor.plugins.stern.spike1_emulate import SwitchInput  # noqa: E402


def _write_map(tmp_path, extra=None):
    m = {
        "1,11": "START BUTTON",
        "1,16": "LEFT COIN SLOT",
        "9,1": "SHOOTER LANE",
        "8,9": "TROUGH #6 (L)",
        "8,10": "TROUGH #5 (L)",
        "8,11": "TROUGH #4 (L)",
        "8,12": "TROUGH #3",
        "8,13": "TROUGH #2",
        "8,14": "TROUGH #1 (R)",
        "8,15": "TROUGH JAM",
    }
    m.update(extra or {})
    (tmp_path / "s1switches.json").write_text(json.dumps(m), encoding="utf-8")


def test_title_map_resolves_slots_from_names(tmp_path):
    _write_map(tmp_path)
    (trough, shooter, start, coin, coils, curated,
     mapped) = s1ball.load_title_map(str(tmp_path))
    assert trough == [(8, 14), (8, 13), (8, 12), (8, 11), (8, 10), (8, 9)]
    assert shooter == (9, 1)
    assert start == (1, 11)
    assert coin == (1, 16)
    assert coils == s1ball.TROUGH_COILS          # no meta key -> fallback
    assert curated is False                      # meta key IS the marker
    assert mapped is True                        # trough came from THIS map


def test_trough_jam_is_not_a_trough_ball_slot(tmp_path):
    _write_map(tmp_path)
    trough, *_ = s1ball.load_title_map(str(tmp_path))
    assert (8, 15) not in trough


def test_trough_coils_meta_key_overrides(tmp_path):
    _write_map(tmp_path, {"_trough_coils": [[9, 2], [4, 0]]})
    *_, coils, curated, mapped = s1ball.load_title_map(str(tmp_path))
    assert coils == {(9, 2), (4, 0)}
    assert curated is True
    assert mapped is True


def test_missing_map_falls_back_to_got_constants(tmp_path):
    (trough, shooter, start, coin, coils, curated,
     mapped) = s1ball.load_title_map(str(tmp_path))
    assert trough == s1ball.TROUGH_SLOTS
    assert curated is False
    assert mapped is False                       # fallback slots, NOT held
    assert (shooter, start, coin) == (s1ball.SHOOTER, s1ball.START,
                                      s1ball.LEFT_COIN)
    assert coils == s1ball.TROUGH_COILS


def test_mapped_title_preloads_trough_without_coil_reactions(tmp_path):
    """A title whose map names its trough but has no ``_trough_coils`` yet
    (Ghostbusters LE at the time of writing) must still hold a FULL trough —
    otherwise the game sits in "LOCATING PINBALLS" — while its coil-serve
    reactions stay off (GOT-fallback coil numbers mean other coils there)."""
    _write_map(tmp_path)
    keeper = s1ball.Keeper(str(tmp_path))
    assert keeper.nballs == 6
    assert keeper.balls == 6
    assert keeper.trough_coils == set()
    closed, _ = SwitchInput.unpack((tmp_path / "s1auto.input").read_bytes())
    assert closed == {8 * 64 + i for i in range(9, 15)}   # the 6 trough bits


def test_unknown_title_stays_passive(tmp_path):
    keeper = s1ball.Keeper(str(tmp_path))                 # no map at all
    assert keeper.nballs == 0
    closed, _ = SwitchInput.unpack((tmp_path / "s1auto.input").read_bytes())
    assert closed == set()


def test_pack_input_matches_the_shared_switchinput_format():
    blob = s1ball.pack_input([(8, 14), (1, 11)], seq=9)
    closed, seq = SwitchInput.unpack(blob)
    assert closed == {8 * 64 + 14, 1 * 64 + 11}
    assert seq == 9


# ------------------------------------------------------------- state adopt --
# item 87: a save-state restore feeds the keeper the slot's published state,
# so a mid-game load models the same balls-in-play the restored game does.

def test_state_command_adopts_published_json(tmp_path):
    _write_map(tmp_path)
    k = s1ball.Keeper(str(tmp_path))
    k.run_cmd('state {"balls": 3, "in_shooter": true, "door_closed": false}')
    assert (k.balls, k.in_shooter, k.door_closed) == (3, True, False)
    # the adopted state is re-published for the switch window's widgets
    st = json.loads((tmp_path / "s1ball.state").read_text())
    assert st["balls"] == 3 and st["in_shooter"] is True


def test_state_command_clamps_to_the_trough_size(tmp_path):
    _write_map(tmp_path)
    k = s1ball.Keeper(str(tmp_path))
    k.run_cmd('state {"balls": 99}')
    assert k.balls == k.nballs


def test_state_command_ignores_bad_json(tmp_path):
    _write_map(tmp_path)
    k = s1ball.Keeper(str(tmp_path))
    before = (k.balls, k.in_shooter, k.door_closed)
    k.run_cmd("state this-is-not-json")
    assert (k.balls, k.in_shooter, k.door_closed) == before


# ------------------------------------------------------------ shipped maps --
# Every curated switchmap the rig ships must parse, name the switches the
# keeper resolves by, and carry the sweep-verified eject coils (WN, primus
# and can_crusher were added 2026-08-31 via the live-registry walk — all
# three run the Whoa Nellie platform, one trough switch, eject (8,5)).

def test_shipped_switchmaps_resolve_for_the_keeper():
    import glob
    maps = glob.glob(os.path.join(_RIG, "switchmaps", "*.json"))
    assert len(maps) >= 7          # GOT, GBLE, KISS, WWE, WN, primus, can_crusher
    for p in maps:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        names = [str(v).upper() for k, v in m.items()
                 if not str(k).startswith("_")]
        assert any(n == "START BUTTON" for n in names), p
        assert any(n.startswith("TROUGH") for n in names), p
        coils = m.get("_trough_coils")
        assert coils and all(len(c) == 2 for c in coils), p


# ------------------------------------------- a map that arrives after boot --
# The keeper starts with the game, and on a title with no curated map the rig
# only learns the switch names once the game has registered them (s1swmap.py's
# live walk).  A keeper that read the map once stayed passive for the session,
# so nothing held the trough and the machine sat on LOCATING PINBALLS on
# exactly those titles (PAD-101).

def test_keeper_adopts_a_map_written_after_it_started(tmp_path):
    k = s1ball.Keeper(str(tmp_path))               # no map yet
    assert (k.mapped, k.curated, k.nballs) == (False, False, 0)
    _write_map(tmp_path)                           # the live walk lands
    assert k.adopt_map() is True
    assert k.mapped is True and k.curated is False
    assert k.trough_slots == [(8, 14), (8, 13), (8, 12), (8, 11), (8, 10),
                              (8, 9)]
    assert k.start == (1, 11) and k.shooter == (9, 1)
    assert k.balls == k.nballs == 6                # the trough fills at once
    assert k.trough_coils == set()                 # no _trough_coils: no serve
    closed, _seq = SwitchInput.unpack(
        (tmp_path / "s1auto.input").read_bytes())
    assert len(closed) == 6                        # ... and it is HELD


def test_keeper_adopts_a_curated_map_with_its_eject_coils(tmp_path):
    k = s1ball.Keeper(str(tmp_path))
    _write_map(tmp_path, {"_trough_coils": [[8, 5]]})
    assert k.adopt_map() is True
    assert k.curated is True
    assert k.trough_coils == {(8, 5)}


def test_keeper_does_not_re_adopt_over_a_map_it_already_has(tmp_path):
    _write_map(tmp_path)
    k = s1ball.Keeper(str(tmp_path))               # mapped from the start
    k.balls = 3                                    # ... mid-game state
    _write_map(tmp_path, {"1,11": "START BUTTON"})
    assert k.adopt_map() is False                  # caller gates on mapped,
    assert k.balls == 3                            # and nothing was reset


def test_keeper_ignores_an_unchanged_map_file(tmp_path):
    k = s1ball.Keeper(str(tmp_path))
    assert k.adopt_map() is False                  # still no file at all
