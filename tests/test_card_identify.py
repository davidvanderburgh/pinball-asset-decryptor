"""PAD-191 — "what game is this card?" answered without copying the card.

Ralf keeps several Spike SD cards on his desk and wanted to sort them out:
"i have several SD Card on my desk and like to simply check, what game it
belongs to... can you help without copying it extra to the harddisk?"  Before
this, every answer the app had went through a FILE: detection read the vendor
filename, the Image Info window refused anything that wasn't ``os.path.isfile``,
and the only way to get a card onto a filename was to image it — the 8-32 GB
copy he was asking to avoid.

The card already names itself: every Spike 2 path starts with a folder named
for the model (``godzilla_pro``), and the build lives in the card's own
``/spk/index/*.sidx``.  So the probe is the one that was already counting the
images on a multi-boot card — a handful of directory reads, nothing extracted
— pointed at the device instead of a file.

These run over the in-memory fake ext4 the Partition Explorer tests use, with
``is_device_path`` monkeypatched onto a synthetic card the way
``test_multiboot_source_note`` does it: the real ``RawDeviceFile`` opens the
fixture (it probes a regular file's sector as 512), so the device path under
test is the real one.
"""

import pytest

from pinball_decryptor.core import image_info, rawdevice
from pinball_decryptor.core.registry import Capabilities, Manufacturer
from pinball_decryptor.plugins.stern import formats, multiimage
from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
from tests._ext4_fake import make_mbr
from tests.test_multiboot_source_note import (BOOT, EBR_CHAIN, EMPTY_TREE,
                                              EXTENDED, GAME_TREE, GAMES, P5,
                                              P6, P7, ROOTFS, ROOTFS_TREE,
                                              _tree, install_readers,
                                              write_card)

#: The Spike 1 partition signature (formats.is_spike1_card_parts): FAT12 boot
#: at LBA 35, the raw STRN kernel partition at 7000, the rootfs at 14000.
SPIKE1_PARTS = [(0x01, 35, 6000), (0xDA, 7000, 7000), (0x83, 14000, 8192)]


def _as_device(monkeypatch, path):
    """Make *path* answer to ``is_device_path`` — i.e. be the card in the
    reader rather than a file on the hard disk."""
    monkeypatch.setattr(rawdevice, "is_device_path", lambda p: p == path)
    multiimage._CACHE.clear()


def _card_in_a_reader(tmp_path, monkeypatch, name="PHYSICALDRIVE9",
                      primaries=(BOOT, ROOTFS, GAMES), chain=(),
                      readers=None):
    """A synthetic Spike 2 card that the app will treat as a raw device.

    Deliberately extensionless: a device has no ``.raw`` to take a filename
    gate, a title or a version from, which is the whole difference this ticket
    turns on.
    """
    card = write_card(tmp_path / name, list(primaries), chain)
    _as_device(monkeypatch, card)
    install_readers(monkeypatch,
                    readers or {24576: ROOTFS_TREE, 26624: GAME_TREE})
    return card


# ---------------------------------------------------------------------------
# naming the game on the card
# ---------------------------------------------------------------------------

def test_a_card_in_the_reader_names_its_game(tmp_path, monkeypatch):
    card = _card_in_a_reader(tmp_path, monkeypatch)
    assert SternManufacturer().identify_card(card) == "Godzilla Pro"


def test_a_multi_boot_card_says_so_and_how_many_games(tmp_path, monkeypatch):
    """The first game is the one everything else in the app works on, so it is
    the one named — but a card that boots into a menu must not be reported as
    an ordinary Godzilla card (PAD-122)."""
    card = _card_in_a_reader(
        tmp_path, monkeypatch, primaries=(BOOT, ROOTFS, GAMES, EXTENDED),
        chain=EBR_CHAIN,
        readers={24576: ROOTFS_TREE, 26624: GAME_TREE, P5: EMPTY_TREE,
                 P6: EMPTY_TREE, P7: _tree("jaws_pro")})
    assert SternManufacturer().identify_card(card) == \
        "Godzilla Pro  (multi-boot card, 2 games)"


def test_a_spike1_card_is_named_by_its_era(tmp_path, monkeypatch):
    """A Spike 1 card has no ``spk`` + game-folder tree to read a title out of.
    Saying which generation it is beats reporting the card as unreadable."""
    card = write_card(tmp_path / "PHYSICALDRIVE8", SPIKE1_PARTS)
    _as_device(monkeypatch, card)
    assert SternManufacturer().identify_card(card) == "Stern Spike 1 card"


def test_something_that_is_not_a_stern_card_says_nothing(tmp_path,
                                                         monkeypatch):
    """The user's backup drive is in the same dropdown; claiming it would be
    worse than an empty answer."""
    other = tmp_path / "PHYSICALDRIVE7"
    other.write_bytes(make_mbr([(0x07, 2048, 4096)]))
    _as_device(monkeypatch, str(other))
    assert SternManufacturer().identify_card(str(other)) == ""


def test_identify_card_never_raises_at_the_caller(tmp_path, monkeypatch):
    """It runs on a worker behind a dropdown selection — a card yanked
    mid-probe must leave the row empty, not a traceback."""
    card = _card_in_a_reader(tmp_path, monkeypatch)

    def boom(_path):
        raise OSError("card went away")
    monkeypatch.setattr(multiimage, "card_images", boom)
    assert SternManufacturer().identify_card(card) == ""


def test_the_same_reader_is_re_read_for_every_card(tmp_path, monkeypatch):
    """The cache keys on (path, size, mtime), and a device may well let the
    host stat it — but the same ``\\\\.\\PHYSICALDRIVE2`` is a different card a
    moment later, which is the entire workflow: swap it, read the answer."""
    card = _card_in_a_reader(tmp_path, monkeypatch)
    calls = []
    real = multiimage.card_images
    monkeypatch.setattr(multiimage, "card_images",
                        lambda p: (calls.append(p), real(p))[1])
    multiimage.images_for_path(card)
    multiimage.images_for_path(card)
    assert len(calls) == 2


def test_the_base_plugin_says_nothing_and_the_capability_is_off():
    """Every other plugin inherits the hook; only one that sets the capability
    gets the row and the badge."""
    assert Manufacturer.identify_card(object(), r"\\.\PHYSICALDRIVE2") == ""
    assert Capabilities().identify_card is False
    assert SternManufacturer().capabilities.identify_card is True


# ---------------------------------------------------------------------------
# detection: a device carries no filename
# ---------------------------------------------------------------------------

def test_detection_claims_a_card_with_no_filename_to_go_on(tmp_path,
                                                           monkeypatch):
    """``detect_game`` gates on the extension, which a device hasn't got; the
    partition signature is the whole answer for one."""
    card = _card_in_a_reader(tmp_path, monkeypatch)
    assert formats.detect_game(card) == formats.SPIKE2_GENERIC_KEY

    game = SternManufacturer().detect(card)
    # Named off the CARD (its game folder), not off "PHYSICALDRIVE9".
    assert game.display == "Godzilla Pro (Spike 2)"
    assert game.era == "spike2"
    # …and the report says which of the two it read: the card, not an image.
    assert game.notes == "Spike 2 card"


def test_a_card_image_is_still_named_by_its_filename(tmp_path, monkeypatch):
    """The file path must not change: a vendor card's name is how the app has
    always titled it, and reading the card for a title costs directory reads
    the Tk thread shouldn't pay on every keystroke."""
    # A title GAME_DB doesn't carry, so the FILENAME is what names it (a
    # known title would be answered from the database either way).
    card = write_card(tmp_path / "zaphod_le-1_00_0.Release.8G.sdcard.raw",
                      [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE})
    game = SternManufacturer().detect(card)
    assert game.display == "Zaphod LE (Spike 2)"
    assert game.notes == "Spike 2 card image"


def test_an_unreadable_card_still_gets_a_title_rather_than_a_crash(
        tmp_path, monkeypatch):
    """A Spike 2 shape whose filesystem won't open (a failing card) — the
    shape is what detection claimed, so the title falls back to the era."""
    card = write_card(tmp_path / "PHYSICALDRIVE6", [BOOT, ROOTFS, GAMES])
    _as_device(monkeypatch, card)
    install_readers(monkeypatch, {})
    assert formats.display_for_key(formats.SPIKE2_GENERIC_KEY, card) \
        == "Stern Spike 2 card"


# ---------------------------------------------------------------------------
# the Image Info report, on the card itself
# ---------------------------------------------------------------------------

def test_image_info_reports_on_the_card_instead_of_a_file(tmp_path,
                                                          monkeypatch):
    card = _card_in_a_reader(tmp_path, monkeypatch)
    sections = dict(image_info.collect(SternManufacturer(), card))

    # There is no file to stat — that is the point of the ticket.
    assert "File" not in sections
    card_rows = dict(sections["Card"])
    assert card_rows["Card"] == card
    assert "nothing is copied" in card_rows["Read"]
    assert dict(sections["Detection"])["Game"] == "Godzilla Pro (Spike 2)"


def test_a_card_that_cannot_be_opened_says_why(tmp_path, monkeypatch):
    """On Windows a raw disk read needs Administrator, and the app is normally
    launched without it — an empty report would read as "unknown card"."""
    missing = str(tmp_path / "PHYSICALDRIVE5")
    _as_device(monkeypatch, missing)
    (title, rows), = [image_info._device_section(missing)]
    assert title == "Card"
    assert "Could not read the card" in dict(rows)


def test_the_text_report_renders_the_card_section(tmp_path, monkeypatch):
    """Copy Report is how a card gets quoted into a forum post."""
    card = _card_in_a_reader(tmp_path, monkeypatch)
    text = image_info.as_text(image_info.collect(SternManufacturer(), card))
    assert "Card" in text and "Godzilla Pro" in text


# ---------------------------------------------------------------------------
# the file paths this shares plumbing with are unchanged
# ---------------------------------------------------------------------------

def test_a_plain_file_still_gets_its_file_section(tmp_path, monkeypatch):
    card = write_card(tmp_path / "godzilla_pro-1_16_0.raw",
                      [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE})
    sections = dict(image_info.collect(SternManufacturer(), card))
    assert "Card" not in sections
    assert dict(sections["File"])["Name"] == "godzilla_pro-1_16_0.raw"


@pytest.mark.parametrize("name", ["card.img", "card.bin", "card.raw"])
def test_the_extension_gate_still_turns_other_files_away(tmp_path, name):
    """Only the device skips it: a .zip or a .txt with a Spike-shaped MBR is
    still not offered as a card."""
    good = write_card(tmp_path / name, [BOOT, ROOTFS, GAMES])
    assert formats.detect_game(good) == formats.SPIKE2_GENERIC_KEY
    other = write_card(tmp_path / (name.rsplit(".", 1)[0] + ".txt"),
                       [BOOT, ROOTFS, GAMES])
    assert formats.detect_game(other) is None
