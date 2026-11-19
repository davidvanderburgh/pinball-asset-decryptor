"""PAD-1408: a maker's whole game shared as one file another owner loads onto their own card."""
import hashlib
import io
import json
import os
import zipfile

import pytest

from pinball_decryptor.core import game_file
from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW

CARD = "godzilla_pro-1_15_0.raw"
STOCK = {
    "audio/a.wav": b"RIFF stock sound a" * 50,
    "images/b.png": b"PNG stock picture b" * 50,
    "video/clip.mp4": b"stock clip of the card" * 200,
}
ELF = b"\x7fELF" + b"\x01" * 60 + b"the maker's object"


def _md5(data):
    return hashlib.md5(data).hexdigest()


def _card_project(tmp_path, name, stock=STOCK):
    """A project as an extract leaves it: the card's files and their baseline."""
    project = str(tmp_path / name)
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(project, CARD), "input_name": CARD}, f)
    for rel, data in stock.items():
        path = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    with open(os.path.join(project, ".checksums.md5"), "w", encoding="utf-8") as f:
        for rel, data in stock.items():
            f.write("%s\t%s\n" % (rel, _md5(data)))
    return project


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def code_cache(tmp_path, monkeypatch):
    folder = str(tmp_path / "code_cache")
    monkeypatch.setattr(MW, "code_cache_dir", lambda: folder)
    return folder


def _maker(tmp_path, code_cache):
    """The maker's project: a changed sound, a stock picture copied over another slot, a
    form mode with its own art and a stock clip, a code mode compiled once, loose files."""
    maker = _card_project(tmp_path, "maker")
    _write(os.path.join(maker, "audio", "a.wav"), b"RIFF the maker's own sound" * 40)
    _write(os.path.join(maker, "images", "b.png"), STOCK["video/clip.mp4"])
    slug, _spec = MP.new_mode(maker, spec=MP.ModeSpec(name="KAIJU RUSH",
                                                      title=MP.GODZILLA_PRO_1_15.key))
    _write(os.path.join(MP.mode_folder(maker, slug), "art.png"), b"maker art" * 30)
    _write(os.path.join(MP.mode_folder(maker, slug), "clip.mp4"), STOCK["video/clip.mp4"])
    code = os.path.join(MP.modes_dir(maker), "laser_show")
    _write(os.path.join(code, "laser_show.c"), b'#define MODE_NAME "LASER SHOW"\n')
    _write(os.path.join(MP.modes_dir(maker), "stock.json"), b'{"rows": [1, 2]}')
    key = MW.code_object_key([CM.source_path(maker, "laser_show")])
    _write(os.path.join(code_cache, key + ".so"), ELF)
    return maker, slug, key


def _all_bytes(zip_path):
    """Every file's bytes in a shared game, the zips inside it opened too."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            data = z.read(n)
            if n.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    out += [(n + "!" + m, inner.read(m)) for m in inner.namelist()]
            else:
                out.append((n, data))
    return out


def test_a_whole_game_travels_without_the_cards_own_files(tmp_path, code_cache):
    maker, slug, key = _maker(tmp_path, code_cache)
    game = str(tmp_path / "kaiju_game.zip")
    head = game_file.export_game(maker, game, name="Kaiju Edition")

    # nothing of the card's own is in the file, at any depth
    stock = {_md5(d) for d in STOCK.values()}
    assert [n for n, d in _all_bytes(game) if _md5(d) in stock] == []
    # ... only named, to be taken from the owner's card
    assert sorted((r["part"], r["member"]) for r in head["stock"]) == [
        (game_file.PACK_MEMBER, "images/b.png"),
        (game_file.MODES_MEMBER, "modes/%s/clip.mp4" % slug)]
    assert head["files"] == 2 and head["modes"] == ["KAIJU RUSH", "LASER SHOW"]
    assert head["modes_root"] == ["stock.json"]
    assert [(o["key"], o["arch"]) for o in head["objects"]] == [(key, "arm")]
    about = game_file.game_file_about(game)
    assert about["name"] == "Kaiju Edition"
    words = game_file.game_file_words(about)
    assert "2 changed files" in words and "KAIJU RUSH" in words and "compiled" in words
    # a mod pack or a file of modes is not a shared game, and the Modes tab says where it loads
    with pytest.raises(MP.ModeProjectError, match="Import Mod Pack"):
        MP.import_modes(game, _card_project(tmp_path, "modes_tab"))
    assert game_file.game_file_about(str(tmp_path / "nope.zip")) is None

    # another owner of the same card loads it into their own extract
    owner = _card_project(tmp_path, "owner")
    res = game_file.import_game(game, owner)
    assert _read(os.path.join(owner, "audio", "a.wav")) == b"RIFF the maker's own sound" * 40
    assert _read(os.path.join(owner, "images", "b.png")) == STOCK["video/clip.mp4"]
    assert _read(os.path.join(MP.mode_folder(owner, slug), "art.png")) == b"maker art" * 30
    assert _read(os.path.join(MP.mode_folder(owner, slug), "clip.mp4")) == STOCK["video/clip.mp4"]
    assert os.path.isfile(CM.source_path(owner, "laser_show"))
    assert _read(os.path.join(MP.modes_dir(owner), "stock.json")) == b'{"rows": [1, 2]}'
    assert res["missing"] == [] and res["objects"] == [key]
    assert sorted(game_file.project_record(owner)["mode_slugs"]) == ["kaiju_rush", "laser_show"]

    # the owner's Write takes the maker's own object for those sources: no compile
    os.remove(os.path.join(code_cache, key + ".so"))

    class NoCompile:
        def run(self, *a, **k):
            raise AssertionError("compiled instead of using the maker's object")

    out = str(tmp_path / "build" / "mode.so")
    assert MW.code_object_key([CM.source_path(owner, "laser_show")]) == key
    MW.compile_code_object([CM.source_path(owner, "laser_show")], out)
    assert _read(out) == ELF
    del NoCompile

    # a newer version of the same game loads over the modes the last one brought
    _write(os.path.join(MP.mode_folder(maker, slug), "art.png"), b"maker art v2" * 30)
    game_file.export_game(maker, game, name="Kaiju Edition")
    res = game_file.import_game(game, owner)
    assert sorted(os.listdir(MP.modes_dir(owner))) == ["kaiju_rush", "laser_show", "stock.json"]
    assert _read(os.path.join(MP.mode_folder(owner, slug), "art.png")) == b"maker art v2" * 30


def test_the_cards_own_files_come_from_the_owners_untouched_originals(tmp_path, code_cache):
    """An owner who changed the very stock file a game takes still gets the card's bytes."""
    maker, slug, _key = _maker(tmp_path, code_cache)
    game = str(tmp_path / "g.zip")
    game_file.export_game(maker, game)
    owner = _card_project(tmp_path, "owner")
    from pinball_decryptor.core import staged_originals
    staged_originals.snapshot(owner, "video/clip.mp4", _md5(STOCK["video/clip.mp4"]))
    _write(os.path.join(owner, "video", "clip.mp4"), b"the owner's own clip")
    res = game_file.import_game(game, owner)
    assert res["missing"] == []
    assert _read(os.path.join(MP.mode_folder(owner, slug), "clip.mp4")) == STOCK["video/clip.mp4"]


def test_a_card_without_the_file_leaves_it_out_and_says_so(tmp_path, code_cache):
    maker, slug, _key = _maker(tmp_path, code_cache)
    game = str(tmp_path / "g.zip")
    game_file.export_game(maker, game)
    other = dict(STOCK)
    del other["video/clip.mp4"]
    owner = _card_project(tmp_path, "owner", stock=other)
    said = []
    res = game_file.import_game(game, owner, log_cb=lambda t, l="info": said.append((l, t)))
    assert sorted(r["member"] for r in res["missing"]) == [
        "images/b.png", "modes/%s/clip.mp4" % slug]
    assert not os.path.isfile(os.path.join(MP.mode_folder(owner, slug), "clip.mp4"))
    assert any(l == "warning" and "video/clip.mp4" in t for l, t in said)


def test_a_project_with_no_extract_or_nothing_changed_is_refused(tmp_path):
    bare = str(tmp_path / "bare")
    os.makedirs(bare)
    with pytest.raises(game_file.GameFileError, match="no extract"):
        game_file.export_game(bare, str(tmp_path / "x.zip"))
    plain = _card_project(tmp_path, "plain")
    with pytest.raises(game_file.GameFileError, match="nothing to share"):
        game_file.export_game(plain, str(tmp_path / "x.zip"))
    assert not os.path.exists(str(tmp_path / "x.zip"))
    junk = str(tmp_path / "junk.zip")
    with zipfile.ZipFile(junk, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(game_file.GameFileError, match="not a shared game"):
        game_file.import_game(junk, plain)


def test_a_bad_object_or_path_in_a_file_is_never_written(tmp_path):
    owner = _card_project(tmp_path, "owner")
    game = str(tmp_path / "evil.zip")
    head = {"format": 1, "kind": game_file.GAME_KIND, "name": "x",
            "objects": [{"key": "a" * 64}, {"key": "../../evil"}],
            "modes_root": ["../escape.txt", "ok.json"]}
    with zipfile.ZipFile(game, "w") as z:
        z.writestr(game_file.GAME_MANIFEST, json.dumps(head))
        z.writestr("code/%s.so" % ("a" * 64), b"not an elf")
        z.writestr("modes_root/../escape.txt", b"x")
        z.writestr("modes_root/ok.json", b"{}")
    res = game_file.import_game(game, owner)
    assert res["objects"] == [] and res["mode_files"] == ["ok.json"]
    assert not os.path.exists(os.path.join(owner, "escape.txt"))
    assert not os.path.isdir(os.path.join(owner, game_file.PROJECT_DIR, "code"))


def test_export_with_changed_files_unticked_carries_the_modes_alone(tmp_path, code_cache):
    maker, slug, key = _maker(tmp_path, code_cache)
    game = str(tmp_path / "modes_only.zip")
    head = game_file.export_game(maker, game, files=False)
    with zipfile.ZipFile(game) as z:
        names = z.namelist()
    assert game_file.PACK_MEMBER not in names and game_file.MODES_MEMBER in names
    assert head["files"] == 0 and head["modes"] == ["KAIJU RUSH", "LASER SHOW"]
    owner = _card_project(tmp_path, "owner")
    game_file.import_game(game, owner)
    assert _read(os.path.join(owner, "audio", "a.wav")) == STOCK["audio/a.wav"]   # not carried
    assert os.path.isfile(CM.source_path(owner, "laser_show"))


def _includes(tmp_path, files, modes, mfr="stern", with_modes=True):
    from pinball_decryptor import app as A

    class Var:
        def __init__(self, v):
            self.v = v

        def get(self):
            return self.v

    class Stub:
        pass

    st = Stub()
    st.window = Stub()
    st.window.pack_files_var, st.window.pack_modes_var = Var(files), Var(modes)
    st._current_mfr = Stub()
    st._current_mfr.key = mfr
    project = str(tmp_path / ("p_%s_%s_%s_%s" % (files, modes, mfr, with_modes)))
    os.makedirs(os.path.join(project, "modes", "story") if with_modes else project)
    return A.App._pack_includes(st, project)


def test_the_export_boxes_pick_what_goes_in_the_pack(tmp_path):
    """Export Mod Pack... has two boxes, both on: with Modes ticked on a project that has modes
    the pack is the whole game; otherwise the Mod Pack it always was."""
    assert _includes(tmp_path, True, True) == (True, True)
    assert _includes(tmp_path, True, False) == (True, False)
    assert _includes(tmp_path, False, True) == (False, True)
    assert _includes(tmp_path, False, False) == (False, False)          # asked to tick one
    assert _includes(tmp_path, True, True, with_modes=False) == (True, False)
    assert _includes(tmp_path, True, True, mfr="jjp") == (True, False)

    from pinball_decryptor.webui.tabs import modpack as tab
    assert {"pack_files_var", "pack_modes_var"} <= set(tab.ModPackTab.exports)
    assert not hasattr(tab.ModPackTab, "share_game") and not hasattr(tab.ModPackTab, "load_game")
    js = open(os.path.join(os.path.dirname(tab.__file__), "..", "static", "js", "tabs",
                           "modpack.js"), encoding="utf-8").read()
    assert 'k="pack_files"' in js and 'k="pack_modes"' in js
    assert "share_game" not in js and "load_game" not in js


def test_a_baseline_taken_after_the_modes_never_counts_them_as_the_cards(tmp_path, code_cache):
    """The baseline walk keeps ``modes``: a project re-extracted after its modes were made lists
    them, and they are still the maker's own, carried in the file."""
    from pinball_decryptor.core import checksums as CK
    maker, slug, _key = _maker(tmp_path, code_cache)
    CK.generate_checksums(maker)
    assert any(r.startswith("modes/") for r in CK.read_baseline_any(maker))
    game = str(tmp_path / "g.zip")
    head = game_file.export_game(maker, game)
    # the mode's copy of the card's clip is still the card's; its own art is the maker's
    assert [r["member"] for r in head["stock"]] == ["modes/%s/clip.mp4" % slug]
    names = [n for n, _d in _all_bytes(game)]
    assert "modes.zip!modes/%s/art.png" % slug in names
    assert "modes_root/stock.json" in names
