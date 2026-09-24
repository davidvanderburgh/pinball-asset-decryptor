"""The web Replace Images tab (webui/tabs/images.py): the Tk tab's behaviour,
driven the way the page drives it (``w.call("images.<method>")``), with modal
questions answered by the harness."""

import csv
import json
import os
import time

import pytest

from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")

BANNER = "images/scene_textures/radimg_unnamed_instance_24_40x20_45402198.png"
SPRITE = "images/scene_textures/radimg_Char_Select_20x10_bba78124.png"
ATLAS = "images/scene_textures/radimg_GameFont_Primary_64x64_3ce3aba2.png"
GLYPH = ("images/scene_textures/glyphs/radimg_GameFont_Primary_64x64_3ce3aba2"
         "/U+0041_A.png")
PLAIN = "images/backglass.png"
BOOT = "images/boot_screen/splash.png"
ALL = sorted([BANNER, SPRITE, ATLAS, GLYPH, PLAIN, BOOT], key=str.lower)
CARD = "/game/scenes/0123456789abcdef/scene.radium"


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    """Never touch the real per-card name library under %APPDATA%."""
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "tag_library.json"))


def _project(tmp_path):
    assets = tmp_path / "gz"
    tex = assets / "images" / "scene_textures"
    (tex / "glyphs" / "radimg_GameFont_Primary_64x64_3ce3aba2").mkdir(
        parents=True)
    (assets / "images" / "boot_screen").mkdir(parents=True)
    Image.new("RGBA", (40, 20), (0, 0, 0, 255)).save(assets / BANNER)
    Image.new("RGBA", (20, 10), (0, 255, 0, 128)).save(assets / SPRITE)
    Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(assets / ATLAS)
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(assets / GLYPH)
    Image.new("RGB", (64, 32), (0, 0, 255)).save(assets / PLAIN)
    Image.new("RGB", (32, 16), (9, 9, 9)).save(assets / BOOT)
    (tex / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n"
        "scene_textures/glyphs/radimg_GameFont_Primary_64x64_3ce3aba2/"
        "U+0041_A.png\tscene_textures/radimg_GameFont_Primary_64x64_3ce3aba2"
        ".png\t0x0041\t0\t0\t8\t8\tGameFont\n", encoding="utf-8")
    # both radium pictures in one container (the "Group by scene" group)
    (tex / "radium_images.txt").write_text(
        "scene_textures/%s\t%s\t100\t10\t0\t0\tpng\n"
        "scene_textures/%s\t%s\t200\t10\t0\t0\tpng\n"
        % (os.path.basename(SPRITE), CARD, os.path.basename(BANNER), CARD),
        encoding="utf-8")
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(assets))
    reps = tmp_path / "mine"
    reps.mkdir()
    Image.new("RGBA", (90, 22), (255, 255, 255, 255)).save(
        reps / "SpaceGodzilla.png")
    Image.new("RGB", (10, 10), (1, 2, 3)).save(reps / "backglass.jpg")
    return str(assets), str(reps)


def _set_folder(w, assets):
    """Set the shared project folder.  Another tab's trace on it may raise
    while that port is unfinished; Tk would only have printed that, and the
    value is set before any trace runs, so it does not stop this tab."""
    def _do():
        try:
            w.window.write_assets_var.set(assets)
        except Exception:                                # noqa: BLE001
            pass
    w.run(_do)


def _wait(w, cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if cond(w.state("images")):
            return w.state("images")
        time.sleep(0.05)
    raise AssertionError("timed out; images state: %r" % {
        k: v for k, v in w.state("images").items()
        if not k.startswith("rows_")})


def _rows(st):
    out = []
    for k in range(st.get("nchunks") or 0):
        out.extend(st.get("rows_%d" % k) or [])
    return out


def _by_rel(st):
    return {r["r"]: r for r in _rows(st)}


def _view_rels(st):
    rows = _rows(st)
    return [rows[e]["r"] for e in st["view"] if isinstance(e, int)]


def _settled(st):
    rows = _rows(st)
    return (not st.get("scanning") and st.get("total")
            and "still checking" not in (st.get("status") or "")
            and rows and all(r["s"] != "…" for r in rows))


@pytest.fixture
def scanned(tmp_path):
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        st = _wait(w, _settled)
        yield w, assets, reps, st


# ------------------------------------------------------------ gating
def _manufacturers():
    from pinball_decryptor.core.registry import all_manufacturers, load_plugins
    load_plugins()
    return list(all_manufacturers())


@pytest.mark.parametrize("mkey", [m.key for m in _manufacturers()])
def test_tab_shows_exactly_where_the_plugin_replaces_images(tmp_path, mkey):
    with web_app(tmp_path, mfr=mkey) as w:
        eras = [e["key"] for e in (w.state("shell")["mfr"]["eras"] or [])] \
            or [""]
        for era in eras:
            if era:
                w.call("ui.set_era", era)
            mfr = w.window.current_mfr
            tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
            want = bool(getattr(mfr.capabilities, "replace_image", False))
            assert tabs["images"]["visible"] is want, (mkey, era)
            st = w.state("images")
            assert st["view"] == [] and st["total"] == 0
            assert st["note"] == (mfr.image_note() or "")
            assert st["empty"]["text"].startswith("Set the project folder")
            assert st["preview"]["orig"] == ""
            assert st["can_clear"] is False
            # the run logic's read: nothing pending on a fresh manufacturer
            assert w.window.pending_image_assignments(str(tmp_path)) is None


def test_stern_spike2_only(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["images"]["visible"]
        assert tabs["images"]["label"] == "Images"
        for era in ("spike1", "whitestar"):
            w.call("ui.set_era", era)
            tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
            assert not tabs["images"]["visible"]


def test_exports_are_on_the_window(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        for name in ("pending_image_assignments", "reveal_image_slot",
                     "image_search_var", "image_source_filter_var",
                     "image_change_filter_var", "image_group_by_scene_var",
                     "image_keep_size_var", "image_status_var"):
            assert getattr(win, name) is not None
        assert not any(n.startswith("image")
                       for n in (getattr(win, "missing_exports", None) or {}))


# ------------------------------------------------------------ scanning
def test_scan_lists_every_slot_with_metadata(scanned):
    w, assets, _reps, st = scanned
    assert _view_rels(st) == ALL                 # "#0" ascending by path
    rows = _by_rel(st)
    assert rows[BANNER]["s"] == "40×20"
    assert rows[PLAIN]["f"] == "PNG"
    assert rows[SPRITE]["f"] == "PNG alpha"
    assert rows[BANNER]["o"] == "Radium"
    assert rows[GLYPH]["o"] == "Glyph"
    assert rows[BOOT]["o"] == "Boot screen"
    assert rows[PLAIN]["o"] == "File"
    assert all(r["p"] == "Choose…" and r["t"] == "" for r in rows.values())
    assert st["status"] == "6 images, 0 changed"
    assert st["empty"] is None and st["dir"] == assets
    # the first row is selected and previewed, as in Tk
    assert st["focus"]["id"] == ALL[0]
    assert st["preview"]["rel"] == ALL[0]
    assert st["preview"]["orig"].endswith(os.path.basename(ALL[0]))
    assert st["preview"]["hdr"] == "Original"
    # nothing picked: keep column not offered until a pick exists
    assert st["cols"] == {"n": False, "keep": True}
    log = " ".join(l["text"] for l in w.window._log["stern"])
    assert "Images scan started." in log and "Images scan finished" in log


def test_no_folder_says_where_to_set_it(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("images.scan")
        st = w.state("images")
        assert st["empty"]["text"] == (
            "Set the project folder on the Extract tab, then click Scan.")
        assert st["scanning"] is False


def test_cancel_scan(scanned):
    w, _assets, _reps, _st = scanned
    w.run(lambda: w.window.service("images")._set_scanning(True))
    w.call("images.cancel_scan")
    st = w.state("images")
    assert st["scanning"] is False and st["view"] == []
    assert st["empty"]["text"] == "Scan cancelled — click Scan to try again."


def test_on_show_rescans_when_the_folder_changed(tmp_path):
    assets, _reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("ui.select_tab", "images")
        st = _wait(w, _settled)
        assert st["total"] == 6


# ------------------------------------------------------------ filters
def test_resolution_sorts_by_width_then_height(tmp_path):
    """PAD-207: every 1920-wide picture sorts together, tallest first, ahead
    of a narrower one with more pixels (892x760 > 1920x316 by area)."""
    assets = tmp_path / "gz"
    (assets / "images").mkdir(parents=True)
    sizes = [(892, 760), (1920, 316), (1920, 1080), (720, 1200),
             (1920, 100), (1360, 1000)]
    for w_, h in sizes:
        Image.new("RGB", (w_, h)).save(assets / "images" / ("p%dx%d.png"
                                                            % (w_, h)))
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(assets))
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, str(assets))
        w.call("images.scan")
        _wait(w, _settled)
        w.call("images.sort", "res")
        st = w.state("images")
        want = ["1920×1080", "1920×316", "1920×100", "1360×1000",
                "892×760", "720×1200"]
        rows = _rows(st)
        assert [rows[e]["s"] for e in st["view"]] == want
        w.call("images.sort", "res")
        st = w.state("images")
        assert [rows[e]["s"] for e in st["view"]] == want[::-1]


def test_search_source_show_and_sort(scanned):
    w, _assets, reps, _st = scanned
    # the search matches a container's name too: both pictures of the
    # "Char_Select" scene come up, as in Tk
    w.call("ui.set", "images", "search", "char_select")
    st = w.state("images")
    assert _view_rels(st) == [SPRITE, BANNER]
    assert st["status"] == "6 images, 0 changed  (2 shown)"
    w.call("ui.set", "images", "search", "backglass")
    assert _view_rels(w.state("images")) == [PLAIN]
    # a glyph matches on its own name only, not its atlas folder
    w.call("ui.set", "images", "search", "gamefont")
    assert _view_rels(w.state("images")) == [ATLAS]
    w.call("ui.set", "images", "search", "")
    w.call("images.set_source", "Radium")
    assert set(_view_rels(w.state("images"))) == {BANNER, SPRITE, ATLAS}
    w.call("images.set_source", "All sources")
    w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
    w.call("images.choose", BANNER)
    w.call("images.set_show", "Changed")
    assert _view_rels(w.state("images")) == [BANNER]
    w.call("images.set_show", "Unchanged")
    assert BANNER not in _view_rels(w.state("images"))
    w.call("images.set_show", "All")
    # Resolution sorts largest first on the first click, then flips
    w.call("images.sort", "res")
    st = w.state("images")
    assert st["sort"] == {"key": "res", "desc": True}
    assert _view_rels(st)[0] == PLAIN or _view_rels(st)[0] == ATLAS
    w.call("images.sort", "res")
    assert w.state("images")["sort"] == {"key": "res", "desc": False}
    assert _view_rels(w.state("images"))[0] == GLYPH
    # Replacement sorts picked rows first
    w.call("images.sort", "rep")
    assert _view_rels(w.state("images"))[0] == BANNER
    # filters persist in the folder's sidecar
    from pinball_decryptor.core import staged_changes
    data = staged_changes.load(w.window.write_assets_var.get())
    assert data["image_source_filter"] == "All sources"
    assert data["image_change_filter"] == "All"


def test_group_by_scene(scanned):
    w, _assets, _reps, _st = scanned
    w.call("images.set_grouped", True)
    st = w.state("images")
    assert st["cols"]["n"] is True
    heads = [e for e in st["view"] if isinstance(e, dict)]
    rad = [h for h in heads if h["g"] == "rad::" + CARD][0]
    assert rad["n"] == 2 and rad["c"] == "2 images" and rad["o"] is False
    # the label is the element hint plus the scene hash shorthand
    assert rad["l"] == "Char_Select · 01234567"
    assert not any(isinstance(e, int) for e in st["view"])   # all collapsed
    w.call("images.toggle_group", "rad::" + CARD)
    st = w.state("images")
    # children in play order (data offset): SPRITE (100) before BANNER (200)
    i = st["view"].index(next(h for h in st["view"]
                              if isinstance(h, dict) and h["g"] == rad["g"]))
    rows = _rows(st)
    assert [rows[e]["r"] for e in st["view"][i + 1:i + 3]] == [SPRITE, BANNER]
    # the group's menu, then rename it
    items = w.call("images.menu", "::grp::rad::" + CARD, [])
    labels = [it.get("label") for it in items if not it.get("sep")]
    assert labels == ["Assign replacement to all 2 images…",
                      "Blank all 2 images (transparent)…", "Rename group…"]
    info = w.call("images.act", "group_rename", "::grp::rad::" + CARD, [])
    assert info["initial"] == "Char_Select · 01234567"
    assert "blank restores" in info["prompt"]
    w.call("images.rename_group", "rad::" + CARD, "  Kaiju   select ")
    st = w.state("images")
    assert any(isinstance(e, dict) and e["l"] == "Kaiju select"
               for e in st["view"])
    from pinball_decryptor.core import staged_changes
    data = staged_changes.load(w.window.write_assets_var.get())
    assert data["image_group_tags"] == {"rad::" + CARD: "Kaiju select"}
    assert data["image_group_by_scene"] is True
    # searching the rename finds the group
    w.call("ui.set", "images", "search", "kaiju")
    heads = [e for e in w.state("images")["view"] if isinstance(e, dict)]
    assert [h["g"] for h in heads] == ["rad::" + CARD]
    # selecting a group previews its first shown child, no replacement
    w.call("images.select", "::grp::rad::" + CARD)
    p = w.state("images")["preview"]
    assert p["group"] == "rad::" + CARD and p["rep"] == ""
    assert p["orig"].endswith(os.path.basename(SPRITE))


def test_group_blank_and_clear(scanned):
    w, assets, _reps, _st = scanned
    w.call("images.set_grouped", True)
    gid = "::grp::rad::" + CARD
    w.answers = ["yes"]
    w.call("images.act", "group_blank", gid, [])
    blank = os.path.join(assets, ".blank.png")
    assert os.path.isfile(blank)
    pend = w.window.pending_image_assignments(assets)
    assert pend[1] == {SPRITE: blank, BANNER: blank}
    items = w.call("images.menu", gid, [])
    assert "Clear replacements in group" in [it.get("label") for it in items]
    w.call("images.act", "group_clear", gid, [])
    assert w.window.pending_image_assignments(assets) is None


# ------------------------------------------------------------ picking
def test_choose_keep_size_and_the_build_tuple(scanned):
    w, assets, reps, _st = scanned
    rep = os.path.join(reps, "SpaceGodzilla.png")
    w.answers = [rep]
    assert w.call("images.choose", BANNER) == BANNER
    asked = w.asked[-1]
    assert asked["kind"] == "file"
    assert asked["title"] == "Choose a replacement for %s" % BANNER
    assert asked["filetypes"][0][0] == "Image files"
    st = w.state("images")
    row = _by_rel(st)[BANNER]
    assert row["p"] == "SpaceGodzilla.png" and row["t"] == "assigned"
    assert row["k"] is False                     # the keep tick is offered
    assert _by_rel(st)[PLAIN]["k"] is None
    assert st["status"] == "6 images, 1 changed"
    assert st["can_clear"] is True
    w.call("images.select", BANNER)
    p = w.state("images")["preview"]
    assert p["rep"] == os.path.normpath(rep) and p["has_pick"]
    assert p["keep"] == {"on": False, "text": (
        "Your picture is 90×22, the original 40×20: it will be squeezed "
        "to fit.")}
    pend = w.window.pending_image_assignments(assets)
    assert pend[1] == {BANNER: os.path.normpath(rep)}
    assert pend[2] == frozenset()
    w.call("images.set_keep", BANNER, True)
    p = w.state("images")["preview"]
    assert p["keep"]["on"] is True and "the scene grows" in p["keep"]["text"]
    assert _by_rel(w.state("images"))[BANNER]["k"] is True
    assert w.window.pending_image_assignments(assets)[2] == frozenset(
        {BANNER})
    from pinball_decryptor.core import staged_changes
    data = staged_changes.load(assets)
    assert data["image"] == {BANNER: os.path.normpath(rep)}
    assert data["image_keep_size"] == [BANNER]
    assert data["replacement_names"] == {BANNER: "SpaceGodzilla.png"}
    # an atlas never keeps its own size
    assert w.call("images.set_keep", ATLAS, True) is False
    # a different folder: nothing for the build, and Write is warned
    assert w.window.pending_image_assignments(str(assets) + "x") is None
    assert w.window.replacement_folder_mismatches(str(assets) + "x") == [
        ("image", 1, assets)]
    assert w.window.replacement_folder_mismatches(assets) == []
    log = " ".join(l["text"] for l in w.window._log["stern"])
    assert "Replace Images: %s ← SpaceGodzilla.png" % BANNER in log


def test_picks_come_back_from_the_sidecar(tmp_path):
    assets, reps = _project(tmp_path)
    rep = os.path.join(reps, "SpaceGodzilla.png")
    from pinball_decryptor.core import staged_changes
    staged_changes.save(assets, {
        "image": {BANNER: rep, PLAIN: os.path.join(reps, "gone.png")},
        "image_keep_size": [BANNER], "image_group_by_scene": True,
        "image_change_filter": "Changed", "image_source_filter": "Radium"})
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        st = _wait(w, _settled)
        assert st["grouped"] is True and st["show"] == "Changed"
        assert st["source"] == "Radium"
        pend = w.window.pending_image_assignments(assets)
        assert pend[1] == {BANNER: rep} and pend[2] == frozenset({BANNER})
        log = " ".join(l["text"] for l in w.window._log["stern"])
        assert 'Saved image replacement for "%s"' % PLAIN in log
        assert "Relink moved files" in log


def test_clear_one_selected_and_all(scanned):
    w, assets, reps, _st = scanned
    rep = os.path.join(reps, "SpaceGodzilla.png")
    for rel in (BANNER, SPRITE, PLAIN):
        w.answers = [rep]
        w.call("images.choose", rel)
    items = w.call("images.menu", PLAIN, [PLAIN])
    labels = [it.get("label") for it in items if not it.get("sep")]
    assert labels[:2] == ["Choose replacement…", "Clear replacement"]
    assert w.call("images.act", "clear_one", PLAIN, [PLAIN]) == 1
    # the multi-row menu
    items = w.call("images.menu", BANNER, [BANNER, SPRITE, GLYPH])
    assert items[0]["label"] == "3 slots selected" and items[0]["disabled"]
    assert items[2]["label"] == "Clear 2 replacements in this selection"
    w.answers = ["no"]
    assert w.call("images.act", "clear_sel", BANNER,
                  [BANNER, SPRITE, GLYPH]) == 0
    assert "Clear the replacements for these 2 slots?" in \
        w.asked[-1]["message"]
    w.answers = ["yes"]
    assert w.call("images.act", "clear_sel", BANNER,
                  [BANNER, SPRITE, GLYPH]) == 2
    assert w.window.pending_image_assignments(assets) is None
    assert w.state("images")["can_clear"] is False
    # Clear replacements… with nothing picked says so
    assert w.call("images.clear_all") == 0
    assert w.asked[-1]["message"].startswith("Nothing is picked")
    w.answers = [rep]
    w.call("images.choose", BANNER)
    w.answers = ["yes"]
    assert w.call("images.clear_all") == 1
    assert "Clear all 1 replacement on this tab?" in w.asked[-1]["message"]


def test_replace_from_folder(scanned):
    w, assets, reps, _st = scanned
    # a folder inside the project is refused
    w.answers = [os.path.join(assets, "images")]
    assert w.call("images.from_folder") == 0
    assert "part of the project folder" in w.asked[-1]["message"]
    # backglass.jpg pairs with backglass.png (type ignored)
    w.answers = [reps, "yes"]
    assert w.call("images.from_folder") == 1
    q = w.asked[-1]["message"]
    assert q.startswith("Use 1 file(s) from")
    assert "different file type" in q
    pend = w.window.pending_image_assignments(assets)
    assert pend[1] == {PLAIN: os.path.join(reps, "backglass.jpg")}


def test_row_menu_for_scene_pictures(scanned):
    w, _assets, _reps, _st = scanned
    labels = [it.get("label") for it in w.call("images.menu", GLYPH, [GLYPH])
              if not it.get("sep")]
    assert "Open in Fonts window…" in labels
    assert "Show scene contents…" in labels
    labels = [it.get("label") for it in w.call("images.menu", PLAIN, [PLAIN])
              if not it.get("sep")]
    assert "Show scene contents…" not in labels
    assert labels[-1] in ("Show in File Explorer", "Reveal in Finder",
                          "Show in File Manager",
                          "Find in Partition Explorer")


def test_fonts_and_scenes_need_a_project(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("images.open_fonts") is False
        assert "Pick your extracted project folder first" in \
            w.asked[-1]["message"]
        assert w.call("images.open_scenes") is False
        assert w.asked[-1]["title"] == "Scenes"


def test_fonts_and_scenes_open_the_windows_on_the_row(scanned):
    """Fonts… / Scenes… and the row menu open the real windows (the Text
    tab's service draws them over any tab), preselected like Tk's
    _open_font_studio / _open_scene_browser; nothing is asked."""
    w, assets, _reps, _st = scanned
    asked = len(w.asked)
    # the glyph row: the Fonts window on the font that owns the slice
    assert w.call("images.act", "fonts", GLYPH, [GLYPH]) is True
    tf = w.state("text_fonts")
    assert tf["open"] is True
    assert tf["sel"] == "radimg_GameFont_Primary_64x64_3ce3aba2"
    w.call("text_fonts.close", True)
    # a radium picture: the Scenes window on the scene that draws it
    assert w.call("images.act", "scenes", BANNER, [BANNER]) is True
    ts = w.state("text_scenes")
    assert ts["open"] is True and ts["sel"] == "/game/scenes/0123456789abcdef"
    # the page-head buttons open them with no row
    assert w.call("images.open_fonts") is True
    assert w.state("text_fonts")["open"] is True
    assert w.call("images.open_scenes") is True
    assert w.state("text_scenes")["open"] is True
    assert len(w.asked) == asked                 # no "not in this version"
    w.call("text_fonts.close", True)
    w.call("text_scenes.close")


def test_one_picker_at_a_time(scanned):
    """A double-click on the Replacement cell sent a pick per click plus the
    row's own double-click: three pickers, one after the other.  Tk's picker
    was modal, so there was only ever one; a pick asked for while one of the
    tab's pickers is up is refused."""
    w, assets, reps, _st = scanned
    svc = w.window.service("images")
    rep = os.path.join(reps, "SpaceGodzilla.png")
    inner = []
    ask = w.ctx.dialogs.ask

    def _ask(spec):
        if spec.get("kind") == "file" and not inner:
            # the clicks that arrive while the first picker is up
            inner.append(svc.choose(PLAIN))
            inner.append(svc._group_assign("::grp::x", [PLAIN]))
            inner.append(svc.export_csv())
            inner.append(svc.from_folder())
        return ask(spec)

    w.ctx.dialogs.ask = _ask
    w.answers = [rep]
    assert w.call("images.choose", BANNER) == BANNER
    assert inner == [None, 0, "", 0]
    assert [a["kind"] for a in w.asked].count("file") == 1
    assert w.window.pending_image_assignments(assets)[1] == {
        BANNER: os.path.normpath(rep)}
    # the guard is released: the next pick asks again
    w.answers = [rep]
    assert w.call("images.choose", PLAIN) == PLAIN
    assert [a["kind"] for a in w.asked].count("file") == 2


def test_column_widths_persist_only_what_was_dragged(tmp_path):
    """Tk _persist_tree_columns / _save_tree_columns: a dragged column's
    width is saved (and wins over fitting to content from then on); the
    others are left to fit.  A key of its own, beside Tk's widths."""
    tk_widths = {"image": {"#0": 565, "res": 177}}
    with web_app(tmp_path, mfr="stern",
                 settings={"column_widths": tk_widths}) as w:
        assert w.state("images")["widths"] == {}
        assert w.call("images.save_widths", {"fmt": 140}) is True
        assert w.call("images.save_widths",
                      {"#0": 420.4, "bogus": 90, "src": 5,
                       "keep": True}) is True
        saved = w.app._settings["column_widths"]
        assert saved["image_web"] == {"fmt": 140, "#0": 420}
        assert saved["image"] == {"#0": 565, "res": 177}   # Tk's untouched
        assert w.state("images")["widths"] == {"fmt": 140, "#0": 420}
        assert w.call("images.save_widths", {"n": 3}) is False
    # a restart reads them back
    with web_app(tmp_path, mfr="stern",
                 settings={"column_widths": saved}) as w:
        assert w.state("images")["widths"] == {"fmt": 140, "#0": 420}


def test_thumb_and_export_csv(scanned, tmp_path):
    w, assets, reps, _st = scanned
    url = w.call("images.thumb", os.path.join(assets, SPRITE), 100, 80)
    assert url.startswith("data:image/png;base64,")
    assert w.call("images.thumb", os.path.join(assets, "nope.png")) == ""
    out = tmp_path / "t.csv"
    w.answers = [str(out)]
    assert w.call("images.export_csv") == str(out)
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["Original Image", "Resolution", "Format", "Source",
                       "Replacement", "Changed On Disk", "Keep Size"]
    assert len(rows) == 7


# ------------------------------------------------------------ fan-outs
def test_changed_on_disk_and_revert_fanouts(scanned):
    w, assets, reps, _st = scanned
    from pinball_decryptor.core import staged_originals
    # PLAIN changed by hand (no snapshot); BOOT changed by a build (snapshot)
    staged_originals.snapshot(assets, BOOT, None)
    Image.new("RGB", (64, 32), (255, 255, 0)).save(os.path.join(assets,
                                                                PLAIN))
    Image.new("RGB", (32, 16), (200, 0, 0)).save(os.path.join(assets, BOOT))
    w.run(lambda: w.window.refresh_after_revert())
    st = _wait(w, _settled)
    for rel in (PLAIN, BOOT):
        row = _by_rel(st)[rel]
        assert row["t"] == "changed" and row["p"] == "✓ changed on disk"
    assert st["status"] == "6 images, 2 changed"
    w.call("images.select", PLAIN)
    p = w.state("images")["preview"]
    assert p["hdr_main"] == "Current file (already modified)"
    assert p["rep"] == "" and p["empty"].startswith("already changed on disk")
    w.call("images.select", BOOT)
    p = w.state("images")["preview"]
    assert p["hdr_main"] == "Original"
    assert p["orig"] == staged_originals.snapshot_path(assets, BOOT)
    assert p["rep"].endswith("splash.png") and p["clearable"]
    # clearing BOOT puts the card's own file back (PAD-142)
    assert w.call("images.clear_one", BOOT) == 1
    assert staged_originals.snapshot_path(assets, BOOT) is None
    assert _by_rel(w.state("images"))[BOOT]["t"] == ""
    # revert: every pick goes and the sidecar keeps only what Revert keeps
    w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
    w.call("images.choose", BANNER)
    w.run(lambda: w.window.clear_replace_assignments(assets))
    assert w.window.pending_image_assignments(assets) is None
    from pinball_decryptor.core import staged_changes
    assert "image" not in staged_changes.load(assets)
    # invalidate keeps the folder identity for the mismatch warning
    w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
    w.call("images.choose", BANNER)
    w.run(lambda: w.window.invalidate_asset_scans(False))
    assert w.window.replacement_folder_mismatches(assets) == []
    assert w.window.replacement_folder_mismatches(assets + "x") == [
        ("image", 1, assets)]


def test_emulate_staging_redraws_the_original_from_the_snapshot(scanned):
    """PAD-209: the preview was drawn while the slot's own file was still
    the card's picture; Emulate's Start then wrote the pick over it, and the
    Original pane went on naming that file, so it showed the pick."""
    w, assets, reps, _st = scanned
    from pinball_decryptor.core import staged_originals
    rep = os.path.join(reps, "SpaceGodzilla.png")
    w.answers = [rep]
    w.call("images.choose", BANNER)
    w.call("images.set_keep", BANNER, True)
    w.call("images.select", BANNER)
    p = w.state("images")["preview"]
    assert p["orig"] == os.path.join(assets, *BANNER.split("/"))
    ver = p["ver"]
    # what Emulate's Start does (App.stage_pending_replacements)
    slots, assigns, keep = w.window.pending_image_assignments(assets)
    from pinball_decryptor.core.image_slots import stage_replacements
    staged, failures = stage_replacements(slots, assigns, assets_dir=assets,
                                          keep_size=keep)
    assert (staged, failures) == (1, [])
    snap = staged_originals.snapshot_path(assets, BANNER)
    assert snap
    w.run(lambda: w.window.folder_staged(assets))
    st = _wait(w, lambda s: s["preview"].get("orig") == snap and _settled(s))
    p = st["preview"]
    assert p["hdr_main"] == "Original" and p["ver"] > ver
    assert p["rep"] == os.path.normpath(rep)
    # the Resolution column is probed again off the file now on disk
    row = _by_rel(st)[BANNER]
    assert row["s"] == "90×22" and row["t"] == "changed"


def test_emulate_start_tells_the_replace_tabs(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs.emulate import EmulateTab
    told, posted = [], []

    class _Win:
        cb = {"on_stage_pending": lambda a, cancel_cb=None: (1, 1, [])}

        def folder_staged(self, folder):
            told.append(folder)

    tab = EmulateTab.__new__(EmulateTab)
    tab.window = _Win()
    tab._stopping = tab._stopped = tab._cancel_prepare = False
    tab._preparing = None
    monkeypatch.setattr(tab, "_post", lambda fn, *a: posted.append((fn, a)),
                        raising=False)
    monkeypatch.setattr(tab, "_log", lambda *a, **k: None, raising=False)
    assert tab._stage_pending("C:/proj") is True
    for fn, a in posted:
        if fn == tab.window.folder_staged:
            fn(*a)
    assert told == ["C:/proj"]


def test_reveal_image_slot_clears_hiding_filters(scanned):
    w, _assets, _reps, _st = scanned
    w.call("ui.set", "images", "search", "backglass")
    w.run(lambda: w.window.reveal_image_slot(SPRITE))
    st = w.state("images")
    assert st["search"] == "" and SPRITE in _view_rels(st)
    assert st["focus"]["id"] == SPRITE and st["preview"]["rel"] == SPRITE
    assert w.state("shell")["tab"] == "images"


def test_manufacturer_switch_is_a_clean_slate(scanned):
    w, assets, reps, _st = scanned
    w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
    w.call("images.choose", BANNER)
    w.call("ui.pick_manufacturer", "jjp")
    w.call("ui.pick_manufacturer", "stern")
    st = w.state("images")
    assert st["total"] == 0 and st["view"] == []
    assert w.window.pending_image_assignments(assets) is None
    assert st["preview"]["orig"] == ""


def test_open_in_default_app(scanned, monkeypatch):
    """PAD-208: the row menu hands the picture (and its pick) to the OS."""
    from pinball_decryptor.webui import shellx_common
    opened = []
    monkeypatch.setattr(shellx_common, "open_in_default_app",
                        lambda p: opened.append(p))
    w, assets, reps, _st = scanned
    labels = [it.get("label") for it in w.call("images.menu", PLAIN, [PLAIN])]
    assert "Open in default app" in labels
    assert "Open replacement in default app" not in labels
    assert w.call("images.act", "open_orig", PLAIN, [PLAIN]) is True
    assert os.path.normcase(opened[-1]) == os.path.normcase(
        os.path.join(assets, PLAIN))
    rep = os.path.join(reps, "SpaceGodzilla.png")
    w.answers = [rep]
    w.call("images.choose", PLAIN)
    labels = [it.get("label") for it in w.call("images.menu", PLAIN, [PLAIN])]
    assert "Open replacement in default app" in labels
    assert w.call("images.act", "open_rep", PLAIN, [PLAIN]) is True
    assert opened[-1] == rep
    # an opener that fails says so instead of doing nothing
    monkeypatch.setattr(shellx_common, "open_in_default_app",
                        lambda p: "no app for .png")
    assert w.call("images.act", "open_orig", PLAIN, [PLAIN]) is False
    assert w.asked[-1]["title"] == "Couldn't open file"
    assert "no app for .png" in w.asked[-1]["message"]
