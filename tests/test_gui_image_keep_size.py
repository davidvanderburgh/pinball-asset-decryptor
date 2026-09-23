"""PAD-154: "Keep this picture's own size" under the Replace Images preview.

A longer kaiju name squeezed into the stock banner was unreadable; a scene
picture (Source "Radium", not a font atlas) with a replacement assigned now
offers to keep the replacement's own size, spells out both sizes, and the
choice reaches the build through the pending tuple and the sidecar.

Driven through the web UI's Replace Images service (webui/tabs/images.py):
the preview's tick is ``preview["keep"]``, the list's Keep size cell is a
row's ``k`` (None: no box, False: ☐, True: ☑)."""
import os
import time

import pytest

from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")

from pinball_decryptor.core import staged_changes                   # noqa: E402

BANNER = "images/scene_textures/radimg_unnamed_instance_24_40x20_45402198.png"
ATLAS = "images/scene_textures/radimg_GameFont_Primary_64x64_3ce3aba2.png"
PLAIN = "images/backglass.png"


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    """Never touch the real per-card name library under %APPDATA%."""
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "tag_library.json"))


def _project(tmp_path, banner=True):
    assets = tmp_path / "gz"
    tex = assets / "images" / "scene_textures"
    tex.mkdir(parents=True)
    if banner:
        Image.new("RGBA", (40, 20), (0, 0, 0, 255)).save(assets / BANNER)
    Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(assets / ATLAS)
    Image.new("RGBA", (64, 32), (0, 0, 0, 255)).save(assets / PLAIN)
    (tex / "glyph_images.txt").write_text(
        "# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n"
        "scene_textures/glyphs/radimg_GameFont_Primary_64x64_3ce3aba2/"
        "U+0041_A.png\tscene_textures/radimg_GameFont_Primary_64x64_3ce3aba2"
        ".png\t0x0041\t0\t0\t8\t8\tGameFont\n", encoding="utf-8")
    rep = tmp_path / "SpaceGodzilla.png"
    Image.new("RGBA", (90, 22), (255, 255, 255, 255)).save(rep)
    return str(assets), str(rep)


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


def _scan(w, assets):
    def _do():
        try:
            w.window.write_assets_var.set(assets)
        except Exception:                                # noqa: BLE001
            pass
    w.run(_do)
    w.call("images.scan")
    end = time.time() + 15
    while time.time() < end:
        w.drain()
        if _settled(w.state("images")):
            return w.window.service("images")
        time.sleep(0.05)
    raise AssertionError("scan did not settle")


@pytest.fixture
def window(tmp_path):
    assets, rep = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, assets)
        yield w, svc, assets, rep


def _choose(w, rel, rep):
    w.answers.append(rep)
    assert w.call("images.choose", rel) == rel


def _keep(w):
    return w.state("images")["preview"]["keep"]


def _keep_cells(w):
    rows = _by_rel(w.state("images"))
    return {rel: rows[rel]["k"] for rel in (BANNER, ATLAS, PLAIN)}


def test_the_tick_appears_for_a_scene_picture_and_reaches_the_build(window):
    w, svc, assets, rep = window
    w.call("images.select", BANNER)
    assert _keep(w) is None                    # nothing assigned yet
    _choose(w, BANNER, rep)
    keep = _keep(w)
    assert keep is not None
    assert keep["on"] is False
    assert svc.image_keep_size_var.get() is False
    assert "90×22" in keep["text"]
    assert "squeezed" in keep["text"]
    assert w.window.pending_image_assignments(assets)[2] == frozenset()

    assert w.call("images.set_keep", BANNER, True) is not False
    assert svc._keep_size == {BANNER}
    assert _keep(w)["text"].startswith("Kept at 90×22")
    assert w.window.pending_image_assignments(assets)[2] == \
        frozenset({BANNER})
    assert staged_changes.load(assets)["image_keep_size"] == [BANNER]

    w.call("images.set_keep", BANNER, False)
    assert w.window.pending_image_assignments(assets)[2] == frozenset()
    assert staged_changes.load(assets)["image_keep_size"] == []


@pytest.mark.parametrize("rel", [ATLAS, PLAIN])
def test_no_tick_where_the_size_cannot_change(window, rel):
    w, svc, assets, rep = window
    w.call("images.select", rel)
    _choose(w, rel, rep)
    assert _keep(w) is None
    assert w.call("images.set_keep", rel, True) is False
    assert svc._keep_size == set()


def test_the_keep_size_column_shows_every_pick(window):
    # PAD-158: the tick under the preview only speaks for the selected row;
    # the list has to say it for every pick ("Perhaps make it a little more
    # obvious are incorporate into the window as another column?").
    w, svc, assets, rep = window
    from pinball_decryptor.webui.tabs import images as images_tab
    cols = [c for c, _t, _d in images_tab.SORT_CFG]
    assert cols.index("keep") == len(cols) - 2 and cols[-1] == "rep"
    assert w.state("images")["cols"]["keep"] is True
    assert _keep_cells(w) == {BANNER: None, ATLAS: None, PLAIN: None}

    for rel in (BANNER, ATLAS, PLAIN):
        _choose(w, rel, rep)
    # A tick box only where the size can change; the Replacement cell still
    # names the pick.
    assert _keep_cells(w) == {BANNER: False, ATLAS: None, PLAIN: None}
    assert _by_rel(w.state("images"))[BANNER]["p"] == "SpaceGodzilla.png"

    # The preview's tick and the column are the same flag, both ways.
    w.call("images.select", BANNER)
    w.call("images.set_keep", BANNER, True)
    assert _keep_cells(w)[BANNER] is True
    assert _keep(w)["on"] is True
    w.call("images.set_keep", BANNER, False)
    assert _keep_cells(w)[BANNER] is False

    # The metadata pass rebuilds the row and keeps the cell.
    w.call("images.set_keep", BANNER, True)

    def _meta():
        i = svc._apply_image_meta(svc._scan_id, BANNER,
                                  svc._by_rel[BANNER].info)
        svc._publish_chunks({i // images_tab.CHUNK})
    w.run(_meta)
    assert _keep_cells(w)[BANNER] is True
    assert _by_rel(w.state("images"))[BANNER]["p"] == "SpaceGodzilla.png"

    # Sorting on it puts the kept pick first.
    w.call("images.sort", "keep")
    assert w.state("images")["sort"] == {"key": "keep", "desc": True}
    assert _view_rels(w.state("images"))[0] == BANNER


def test_clicking_the_box_flips_it(window):
    """The page's Keep size box calls ``images.set_keep`` with the flipped
    value; the pick itself is untouched."""
    w, svc, assets, rep = window
    _choose(w, BANNER, rep)
    _choose(w, ATLAS, rep)
    n_asked = len(w.asked)

    w.call("images.set_keep", BANNER, not _keep_cells(w)[BANNER])
    assert svc._keep_size == {BANNER}
    assert _keep_cells(w)[BANNER] is True
    assert staged_changes.load(assets)["image_keep_size"] == [BANNER]
    w.call("images.set_keep", BANNER, not _keep_cells(w)[BANNER])
    assert svc._keep_size == set()
    # An empty cell is not a box: nothing to flip on a font atlas.
    assert _keep_cells(w)[ATLAS] is None
    assert w.call("images.set_keep", ATLAS, True) is False
    assert svc._keep_size == set()
    assert len(w.asked) == n_asked             # no picker opened


def test_no_column_without_a_picture_that_can_keep_its_size(tmp_path):
    assets, rep = _project(tmp_path, banner=False)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, assets)
        assert w.state("images")["cols"]["keep"] is False


def test_a_cleared_pick_takes_its_flag_out_of_the_sidecar(window):
    w, svc, assets, rep = window
    _choose(w, BANNER, rep)
    w.call("images.select", BANNER)
    w.call("images.set_keep", BANNER, True)
    w.call("images.clear_one", BANNER)
    assert BANNER not in svc._assignments
    assert staged_changes.load(assets)["image_keep_size"] == []
    assert w.window.pending_image_assignments(assets) is None
    assert os.path.isfile(os.path.join(assets, BANNER))


def test_the_original_size_is_the_snapshots_once_a_pick_is_applied(window):
    # PAD-179: after a run applied a pick kept at its own size, the slot's
    # file IS that pick. The note called it the original ("Same size as the
    # original (90×22)") while the build fits to the real one.
    from pinball_decryptor.core import staged_originals
    w, svc, assets, rep = window
    assert staged_originals.snapshot(assets, BANNER, None)
    Image.new("RGBA", (90, 22), (255, 255, 255, 255)).save(
        os.path.join(assets, BANNER))
    _choose(w, BANNER, rep)
    w.call("images.select", BANNER)
    keep = _keep(w)
    assert keep is not None
    assert "the original 40×20" in keep["text"]
    assert "squeezed" in keep["text"]
