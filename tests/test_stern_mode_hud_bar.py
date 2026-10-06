"""A mode HUD's pictures go on the card premultiplied, and the "bar" gauge (PAD-416).

David, on GODZILLA ANGRY's RAGE pips: "is the rage meter intentionally filling up with the colors outside the meter?
it looks like a glitch. also, can we make this meter look more stock like the meter in the top left? ... the whole
meter should be 100% towards the mode". The game draws its pictures premultiplied, so a soft edge of ours in plain
alpha came out as solid colour; and the meter is now one tube filled by slices, in the stock POWERUP meter's manner.
"""
import numpy as np

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
