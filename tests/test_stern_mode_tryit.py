"""Tests for :mod:`pinball_decryptor.plugins.stern.mode_tryit` (item 127, its set built by item
149's Write code).

Try it hands its build to :func:`mode_write.build_tryit_set` (``engine.write_overrides``: Write's
own code, tested in ``test_stern_mode_write_engine``) and keeps what is its own: the layout (the
stage BESIDE the set, as ``<set>-modes``), the pure launch environment, the title check (the card
being booted is the build the modes are for, matched to the project's card by item 148), code
modes and the rig script. Here Write's builder is stood in for by :func:`_writes_builder`, which
lays out the payload a real one does; the real cards of every ported title run it for real where
this PC has them (read-only, a second or two each). Desk only.
"""

import json
import os

import pytest

# The mode maker ships dark behind a preview switch (core/preview.py); these tests are
# about what it does when it is ON (tests/test_preview_switch.py covers it OFF).
pytestmark = pytest.mark.usefixtures("preview_modes_on")

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_tryit as MT

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"
GZ = MP.GODZILLA_PRO_1_15


def _quiet(project, name, **kw):
    kw.setdefault("screen", False)
    kw.setdefault("clip", "none")
    return MP.new_mode(project, name, MP.ModeSpec(name=name, **kw))


def _writes_builder(monkeypatch, calls, files=None, end_sound=None, own_sounds=None):
    """Stand in for :func:`mode_write.build_tryit_set` and record what Try it handed it. It lays
    out what the real one does, from the project's own modes matched to its card: the set's
    files (by default the game program and the rebuilt manifest, what Write's set holds for
    modes with no screen or clip) and the stage beside it - the pinned object, the title's
    port and each slot's mode file."""
    from pinball_decryptor.plugins.stern import mode_write as MW

    def build(project, card, base, log=None, progress=None, cancel=None, label=None):
        calls.append((project, card, base))
        modes = MW.card_modes(project, MW.project_modes(project))
        prof = MP.profile(modes[0][1].title)
        s = os.path.join(base, MW.TRYIT_SET)
        stage = s + "-modes"
        held = (["%s/game" % prof.game_dir, "spk/index/%s-x.sidx" % prof.game_dir]
                if files is None else list(files))
        for rel in held:
            path = os.path.join(s, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"set file")
        os.makedirs(stage, exist_ok=True)
        with open(MR.prebuilt_object(), "rb") as a, open(os.path.join(stage, "pad_mode.so"), "wb") as b:
            b.write(a.read())
        with open(MP.port_path(prof), "rb") as a, open(os.path.join(stage, "game.port"), "wb") as b:
            b.write(a.read())
        names = []
        for slot, (slug, spec) in enumerate(modes):
            name = "mode.cfg" if slot == 0 else "mode%d.cfg" % slot
            own = (own_sounds or {}).get(slug) or {}
            with open(os.path.join(stage, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(MP.runtime_cfg(spec, slug, own_sounds=own.get("requests") or None,
                                       own_sound_ms=own.get("ms") or None))
            names.append(name)
        return MW.TryItSet(set_dir=s, stage_dir=stage, game_dir=prof.game_dir, version=prof.version,
                           files=held, new_files=[], mode_files=names,
                           slots=[(i, g, m.name) for i, (g, m) in enumerate(modes)],
                           port=os.path.join(stage, "game.port"), end_sound=end_sound,
                           own_sounds=dict(own_sounds or {}))
    monkeypatch.setattr(MW, "build_tryit_set", build)
    return build


def _card(tmp_path, name="card.raw"):
    card = tmp_path / name
    card.write_bytes(b"\0" * 64)
    return str(card)


def test_try_env_is_pure_and_names_the_set_and_the_object():
    env = MT.try_env(r"C:\Users\x\AppData\Local\Temp\spike2_mode_tryit\set")
    assert env == ["PAD_OVERRIDE_DIR=/mnt/c/Users/x/AppData/Local/Temp/spike2_mode_tryit/set",
                   "PAD_MODE_SO=/lib/pad_mode.so"]
    assert MT.try_env("/home/me/set")[0] == "PAD_OVERRIDE_DIR=/home/me/set"
    assert MT.try_env()[0].startswith("PAD_OVERRIDE_DIR=")


def test_run_env_binds_the_set_only_when_it_holds_a_file_of_the_title(tmp_path, monkeypatch):
    """A set with no file of the TITLE is refused by run_game.sh (exit 1, before boot), so that
    run takes only the object. Write's set always carries the rebuilt spk/index manifest, which
    sits BESIDE the title: a card run mounts only the title's directory and skips it, so a set
    of nothing else (Jaws, whose program has no validator to bypass) takes the object alone
    too. A set with the game program or a scene is bound."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Alpha")
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    base = str(tmp_path / "try")
    _writes_builder(monkeypatch, [], files=[])
    ts = MT.build_set(project, _card(tmp_path), base=base)
    assert ts.files == [] and MT.run_env(ts) == ["PAD_MODE_SO=/lib/pad_mode.so"]
    _writes_builder(monkeypatch, [], files=["spk/index/godzilla_pro-1_15_0.sidx"])
    ts = MT.build_set(project, _card(tmp_path), base=base)
    assert MT.title_files(ts) == [] and MT.run_env(ts) == ["PAD_MODE_SO=/lib/pad_mode.so"]
    _writes_builder(monkeypatch, [])
    ts = MT.build_set(project, _card(tmp_path), base=base)
    assert MT.title_files(ts) == ["godzilla_pro/game"]
    assert MT.run_env(ts) == MT.try_env(ts.set_dir)
    assert MT.run_env(ts)[0].startswith("PAD_OVERRIDE_DIR=")
    # a file under ANOTHER title's tree is not this title's either
    other = MT.TrySet(set_dir=ts.set_dir, stage_dir=ts.stage_dir, game_dir="godzilla_pro",
                      version="1.15.0", files=["godzilla_le/game"])
    assert MT.run_env(other) == ["PAD_MODE_SO=/lib/pad_mode.so"]


def test_the_stage_is_beside_the_set_never_in_it(tmp_path):
    s, r = MT.set_dir(str(tmp_path)), MT.stage_dir(str(tmp_path))
    assert os.path.dirname(s) == os.path.dirname(r) and not r.startswith(s + os.sep)


def test_profile_version_and_the_title_check():
    assert MT.profile_version(GZ) == "1.15"
    MT.check_title(GZ, "godzilla_pro", "1.15.0")
    MT.check_title(GZ, "godzilla_pro", "1.15")
    with pytest.raises(MT.TryItError, match="Godzilla Pro 1.15"):
        MT.check_title(GZ, "godzilla_le", "1.16.0")
    with pytest.raises(MT.TryItError):
        MT.check_title(GZ, "godzilla_pro", "1.16.0")


def test_the_set_is_built_by_writes_code(tmp_path, monkeypatch):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Alpha")
    _quiet(project, "Beta", seconds=12, award=250000)
    card = _card(tmp_path)
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    calls = []
    _writes_builder(monkeypatch, calls)
    base = str(tmp_path / "try")
    said = []
    ts = MT.build_set(project, card, base=base, log=said.append)
    assert calls == [(project, card, base)]
    assert any("Write's own code" in m for m in said)
    assert ts.set_dir == MT.set_dir(base) and ts.stage_dir == MT.stage_dir(base)
    assert ts.version == "1.15.0" and ts.game_dir == "godzilla_pro"
    assert ts.slots == [(0, "alpha", "Alpha"), (1, "beta", "Beta")]
    assert ts.mode_files == ["mode.cfg", "mode1.cfg"] and sorted(ts.specs) == ["alpha", "beta"]
    assert sorted(os.listdir(ts.stage_dir)) == ["game.port", "mode.cfg", "mode1.cfg", "pad_mode.so"]
    beta = open(os.path.join(ts.stage_dir, "mode1.cfg"), encoding="utf-8").read()
    assert "name           Beta" in beta and "seconds        12" in beta


def test_a_card_for_another_build_is_refused(tmp_path, monkeypatch):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Alpha")
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_le", "1.16.0", 2))
    calls = []
    _writes_builder(monkeypatch, calls)
    with pytest.raises(MT.TryItError, match="Godzilla Pro 1.15"):
        MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert not calls


def test_a_project_without_modes_or_a_card_says_so(tmp_path):
    with pytest.raises(MT.TryItError, match="no modes"):
        MT.build_set(str(tmp_path), None, base=str(tmp_path / "try"))
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Alpha")
    with pytest.raises(MT.TryItError, match="card image"):
        MT.build_set(project, str(tmp_path / "missing.raw"), base=str(tmp_path / "try"))


def test_a_folder_that_is_not_ours_is_never_cleared(tmp_path, monkeypatch):
    """Write's own guard: write_overrides never empties a folder it did not make."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Alpha")
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    base = tmp_path / "try"
    (base / "set").mkdir(parents=True)
    (base / "set" / "notes.txt").write_text("mine")
    with pytest.raises(MT.TryItError, match="not put there by this app"):
        MT.build_set(project, _card(tmp_path), base=str(base))
    assert (base / "set" / "notes.txt").read_text() == "mine"


def test_the_sounds_a_set_does_not_carry_are_named(tmp_path, monkeypatch):
    """The ready line names a mode whose own sound the set (so a card) does not carry."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    for name, kw in (("Alpha", {"end_sound": "end.wav"}),
                     ("Beta", {"end_sound": "end.wav", "sound_start": "go.wav"})):
        slug, _spec = _quiet(project, name)
        for wav in ("end.wav", "go.wav"):
            with open(os.path.join(MP.mode_folder(project, slug), wav), "wb") as f:
                f.write(b"RIFF")
        spec = MP.load(os.path.join(MP.mode_folder(project, slug), MP.MODE_FILE))
        for k, v in kw.items():
            setattr(spec, k, v)
        MP.save(project, slug, spec)
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    _writes_builder(monkeypatch, [], end_sound={"name": "Alpha", "request": 1295, "idx": 1560},
                    own_sounds={"beta": {"requests": {"sound_start": 1251}, "ms": {}}})
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert MT.sounds_left_out(ts) == ["Beta"]             # its end sound: a card carries one
    _writes_builder(monkeypatch, [], end_sound={"name": "Beta", "request": 1295, "idx": 1560},
                    own_sounds={"beta": {"requests": {"sound_start": 1251}, "ms": {}}})
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert MT.sounds_left_out(ts) == ["Alpha"]
    _writes_builder(monkeypatch, [], end_sound={"name": "Beta", "request": 1295, "idx": 1560})
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert MT.sounds_left_out(ts) == ["Alpha", "Beta"]    # Beta's start sound is not carried
    _quiet(project, "Gamma")
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert "Gamma" not in MT.sounds_left_out(ts)


def test_slots_code_modes_and_what_waits_for_the_next_try(tmp_path):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Beta")
    _quiet(project, "Alpha")
    assert MT.slot_of(project, "alpha") == 0 and MT.slot_of(project, "beta") == 1
    assert MT.slot_of(project, "nope") is None
    code = os.path.join(MP.mode_folder(project, "blitz"), "blitz.c")
    os.makedirs(os.path.dirname(code))
    open(code, "w").write("/* a mode */\n")
    assert MT.code_mode_sources(project) == [("blitz", code)]
    spec = MP.ModeSpec(name="X")
    before = MT.asset_signature(spec)
    spec.award, spec.seconds, spec.name = 5, 9, "Y"
    assert MT.asset_signature(spec) == before           # these reload live
    spec.panel_color = "#000000"
    assert MT.asset_signature(spec) != before           # this waits for the next Try it
    # the family's built assets wait too: a second clip (141), a new span of a film (142)
    for key, value in (("clip_both", {"clip": "title", "title": "END"}), ("clip_from", 12.5),
                       ("art_from", 3.0)):
        before = MT.asset_signature(spec)
        setattr(spec, key, value)
        assert MT.asset_signature(spec) != before, key
    # a mode's own sounds (150) are built into the set's sound bank: an edit to one waits
    # for the next Try it, and the tab says so
    sounds = MT.sound_signature(spec)
    assert MT.own_sound_modes([spec]) == []
    spec.music = "theme.wav"
    assert MT.sound_signature(spec) != sounds and MT.own_sound_modes([spec]) == ["Y"]


@pytest.mark.skipif(not os.path.isfile(CARD), reason="the Godzilla Pro 1.15 card image is not here")
def test_the_title_is_read_from_the_card_itself():
    game_dir, version, _part = MT.card_title(CARD)
    assert (game_dir, version) == ("godzilla_pro", "1.15.0")


def test_code_mode_text_renames_everything_the_template_names():
    template = open(os.path.join(MR.sdk_dir(), "template_mode.c"), encoding="utf-8").read()
    out = MT.code_mode_text(template, "Blitz Rush", "blitz_rush")
    assert '#define MODE_NAME        "Blitz Rush"' in out
    assert '"PadMode_blitz_rush_Screen"' in out
    assert '"PadMode_blitz_rush_Screen.PadMode_blitz_rush_Screen_Words"' in out
    assert 'pm_trigger("blitz_rush.start")' in out and 'pm_trigger("blitz_rush.stop")' in out
    assert "PM_REGISTER(blitz_rush_mode);" in out
    for gone in ("TARGET RUSH\"", "PadMode_template_", '"template.start"', "target_rush"):
        assert gone not in out, gone
    assert "m_2x_mode" in MT.code_mode_text(template, "2x", "2x")   # a C name cannot start with a digit


def test_new_code_mode_never_overwrites(tmp_path):
    slug, path = MT.new_code_mode(str(tmp_path), "Blitz")
    slug2, path2 = MT.new_code_mode(str(tmp_path), "Blitz")
    assert (slug, slug2) == ("blitz", "blitz_2") and os.path.isfile(path) and os.path.isfile(path2)
    assert MT.code_mode_sources(str(tmp_path)) == [("blitz", path), ("blitz_2", path2)]


def _bash():
    import shutil
    import sys
    return shutil.which("bash") if sys.platform != "win32" else None


@pytest.mark.skipif(not _bash(), reason="the rig script runs under Linux bash")
def test_tryit_sh_installs_triggers_and_pushes(tmp_path):
    """modes/tryit.sh against a stand-in rootfs (PAD_ROOT): the object into lib, the port
    and mode files into dump after the old ones are cleared, and the trigger files."""
    import subprocess
    script = os.path.join(os.path.dirname(MR.sdk_dir()), "tryit.sh")
    root = tmp_path / "root"
    (root / "lib").mkdir(parents=True)
    (root / "dump").mkdir()
    for stale in ("mode3.cfg", "mode.start", "mode.log", "mode.stop"):
        (root / "dump" / stale).write_text("old")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "pad_mode.so").write_bytes(b"\x7fELF")
    (stage / "game.port").write_text("game godzilla_pro\n")
    (stage / "mode.cfg").write_text("name A\n")
    (stage / "mode1.cfg").write_text("name B\n")
    env = dict(os.environ, PAD_HOME=str(tmp_path), PAD_ROOT=str(root))

    def run(*args):
        return subprocess.run(["bash", script] + list(args), env=env, capture_output=True,
                              text=True, timeout=60)
    r = run("install", str(stage))
    assert r.returncode == 0, r.stderr
    assert (root / "lib" / "pad_mode.so").read_bytes() == b"\x7fELF"
    assert sorted(os.listdir(root / "dump")) == ["game.port", "mode.cfg", "mode1.cfg"]
    assert run("start", "0").returncode == 0 and (root / "dump" / "mode.start").exists()
    assert run("start", "2").returncode == 0 and (root / "dump" / "mode2.start").exists()
    assert run("stop").returncode == 0 and (root / "dump" / "mode.stop").exists()
    edited = tmp_path / "edited.cfg"
    edited.write_text("name B2\n")
    assert run("push", str(edited), "1").returncode == 0
    assert (root / "dump" / "mode1.cfg").read_text() == "name B2\n"
    assert not [n for n in os.listdir(root / "dump") if n.endswith(".tmp")]
    assert run("start", "9").returncode != 0
    assert run("install", str(tmp_path / "nothing")).returncode != 0


@pytest.mark.skipif(not _bash(), reason="the rig script runs under Linux bash")
def test_tryit_sh_stop_ends_code_modes_by_their_own_trigger(tmp_path):
    """End mode on a Try it run with CODE modes: a code mode reads only its own
    ``/dump/<folder>.stop``, never ``mode.stop``. ``stop NAME...`` writes both, and a name
    that is not a plain [a-z0-9_] folder name is refused before anything is written."""
    import subprocess
    script = os.path.join(os.path.dirname(MR.sdk_dir()), "tryit.sh")
    root = tmp_path / "root"
    (root / "lib").mkdir(parents=True)
    (root / "dump").mkdir()
    env = dict(os.environ, PAD_HOME=str(tmp_path), PAD_ROOT=str(root))

    def run(*args):
        return subprocess.run(["bash", script] + list(args), env=env, capture_output=True,
                              text=True, timeout=60)
    r = run("stop", "blitz", "code_only_2")
    assert r.returncode == 0, r.stderr
    assert sorted(os.listdir(root / "dump")) == ["blitz.stop", "code_only_2.stop", "mode.stop"]
    for n in os.listdir(root / "dump"):
        os.unlink(root / "dump" / n)
    for bad in ("../lib/x", "Blitz", "a b", ""):
        assert run("stop", "blitz", bad).returncode != 0, bad
        assert os.listdir(root / "dump") == [], bad


# ---- item 148: the PROJECT'S CARD decides the title --------------------------------------
LE_CARD = "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
PRO_CARD = "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"


def _name_card(project, card_name, card_version):
    """The project's extract record, naming the card it was made from (item 148)."""
    rec = {"input_path": "D:\\cards\\" + card_name, "input_name": card_name, "size": 1,
           "mtime": 1, "card_version": card_version}
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f)


def _le():
    return MP.profile_for_card("godzilla_le", "1.16.0")


def test_the_projects_card_decides_the_title_as_a_build_does(tmp_path, monkeypatch):
    """A mode keeps the title it was made for in mode.json (every mode made before item 148
    says Godzilla Pro 1.15), but the project's CARD decides the port, the masks and the
    scenes. A project made from a Premium/LE 1.16 card with its modes saved as Pro 1.15
    (David's own) runs on its own card: the title check takes LE 1.16, the run's specs carry
    LE's masks, and Write's builder (mode_write.card_modes) stages LE's port and mode files."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _name_card(project, LE_CARD, "1.16.0")
    slug, spec = _quiet(project, "Shield", scoring_shots=["Shield target right", "Left ramp"])
    assert spec.title == GZ.key
    mode_json = os.path.join(MP.mode_folder(project, slug), MP.MODE_FILE)
    saved = open(mode_json, "rb").read()
    le = _le()
    shots = ["Shield target right", "Left ramp"]
    assert le.mask(shots) != GZ.mask(shots)                 # the two builds' masks differ
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_le", "1.16.0", 2))
    _writes_builder(monkeypatch, [])
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert ts.specs[slug].title == le.key and ts.slots == [(0, slug, "Shield")]
    with open(os.path.join(ts.stage_dir, "game.port"), "rb") as a, open(MP.port_path(le), "rb") as b:
        assert a.read() == b.read()
    cfg = open(os.path.join(ts.stage_dir, "mode.cfg"), encoding="utf-8").read()
    assert "shots          0x%08x" % le.mask(shots) in cfg
    assert cfg == MP.runtime_cfg(MP.retarget(spec, le)[0], slug)
    assert open(mode_json, "rb").read() == saved            # a run matches it, never rewrites it
    # the project's card is the one to pick: a Pro 1.15 card is refused, naming the card's game
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    with pytest.raises(MT.TryItError, match="Godzilla Premium/LE 1.16"):
        MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try2"))
    # a project that names no card keeps each mode's own title, as before item 148
    bare = str(tmp_path / "bare")
    os.makedirs(bare)
    _quiet(bare, "Shield", scoring_shots=shots)
    ts = MT.build_set(bare, _card(tmp_path), base=str(tmp_path / "try3"))
    assert "shots          0x%08x" % GZ.mask(shots) in open(
        os.path.join(ts.stage_dir, "mode.cfg"), encoding="utf-8").read()


def test_a_mode_naming_a_shot_the_projects_card_lacks_is_refused(tmp_path):
    """Never a run with shots quietly left out: the same refusal a build gives."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _name_card(project, PRO_CARD, "1.15.0")
    le = _le()
    MP.new_mode(project, "Sling", MP.ModeSpec(name="Sling", title=le.key, screen=False, clip="none",
                                              scoring_shots=["Slingshot", "Left ramp"]))
    with pytest.raises(MT.TryItError, match="Slingshot"):
        MT.build_set(project, None, base=str(tmp_path / "try"))


def test_project_title_names_the_card_to_pick(tmp_path):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    assert MT.project_title(project).key == GZ.key          # no card, no modes
    MP.new_mode(project, "Alpha", MP.ModeSpec(name="Alpha", title=_le().key, screen=False,
                                              clip="none"))
    assert MT.project_title(project).key == _le().key       # no card: the modes' own title
    _name_card(project, PRO_CARD, "1.15.0")
    assert MT.project_title(project).key == GZ.key          # the card decides


# ---- item 148's other titles: only the scenes a title can use are read ---------------------
SPIKE2_IMAGES = r"D:\Pinball\images\Stern\spike2"
OTHER_TITLES = (
    ("turtles_pro_1_58", "turtles_pro-1_58_0.Release.8G.sdcard.raw", "1.58.0"),
    ("turtles_pro_1_59", "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0"),
    ("deadpool_pro_1_16", "deadpool_pro-1_16_0.Release.8G.sdcard.raw", "1.16.0"),
    ("deadpool_le_1_14", "deadpool_le-1_14_0.Release.8G.sdcard.raw", "1.14.0"),
    ("jaws_le_1_02", "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0"),
    ("godzilla_le_1_16", LE_CARD, "1.16.0"),
)


def test_write_reads_only_the_scenes_a_title_can_use():
    """Item 148 through Write's code: TMNT Pro and Deadpool's ports name no HUD scene, and a
    lookup of ``/turtles_pro/assets/lcd/auto_loaded//scene.radium`` refused every form mode
    there. Write's scene paths name only the scenes a build adds to."""
    from pinball_decryptor.plugins.stern import mode_write as MW
    le = _le()
    lcd = "assets/lcd/auto_loaded"
    assert MW.scene_rels(GZ) == ("godzilla_pro/%s/%s/scene.radium" % (lcd, GZ.hud_scene),
                                 "godzilla_pro/%s/%s/scene.radium" % (lcd, GZ.bank_scene))
    assert all(MW.scene_rels(le))
    for key in ("turtles_pro_1_58", "turtles_pro_1_59", "deadpool_pro_1_16", "deadpool_le_1_14"):
        prof = MP.profile(key)
        assert prof.hud_scene == "" and not prof.can("screen") and not prof.can("clip"), key
        assert MW.scene_rels(prof) == ("", ""), key
    jaws = MP.profile("jaws_le_1_02")
    assert not jaws.can("screen") and jaws.can("clip")
    assert MW.scene_rels(jaws) == ("", "jaws_le/%s/%s/scene.radium" % (lcd, jaws.bank_scene))


@pytest.mark.parametrize("key,card_name,card_version", OTHER_TITLES)
def test_try_it_takes_a_form_mode_on_every_ported_title(tmp_path, monkeypatch, key, card_name,
                                                        card_version):
    """Item 127 with item 148: a project made from each ported title's card passes Try it's
    title check and hands Write's builder the title's own modes: its masks in the specs, its
    port in the stage."""
    prof = MP.profile(key)
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _name_card(project, card_name, card_version)
    shots = [n for n, _m in prof.shots][:2]
    slug, _spec = MP.new_mode(project, "RUSH", MP.ModeSpec(
        name="RUSH", title=prof.key, start_shot=prof.example_start_shot, scoring_shots=shots,
        screen=False, clip="none"))
    monkeypatch.setattr(MT, "card_title", lambda c: (prof.game_dir, card_version, 3))
    calls = []
    _writes_builder(monkeypatch, calls)
    ts = MT.build_set(project, _card(tmp_path, card_name), base=str(tmp_path / "try"))
    assert len(calls) == 1
    assert (ts.game_dir, ts.version) == (prof.game_dir, card_version)
    with open(os.path.join(ts.stage_dir, "game.port"), "rb") as a, open(MP.port_path(prof), "rb") as b:
        assert a.read() == b.read()
    cfg = open(os.path.join(ts.stage_dir, "mode.cfg"), encoding="utf-8").read()
    assert ts.specs[slug].title == prof.key and cfg == MP.runtime_cfg(ts.specs[slug], slug)
    assert "shots          0x%08x" % prof.mask(shots) in cfg


def test_a_mode_made_on_godzilla_runs_on_a_tmnt_card_without_its_screen_or_clip(tmp_path, monkeypatch):
    """A mode saved as Godzilla Pro 1.15 with a screen and a title clip, in a project made
    from a TMNT Pro 1.59 card: its shots are TMNT's by name, and the parts TMNT cannot do are
    left out, as a Write build leaves them out."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _name_card(project, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    slug, spec = MP.new_mode(project, "LOUD", MP.ModeSpec(
        name="LOUD", start_shot="Left ramp", scoring_shots=["Left ramp", "Right ramp"],
        screen=True, clip="title"))
    assert spec.title == GZ.key
    monkeypatch.setattr(MT, "card_title", lambda c: ("turtles_pro", "1.59.0", 3))
    _writes_builder(monkeypatch, [])
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"), ffmpeg=None)
    cfg = open(os.path.join(ts.stage_dir, "mode.cfg"), encoding="utf-8").read()
    assert "shots          0x00000210" in cfg                     # TMNT's Left + Right ramp
    for gone in ("screen_scene", "clip_start"):
        assert gone not in cfg
    assert ts.specs[slug].title == "turtles_pro_1_59"


@pytest.mark.parametrize("key,card_name,card_version", OTHER_TITLES + (
    ("godzilla_pro_1_15", PRO_CARD, "1.15.0"),))
def test_the_real_cards_give_a_run_through_writes_code(tmp_path, monkeypatch, key, card_name,
                                                      card_version):
    """The real thing, no stand-in: Try it on each ported title's real card image (read-only)
    builds its set with engine.write_overrides in a second or two. The stage carries the
    pinned object, the title's own port and the mode file; the set holds the patched game
    program where the title has a validator to bypass (every one but Jaws), so the run binds
    it; Jaws' set holds only the manifest beside the title, so its run takes the object alone
    (run_game.sh would refuse a set that binds nothing)."""
    card = os.path.join(SPIKE2_IMAGES, card_name)
    if not os.path.isfile(card):
        pytest.skip("%s is not here" % card_name)
    pytest.importorskip("numpy")
    # the build's host gate: on a Mac a Write (and so this set) leaves the modes out
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    prof = MP.profile(key)
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _name_card(project, card_name, card_version)
    slug, _spec = MP.new_mode(project, "RUSH", MP.ModeSpec(
        name="RUSH", title=prof.key, start_shot=prof.example_start_shot,
        scoring_shots=[n for n, _m in prof.shots][:2], screen=False, clip="none"))
    ts = MT.build_set(project, card, base=str(tmp_path / "try"))
    assert sorted(os.listdir(ts.stage_dir)) == ["game.port", "mode.cfg", "pad_mode.so"]
    with open(os.path.join(ts.stage_dir, "game.port"), "rb") as a, open(MP.port_path(prof), "rb") as b:
        assert a.read() == b.read()
    with open(os.path.join(ts.stage_dir, "pad_mode.so"), "rb") as a, \
            open(MR.prebuilt_object(), "rb") as b:
        assert a.read() == b.read()
    cfg = open(os.path.join(ts.stage_dir, "mode.cfg"), encoding="utf-8").read()
    assert cfg == MP.runtime_cfg(ts.specs[slug], slug)
    assert "spk/index/%s-%s.sidx" % (prof.game_dir, card_version.replace(".", "_")) in ts.files
    if key == "jaws_le_1_02":
        assert MT.title_files(ts) == [] and MT.run_env(ts) == ["PAD_MODE_SO=/lib/pad_mode.so"]
    else:
        assert MT.title_files(ts) == ["%s/game" % prof.game_dir]
        assert MT.run_env(ts) == MT.try_env(ts.set_dir)


@pytest.mark.skipif(not _bash() or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="the rig script runs under Linux bash, as a user root does not stop")
def test_tryit_sh_install_names_a_root_owned_lib_and_the_fix(tmp_path):
    """A first emulator Start with save states unpacks the guest filesystem as ROOT (PAD-140
    met it), and Try it installs as the desktop user: cp said only "Permission denied".
    install refuses before touching anything, naming the directory, its owner and the
    command that hands it back."""
    import subprocess
    script = os.path.join(os.path.dirname(MR.sdk_dir()), "tryit.sh")
    root = tmp_path / "root"
    (root / "lib").mkdir(parents=True)
    (root / "dump").mkdir()
    (root / "dump" / "mode.cfg").write_text("name OLD\n")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "pad_mode.so").write_bytes(b"\x7fELF")
    (stage / "game.port").write_text("game godzilla_pro\n")
    (stage / "mode.cfg").write_text("name A\n")
    env = dict(os.environ, PAD_HOME=str(tmp_path), PAD_ROOT=str(root))
    os.chmod(root / "lib", 0o555)
    try:
        r = subprocess.run(["bash", script, "install", str(stage)], env=env, capture_output=True,
                           text=True, timeout=60)
    finally:
        os.chmod(root / "lib", 0o755)
    assert r.returncode != 0
    assert "%s belongs to" % (root / "lib") in r.stderr and "chown -R" in r.stderr, r.stderr
    assert not (root / "lib" / "pad_mode.so").exists()
    assert (root / "dump" / "mode.cfg").read_text() == "name OLD\n"      # nothing touched
    r = subprocess.run(["bash", script, "install", str(stage)], env=env, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (root / "lib" / "pad_mode.so").read_bytes() == b"\x7fELF"
