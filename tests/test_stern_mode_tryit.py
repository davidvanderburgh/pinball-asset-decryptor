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


#: The keyword arguments the last stand-in build was handed (progress, cancel, sound_ok).
HANDED = {}


def _writes_builder(monkeypatch, calls, files=None, end_sound=None, own_sounds=None):
    """Stand in for :func:`mode_write.build_tryit_set` and record what Try it handed it. It lays
    out what the real one does, from the project's own modes matched to its card: the set's
    files (by default the game program and the rebuilt manifest, what Write's set holds for
    modes with no screen or clip) and the stage beside it - the pinned object, the title's
    port and each slot's mode file."""
    from pinball_decryptor.plugins.stern import mode_write as MW

    def build(project, card, base, log=None, progress=None, cancel=None, label=None,
              sound_ok=None):
        calls.append((project, card, base))
        HANDED.clear()
        HANDED.update(progress=progress, cancel=cancel, sound_ok=sound_ok)
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
    spec.award, spec.seconds = 5, 9
    assert MT.asset_signature(spec) == before           # these reload live
    # the name is drawn on a generated panel (no title or picture of its own) and on a title
    # clip with no title: there it waits for the next Try it, elsewhere it reloads live
    spec.name = "Y"
    assert MT.asset_signature(spec) != before
    spec.screen_title = "OWN TITLE"
    before = MT.asset_signature(spec)
    spec.name = "Z"
    assert MT.asset_signature(spec) == before
    spec.clip, spec.clip_title = "title", ""
    before = MT.asset_signature(spec)
    spec.name = "W"
    assert MT.asset_signature(spec) != before
    spec.clip, spec.name = "none", "Y"
    before = MT.asset_signature(spec)
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


class _Entry:
    def __init__(self, name, is_dir=False):
        self.name, self.is_dir = name, is_dir


class _Part:
    def __init__(self, index, size, browsable=True):
        self.index, self.size, self.browsable = index, size, browsable


def _fake_card(monkeypatch, layout):
    """A stand-in CardImage: *layout* is ``{partition index: (size, {"/": [...], "/spk/index":
    [...]})}`` of :class:`_Entry` lists, so card_title can be read off a desk."""
    from pinball_decryptor.plugins.stern import explorer

    class Image:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def partitions(self):
            return [_Part(i, size) for i, (size, _dirs) in layout.items()]

        def list_dir(self, index, path):
            dirs = layout[index][1]
            if path not in dirs:
                raise OSError(path)
            return dirs[path]
    monkeypatch.setattr(explorer, "CardImage", Image)


def test_card_title_reads_the_index_name_so_a_multi_boot_card_is_its_title(monkeypatch):
    """The title comes from ``/spk/index/<title>-<version>.sidx``, as probe_card_title and
    the engine's card_title_index read it. A multi-boot card keeps img1/img2 beside the
    title's directory; under the old one-directory rule that was "an unknown title" and
    the title check refused the card the modes were made for."""
    idx = [_Entry("godzilla_le-1_16_0.sidx"), _Entry("godzilla_le.sidx")]
    root = [_Entry("godzilla_le", True), _Entry("img1", True), _Entry("img2", True),
            _Entry("spk", True), _Entry("lost+found", True)]
    _fake_card(monkeypatch, {3: (10 ** 9, {"/": root, "/spk/index": idx}),
                             2: (10 ** 6, {"/": [_Entry("etc", True)]})})
    assert MT.card_title("multi.raw") == ("godzilla_le", "1.16.0", 3)
    MT.check_title(_le(), "godzilla_le", "1.16.0")
    # no index name parses: the one title directory decides, as before, with the version
    # the file name gives (none here)
    _fake_card(monkeypatch, {3: (10 ** 9, {"/": [_Entry("jaws_le", True), _Entry("spk", True)],
                                           "/spk/index": [_Entry("jaws.sidx")]})})
    assert MT.card_title("renamed.raw") == ("jaws_le", "", 3)
    _fake_card(monkeypatch, {3: (10 ** 9, {"/": [_Entry("a", True), _Entry("b", True)],
                                           "/spk/index": []})})
    assert MT.card_title("odd.raw") == ("", "", 3)
    with pytest.raises(MT.TryItError, match="no games partition"):
        _fake_card(monkeypatch, {2: (10 ** 6, {"/": []})})
        MT.card_title("blank.raw")


def test_build_set_hands_progress_cancel_and_the_sound_gate_to_writes_builder(tmp_path, monkeypatch):
    """The tab's bar and its Cancel reach the engine's checkpoints through the one builder;
    sound_ok goes along only when the caller set it (the builder's default is the gate)."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _quiet(project, "Alpha")
    monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 2))
    calls = []
    _writes_builder(monkeypatch, calls)
    progress, cancel = (lambda d, t, s: None), (lambda: False)
    MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"), progress=progress,
                 cancel=cancel, sound_ok=False)
    assert HANDED == {"progress": progress, "cancel": cancel, "sound_ok": False}
    MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"))
    assert HANDED == {"progress": None, "cancel": None, "sound_ok": None}
    assert calls[0][1] == calls[1][1] == _card(tmp_path)          # the card to BOOT, unchanged
    with pytest.raises(MT.TryItError, match="Extract tab"):
        MT.build_set("", _card(tmp_path), base=str(tmp_path / "try"))


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


def test_a_new_code_mode_gets_a_default_assets_file_that_keeps_the_compile_only_path(tmp_path, monkeypatch):
    """A fresh template carries nothing of its own yet, so its assets.json names it and leaves
    has_assets() False: Try it compiles it in without going through Write's set."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    project = str(tmp_path)
    slug, _path = MT.new_code_mode(project, 'Blitz "Rush"')
    assets = os.path.join(MP.mode_folder(project, slug), CM.ASSETS_FILE)
    assert os.path.isfile(assets)
    spec = CM.load(project, slug)
    assert spec.name == "Blitz 'Rush'" and not spec.has_assets() and spec.screen is False
    assert [s for s, _c in CM.list_code(project)] == [slug]
    assert MT.code_modes_with_assets(project) == []

    # the write is checked by reading it back: a file that does not load is said, by name
    def refuse(project, slug):
        raise ValueError("bad")
    monkeypatch.setattr(CM, "load", refuse)
    with pytest.raises(MT.TryItError, match="assets.json"):
        MT.new_code_mode(project, "Other")


def test_list_all_puts_the_form_modes_first_then_the_code_modes(tmp_path):
    from pinball_decryptor.plugins.stern import code_modes as CM
    project = str(tmp_path / "proj")
    os.makedirs(project)
    assert MT.list_all(project) == [] and MT.list_all("") == []
    _quiet(project, "Zeta")
    _quiet(project, "Alpha")
    MT.new_code_mode(project, "Blitz")                              # named by its assets.json
    named = os.path.join(MP.mode_folder(project, "aaa"), "aaa.c")   # by its MODE_NAME define
    os.makedirs(os.path.dirname(named))
    open(named, "w").write('#define MODE_NAME "TRIPLE A"\n')
    bare = os.path.join(MP.mode_folder(project, "zzz"), "zzz.c")    # by its folder
    os.makedirs(os.path.dirname(bare))
    open(bare, "w").write("/* no name */\n")
    broken = MP.mode_folder(project, "gone")                        # a mode.json that does not load
    os.makedirs(broken)
    open(os.path.join(broken, MP.MODE_FILE), "w").write("{not json")
    assert MT.list_all(project) == [("alpha", "form", "Alpha"), ("zeta", "form", "Zeta"),
                                    ("aaa", "code", "TRIPLE A"), ("blitz", "code", "Blitz"),
                                    ("zzz", "code", "ZZZ")]
    # a code mode whose assets.json does not load is still listed, from its C file
    open(os.path.join(MP.mode_folder(project, "blitz"), CM.ASSETS_FILE), "w").write("{not json")
    assert ("blitz", "code", "Blitz") in MT.list_all(project)


def test_duplicate_code_mode_builds_a_distinct_trigger_name(tmp_path):
    from pinball_decryptor.plugins.stern import code_modes as CM
    project = str(tmp_path)
    slug, path = MT.new_code_mode(project, "Blitz")
    folder = MP.mode_folder(project, slug)
    open(os.path.join(folder, "music.wav"), "wb").write(b"RIFF")   # a file of its own comes along
    new_slug, new_path = MT.duplicate_code_mode(project, slug)
    assert (new_slug, new_path) == ("blitz_copy", os.path.join(MP.mode_folder(project, "blitz_copy"),
                                                              "blitz_copy.c"))
    assert os.path.isfile(new_path) and os.path.isfile(path)
    assert not os.path.exists(os.path.join(MP.mode_folder(project, new_slug), "blitz.c"))
    assert os.path.isfile(os.path.join(MP.mode_folder(project, new_slug), "music.wav"))
    out = open(new_path, encoding="utf-8").read()
    assert '#define MODE_NAME        "Blitz COPY"' in out
    assert '"PadMode_blitz_copy_Screen"' in out
    assert 'pm_trigger("blitz_copy.start")' in out and 'pm_trigger("blitz_copy.stop")' in out
    assert "/dump/blitz_copy.start" in out
    assert "PM_REGISTER(blitz_copy_mode);" in out and "struct pm_mode blitz_copy_mode" in out
    assert out.startswith("/* blitz_copy.c - ")
    for gone in ('"blitz.start"', '"blitz.stop"', "PadMode_blitz_Screen", "/dump/blitz.", "blitz_mode"):
        assert gone not in out, gone
    assert CM.load(project, new_slug).name == "Blitz COPY" and not CM.load(project, new_slug).has_assets()
    assert MT.code_mode_sources(project) == [("blitz", path), (new_slug, new_path)]
    # the original is untouched
    assert 'pm_trigger("blitz.start")' in open(path, encoding="utf-8").read()
    # a name of the person's choosing, and never an overwrite
    again, _p = MT.duplicate_code_mode(project, slug, name="Blitz")
    assert again == "blitz_2"
    third, _p = MT.duplicate_code_mode(project, slug)
    assert third == "blitz_copy_2"
    with pytest.raises(MT.TryItError, match="no code mode called nope"):
        MT.duplicate_code_mode(project, "nope")


def test_duplicate_code_mode_renames_an_examples_folder_define_and_struct(tmp_path):
    """The SDK examples name their folder once (#define FOLDER) and their struct after it."""
    project = str(tmp_path)
    folder = MP.mode_folder(project, "ghidorah_heads")
    os.makedirs(folder)
    src = os.path.join(folder, "ghidorah_heads.c")
    with open(src, "w", encoding="utf-8", newline="\n") as f:
        f.write('/* ghidorah_heads.c - KING GHIDORAH: a boss battle.\n'
                ' *   echo 1 > /dump/ghidorah_heads.start      start now\n */\n'
                '#include "intricate_kit.h"\n'
                '#define MODE_NAME          "KING GHIDORAH"\n'
                '#define FOLDER             "ghidorah_heads"\n'
                'static const struct pm_mode ghidorah_heads = { .name = MODE_NAME };\n'
                'PM_REGISTER(ghidorah_heads);\n')
    open(os.path.join(folder, "intricate_kit.h"), "w").write("/* kit */\n")
    new_slug, new_path = MT.duplicate_code_mode(project, "ghidorah_heads", name="Ghidorah Two")
    assert new_slug == "ghidorah_two"
    out = open(new_path, encoding="utf-8").read()
    assert out.startswith("/* ghidorah_two.c - KING GHIDORAH")
    assert "/dump/ghidorah_two.start" in out
    assert '#define MODE_NAME          "Ghidorah Two"' in out
    assert '#define FOLDER             "ghidorah_two"' in out
    assert "struct pm_mode ghidorah_two = " in out and "PM_REGISTER(ghidorah_two);" in out
    assert "ghidorah_heads" not in out
    assert os.path.isfile(os.path.join(MP.mode_folder(project, new_slug), "intricate_kit.h"))
    # no assets.json to start with means none is invented: the name lives in the define
    assert not os.path.exists(os.path.join(MP.mode_folder(project, new_slug), "assets.json"))
    assert ("ghidorah_two", "code", "Ghidorah Two") in MT.list_all(project)


def test_delete_code_mode_removes_only_a_code_mode_folder_under_modes(tmp_path):
    project = str(tmp_path / "proj")
    os.makedirs(project)
    slug, path = MT.new_code_mode(project, "Blitz")
    _quiet(project, "Form")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "elsewhere.c").write_text("/* not ours */\n")
    for bad in ("../elsewhere", str(outside), "", "nope", "form"):
        with pytest.raises(MT.TryItError):
            MT.delete_code_mode(project, bad)
    assert (outside / "elsewhere.c").is_file() and os.path.isdir(MP.mode_folder(project, "form"))
    MT.delete_code_mode(project, slug)
    assert not os.path.exists(MP.mode_folder(project, slug)) and not os.path.isfile(path)
    assert [s for s, _k, _n in MT.list_all(project)] == ["form"]


def test_code_trigger_names_are_what_tryit_sh_accepts():
    assert MT.code_trigger_name("blitz_2") and MT.code_trigger_name("x9")
    for bad in ("", "Blitz", "blitz rush", "blitz-rush", "blitz.start", "../x"):
        assert not MT.code_trigger_name(bad), bad
    codes = [("blitz", "/p/modes/blitz/blitz.c"), ("Made-By-Hand", "/p/modes/Made-By-Hand/Made-By-Hand.c")]
    assert MT.unreachable_code_modes(codes) == ["Made-By-Hand"]
    assert MT.unreachable_code_modes(["ok", "not ok"]) == ["not ok"]
    assert MT.unreachable_code_modes([]) == [] and MT.unreachable_code_modes(None) == []


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
    assert MT.project_title(project) is None                 # no card, no modes: no game
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
    tmnt = MP.profile("turtles_pro_1_58")
    assert tmnt.hud_scene == "" and not tmnt.can("screen") and not tmnt.can("clip")
    assert MW.scene_rels(tmnt) == ("", "")
    # item 164: TMNT Pro 1.59 and the Deadpools add a clip to their bank, and a screen to their HUD
    # scene only where one was seen on the glass
    for key in ("turtles_pro_1_59", "deadpool_pro_1_16", "deadpool_le_1_14"):
        prof = MP.profile(key)
        assert prof.can("clip"), key
        hud = "%s/%s/scene.radium" % (prof.game_dir, prof.lcd("hud")) if prof.can("screen") else ""
        assert MW.scene_rels(prof) == (hud, "%s/%s/%s/scene.radium" % (prof.game_dir, lcd, prof.bank_scene)), key
    assert MP.profile("turtles_pro_1_59").can("screen")
    jaws = MP.profile("jaws_le_1_02")
    assert jaws.can("screen") and jaws.can("clip")          # item 164: its score panel carries a screen
    assert MW.scene_rels(jaws) == ("jaws_le/%s/%s/scene.radium" % (lcd, jaws.hud_scene),
                                   "jaws_le/%s/%s/scene.radium" % (lcd, jaws.bank_scene))


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
    from a TMNT Pro 1.58 card: its shots are TMNT's by name, and the parts TMNT cannot do are
    left out, as a Write build leaves them out."""
    project = str(tmp_path / "proj")
    os.makedirs(project)
    _name_card(project, "turtles_pro-1_58_0.Release.8G.sdcard.raw", "1.58.0")
    slug, spec = MP.new_mode(project, "LOUD", MP.ModeSpec(
        name="LOUD", start_shot="Left ramp", scoring_shots=["Left ramp", "Right ramp"],
        screen=True, clip="title"))
    assert spec.title == GZ.key
    monkeypatch.setattr(MT, "card_title", lambda c: ("turtles_pro", "1.58.0", 3))
    _writes_builder(monkeypatch, [])
    ts = MT.build_set(project, _card(tmp_path), base=str(tmp_path / "try"), ffmpeg=None)
    cfg = open(os.path.join(ts.stage_dir, "mode.cfg"), encoding="utf-8").read()
    assert "shots          0x00000210" in cfg                     # TMNT's Left + Right ramp
    for gone in ("screen_scene", "clip_start"):
        assert gone not in cfg
    assert ts.specs[slug].title == "turtles_pro_1_58"


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


def _tryit_rig(tmp_path):
    """A stand-in rootfs for tryit.sh, and a runner over it: (root, run)."""
    import subprocess
    script = os.path.join(os.path.dirname(MR.sdk_dir()), "tryit.sh")
    root = tmp_path / "root"
    (root / "lib").mkdir(parents=True)
    (root / "dump").mkdir()
    env = dict(os.environ, PAD_HOME=str(tmp_path), PAD_ROOT=str(root))

    def run(*args, **extra_env):
        e = dict(env, **{k: v for k, v in extra_env.items() if v is not None})
        for k, v in extra_env.items():
            if v is None:
                e.pop(k, None)
        return subprocess.run(["bash", script] + list(args), env=e, capture_output=True,
                              text=True, timeout=60)
    return root, run


@pytest.mark.skipif(not _bash() or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="the rig script runs under Linux bash, as a user root does not stop")
def test_tryit_sh_check_asks_the_ownership_question_before_any_build(tmp_path):
    """``check`` is install's ownership test alone, so the app can ask it in a second
    BEFORE a minutes-long build: ready is exit 0 and one line, blocked is exit 1 with
    install's own sentence, and neither writes anything under the rig."""
    root, run = _tryit_rig(tmp_path)
    r = run("check")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[tryit] the rig is ready for the modes"
    assert os.listdir(root / "dump") == [] and os.listdir(root / "lib") == []
    os.chmod(root / "lib", 0o555)
    try:
        r = run("check")
    finally:
        os.chmod(root / "lib", 0o755)
    assert r.returncode == 1
    assert "cannot put the modes in the emulator: %s belongs to" % (root / "lib") in r.stderr
    assert "chown -R" in r.stderr and "ready" not in r.stdout, r.stderr
    assert os.listdir(root / "dump") == [] and os.listdir(root / "lib") == []
    # The fix line names the distro when the shell knows it (a machine with two distros
    # runs a bare `wsl` in the DEFAULT one), and stays the plain form when it does not.
    os.chmod(root / "dump", 0o555)
    try:
        named = run("check", WSL_DISTRO_NAME="PAD-Runtime")
        plain = run("check", WSL_DISTRO_NAME=None)
    finally:
        os.chmod(root / "dump", 0o755)
    assert named.returncode == 1 and plain.returncode == 1
    assert "Hand it back with: wsl -d PAD-Runtime -u root chown -R " in named.stderr, named.stderr
    assert named.stderr.rstrip().endswith(str(root / "dump")), named.stderr
    assert "Hand it back with: wsl -u root chown -R " in plain.stderr, plain.stderr
    assert " -d " not in plain.stderr


@pytest.mark.skipif(not _bash(), reason="the rig script runs under Linux bash")
def test_tryit_sh_start_code_touches_the_code_modes_own_trigger(tmp_path):
    """A mode written in C reads only its own ``/dump/<folder>.start``; ``start-code
    NAME`` touches exactly that, and a name that is not a plain [a-z0-9_] folder name
    is refused before anything is written (the rule ``stop`` uses)."""
    root, run = _tryit_rig(tmp_path)
    r = run("start-code", "blitz_2")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[tryit] blitz_2.start"
    assert os.listdir(root / "dump") == ["blitz_2.start"]
    os.unlink(root / "dump" / "blitz_2.start")
    for bad in ("../lib/x", "Blitz", "a b", ""):
        r = run("start-code", bad)
        assert r.returncode != 0 and "[a-z0-9_] only" in r.stderr, bad
        assert os.listdir(root / "dump") == [], bad
    assert run("start-code").returncode != 0 and os.listdir(root / "dump") == []


@pytest.mark.skipif(not _bash(), reason="the rig script runs under Linux bash")
def test_tryit_sh_push_uses_a_temp_name_per_call(tmp_path):
    """Two pushes of one slot at once (hot reload beside an install) each copy under
    their OWN temporary name: both land whole, the slot holds one of them intact, no
    temp file is left behind, and a push after them leaves the newest."""
    import subprocess
    script = os.path.join(os.path.dirname(MR.sdk_dir()), "tryit.sh")
    root, run = _tryit_rig(tmp_path)
    env = dict(os.environ, PAD_HOME=str(tmp_path), PAD_ROOT=str(root))
    a = tmp_path / "a.cfg"
    b = tmp_path / "b.cfg"
    a.write_text("name A\n" * 2000)
    b.write_text("name B\n" * 2000)
    procs = [subprocess.Popen(["bash", script, "push", str(f), "1"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for f in (a, b) * 4]
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    assert (root / "dump" / "mode1.cfg").read_text() in (a.read_text(), b.read_text())
    assert os.listdir(root / "dump") == ["mode1.cfg"]
    c = tmp_path / "c.cfg"
    c.write_text("name C\n")
    assert run("push", str(c), "1").returncode == 0
    assert (root / "dump" / "mode1.cfg").read_text() == "name C\n"
    assert os.listdir(root / "dump") == ["mode1.cfg"]
