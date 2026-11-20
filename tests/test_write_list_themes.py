"""The Write tab's change list names the themes' changes (Simon, 2026-11-20: "theme changes in the Write tab's change
list"): a picture chosen for a theme, and a theme's own color profile, are each a pending row, and the scan's
fingerprint follows them so the list refreshes."""
import types

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.plugins.stern import scene_variants as SV
from pinball_decryptor.webui import write_scan as W

from tests.test_image_sets_pictures import REL, _png, _project, _scene

pytest.importorskip("PIL.Image")

TREL = "images/" + REL


class _Stern:
    key = "stern"


def _themed(tmp_path):
    _data, off = _scene()
    p = _project(tmp_path, off)
    SV.set_themes_on(p, True)
    assert SV.add_set(p, "LIGHT") == 2
    assert SV.add_set(p, "NIGHT") == 3
    return p


def test_no_themes_no_rows(tmp_path):
    _data, off = _scene()
    p = _project(tmp_path, off)
    assert W.theme_rows(_Stern(), p) == []


def test_themes_with_nothing_changed_no_rows(tmp_path):
    p = _themed(tmp_path)
    assert W.theme_rows(_Stern(), p) == []


def test_a_picked_picture_is_a_row(tmp_path):
    p = _themed(tmp_path)
    SV.set_picture(p, 2, TREL, _png(tmp_path / "LIGHT-CARD.png", (200, 200, 200, 255)))
    rows = W.theme_rows(_Stern(), p)
    assert len(rows) == 1
    label, kind, status, state = rows[0]
    assert label.startswith("theme 2 (LIGHT): " + TREL)
    assert "LIGHT-CARD.png" in label
    assert (kind, status, state) == ("png", W.PENDING_THEMES, "pending")


def test_an_own_color_profile_is_a_row(tmp_path):
    p = _themed(tmp_path)
    cp.store_own_profile(p, "images", SV.theme_key(3, TREL), cp.Profile(name="Red", gain=(1.0, 0.3, 0.3)))
    cp.set_asset_slot(p, "images", SV.theme_key(3, TREL), True)
    rows = W.theme_rows(_Stern(), p)
    assert len(rows) == 1 and rows[0][0].startswith("theme 3 (NIGHT): " + TREL)
    assert "own color profile" in rows[0][0]


def test_picked_and_profiled_is_one_row(tmp_path):
    p = _themed(tmp_path)
    SV.set_picture(p, 2, TREL, _png(tmp_path / "LIGHT-CARD.png", (200, 200, 200, 255)))
    cp.set_asset_slot(p, "images", SV.theme_key(2, TREL), True)
    rows = W.theme_rows(_Stern(), p)
    assert len(rows) == 1
    assert "LIGHT-CARD.png" in rows[0][0] and "own color profile" in rows[0][0]


def test_not_stern_no_rows(tmp_path):
    p = _themed(tmp_path)
    SV.set_picture(p, 2, TREL, _png(tmp_path / "LIGHT-CARD.png", (200, 200, 200, 255)))

    class _Other:
        key = "jjp"
    assert W.theme_rows(_Other(), p) == []
    assert W.theme_rows(None, p) == []


def test_pending_rows_include_them(tmp_path, manufacturers_by_key):
    p = _themed(tmp_path)
    SV.set_picture(p, 2, TREL, _png(tmp_path / "LIGHT-CARD.png", (200, 200, 200, 255)))
    rows = W.pending_rows(types.SimpleNamespace(), manufacturers_by_key["stern"], p, grow_on=True, direct=False)
    assert [r[0] for r in rows if r[2] == W.PENDING_THEMES] == [r[0] for r in W.theme_rows(_Stern(), p)]


def test_fingerprint_follows_a_pick(tmp_path):
    p = _themed(tmp_path)
    window = types.SimpleNamespace()
    before = W.fingerprint(window, p, 0, True)
    SV.set_picture(p, 2, TREL, _png(tmp_path / "LIGHT-CARD.png", (200, 200, 200, 255)))
    after = W.fingerprint(window, p, 0, True)
    assert before != after
    assert W.fingerprint(window, p, 0, True) == after
