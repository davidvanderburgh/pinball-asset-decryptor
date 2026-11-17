"""PAD-1360: the Spike 3 rig's Guided Setup detector must not take a settings page for it.

``s3press.autoguide`` walks Guided Setup (BACK, then SELECT on Save & Exit) whenever
``is_guided_setup`` sees it on the newest frame. That test used to tell Guided Setup from the
service menu by the white values in its right-hand column, but the menu's SETTINGS pages (Quick
Adjustments, Coil Settings, LCD/Lamp...) show white values too: autoguide pressed BACK about two
seconds after SELECT opened one, so on the rig no setting page ever stayed open (proven under
gdb: the menu's own handler got a BACK nobody pressed, from the button dispatcher). Now only the
page's own title counts, by its fingerprint.

The frames here are synthetic (no game art): a title drawn to the stored fingerprint, a cyan row,
white values.
"""
import os
import sys

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu"))
import s3press as P  # noqa: E402


def frame(path, fp=P.GUIDED_TITLE, x=P.GUIDED_TITLE_X, cyan=True, values=True):
    """A 1920x1080 menu-like frame: dark red, a white title whose slices are filled to FP
    (hundredths of the 160-row title band) between columns X, a cyan highlighted row, white
    values in the right-hand column."""
    a = np.zeros((1080, 1920, 3), np.uint8)
    a[:, :] = (90, 0, 0)
    if fp:
        x0, x1 = x
        k = x1 - x0 + 1
        n = len(fp)
        for i, g in enumerate(fp):
            rows = int(round(g / 100.0 * 160))
            for c in range(x0 + i * k // n, x0 + (i + 1) * k // n):
                a[40:40 + rows, c] = 255
        a[40:200, x0] = 255          # the title's ends are white columns, as letters' are
        a[40:200, x1] = 255
    if cyan:
        a[250:290, 20:400] = (0, 230, 230)
    if values:
        a[260:600, 850:1150] = 255
    Image.fromarray(a).save(path)
    return str(path)


def test_guided_setup_is_seen(tmp_path):
    assert P.is_guided_setup(frame(tmp_path / "gs.png"))


def test_guided_setup_needs_a_highlighted_row(tmp_path):
    assert not P.is_guided_setup(frame(tmp_path / "gs.png", cyan=False))


def test_a_settings_page_is_not_guided_setup(tmp_path):
    """The PAD-1360 case: title, cyan row and white values, as Coil Settings shows them, but its
    own title (Coil Settings' extent, another fingerprint)."""
    other = [(g * 7 + 13) % 50 for g in P.GUIDED_TITLE]
    f = frame(tmp_path / "coil.png", fp=other, x=(692, 1227))
    assert not P.is_guided_setup(f)


def test_a_title_of_the_same_width_but_other_letters_is_not_guided_setup(tmp_path):
    other = list(reversed(P.GUIDED_TITLE))
    assert not P.is_guided_setup(frame(tmp_path / "same_width.png", fp=other))


def test_no_title_no_guided_setup(tmp_path):
    f = frame(tmp_path / "attract.png", fp=None)
    a = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
    assert P.title_fingerprint(a) is None
    assert not P.is_guided_setup(f)


def test_the_fingerprint_reads_back(tmp_path):
    f = frame(tmp_path / "gs.png")
    a = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
    x0, x1, fp = P.title_fingerprint(a)
    assert (x0, x1) == P.GUIDED_TITLE_X
    assert sum(abs(v - g / 100.0) for v, g in zip(fp, P.GUIDED_TITLE)) / len(fp) < 0.01
