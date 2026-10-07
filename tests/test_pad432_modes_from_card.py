"""PAD-432: modes taken from one card image into another card's project in one load.

A Write leaves the project's modes beside mode.so as the file Save to a file writes
(/usr/local/padmode/pad_modes.zip); Load from a card image reads it back out of the image and
loads it as Load from a file does, matched to the project's card (another version or model of
the game). A card written before that gives back its form modes' basics from its mode files,
and the words say what did not come back.

The tests marked ``e2fs`` build a real ext4 card (as test_spike2_mode_install does) and are
skipped where e2fsprogs is missing (Windows, CI); the rest run anywhere.
"""
import io
import json
import os
import shutil
import sys
import zipfile

import pytest

from pinball_decryptor.plugins.stern import mode_from_card as MFC
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
e2fs = pytest.mark.skipif(
    not (shutil.which("mke2fs") and shutil.which("debugfs") and shutil.which("e2fsck")),
    reason="needs e2fsprogs (mke2fs, debugfs, e2fsck)")


def _card_project(path, image_name):
    os.makedirs(str(path), exist_ok=True)
    with open(os.path.join(str(path), ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(str(path), image_name), "input_name": image_name}, f)
    return str(path)


def _pro115(tmp_path):
    """A Godzilla Pro 1.15 project with a form mode and a code mode."""
    project = _card_project(tmp_path / "pro115", "godzilla_pro-1_15_0.raw")
    spec = MP.ModeSpec(name="KAIJU RUSH", title="godzilla_pro_1_15")
    spec.start_shot, spec.start_count = "Maser target", 2
    spec.scoring_shots = ["Left ramp", "Building"]
    spec.seconds, spec.award = 40, 750000
    slug, _ = MP.new_mode(project, spec=spec)
    with open(os.path.join(MP.mode_folder(project, slug), "screen.png"), "wb") as f:
        f.write(b"\x89PNG not really")
    code = MP.mode_folder(project, "dual_strike")
    os.makedirs(code)
    with open(os.path.join(code, "dual_strike.c"), "w") as f:
        f.write("/* a code mode */\n")
    return project


def _port115():
    return MP.port_path(MP.profile("godzilla_pro_1_15"))


# ------------------------------------------------------------------ the file the Write carries
def test_card_bundle_is_the_projects_modes_and_names_its_card(tmp_path):
    project = _pro115(tmp_path)
    path = MW.card_bundle(project, str(tmp_path / MP.CARD_BUNDLE))
    with zipfile.ZipFile(path) as z:
        head = json.loads(z.read(MP.SHARE_MANIFEST))
        names = set(z.namelist())
    assert head["kind"] == MP.SHARE_KIND
    assert head["from"] == {"title": "godzilla_pro_1_15", "label": "Godzilla Pro 1.15",
                            "card": "godzilla_pro-1_15_0.raw"}
    assert "modes/kaiju_rush/screen.png" in names and "modes/dual_strike/dual_strike.c" in names
    # a project with no modes: no file, and the Write goes on without one
    empty = _card_project(tmp_path / "empty", "godzilla_pro-1_15_0.raw")
    assert MW.card_bundle(empty, str(tmp_path / "none.zip")) == ""


def test_the_install_command_carries_the_bundle_only_when_there_is_one(tmp_path):
    class Ex:
        def to_exec_path(self, p):
            return p.replace("\\", "/")
    payload = {"so": "a/mode.so", "cfgs": ["a/mode.cfg"], "port": "a/game.port"}
    assert "--bundle" not in MW.install_command(Ex(), "card.raw", payload, 1)
    payload["bundle"] = "a/pad_modes.zip"
    assert "--bundle" in MW.install_command(Ex(), "card.raw", payload, 1)
    payload["bundle"] = ""
    assert "--bundle" not in MW.install_command(Ex(), "card.raw", payload, 1)


def test_p2_payload_stages_the_bundle_beside_mode_so(tmp_path, monkeypatch):
    project = _pro115(tmp_path)
    so = tmp_path / "obj.so"
    so.write_bytes(b"\x7fELF")
    cfg = tmp_path / "m.cfg"
    cfg.write_text("name X\n")

    class R:
        object = str(so)
        mode_files = [("mode.cfg", str(cfg))]
        port = _port115()
    out = MW.p2_payload(R(), str(tmp_path / "p2"), project=project)
    assert out["bundle"] == str(tmp_path / "p2" / MP.CARD_BUNDLE) and os.path.isfile(out["bundle"])
    assert "bundle" not in MW.p2_payload(R(), str(tmp_path / "p2b"))


# ------------------------------------------------------------------ a card written before PAD-432
def test_a_mode_file_gives_back_its_basics_by_the_cards_own_port(tmp_path):
    p = MP.profile("godzilla_pro_1_15")
    spec = MP.ModeSpec(name="KAIJU RUSH", title=p.key)
    spec.start_shot, spec.start_count = "Maser target", 2
    spec.scoring_shots = ["Left ramp", "Building"]
    spec.seconds, spec.award, spec.stack = 40, 750000, False
    spec.starts, spec.cooldown = "once_per_ball", 12
    text = MP.runtime_cfg(spec, "kaiju_rush")
    got, lost = MFC.recover_spec(text, p)
    assert (got.name, got.title, got.start_shot, got.start_count) == ("KAIJU RUSH", p.key, "Maser target", 2)
    assert (got.seconds, got.award, got.stack) == (40, 750000, False)
    assert set(got.scoring_shots) == {"Left ramp", "Building"}
    assert (got.starts, got.cooldown) == ("once_per_ball", 12)
    assert got.clip == "none" and got.end_sound == ""
    assert lost == "" or "Advanced" in lost
    # a key the recovery does not carry is named
    _got, lost = MFC.recover_spec(text + "trigger_seq    1 2 3\n", p)
    assert "trigger_seq" in lost


def test_an_old_card_without_the_file_is_recovered_and_says_what_did_not_come_back(tmp_path, monkeypatch):
    p = MP.profile("godzilla_pro_1_15")
    spec = MP.ModeSpec(name="KAIJU RUSH", title=p.key)
    spec.start_shot, spec.scoring_shots = "Maser target", ["Left ramp"]
    files = {"mode.so": b"\x7fELF", "mode.cfg": MP.runtime_cfg(spec, "kaiju_rush").encode(),
             "game.port": open(_port115(), "rb").read(), "dual_strike.assets": b"x"}
    monkeypatch.setattr(MFC, "read_padmode", lambda image: files)
    path, about, notes = MFC.card_modes_file(str(tmp_path / "old card.raw"), str(tmp_path))
    assert os.path.basename(path) == "old card modes.zip"
    assert about["title"] == p.key and about["card"] == "old card.raw"
    assert "written before cards carried their modes whole" in notes[0]
    assert any("DUAL_STRIKE is a code mode" in n for n in notes)
    # it loads into a Premium 1.16 project like any file of modes
    le = _card_project(tmp_path / "le", "godzilla_le-1_16_0.raw")
    report = MP.import_modes(path, le)
    assert [(m.name, m.state) for m in report.modes] == [("KAIJU RUSH", MP.COPY_CARRIED)]
    got = dict(MP.list_modes(le)[0])["kaiju_rush"]
    assert got.title == "godzilla_le_1_16" and got.start_shot and got.scoring_shots


def test_a_card_with_no_modes_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(MFC, "read_padmode", lambda image: {})
    with pytest.raises(MFC.CardModesError, match="carries no modes"):
        MFC.card_modes_file(str(tmp_path / "stock.raw"), str(tmp_path))


def test_a_file_that_is_no_card_image_is_refused(tmp_path):
    bad = tmp_path / "notes.raw"
    bad.write_bytes(b"\0" * 4096)
    with pytest.raises(MFC.CardModesError):
        MFC.read_padmode(str(bad))


def test_the_bundle_on_the_card_is_handed_back_as_it_is(tmp_path, monkeypatch):
    project = _pro115(tmp_path)
    data = open(MW.card_bundle(project, str(tmp_path / "b.zip")), "rb").read()
    monkeypatch.setattr(MFC, "read_padmode", lambda image: {"mode.so": b"x", MP.CARD_BUNDLE: data})
    os.makedirs(tmp_path / "out")
    path, about, notes = MFC.card_modes_file(str(tmp_path / "gz.raw"), str(tmp_path / "out"))
    assert open(path, "rb").read() == data and notes == []
    assert about["label"] == "Godzilla Pro 1.15"
    # into the Pro 1.16 project: retargeted, the code mode copied as it is
    pro116 = _card_project(tmp_path / "pro116", "godzilla_pro-1_16_0.raw")
    report = MP.import_modes(path, pro116)
    states = {m.slug: m.state for m in report.modes}
    assert states == {"kaiju_rush": MP.COPY_CARRIED, "dual_strike": MP.COPY_CODE}
    assert os.path.isfile(os.path.join(MP.mode_folder(pro116, "kaiju_rush"), "screen.png"))
    assert dict(MP.list_modes(pro116)[0])["kaiju_rush"].title == "godzilla_pro_1_16"


# ------------------------------------------------------------------ the Modes tab
def test_load_from_a_card_image_in_the_modes_tab(tmp_path, monkeypatch):
    from pinball_decryptor.core import preview
    from tests.test_webui_modes import _modes_on_disk, _project
    from tests.webui_harness import web_app
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    data = open(MW.card_bundle(_pro115(tmp_path), str(tmp_path / "b.zip")), "rb").read()
    monkeypatch.setattr(MFC, "read_padmode", lambda image: {"mode.so": b"x", MP.CARD_BUNDLE: data})
    le = _card_project(tmp_path / "le", "godzilla_le-1_16_0.raw")
    image = str(tmp_path / "Heisei V1.96A.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, le, card=None)
        w.answers.append(image)
        got = w.call("modes.load_card")
        assert got and _modes_on_disk(le) == ["kaiju_rush"]      # dual_strike: a code mode, no mode.json
        assert os.path.isfile(os.path.join(MP.mode_folder(le, "dual_strike"), "dual_strike.c"))
        msg = w.asked[-1]["message"]
        assert "from Heisei V1.96A.raw, made for Godzilla Pro 1.15." in msg
        # Save a card image's modes to a file: the same file, wherever they say
        out = str(tmp_path / "saved.zip")
        w.answers.extend([image, out])
        assert w.call("modes.save_card") == out
        assert open(out, "rb").read() == data


def test_the_page_offers_both_card_image_items():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui",
                           "static", "js", "tabs", "modes.js"), encoding="utf-8").read()
    assert 'call("modes.load_card")' in js and 'call("modes.save_card")' in js


# ------------------------------------------------------------------ on a real ext4 card
def _card(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    sys.path.insert(0, RIG)
    from test_spike2_mode_install import _mkcard
    return _mkcard(tmp_path)


@e2fs
def test_install_puts_the_bundle_on_the_card_and_the_load_reads_it_back(tmp_path):
    sys.path.insert(0, RIG)
    import mode_install as mi
    card = _card(tmp_path)
    project = _pro115(tmp_path)
    bundle = MW.card_bundle(project, str(tmp_path / MP.CARD_BUNDLE))
    so, cfg = tmp_path / "mode.so", tmp_path / "m.cfg"
    so.write_bytes(b"\x7fELF" + b"\0" * 4096)
    cfg.write_text("name KAIJU RUSH\n")
    names = mi.install(card, str(so), str(cfg), _port115(), bundle=bundle)
    assert MP.CARD_BUNDLE in names and mi.LEFT_OFF == ""
    files = MFC.read_padmode(card)
    assert files[MP.CARD_BUNDLE] == open(bundle, "rb").read()
    assert files["mode.so"] == so.read_bytes()
    path, about, notes = MFC.card_modes_file(card, str(tmp_path))
    assert notes == [] and about["title"] == "godzilla_pro_1_15"
    # a Write without it takes the old one off; a removal takes it too
    mi.install(card, str(so), str(cfg), _port115())
    assert MP.CARD_BUNDLE not in MFC.read_padmode(card)
    mi.install(card, str(so), str(cfg), _port115(), bundle=bundle)
    mi.remove(card)
    assert MFC.read_padmode(card) == {}


@e2fs
def test_a_bundle_too_big_for_p2_is_left_off_and_the_modes_still_go_on(tmp_path):
    sys.path.insert(0, RIG)
    import mode_install as mi
    card = _card(tmp_path)
    big = tmp_path / MP.CARD_BUNDLE
    big.write_bytes(os.urandom(60 << 20))
    so, cfg = tmp_path / "mode.so", tmp_path / "m.cfg"
    so.write_bytes(b"\x7fELF" + b"\0" * 4096)
    cfg.write_text("name KAIJU RUSH\n")
    names = mi.install(card, str(so), str(cfg), bundle=str(big))
    assert MP.CARD_BUNDLE not in names and "left off" in mi.LEFT_OFF
    assert set(MFC.read_padmode(card)) == {"mode.so", "mode.cfg"}


# ------------------------------------------------------------------ what travels, and from where
def test_the_card_copy_keeps_every_source_and_leaves_big_media_out(tmp_path, monkeypatch):
    project = _pro115(tmp_path)
    clip = os.path.join(MP.mode_folder(project, "dual_strike"), "clip.mp4")
    with open(clip, "wb") as f:
        f.write(b"\0" * 4096)
    monkeypatch.setattr(MW, "CARD_BUNDLE_MEDIA", 1000)       # room for the 15-byte png only
    path = MW.card_bundle(project, str(tmp_path / MP.CARD_BUNDLE))
    with zipfile.ZipFile(path) as z:
        head = json.loads(z.read(MP.SHARE_MANIFEST))
        names = set(z.namelist())
    assert head["left_out"] == ["modes/dual_strike/clip.mp4"]
    assert "modes/dual_strike/dual_strike.c" in names and "modes/kaiju_rush/mode.json" in names
    assert "modes/kaiju_rush/screen.png" in names and "modes/dual_strike/clip.mp4" not in names
    notes = MFC.left_out_notes(open(path, "rb").read())
    assert notes == ["DUAL_STRIKE: clip.mp4 was too big to travel on the card; Cut from films makes it again"]
    # Save to a file (no budget) still carries everything
    MP.export_modes(project, str(tmp_path / "all.zip"))
    with zipfile.ZipFile(str(tmp_path / "all.zip")) as z:
        assert "modes/dual_strike/clip.mp4" in z.namelist()
        assert "left_out" not in json.loads(z.read(MP.SHARE_MANIFEST))


def _built_here(tmp_path, project, name="built.raw"):
    """A card image path with a build record beside it naming ``project``."""
    from pinball_decryptor.core import extract_source
    image = tmp_path / name
    image.write_bytes(b"")
    with open(str(image) + extract_source.BUILD_RECORD_SUFFIX, "w", encoding="utf-8") as f:
        json.dump({"assets": project}, f)
    return str(image)


def test_the_cards_own_file_wins_over_its_project_and_the_project_fills_its_big_media(tmp_path, monkeypatch):
    """What is on the card is the modes as written; the project the card was built from only
    puts back the media the card's file was too small to carry."""
    project = _pro115(tmp_path)
    clip = os.path.join(MP.mode_folder(project, "dual_strike"), "clip.mp4")
    with open(clip, "wb") as f:
        f.write(b"\0" * 4096)
    monkeypatch.setattr(MW, "CARD_BUNDLE_MEDIA", 1000)       # the clip stays off the card
    data = open(MW.card_bundle(project, str(tmp_path / "b.zip")), "rb").read()
    # the project moved on after the Write: KAIJU RUSH is 45 s there now, the card says 40
    spec = dict(MP.list_modes(project)[0])["kaiju_rush"]
    spec.seconds = 45
    MP.save(project, "kaiju_rush", spec)
    image = _built_here(tmp_path, project)
    monkeypatch.setattr(MFC, "read_padmode", lambda image: {"mode.so": b"x", MP.CARD_BUNDLE: data})
    os.makedirs(tmp_path / "out")
    path, about, notes = MFC.card_modes_file(image, str(tmp_path / "out"))
    assert about["project"] == project and about["title"] == "godzilla_pro_1_15"
    assert notes == []                                       # the clip came back from the project
    with zipfile.ZipFile(path) as z:
        head = json.loads(z.read(MP.SHARE_MANIFEST))
        assert "left_out" not in head
        assert "modes/dual_strike/clip.mp4" in z.namelist()
        assert json.loads(z.read("modes/kaiju_rush/mode.json"))["seconds"] == 40
    # the project no longer has the clip: it stays left out, and the note says so
    os.remove(clip)
    os.makedirs(tmp_path / "out2")
    path, about, notes = MFC.card_modes_file(image, str(tmp_path / "out2"))
    assert "project" not in about
    assert notes == ["DUAL_STRIKE: clip.mp4 was too big to travel on the card; Cut from films makes it again"]


def test_an_old_card_built_here_takes_its_projects_modes_and_says_so(tmp_path, monkeypatch):
    project = _pro115(tmp_path)
    image = _built_here(tmp_path, project, "old.raw")
    monkeypatch.setattr(MFC, "read_padmode", lambda image: {
        "mode.so": b"x", "mode.cfg": b"name KAIJU RUSH\n", "game.port": open(_port115(), "rb").read()})
    path, about, notes = MFC.card_modes_file(image, str(tmp_path))
    assert about["project"] == project and about["title"] == "godzilla_pro_1_15"
    assert len(notes) == 1 and "taken from the project it was built from" in notes[0]
    with zipfile.ZipFile(path) as z:
        assert "modes/kaiju_rush/screen.png" in z.namelist()
        assert "modes/dual_strike/dual_strike.c" in z.namelist()


def test_a_card_with_no_modes_is_refused_even_with_a_build_record(tmp_path, monkeypatch):
    project = _pro115(tmp_path)
    image = _built_here(tmp_path, project, "nomodes.raw")
    monkeypatch.setattr(MFC, "read_padmode", lambda image: {})
    with pytest.raises(MFC.CardModesError, match="carries no modes"):
        MFC.card_modes_file(image, str(tmp_path))


def test_a_left_out_path_that_leaves_the_modes_folder_is_never_read(tmp_path):
    """The manifest is the card's, and a card is anyone's."""
    project = _pro115(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    path = str(tmp_path / "f.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(MP.SHARE_MANIFEST, json.dumps({
            "format": 1, "kind": MP.SHARE_KIND, "modes": ["kaiju_rush"],
            "left_out": ["modes/kaiju_rush/../../secret.txt", "../secret.txt", "modes/kaiju_rush/screen.png"]}))
        z.writestr("modes/kaiju_rush/mode.json", "{}")
    assert MFC.fill_left_out(path, project) == ["modes/kaiju_rush/screen.png"]
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read(MP.SHARE_MANIFEST))["left_out"] == [
            "modes/kaiju_rush/../../secret.txt", "../secret.txt"]
        assert not any("secret" in n for n in z.namelist())


def test_a_mode_whose_shots_carry_but_the_card_cannot_build_is_to_fix(tmp_path):
    src = _card_project(tmp_path / "src", "godzilla_pro-1_15_0.raw")
    spec = MP.ModeSpec(name="SKILLED", title="godzilla_pro_1_15")
    spec.starts_on = "event skill_shot"                     # Pro 1.16's port reports no such event
    MP.new_mode(src, spec=spec)
    assert MP.validate(spec) == []
    dest = _card_project(tmp_path / "dest", "godzilla_pro-1_16_0.raw")
    report = MP.copy_modes(src, dest)
    (m,) = report.modes
    assert m.state == MP.COPY_TO_FIX and "a build there refuses it until then" in m.words


def test_an_old_cards_code_modes_that_are_the_apps_examples_come_back(tmp_path, monkeypatch):
    files = {"mode.so": b"\x7fELF", "game.port": open(_port115(), "rb").read(),
             "ghidorah_heads.assets": b"x", "my_own.assets": b"x"}
    monkeypatch.setattr(MFC, "read_padmode", lambda image: files)
    path, _about, notes = MFC.card_modes_file(str(tmp_path / "old.raw"), str(tmp_path))
    with zipfile.ZipFile(path) as z:
        assert "modes/ghidorah_heads/ghidorah_heads.c" in z.namelist()
    assert any("KING GHIDORAH is the app's own example" in n for n in notes)
    assert any("MY_OWN is a code mode: its C is not on the card" in n for n in notes)
