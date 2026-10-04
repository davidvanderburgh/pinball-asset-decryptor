"""PAD-351 (DragonRR): a picture an earlier build kept at its own size, picked again, went
back to the game's size - Keep size starts unticked on every new pick, so the next build
squeezed it.  A new pick for such a picture now starts with Keep size ticked."""

import os

import pytest

from pinball_decryptor.core import staged_changes, staged_originals
from tests.test_webui_images import (BANNER, SPRITE, _by_rel, _project, _set_folder,
                                     _settled, _wait)
from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE", str(tmp_path / "tag_library.json"))


def _grown(assets, rel, size):
    """*rel* as a build with its pick kept at its own size leaves it, pick since gone."""
    assert staged_originals.snapshot(assets, rel, None)
    Image.new("RGBA", size, (90, 20, 200, 255)).save(os.path.join(assets, *rel.split("/")))


def _scan(w, assets):
    _set_folder(w, assets)
    w.call("images.scan")
    return _wait(w, _settled)


def test_a_new_pick_on_a_grown_picture_keeps_its_own_size(tmp_path):
    assets, reps = _project(tmp_path)
    _grown(assets, BANNER, (54, 26))                   # stock 40x20
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, assets)
        w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
        assert w.call("images.choose", BANNER) == BANNER
        assert _by_rel(w.state("images"))[BANNER]["k"] is True
        assert staged_changes.load(assets)["image_keep_size"] == [BANNER]
        assert w.window.pending_image_assignments(assets)[2] == frozenset({BANNER})
        # the user can still untick it
        assert w.call("images.set_keep", BANNER, False)
        assert staged_changes.load(assets)["image_keep_size"] == []


def test_a_new_pick_on_a_stock_size_picture_still_starts_unticked(tmp_path):
    assets, reps = _project(tmp_path)
    _grown(assets, SPRITE, (20, 10))                   # built before, at the stock size
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, assets)
        for rel in (BANNER, SPRITE):
            w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
            assert w.call("images.choose", rel) == rel
            assert _by_rel(w.state("images"))[rel]["k"] is False
        assert not staged_changes.load(assets).get("image_keep_size")
