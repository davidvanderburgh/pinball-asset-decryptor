"""Tests for PAD-396: a mode taken between the models of one game (Godzilla's Pro beside its Premium/LE).

A shot the other model names otherwise goes to its shot on the same switches; a mechanism that model
does not have is left out; the mode keeps its shots and mechanisms for every model it has been on, so
going back gives them back; Port to... replaces the earlier port and keeps what was set there. Desk
only: the real port files, no card, no emulator.
"""

import json

from pinball_decryptor.plugins.stern import mode_project as MP

LE_CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
PRO_CARD = "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"


def _proj(tmp_path, folder, name):
    project = tmp_path / folder
    project.mkdir()
    rec = {"input_path": "D:\\cards\\" + name, "input_name": name, "size": 1, "mtime": 1,
           "card_version": "1.16.0"}
    (project / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
    return project


def _premium_mode():
    """Made on the Premium/LE: its centre shield target, its shield ramp spinner, its bridge and
    Mechagodzilla magnet, and the magnet both models have."""
    spec = MP.ModeSpec(name="KAIJU BRIDGE", title="godzilla_le_1_16")
    spec.start_shot, spec.start_count = "Shield target center", 2
    spec.scoring_shots = ["Shield ramp spinner", "Left ramp", "Shield target right"]
    spec.shot_award = [["Shield ramp spinner", 5000]]
    spec.magnet_ms = 2000
    spec.coil_holds = [["bridge", 3000, "Left ramp"], ["mg_magnet", 2000, ""]]
    assert MP.validate(spec) == []
    return spec


def test_premium_mode_runs_on_the_pro():
    pro, le = MP.profile("godzilla_pro_1_16"), MP.profile("godzilla_le_1_16")
    old = _premium_mode()
    before = old.to_json()
    new, dropped = MP.retarget(old, pro)
    assert dropped == []
    assert new.title == "godzilla_pro_1_16"
    # the same switches, the Pro's names: its right shield target is the Premium's centre one's switch
    assert new.start_shot == "Shield target right"
    assert new.scoring_shots == ["Right spinner", "Left ramp", "Shield target right"]
    assert new.shot_award == [["Right spinner", 5000]]
    assert new.coil_holds == [] and new.magnet_ms == 2000       # no bridge on a Pro; the magnet is
    assert MP.validate(new) == []
    assert new.models["le"]["coil_holds"] == old.coil_holds
    assert new.ported == MP._model_fields(new)
    assert old.to_json() == before                               # the mode it came from is untouched
    words = MP.retarget_words(old, new, dropped, pro)
    assert "Shield ramp spinner is Right spinner on Godzilla Pro 1.16" in words
    assert "does not hold the bridge or the Mechagodzilla magnet" in words
    assert "Premium/LE shots and mechanisms are kept" in words
    assert "until you pick one" not in words
    assert le.key not in new.models


def test_back_to_the_premium_gives_its_own_back_and_keeps_the_pros():
    pro, le = MP.profile("godzilla_pro_1_16"), MP.profile("godzilla_le_1_16")
    old = _premium_mode()
    on_pro = MP.retarget(old, pro)[0]
    on_pro.scoring_shots = ["Right spinner", "Big loop"]         # the Pro's own choice
    on_pro.seconds = 45                                          # shared by every model
    back, dropped = MP.retarget(on_pro, le)
    assert dropped == []
    for f in MP.MODEL_FIELDS:
        assert getattr(back, f) == getattr(old, f), f
    assert back.seconds == 45
    assert back.models["pro"]["scoring_shots"] == ["Right spinner", "Big loop"]
    assert "takes back its own shots and mechanisms" in MP.retarget_words(on_pro, back, dropped, le)
    again = MP.retarget(back, pro)[0]
    assert again.scoring_shots == ["Right spinner", "Big loop"] and again.seconds == 45


def test_another_version_of_one_model_is_not_a_port():
    p15, p16 = MP.profile("godzilla_pro_1_15"), MP.profile("godzilla_pro_1_16")
    spec = MP.blank_spec(p15)
    new, dropped = MP.retarget(spec, p16)
    assert dropped == [] and new.models == {} and new.ported == {}
    assert MP.model_of_key("godzilla_le_1_16") == "le" and MP.model_word("godzilla_pro_1_15") == "Pro"
    assert MP.model_of_key("beatles_1_0") == "" and not MP.other_model(p15.key, p16)


def test_copy_to_the_pro_project_carries_it(tmp_path):
    src = _proj(tmp_path, "premium", LE_CARD)
    dest = _proj(tmp_path, "pro", PRO_CARD)
    slug, _s = MP.new_mode(str(src), spec=_premium_mode())
    r = MP.copy_modes(str(src), str(dest))
    assert [(m.slug, m.state) for m in r.modes] == [(slug, MP.COPY_CARRIED)]
    got = MP.load(str(dest / "modes" / slug / "mode.json"))
    assert got.title == "godzilla_pro_1_16" and MP.validate(got) == []


def test_port_replaces_the_earlier_port_and_keeps_the_pros_edits(tmp_path):
    src = _proj(tmp_path, "premium", LE_CARD)
    dest = _proj(tmp_path, "pro", PRO_CARD)
    slug, _s = MP.new_mode(str(src), spec=_premium_mode())
    assert MP.port_replaces(str(src), str(dest)) == []
    MP.port_modes(str(src), str(dest))
    path = dest / "modes" / slug / "mode.json"

    # an untouched port is made again from the Premium's edit
    spec = MP.load(str(src / "modes" / slug / "mode.json"))
    spec.scoring_shots = ["Shield ramp spinner", "Right ramp"]
    MP.save(str(src), slug, spec)
    assert MP.port_replaces(str(src), str(dest)) == ["KAIJU BRIDGE"]
    r = MP.port_modes(str(src), str(dest))
    assert [(m.state, m.new_slug) for m in r.modes] == [(MP.COPY_CARRIED, slug)]
    assert [s for s, _ in MP.list_modes(str(dest))[0]] == [slug]          # replaced, not a _2
    assert MP.load(str(path)).scoring_shots == ["Right spinner", "Right ramp"]

    # an edit made on the Pro stays the Pro's; what every model shares follows the Premium
    on_pro = MP.load(str(path))
    on_pro.start_shot = "Big loop"
    MP.save(str(dest), slug, on_pro)
    spec.seconds = 50
    MP.save(str(src), slug, spec)
    MP.port_modes(str(src), str(dest))
    got = MP.load(str(path))
    assert got.start_shot == "Big loop" and got.scoring_shots == ["Right spinner", "Right ramp"]
    assert got.seconds == 50 and MP.validate(got) == []


def test_port_targets_are_the_other_models_projects(tmp_path):
    src = _proj(tmp_path, "premium", LE_CARD)
    pro = _proj(tmp_path, "pro", PRO_CARD)
    other = _proj(tmp_path, "premium2", LE_CARD)
    turtles = _proj(tmp_path, "tmnt", "turtles_pro-1_59_0.Release.8G.sdcard.raw")
    got = MP.port_targets(str(src), [str(src), str(other), str(turtles), str(pro), str(tmp_path / "gone")])
    assert got == [(str(pro), "Godzilla Pro 1.16 (pro)", "Pro")]
    back = MP.port_targets(str(pro), [str(src)])
    assert [m for _f, _w, m in back] == ["Premium/LE"]
