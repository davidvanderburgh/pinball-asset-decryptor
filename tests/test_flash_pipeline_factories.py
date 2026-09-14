"""Every brand that can flash takes the call the app makes (PAD-138).

The menu-only write taught ONE flash factory (Stern's) a ``menu_only``
keyword, and ``App._start_flash_image`` handed it to every brand's - so a
JJP USB stick died with a TypeError before a byte moved, and CGC would have
too.  These pin the contract from the plugins' side: the whole-image call
is the six positional arguments and nothing else, and ``menu_only`` is taken
exactly where the plugin also names the phases of a menu-only write (which
is what the app and the flash dialog both look for).
"""
import inspect

import pytest

from pinball_decryptor.core import registry

registry.load_plugins()
FLASHERS = [m for m in registry.all_manufacturers()
            if m.capabilities.flash_image]


def test_the_brands_that_flash_are_all_here():
    assert {"stern", "jjp", "cgc"} <= {m.key for m in FLASHERS}


@pytest.mark.parametrize("mfr", FLASHERS, ids=lambda m: m.key)
def test_every_flasher_takes_the_whole_image_call(mfr):
    inspect.signature(mfr.make_flash_pipeline).bind(
        "x.img", "device", None, None, None, None)


@pytest.mark.parametrize("mfr", FLASHERS, ids=lambda m: m.key)
def test_menu_only_is_taken_exactly_where_its_phases_are_named(mfr):
    takes = "menu_only" in inspect.signature(
        mfr.make_flash_pipeline).parameters
    assert takes == bool(getattr(mfr, "menu_flash_phases", ()))
