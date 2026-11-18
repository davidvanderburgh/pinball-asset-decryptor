"""Settings that take effect on the next power-up are marked (Simon and David, 2026-11-18: "When we know an item will
require a reboot we should put an asterisk on it", and the Custom Code page's help: "Settings added by custom code.
Items with * take effect on next power up.")."""
import os

import pytest

from pinball_decryptor.plugins.stern import menu_settings as MS


def test_the_power_up_settings_are_image_set_and_edition():
    assert MS.POWER_UP == {MS.IMAGE_SET, MS.EDITION}


def test_the_caption_is_marked_where_it_has_room():
    assert MS.shown_caption(MS.IMAGE_SET) == "Image Set *"
    assert MS.shown_caption(MS.IMAGE_SET, 11) == "Image Set *"
    assert MS.shown_caption(MS.IMAGE_SET, 10) == "Image Set"     # no room for the mark: the plain caption
    assert MS.shown_caption(MS.EDITION, 40) == "Edition *"
    assert MS.shown_caption(MS.COOP_PLAY, 40) == "Co-op Play"     # takes effect at once: no mark


def test_the_page_help_wording_is_simons_and_fits_godzillas_room():
    assert MS.OWN_HELP_POWER_UP[0] == "Settings added by custom code. Items with * take effect on next power up."
    # Godzilla LE 1.16's line it replaces: "Wireless audio devices, such as headphones, can be connected to this game."
    assert len(MS.OWN_HELP_POWER_UP[0]) <= 74
    assert all(len(a) > len(b) for a, b in zip(MS.OWN_HELP_POWER_UP, MS.OWN_HELP_POWER_UP[1:]))


from tests.test_pad1382_more_settings import LE116, _program  # noqa: E402


@pytest.mark.skipif(not os.path.isfile(LE116), reason="the stock Godzilla LE 1.16 card is not here (PAD494_CARDS)")
def test_on_godzilla_the_page_help_says_what_the_asterisk_means():
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    t = AdjustmentTable(_program(LE116))
    texts = {s.rstrip(b"\x00").decode("latin1") for s in MS.own_page(t, starred=True).values()}
    assert MS.OWN_HELP_POWER_UP[0] in texts
    texts = {s.rstrip(b"\x00").decode("latin1") for s in MS.own_page(t, starred=False).values()}
    assert MS.OWN_HELP in texts
