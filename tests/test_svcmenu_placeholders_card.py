"""Placeholder rows (tests/test_svcmenu_placeholders.py) planned on a real Godzilla 1.16 program: music mode, edition
and image set as NULL1/NULL2 beside co-op play and handicap - five settings on the game's three spare rows, so some
share MORE SETTINGS, as a Write plans them."""
import os

import pytest

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


def test_placeholders_plan_on_godzilla_116():
    from pinball_decryptor.plugins.stern import coop_play as CP, handicap as HC
    from pinball_decryptor.plugins.stern import menu_settings as MS
    from pinball_decryptor.plugins.stern import service_menu as SM
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    names = list(SM.PLACEHOLDER_NAMES)
    rows = [(k, len(names), names) for k in SM.OFF_KEYS]
    rows += [("coop_play", CP.MENU_VALUES, (), {"default": 1, "help_text": CP.MENU_HELP, "from_zero": True}),
             ("handicap", HC.MENU_VALUES, (), {"default": 1, "help_text": HC.MENU_HELP, "onoff": True})]
    t = AdjustmentTable(_program(LE116))
    settings, _writes, _cat, refused = MS.plan_many(t, rows)
    assert not refused, refused
    keys = {s.key for s in settings}
    assert {r[0] for r in rows} <= keys
    assert {"more_select", "more_value"} <= keys        # five settings, three spare rows: some share MORE SETTINGS
    for s in settings:
        if s.key in SM.OFF_KEYS:
            assert "NULL1" in s.help and "NULL2" in s.help, s.help
    # the menu preview lays them out the same way
    menu = SM.pages(_program(LE116), rows)
    assert menu["pages"]
