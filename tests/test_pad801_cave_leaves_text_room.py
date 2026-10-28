"""PAD-801: the blip-free cave leaves the program-text segment its room.

Godzilla Pro 1.16's only text/data gap is 32 KB and a cave costs ~1 KB a
replaced sound, so 29 of them filled it: longer program text, MUSIC MODE and
the modes' own clips were all refused "no free address space between its text
and data segments".  The cave now goes above .bss (where every bigger cave
goes already) when the gap would keep less than the text's room.
"""
import os

import pytest

from pinball_decryptor.plugins.stern import engine as E

PAGE = E._EXT_PAGE
GAP = (0x6f4000, 0x6fc000)                  # Godzilla Pro 1.16's 32 KB gap
ABOVE = (0x84a000, 0x84a000 + E._EXT_ABOVE)
FN = 0x100000                               # in reach of both


def test_a_small_cave_still_goes_in_the_gap():
    pick = E._pick_region([GAP, ABOVE], 3 * PAGE, FN, gaps=[GAP])
    assert pick == GAP


def test_a_cave_that_would_crowd_the_text_out_goes_above_bss():
    for want in (5 * PAGE, 7 * PAGE, 8 * PAGE):
        assert E._pick_region([GAP, ABOVE], want, FN, gaps=[GAP]) == ABOVE


def test_without_the_text_preference_placement_is_as_before():
    assert E._pick_region([GAP, ABOVE], 8 * PAGE, FN) == GAP


def test_the_gap_is_still_used_when_nothing_else_is_in_reach():
    far = (FN + E._CAVE_MAX_BRANCH + 0x100000,
           FN + E._CAVE_MAX_BRANCH + 0x100000 + E._EXT_ABOVE)
    assert E._pick_region([GAP, far], 8 * PAGE, FN, gaps=[GAP]) == GAP


def test_a_small_gap_keeps_half_for_the_text():
    assert E._text_room(32 << 10) == 16 << 10
    assert E._text_room(64 << 10) == E._TEXT_ROOM
    assert E._text_room(12 << 10) == PAGE      # half, in whole pages
    assert E._text_room(16 << 10) == 8 << 10
    assert E._text_room(6 << 10) == PAGE


# ---- the real program (David's machine) ------------------------------------------
CARD = os.path.join(os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2"),
                    "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")


def _program():
    if not os.path.isfile(CARD):
        pytest.skip("no %s on this machine" % os.path.basename(CARD))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(CARD)
    with CardImage(CARD) as img:
        return bytearray(img.preview(part, "/%s/game" % game, cap=256 << 20))


@pytest.mark.parametrize("sounds, in_gap", [(10, True), (29, False), (40, False)])
def test_godzilla_pro_keeps_room_for_longer_text_whatever_the_cave(sounds, in_gap):
    raw = _program()
    assert E._text_reloc_plan(raw)[0]["capacity"] == 32 << 10
    fn = E._locate_window_read_fn(raw)
    va, _off, _gap = E._append_cave_segment(raw, 1048 * sounds + 256, fn)
    assert (GAP[0] <= va < GAP[1]) == in_gap
    reloc, why = E._text_reloc_plan(raw)
    assert reloc is not None, why
    assert reloc["capacity"] >= E._TEXT_ROOM
