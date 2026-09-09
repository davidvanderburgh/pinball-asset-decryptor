"""PAD-122: a multi-boot card carries several games and this app edits ONE.

The probe (``plugins.stern.multiimage``) counts the games on a card without
extracting anything, and the App shows what it found before an Extract or a
Build starts.  These run over the same in-memory fake ext4 the Partition
Explorer tests use — the real reader is exercised on real cards — plus a
synthetic MBR/EBR so the logical partitions the default multi-boot layout puts
its extra games in are actually walked.
"""

import struct

from pinball_decryptor.plugins.stern import multiimage
from tests._ext4_fake import FakeExt4Reader, make_mbr

# ---------------------------------------------------------------------------
# card fixtures
# ---------------------------------------------------------------------------

#: The Spike 2 signature partitions (formats.is_spike_card_parts): an 8 MB FAT
#: boot at LBA 8192 followed by an ext partition at 24576.  Present so
#: ``detect_game`` claims these fixtures as Spike 2 cards.
BOOT = (0x0C, 8192, 16384)
ROOTFS = (0x83, 24576, 2048)
GAMES = (0x83, 26624, 8192)
EXTENDED = (0x0F, 30000, 20000)

#: EBR sector -> the logical partition it declares and the next EBR, so the
#: chain walks p5 (data), p6 (dump) and p7 (an extra game's partition) the way
#: a card built by ``mkmulticard.py --layout parts`` does.
EBR_CHAIN = [(30000, 2048, 2048), (32000, 2048, 2048), (34000, 2048, 4096)]

P5, P6, P7 = 32048, 34048, 36048          # ...their start LBAs

GAME_TREE = {
    "spk": {"index": {"godzilla_pro-1_16_0.sidx": b"SIDX"}},
    "godzilla_pro": {"image.bin": b"\x00" * 64, "game": b"\x7fELF"},
    "game": ("symlink", "godzilla_pro/game"),
}
ROOTFS_TREE = {"lib": {"libc.so": b"x"}, "usr": {"bin": {"sh": b"x"}},
               "etc": {"version": b"1.16.0"}}
EMPTY_TREE = {"lost+found": {}}


def _tree(folder):
    """A games tree whose game folder is *folder* (one image's worth)."""
    return {"spk": {"index": {folder + "-1_0_0.sidx": b"SIDX"}},
            folder: {"image.bin": b"\x00" * 64, "game": b"\x7fELF"}}


def write_card(path, primaries, chain=(), sector_size=512):
    """Write a synthetic card: an MBR, an EBR chain, and nothing else.

    *primaries* is ``[(type, lba, sectors), ...]``; *chain* is
    ``[(ebr_lba, rel_lba, sectors), ...]`` — each EBR declares one logical
    partition and links to the next.  The file is only as big as the last
    sector read, because every filesystem in it is faked.
    """
    ext_base = next((lba for t, lba, _n in primaries if t in (0x05, 0x0F)), 0)
    with open(str(path), "wb") as f:
        f.write(make_mbr(primaries))
        for i, (ebr_lba, rel, sectors) in enumerate(chain):
            buf = bytearray(512)
            buf[446 + 4] = 0x83
            struct.pack_into("<II", buf, 446 + 8, rel, sectors)
            if i + 1 < len(chain):
                buf[446 + 16 + 4] = 0x0F
                struct.pack_into("<II", buf, 446 + 16 + 8,
                                 chain[i + 1][0] - ext_base, 4096)
            buf[510:512] = b"\x55\xaa"
            f.seek(ebr_lba * sector_size)
            f.write(bytes(buf))
        f.seek((chain[-1][0] if chain else 0) * sector_size + 1024)
        f.write(b"\x00")
    return str(path)


def install_readers(monkeypatch, by_lba):
    """Patch ``multiimage.Ext4Reader`` so each LBA in *by_lba* opens as a
    ``FakeExt4Reader`` over its spec and every other offset refuses."""
    def fake(_fileobj, off, _size):
        spec = by_lba.get(off // 512)
        if spec is None:
            raise ValueError("not an ext filesystem")
        return FakeExt4Reader(spec)
    monkeypatch.setattr(multiimage, "Ext4Reader", fake)


# ---------------------------------------------------------------------------
# counting the games
# ---------------------------------------------------------------------------

def test_single_game_card_is_one_image_and_says_nothing(tmp_path, monkeypatch):
    card = write_card(tmp_path / "godzilla_pro-1_16_0.raw",
                      [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE})

    images = multiimage.card_images(card)
    assert [(i.part, i.subdir, i.folder) for i in images] \
        == [(3, "", "godzilla_pro")]
    # A plain card is the case that must stay silent — no dialog, no log.
    assert multiimage.source_note(images) == ""
    assert multiimage.log_lines(images) == []


def test_rootfs_and_empty_partitions_are_not_games(tmp_path, monkeypatch):
    """/data and /dump are ext4 with nothing in them, and the rootfs has no
    spk — the strict rule (spk + a folder holding image.bin) is what keeps
    them out of the menu (tools/spike2_emu/parts.py makes the same point)."""
    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES, EXTENDED],
                      EBR_CHAIN[:2])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE})
    assert len(multiimage.card_images(card)) == 1


def test_parts_layout_extra_game_lives_in_a_logical_partition(tmp_path,
                                                              monkeypatch):
    """The default layout appends each extra image's games partition to the
    EBR chain — invisible to the primary-only enumeration the extract uses,
    which is exactly why this probe walks the chain."""
    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES, EXTENDED],
                      EBR_CHAIN)
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE,
                                  P7: _tree("jaws_pro")})

    images = multiimage.card_images(card)
    assert [(i.part, i.subdir, i.folder) for i in images] == [
        (3, "", "godzilla_pro"), (7, "", "jaws_pro")]


def test_multi_layout_puts_every_extra_in_one_partition(tmp_path, monkeypatch):
    """--layout multi: p7 is ONE ext4 holding img1/, img2/, … — it has no spk
    of its own, so the rule is applied a level down, in numeric order."""
    p7 = {"img1": _tree("jaws_pro"), "img2": _tree("venom_le"),
          "img10": _tree("deadpool_pro")}
    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES, EXTENDED],
                      EBR_CHAIN)
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE, P7: p7})

    images = multiimage.card_images(card)
    assert [(i.part, i.subdir, i.folder) for i in images] == [
        (3, "", "godzilla_pro"), (7, "img1", "jaws_pro"),
        (7, "img2", "venom_le"), (7, "img10", "deadpool_pro")]


def test_store_layout_extras_sit_beside_the_primary_tree(tmp_path, monkeypatch):
    """--layout store: the extras are img1/, img2/ INSIDE the primary's own
    partition.  The primary is still first — it is the tree the extract's
    breadth-first search reaches before any imgN — and the imgN folders must
    not be mistaken for its game folder."""
    p3 = dict(GAME_TREE)
    p3["img1"] = _tree("jaws_pro")
    p3["img2"] = _tree("venom_le")
    p3[".blobs"] = {"00ff": b"x"}
    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: p3})

    images = multiimage.card_images(card)
    assert [(i.part, i.subdir, i.folder) for i in images] == [
        (3, "", "godzilla_pro"), (3, "img1", "jaws_pro"),
        (3, "img2", "venom_le")]


def test_unreadable_card_is_not_a_multi_boot_card(tmp_path, monkeypatch):
    missing = str(tmp_path / "nope.raw")
    assert multiimage.card_images(missing) == []
    assert multiimage.note_for_path(missing) == ""


# ---------------------------------------------------------------------------
# saying it
# ---------------------------------------------------------------------------

def _three():
    return [multiimage.CardImage(3, "", "godzilla_pro"),
            multiimage.CardImage(7, "img1", "jaws_pro"),
            multiimage.CardImage(7, "img2", "venom_le")]


def test_source_note_names_the_count_the_first_game_and_the_way_out():
    note = multiimage.source_note(_three())
    assert "3 game images" in note
    # The one in play is named, and named FIRST — the tester's question was
    # "which image does the replacement replace?".
    assert "only the first one, Godzilla Pro" in note
    assert "1. Godzilla Pro" in note and "2. Jaws Pro" in note
    assert "3. Venom LE" in note
    # ...and what a Build still gives him, so "only the first" doesn't read as
    # "don't bother" (PAD-122: "it is fairly pointless").
    assert "working multi-boot card" in note
    assert multiimage.HOW_TO_EDIT_ANOTHER in note
    assert "Multi-boot tab" in note


def test_log_lines_carry_the_partition_of_every_game():
    lines = multiimage.log_lines(_three())
    assert all(line.startswith("[multi-boot]") for line in lines)
    assert "(p3)" in lines[1] and "this run" in lines[1]
    assert "(p7/img1)" in lines[2] and "this run" not in lines[2]
    assert multiimage.HOW_TO_EDIT_ANOTHER in lines[-1]


def test_pretty_uses_the_cards_own_folder_name():
    assert multiimage.pretty(multiimage.CardImage(3, "", "godzilla_pro")) \
        == "Godzilla Pro"
    assert multiimage.pretty(multiimage.CardImage(7, "", "venom_le")) \
        == "Venom LE"
    assert multiimage.pretty(multiimage.CardImage(7, "", "")) == "image 7"


# ---------------------------------------------------------------------------
# the plugin hook + the confirm
# ---------------------------------------------------------------------------

def test_stern_source_note_only_speaks_for_a_multi_image_spike2_card(
        tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer

    mfr = SternManufacturer()
    card = write_card(tmp_path / "godzilla_pro-1_16_0.Release.16G.sdcard.raw",
                      [BOOT, ROOTFS, GAMES, EXTENDED], EBR_CHAIN)
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE,
                                  P7: _tree("jaws_pro")})
    multiimage._CACHE.clear()
    assert "2 game images" in mfr.source_note(card)

    # A Whitestar ROM zip and anything that isn't a Spike 2 card are not asked
    # about at all — the probe would open a file it knows nothing about.
    assert mfr.source_note(str(tmp_path / "abc.zip")) == ""
    plain = tmp_path / "notacard.raw"
    plain.write_bytes(b"\x00" * 1024)
    assert mfr.source_note(str(plain)) == ""


def test_a_card_read_in_the_reader_is_probed_too(tmp_path, monkeypatch):
    """"From SD card" is the likeliest way to meet a multi-boot card, and a
    device is neither named like a card nor readable in odd-sized chunks — so
    the probe goes through RawDeviceFile and the plugin's filename gate is
    skipped.  ``is_device_path`` is what says which; the real RawDeviceFile
    opens the fixture (it probes a regular file's sector as 512)."""
    from pinball_decryptor.core import rawdevice
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer

    card = write_card(tmp_path / "PHYSICALDRIVE9", [BOOT, ROOTFS, GAMES,
                                                    EXTENDED], EBR_CHAIN)
    monkeypatch.setattr(rawdevice, "is_device_path", lambda p: p == card)
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE,
                                  P7: _tree("jaws_pro")})
    multiimage._CACHE.clear()
    assert len(multiimage.card_images(card)) == 2
    # ...and the extensionless "device" is not turned away by detect_game.
    assert "2 game images" in SternManufacturer().source_note(card)


def test_stern_source_note_survives_a_failing_probe(tmp_path, monkeypatch):
    """A courtesy probe must never be what stops a Build."""
    from pinball_decryptor.plugins.stern import manufacturer as mfr_mod

    def boom(_path):
        raise OSError("card went away")
    monkeypatch.setattr(multiimage, "note_for_path", boom)
    card = write_card(tmp_path / "godzilla_pro-1_16_0.raw",
                      [BOOT, ROOTFS, GAMES])
    assert mfr_mod.SternManufacturer().source_note(card) == ""


class _Mfr:
    source_note_title = "Multi-boot card"

    def __init__(self, note="", raises=False):
        self._note, self._raises = note, raises

    def source_note(self, path):
        if self._raises:
            raise RuntimeError("probe blew up")
        return self._note


class _App:
    """Just enough of App for the confirm helper (no Tk)."""
    def __init__(self, mfr):
        self._current_mfr = mfr


def _confirm(monkeypatch, mfr, answer=True):
    from pinball_decryptor import app as app_mod

    seen = {}

    class _MB:
        @staticmethod
        def askyesno(title, message, **kw):
            seen["title"], seen["message"], seen["kw"] = title, message, kw
            return answer

    monkeypatch.setattr(app_mod, "messagebox", _MB)
    ok = app_mod.App._source_note_accepted(_App(mfr), "card.raw")
    return ok, seen


def test_confirm_is_skipped_when_the_plugin_has_nothing_to_say(monkeypatch):
    ok, seen = _confirm(monkeypatch, _Mfr(note=""))
    assert ok and not seen


def test_confirm_shows_the_note_and_a_no_stops_the_run(monkeypatch):
    ok, seen = _confirm(monkeypatch, _Mfr(note="four games on here"),
                        answer=False)
    assert ok is False
    assert seen["title"] == "Multi-boot card"
    assert seen["message"].startswith("four games on here")
    assert seen["message"].endswith("Continue?")
    assert seen["kw"].get("icon") == "warning"


def test_confirm_never_blocks_on_a_probe_that_raises(monkeypatch):
    ok, seen = _confirm(monkeypatch, _Mfr(raises=True))
    assert ok and not seen


# ---------------------------------------------------------------------------
# the run log
# ---------------------------------------------------------------------------

def test_pipeline_logs_the_other_games_once_a_run_starts(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import pipeline

    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES, EXTENDED],
                      EBR_CHAIN)
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE,
                                  P7: _tree("jaws_pro")})
    multiimage._CACHE.clear()
    lines = []
    pipeline._log_multi_image(card, lambda text, level="info":
                              lines.append((text, level)))
    assert lines and all(level == "warning" for _t, level in lines)
    assert "2 game images" in lines[0][0]
    assert any("jaws_pro" in t.lower() or "Jaws Pro" in t for t, _l in lines)


def test_pipeline_log_is_silent_on_an_ordinary_card(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import pipeline

    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE})
    multiimage._CACHE.clear()
    lines = []
    pipeline._log_multi_image(card, lambda text, level="info":
                              lines.append(text))
    assert lines == []


# ---------------------------------------------------------------------------
# Image Info
# ---------------------------------------------------------------------------

def test_image_info_lists_the_games_on_a_multi_boot_card(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.info import _multi_image_section

    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES, EXTENDED],
                      EBR_CHAIN)
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE,
                                  P5: EMPTY_TREE, P6: EMPTY_TREE,
                                  P7: _tree("jaws_pro")})
    multiimage._CACHE.clear()
    (title, rows), = _multi_image_section(card)
    rows = dict(rows)
    assert title == "Games on this Card"
    assert rows["Boot menu"].startswith("2 games")
    assert rows["Game 1"].startswith("Godzilla Pro  (p3)")
    assert "extracts and writes" in rows["Game 1"]
    assert rows["Game 2"].startswith("Jaws Pro  (p7)")
    assert "extracts and writes" not in rows["Game 2"]

    # A single-game card adds no section at all.
    plain = write_card(tmp_path / "one.raw", [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE})
    multiimage._CACHE.clear()
    assert _multi_image_section(plain) == []


def test_images_for_path_is_cached_on_file_identity(tmp_path, monkeypatch):
    card = write_card(tmp_path / "card.raw", [BOOT, ROOTFS, GAMES])
    install_readers(monkeypatch, {24576: ROOTFS_TREE, 26624: GAME_TREE})
    multiimage._CACHE.clear()
    calls = []
    real = multiimage.card_images
    monkeypatch.setattr(multiimage, "card_images",
                        lambda p: (calls.append(p), real(p))[1])
    first = multiimage.images_for_path(card)
    again = multiimage.images_for_path(card)
    assert first == again and len(calls) == 1
