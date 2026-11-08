"""PAD-1053: the co-op settings file - every co-op setting of a project saved to one file and loaded into another.

DoomWalrus666: "save a zip or json that records all of my co-op settings. What awards are active, what characters are
available and what are their abilities, and what pictures are loaded on each character". coop_play.export_settings
writes a zip (pad_coop.json and the pictures) or a .json (no pictures); import_settings puts it in place of a
project's co-op settings; the Modes tab's co-op Save... and Load... drive them, and its Load from a file... and the
Mod Pack tab's import tell the file from theirs."""
import json
import os
import pathlib
import types
import zipfile

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP

ROOT = pathlib.Path(__file__).resolve().parents[1]
GZ = types.SimpleNamespace(label="Godzilla Premium/LE 1.16.0")


def _png(path, rgb):
    from PIL import Image
    Image.new("RGB", (30, 40), rgb).save(path)


def _source(tmp_path, monkeypatch):
    """A project with co-op on, switched in the menu, two awards changed, three characters (two with pictures)."""
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: GZ)
    project = str(tmp_path / "src")
    os.makedirs(project)
    CP.save(project, True, menu=True)
    CP.save_award(project, "score", on=False)
    CP.save_award(project, "champion:JET FIGHTER CHAMPION", on=True, words="most jets")
    CP.save_characters(project, {"pick": True, "time": 45, "theme": {"title": "CHOOSE YOUR GODZILLA",
                                                                      "accent": "#38c8ff"},
                                 "list": [{"name": "GODZILLA 1954", "ability": "longer_save"},
                                          {"name": "SHIN GODZILLA", "ability": "tier2"},
                                          {"name": "MOTHRA VS GODZILLA", "ability": ""}]})
    _png(tmp_path / "a.png", (200, 10, 10))
    _png(tmp_path / "b.jpg", (10, 200, 10))
    CP.save_picture(project, 0, str(tmp_path / "a.png"))
    CP.save_picture(project, 1, str(tmp_path / "b.jpg"))
    return project


def test_a_zip_carries_every_setting_and_the_pictures_into_another_project(tmp_path, monkeypatch):
    src = _source(tmp_path, monkeypatch)
    out = str(tmp_path / "godzilla co-op.zip")
    assert CP.export_settings(src, out) == {"characters": 3, "pictures": 2, "awards": 1, "left_out": 0}
    with zipfile.ZipFile(out) as zf:
        names = sorted(zf.namelist())
        head = json.loads(zf.read(CP.FILE_MANIFEST))
    assert names == ["pad_coop.json", "pictures/1_godzilla_1954.png", "pictures/2_shin_godzilla.jpg"]
    assert head["kind"] == "pad-coop" and head["from"]["label"] == GZ.label
    assert CP.file_about(out) == {"made_for": GZ.label, "characters": 3, "pictures": 2, "awards": 1}

    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    CP.save_characters(dest, {"pick": True, "list": [{"name": "OLD ONE", "ability": "heat_ray"}]})
    got = CP.import_settings(dest, out)
    assert got == {"made_for": GZ.label, "characters": 3, "pictures": 2, "awards": 1, "preset": False}
    assert CP.load(dest) and CP.menu_asked(dest)
    assert CP.load_awards(dest) == CP.load_awards(src)
    chars = CP.load_characters(dest)
    assert chars["pick"] and chars["time"] == 45 and chars["theme"] == CP.load_characters(src)["theme"]
    assert [(c["name"], c["ability"]) for c in chars["list"]] == \
        [("GODZILLA 1954", "longer_save"), ("SHIN GODZILLA", "tier2"), ("MOTHRA VS GODZILLA", "")]
    for i, c in enumerate(chars["list"][:2]):                   # the very pictures, copied into the project
        mine = CP.picture_path(dest, c)
        assert mine and mine.startswith(os.path.join(dest, CP.PICTURE_DIR))
        assert open(mine, "rb").read() == open(CP.picture_path(src, CP.load_characters(src)["list"][i]), "rb").read()
    assert not chars["list"][2]["picture"]


def test_a_json_has_the_settings_without_the_pictures(tmp_path, monkeypatch):
    src = _source(tmp_path, monkeypatch)
    out = str(tmp_path / "coop.json")
    assert CP.export_settings(src, out)["left_out"] == 2
    head = json.load(open(out, encoding="utf-8"))
    assert all(not c["picture"] for c in head["characters"]["list"])
    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    assert CP.import_settings(dest, out)["pictures"] == 0
    assert [c["ability"] for c in CP.load_characters(dest)["list"]] == ["longer_save", "tier2", ""]


def test_co_op_off_in_the_file_is_off_here_with_its_choices_kept(tmp_path, monkeypatch):
    src = _source(tmp_path, monkeypatch)
    CP.save(src, False)
    out = str(tmp_path / "off.zip")
    CP.export_settings(src, out)
    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    CP.save(dest, True, menu=True)
    CP.import_settings(dest, out)
    assert not CP.load(dest) and not CP.menu_asked(dest)
    assert len(CP.load_characters(dest)["list"]) == 3 and CP.load_awards(dest)


def test_a_characters_file_replaces_the_characters_only(tmp_path, monkeypatch):
    src = _source(tmp_path, monkeypatch)
    got = CP.import_settings(src, CP.presets()["godzilla"])
    assert got["preset"] and got["characters"] == 11 and got["made_for"] == "Godzilla"
    assert CP.load(src) and CP.menu_asked(src) and CP.load_awards(src)       # the rest as it was
    assert len(CP.load_characters(src)["list"]) == 11
    assert CP.file_about(CP.presets()["godzilla"]) is None                   # not a settings file to the other tabs


def test_what_is_not_a_settings_file_says_so(tmp_path, monkeypatch):
    project = str(tmp_path)
    for name, body in (("x.json", "{}"), ("y.json", "not json"), ("z.json", "[1]")):
        (tmp_path / name).write_text(body, encoding="utf-8")
        with pytest.raises(CP.CoopError):
            CP.import_settings(project, str(tmp_path / name))
    with zipfile.ZipFile(tmp_path / "modes.zip", "w") as zf:                 # a modes zip, a mod pack
        zf.writestr("pad_modes.json", json.dumps({"kind": "pad-modes", "modes": []}))
    with pytest.raises(CP.CoopError, match="no pad_coop.json"):
        CP.import_settings(project, str(tmp_path / "modes.zip"))
    assert CP.file_about(str(tmp_path / "modes.zip")) is None
    with pytest.raises(CP.CoopError, match="Tick Co-op play"):
        CP.export_settings(project, str(tmp_path / "none.zip"))
    assert not CP.settings_saved(project)


def test_a_picture_that_is_not_one_is_dropped_not_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: GZ)
    out = tmp_path / "bad.zip"
    head = {"kind": "pad-coop", "version": 1, "on": True,
            "characters": {"pick": True, "list": [{"name": "A", "picture": "pictures/1_a.png"},
                                                  {"name": "B", "picture": "../../evil.png"}]}}
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("pad_coop.json", json.dumps(head))
        zf.writestr("pictures/1_a.png", b"not a png")
    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    assert CP.import_settings(dest, str(out))["pictures"] == 0
    assert [c["picture"] for c in CP.load_characters(dest)["list"]] == ["", ""]
    assert not (tmp_path / "evil.png").exists()


def test_the_modes_tab_saves_and_loads_them(tmp_path, monkeypatch):
    """Save... and Load... sit with Awards... and Characters...; Load asks before replacing settings the project has,
    names what came in, and Load from a file... hands a co-op file to it."""
    from pinball_decryptor.webui.tabs import modes as M
    src = _source(tmp_path, monkeypatch)
    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    svc = M.ModesTab.__new__(M.ModesTab)
    state, said, asked, shown = {}, [], [], []
    here = {"p": src}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k, d=None: state.get(k, d), raising=False)
    monkeypatch.setattr(svc, "project", lambda: here["p"], raising=False)
    monkeypatch.setattr(svc, "_say", lambda w, *a, **k: said.append(w), raising=False)
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    monkeypatch.setattr(M.compat.messagebox, "askyesno", lambda t, m: asked.append(m) or answer[0])
    monkeypatch.setattr(M.compat.messagebox, "showinfo", lambda t, m: shown.append(m))
    out = str(tmp_path / "saved.zip")
    assert svc.coop_settings_save(out) == out
    assert "3 character(s), 2 picture(s)" in said[-1]
    here["p"] = dest
    assert svc.coop_settings_save(str(tmp_path / "nothing.zip")) is None    # nothing to save here
    answer = [True]
    assert svc.coop_settings_load(out)["characters"] == 3 and not asked     # nothing here to replace: no question
    assert state["coop_on"] and state["coop_menu"] and state["coop_awards_ok"]
    assert "co-op play on, 3 character(s) with 2 picture(s), and the awards" in shown[-1]
    answer = [False]
    CP.save_characters(dest, {"pick": True, "list": [{"name": "MINE", "ability": ""}]})
    assert svc.coop_settings_load(out) is None and asked                   # declined: mine kept
    assert [c["name"] for c in CP.load_characters(dest)["list"]] == ["MINE"]
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: types.SimpleNamespace(label="Jaws Pro 1.0"))
    monkeypatch.setattr(svc, "_save_if_edited", lambda: None, raising=False)
    answer = [True]
    assert svc.load_file(out)["characters"] == 3                           # Load from a file... hands it over
    assert "made for %s" % GZ.label in shown[-1]
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert 'call("modes.coop_settings_save")' in js and 'call("modes.coop_settings_load")' in js


def test_the_mod_pack_tab_says_it_is_co_op_settings(tmp_path, monkeypatch):
    from pinball_decryptor import app as A
    src = _source(tmp_path, monkeypatch)
    out = str(tmp_path / "saved.zip")
    CP.export_settings(src, out)
    obj = A.App.__new__(A.App)
    obj.window = types.SimpleNamespace()                 # no Modes tab: the box only says what it is
    told = []
    monkeypatch.setattr(A.messagebox, "showinfo", lambda t, m: told.append((t, m)))
    obj._offer_modes_file(out, {"coop": CP.file_about(out)}, "Import Mod Pack")
    assert told[0][0] == "Import Mod Pack"
    assert "file of co-op settings, not a mod pack" in told[0][1] and "3 characters, 2 pictures" in told[0][1]
