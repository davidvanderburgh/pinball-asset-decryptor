"""A mode HUD's pictures go on the card premultiplied, and the "bar" gauge (PAD-416).

David, on GODZILLA ANGRY's RAGE pips: "is the rage meter intentionally filling up with the colors outside the meter?
it looks like a glitch. also, can we make this meter look more stock like the meter in the top left? ... the whole
meter should be 100% towards the mode". The game draws its pictures premultiplied, so a soft edge of ours in plain
alpha came out as solid colour; and the meter is now one tube filled by slices, in the stock POWERUP meter's manner.
"""
import os

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import mode_hud as H


def test_premultiplied_and_back():
    a = np.array([[[255, 255, 255, 70], [200, 100, 0, 255], [10, 20, 30, 0]]], dtype=np.uint8)
    p = H.premultiplied(a)
    assert p[0, 0].tolist() == [70, 70, 70, 70]                  # a faint white is faint on the card, not white
    assert p[0, 1].tolist() == [200, 100, 0, 255]                # opaque: unchanged
    assert p[0, 2].tolist() == [0, 0, 0, 0]
    back = H.straight_alpha(p)
    assert back[0, 0].tolist() == [255, 255, 255, 70] and back[0, 1].tolist() == [200, 100, 0, 255]


def test_no_channel_above_its_alpha_once_premultiplied():
    """As the game's own textures are (the BATTLE badge, its font pages)."""
    for arr in (H.bar_glass(), H.bar_frame(H.icon("rage")), H.gauge_pips("segment", 3, [(255, 120, 0)])[0][0]):
        p = H.premultiplied(arr)
        assert (p[..., :3].max(axis=-1) <= p[..., 3]).all()


def test_the_bar_frame_glass_and_slices_fit_together():
    frame, glass = H.bar_frame(H.icon("rage")), H.bar_glass()
    assert frame.shape == glass.shape == (H.BAR_H, H.BAR_W, 4)
    x0, y0, x1, y1 = H.BAR_TUBE
    slices = H.bar_slices([(150, 0, 0), (255, 170, 20)], 40)
    assert len(slices) == 40
    assert [x for _a, x in slices] == sorted(x for _a, x in slices) and slices[0][1] == 0
    assert all(a.shape[0] % 4 == 0 and a.shape[1] % 4 == 0 for a, _x in slices)    # BC3 blocks
    covered = sum(min(a.shape[1], (slices[i + 1][1] if i + 1 < 40 else x1 - x0) - x) for i, (a, x) in enumerate(slices))
    assert covered == x1 - x0                                     # the slices fill the tube, end to end
    # the tube's inside is dark on the frame: an empty meter reads empty
    inside = frame[y0 + 8:y1 - 8, x0 + 20:x1 - 20, :3]
    assert inside.mean() < 40
    # the glass over it only shines: nothing opaque inside the tube but the rings
    assert (glass[y0 + 12:y1 - 12, x0 + 10:x0 + 30, 3] < 80).all()


def test_the_liquid_runs_through_its_colours_from_the_empty_end():
    liquid = H.bar_liquid([(150, 0, 0), (255, 170, 20)])
    mid = liquid.shape[0] // 2
    left, right = liquid[mid, 4, :3].astype(int), liquid[mid, -5, :3].astype(int)
    assert left[0] < right[0] and left[1] < right[1]               # dark red to orange


# ---- PAD-690: the progress panel - a badge for every mode, each its own icon, scaled to fit -----------------------
def test_every_mode_of_a_pack_wears_its_own_badge_icon():
    huds = [("a", {"timer": {"label": "A", "icon": "claw"}}), ("b", {"timer": {"label": "B", "icon": "claw"}}),
            ("c", {"badge": {"label": "C", "icon": "rose"}}), ("d", {}),
            ("e", {"timer": {"label": "E", "icon": "claw"}, "icon_file": "e/badge.png"})]
    out = dict(H.unique_icons(huds))
    got = {slug: spec.get("badge_icon") for slug, spec in out.items()}
    assert got == {"a": "claw", "b": "xilien", "c": "rose", "d": "radiation", "e": None}   # e wears its picture
    assert out["e"]["icon_file"] == "e/badge.png"


def test_a_modes_own_picture_is_its_badge_icon(tmp_path):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((10, 5, 110, 55), fill=(200, 30, 30, 255))       # a wide shape on a clear ground
    im.save(tmp_path / "badge.png")
    a = H.badge_icon({"icon_file": str(tmp_path / "badge.png")}, {})
    assert a.shape == (44, 44) and a.max() == 255
    assert a[0].max() == 0 and a[22].max() == 255                               # fitted on its longer side, centred
    assert (H.badge_icon({}, {"icon": "rose"}) == H.icon("rose")).all()
    with pytest.raises(H.HudError):
        H.badge_icon({"icon_file": str(tmp_path / "none.png")}, {})


def test_every_icon_a_badge_may_wear_is_drawn_and_none_alike():
    seen = {}
    for kind in H.ICONS:
        a = H.icon(kind)
        assert a.shape == (44, 44) and a.max() == 255, kind
        assert a.tobytes() not in seen, (kind, seen.get(a.tobytes()))
        seen[a.tobytes()] = kind


def test_the_panel_fits_every_mode_between_the_rage_meter_and_the_score_panels():
    for n in (1, 4, H.PROGRESS_SLOTS):
        s, x, ys = H.progress_layout(n, 210)
        assert len(ys) == n and 0 < s <= 1.0
        assert abs(ys[0] + 267.0 * s - H.PROGRESS_Y) < 0.01                             # the first badge's top
        assert ys[-1] + 267.0 * s + H.PROGRESS_DY * s <= H.PROGRESS_BOTTOM + 0.01        # the last one's bottom
        assert x + s * (210 - 21.0) <= H.GLASS_W                                         # on the glass
    assert H.progress_layout(H.PROGRESS_SLOTS, 210)[0] < H.progress_layout(4, 210)[0]
    assert H.progress_layout(H.PROGRESS_SLOTS, 210)[0] >= 0.6                         # David: legible, not a third


def test_the_build_hands_a_modes_badge_picture_to_its_hud(tmp_path):
    from types import SimpleNamespace
    from pinball_decryptor.plugins.stern import mode_assets as MA, mode_project as MP
    project = str(tmp_path)
    for slug in ("one", "two"):
        os.makedirs(MP.mode_folder(project, slug))
    open(os.path.join(MP.mode_folder(project, "two"), MA.BADGE_ICON_FILE), "wb").close()
    prof = SimpleNamespace(can=lambda what: True, lcd=lambda what: "x/" + MA.HUD_SCENE)
    code = [("one", SimpleNamespace(hud={"title": "ONE"})), ("two", SimpleNamespace(hud={"title": "TWO"})),
            ("off", SimpleNamespace(hud={}))]
    huds = dict(MA._code_huds(project, code, prof, b"font"))
    assert set(huds) == {"one", "two"} and "icon_file" not in huds["one"]
    assert huds["two"]["icon_file"] == os.path.join(MP.mode_folder(project, "two"), MA.BADGE_ICON_FILE)
