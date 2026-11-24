"""PAD-1549: where Sonic's ring displays are.  Edit pixels shows, beside a ring
picture, the game's own playfield picture with the five ring displays marked
on it; the positions are PAD's (the game program that places them is locked
to Sonic's own key), the picture is the project's."""

import time

import pytest

from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")

FRAME = "graphics/Mini LED/Bad_Crabby/Loop/Crab00.png"
OTHER = "graphics/Attract/logo.png"


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE", str(tmp_path / "tag_library.json"))


def _project(tmp_path, photo):
    from pinball_decryptor.webui.tabs.pixel_edit import RING_MAP_PHOTO
    assets = tmp_path / "sonic"
    for rel in (FRAME, OTHER, RING_MAP_PHOTO):
        (assets / rel).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (14, 14), (220, 30, 60, 255)).save(assets / FRAME)
    Image.new("RGBA", (20, 10), (1, 2, 3, 255)).save(assets / OTHER)
    if photo:
        Image.new("RGB", (341, 768), (40, 90, 40)).save(assets / RING_MAP_PHOTO)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(assets))
    return str(assets)


def _rows(st):
    out = []
    for k in range(st.get("nchunks") or 0):
        out.extend(st.get("rows_%d" % k) or [])
    return out


def _open(tmp_path, mfr, photo, rel):
    assets = _project(tmp_path, photo)
    with web_app(tmp_path, mfr=mfr) as w:
        def _do():
            try:
                w.window.write_assets_var.set(assets)
            except Exception:                            # noqa: BLE001
                pass
        w.run(_do)
        w.call("images.scan")
        end = time.time() + 20
        while time.time() < end:
            w.drain()
            st = w.state("images")
            if (not st.get("scanning") and st.get("total") and _rows(st)
                    and "still checking" not in (st.get("status") or "")):
                break
            time.sleep(0.05)
        return assets, w.call("images.pixel_open", rel)


def test_the_five_rings_sit_on_the_playfield_picture():
    from pinball_decryptor.webui.tabs.pixel_edit import SONIC_RINGS
    assert [r["n"] for r in SONIC_RINGS] == [1, 2, 3, 4, 5]
    assert len({r["name"] for r in SONIC_RINGS}) == 5
    for r in SONIC_RINGS:
        assert 0.05 < r["x"] < 0.95 and 0.05 < r["y"] < 0.5, r   # all five are on the upper half
        assert r["where"]
    left = [r for r in SONIC_RINGS if r["x"] < 0.5]
    assert {r["name"] for r in left} == {"Top left", "Left ramp", "Left orbit"}


def test_a_ring_picture_opens_with_the_ring_map(tmp_path):
    from pinball_decryptor.webui.tabs.pixel_edit import RING_MAP_PHOTO, SONIC_RINGS
    import os
    assets, sp = _open(tmp_path, "jjp", True, FRAME)
    assert sp["ring"] is True
    m = sp["ringmap"]
    assert os.path.normcase(os.path.abspath(m["photo"])) == os.path.normcase(
        os.path.abspath(os.path.join(assets, *RING_MAP_PHOTO.split("/"))))
    assert [(r["n"], r["x"], r["y"]) for r in m["rings"]] == [(r["n"], r["x"], r["y"]) for r in SONIC_RINGS]


def test_no_playfield_picture_means_no_map(tmp_path):
    _assets, sp = _open(tmp_path, "jjp", False, FRAME)
    assert sp["ring"] is True and sp["ringmap"] is None


def test_other_pictures_and_makers_get_no_map(tmp_path):
    _assets, sp = _open(tmp_path, "jjp", True, OTHER)
    assert sp["ring"] is False and sp["ringmap"] is None
    (tmp_path / "s").mkdir()
    _assets, sp = _open(tmp_path / "s", "stern", True, FRAME)
    assert sp["ring"] is False and sp["ringmap"] is None
