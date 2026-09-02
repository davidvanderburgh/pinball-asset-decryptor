"""The Spike 1 rig's card reader (tools/spike1_emu/build_rootfs.py).

`transformers_pin-1.0.18` IS a Spike 1 card — Transformers The Pin (Stern,
2012), one of the first SPIKE machines, three years before SPIKE reached the
coin-op line, with two 8-digit LED displays instead of a DMD.  It is the
EARLIEST firmware era, and that era is everything the rig touches: the game and
its plain WAV sounds live in `/usr/local/games/<title>/` rather than
`/games/<TITLE>/` with an `image.bin`.  The rig answered "is this a Spike 1
card?"; it now names the era instead (PAD-101).

Note what does NOT separate the two: `/etc/version 201006031147`, glibc 2.6.1
and kernel 2.6.30 are on the GOT LE and Whoa Nellie cards too — the base rootfs
is shared across Spike 1, so it says nothing about a card's age.
"""

import os
import sys

_RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike1_emu")
if _RIG not in sys.path:
    sys.path.insert(0, _RIG)

import build_rootfs  # noqa: E402


class _FakeRootfs:
    """Just enough Ext4Reader for early_spike1_game_dir: a path list."""

    def __init__(self, paths):
        self._paths = paths

    def iter_regular_files(self, max_depth=9, min_size=1, root_ino=2):
        for p in self._paths:
            yield p, 12, {"size": 4096}


def test_an_early_spike1_card_is_recognised_by_its_game_dir():
    rootfs = _FakeRootfs(["/bin/busybox", "/usr/local/games/tf-elg/game",
                          "/usr/local/games/tf-elg/gamer",
                          "/usr/local/games/tf-elg/sounds/BG_Shockwave_loop.wav",
                          "/usr/local/games/alphanumeric-1_0_4.hex"])
    assert build_rootfs.early_spike1_game_dir(rootfs) == "tf-elg"


def test_a_dmd_generation_rootfs_has_no_such_game_dir():
    rootfs = _FakeRootfs(["/bin/busybox", "/usr/local/spike/display.hex",
                          "/games/GOT_LE/game"])
    assert build_rootfs.early_spike1_game_dir(rootfs) is None


def test_no_rootfs_at_all_is_not_an_early_card():
    assert build_rootfs.early_spike1_game_dir(None) is None
