"""PAD-666: a new mode starts on a shot no other mode of the project starts on.

David's Heisei card went out with a stray NEW MODE (the blank form's default: Maser target x3) whose start
shot was MASER BARRAGE's: both counted the same hits. A blank form mode, and a new blocks mode's starter,
now take a free shot (mode_project.start_shots_taken); with nothing taken they are what they always were.
"""

import json

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP
from tests.mode_examples.blocks import examples as BX
from tests.test_app_run_logic_modes import _modes_card_project, _project, _svc
from tests.webui_harness import web_app

LE = MP.profile_for_card("godzilla_le", "1.16.0")
CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def _maser_barrage(project):
    """MASER BARRAGE's own trigger: its idle Maser target hat (the Godzilla blocks program kept as test material, without its media)."""
    ex = BX.example("MASER BARRAGE")
    program = BX.without_media(ex["program"])
    BM.save(str(project), "maser_barrage", program)
    return program


def test_nothing_taken_leaves_the_blank_mode_as_it_was():
    assert MP.blank_spec(LE) == MP.blank_spec(LE, taken=set())
    assert MP.blank_spec(LE).start_shot == "Maser target"
    assert MP.blank_spec(MP.GODZILLA_PRO_1_15, taken=set()) == MP.ModeSpec(name="NEW MODE")


def test_a_taken_start_shot_moves_to_the_first_free_non_ramp_shot():
    spec = MP.blank_spec(LE, taken={"Maser target"})
    assert spec.start_shot == "Building"
    assert spec.scoring_shots == ["Left ramp", "Right ramp"]
    spec = MP.blank_spec(LE, taken={"Maser target", "Building"})
    assert spec.start_shot == "Godzilla target"
    # every playfield shot taken: the example shot stays (sharing beats no mode)
    every = set(MP.playfield_shots(LE))
    assert MP.blank_spec(LE, taken=every).start_shot == "Maser target"


def test_a_start_shot_never_scores_too():
    names = [n for n, _m in LE.shots]
    ramps = [n for n in names if n.lower().endswith("ramp")]
    taken = set(MP.playfield_shots(LE)) - {ramps[0]}
    spec = MP.blank_spec(LE, taken=taken)
    assert spec.start_shot == ramps[0]
    assert ramps[0] not in spec.scoring_shots and len(spec.scoring_shots) == 2


def test_the_shots_taken_by_form_and_blocks_modes(tmp_path):
    project = _modes_card_project(tmp_path, CARD, "1.16.0")
    assert MP.start_shots_taken(str(project)) == set()
    _maser_barrage(project)
    MP.new_mode(str(project), "TWO WAYS", MP.ModeSpec(name="TWO WAYS", title=LE.key, start_shot="Left spinner",
                                                     start_or=["Top spinner"], start_also=[["Building", 2]]))
    MP.new_mode(str(project), "IN ORDER", MP.ModeSpec(name="IN ORDER", title=LE.key, starts_on="sequence",
                                                     start_sequence=["Left ramp", "Right ramp"]))
    MP.new_mode(str(project), "ON EVENT", MP.ModeSpec(name="ON EVENT", title=LE.key, starts_on="event x",
                                                     start_shot="Godzilla target"))
    lit = BM.starter("LIT", ["Shield target left", "Big loop"])
    lit["scripts"][0]["do"] = [{"op": "light_mode", "shot": "Big loop", "color": "#ff0000", "pattern": "blink"}]
    BM.save(str(project), "lit", BM.normalize(lit))
    (project / "modes" / "broken").mkdir()
    (project / "modes" / "broken" / BM.BLOCKS_FILE).write_text("not json", encoding="utf-8")
    assert MP.start_shots_taken(str(project)) == {
        "Maser target",                                       # MASER BARRAGE's idle hat
        "Left spinner", "Top spinner", "Building",            # start shot, its "or" and its "and also"
        "Left ramp", "Right ramp",                            # shots in order
        "Shield target left", "Big loop",                     # a blocks idle hat and where it lights itself
    }                                                         # ON EVENT's shot starts nothing; broken is skipped
    assert MP.start_shots_taken("") == set()


def test_new_on_the_tab_takes_a_free_shot(tmp_path):
    """David's case: New > Form > Blank mode beside MASER BARRAGE, and New > Blocks beside both."""
    project = _modes_card_project(tmp_path, CARD, "1.16.0")
    _maser_barrage(project)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        assert _svc(w)._profile.key == LE.key
        slug = w.call("modes.new")
        spec = MP.load(str(project / "modes" / slug / MP.MODE_FILE))
        assert (spec.name, spec.start_shot, spec.start_count) == ("NEW MODE", "Building", 3)
        w.call("modes.new")                                  # a second one: Building is taken now too
        assert MP.load(str(project / "modes" / "new_mode_2" / MP.MODE_FILE)).start_shot == "Godzilla target"
        MP.save(str(project), "kaiju_ramps", MP.ModeSpec(name="KAIJU RAMPS", title=LE.key, start_shot="Left ramp"))
        slug = w.call("modes.new_blocks_mode", "NEW BLOCKS")
        program = json.loads((project / "modes" / slug / BM.BLOCKS_FILE).read_text(encoding="utf-8"))
        start = program["scripts"][0]["hat"]
        assert start["kind"] == "shot" and start["when"] == "idle"
        assert start["shot"] == "Right ramp"                 # Left ramp is KAIJU RAMPS's
        assert start["shot"] not in {"Maser target", "Building", "Godzilla target", "Left ramp"}
