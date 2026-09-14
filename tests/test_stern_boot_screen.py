"""PAD-147: the boot screen on the Replace Images tab.

The Stern logo a Spike 2 shows while it starts up is not with the game's
files: it is ``/usr/local/spike/SternLogo.png`` on the OS partition (sda2),
drawn by ``boot_display``.  A tester asked for an easy way to replace it on a
multigame card, and David wanted it in the normal Replace Images flow.

Extract now lifts it into ``images/boot_screen/`` with a manifest of its own,
and Write puts a replacement back on THAT partition: into the file's own
blocks when it fits, copied on whole through the ext4 driver when it is
bigger.  A fake filesystem stands in for the card, the way test_stern_image
does it.
"""
import os

import pytest

from pinball_decryptor.core import card_paths
from pinball_decryptor.core import ext4_grow
from pinball_decryptor.core.checksums import generate_checksums, read_checksums
from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern import ext4 as ext4_mod

LOGO = "/usr/local/spike/SternLogo.png"
LOGO_ROW = "boot_screen/SternLogo.png"
OS_BASE = 12582912        # sda2, the same LBA on every Spike 2 card
GAMES_BASE = 364904448    # sda3
STOCK = b"\x89PNG\r\n\x1a\n" + b"L" * 300


class _FakeReader:
    """Just enough of Ext4Reader for the boot screen: a tree of inodes."""

    def __init__(self, base, files):
        self.base = base
        self._inodes = {}
        self._data = {}
        self._next = 2
        root = self._new({"mode": ext4_mod.S_IFDIR, "children": {}})
        for path, data in files.items():
            parent = root
            names = path.strip("/").split("/")
            for name in names[:-1]:
                kids = self._inodes[parent]["children"]
                if name not in kids:
                    kids[name] = self._new({"mode": ext4_mod.S_IFDIR,
                                            "children": {}})
                parent = kids[name]
            ino = self._new({"mode": ext4_mod.S_IFREG | 0o755,
                             "size": len(data)})
            self._inodes[parent]["children"][names[-1]] = ino
            self._data[ino] = data

    def _new(self, node):
        ino = self._next
        self._next += 1
        node["ino"] = ino
        self._inodes[ino] = node
        return ino

    def read_inode(self, ino):
        return self._inodes[ino]

    def _iter_dir(self, node):
        yield ".", node["ino"], 2
        for name, ino in node.get("children", {}).items():
            yield name, ino, (2 if "children" in self._inodes[ino] else 1)

    def extract_file(self, node, out_path):
        with open(out_path, "wb") as f:
            f.write(self._data[node["ino"]])

    def disk_ranges(self, node, file_off, length):
        # Two extents, so a write that has to be split across them is.
        start = self.base + 4096 * node["ino"]
        half = length // 2
        return [(start, half), (start + (1 << 20), length - half)]


@pytest.fixture
def card(monkeypatch):
    """A card whose sda2 holds the boot screen (and a font beside it) and
    whose sda3, the games partition, holds a same-named decoy."""
    fakes = {
        OS_BASE: _FakeReader(OS_BASE, {
            LOGO: STOCK,
            "/usr/local/spike/VeraMono.ttf": b"font",
            "/usr/local/bin/boot_display": b"\x7fELF"}),
        GAMES_BASE: _FakeReader(GAMES_BASE, {
            "/usr/local/spike/Decoy.png": b"\x89PNG decoy"}),
    }
    monkeypatch.setattr(ext4_mod, "Ext4Reader",
                        lambda _f, off, _size: fakes[off])
    # largest first, as formats.linux_partitions hands them over
    return [(GAMES_BASE, 7 << 30), (OS_BASE, 336 << 20)]


def _quiet(*_a, **_k):
    pass


# ---- Extract ----------------------------------------------------------------

def test_extract_takes_the_logo_off_the_os_partition(tmp_path, card):
    n = engine.extract_boot_images(None, card, str(tmp_path),
                                   games_base=GAMES_BASE, log=_quiet)
    assert n == 1
    out = tmp_path / "images" / "boot_screen"
    assert (out / "SternLogo.png").read_bytes() == STOCK
    # Only images: the font beside it stays on the card, and the games
    # partition is never searched for a boot screen.
    assert sorted(os.listdir(out)) == ["SternLogo.png", "manifest.txt"]
    rows = [r for r in (out / "manifest.txt").read_text("utf-8").splitlines()
            if r and not r.startswith("#")]
    assert rows == ["%s\t%s\t%d" % (LOGO_ROW, LOGO, len(STOCK))]


def test_a_card_with_no_boot_screen_extracts_nothing(tmp_path, monkeypatch):
    games = _FakeReader(GAMES_BASE, {"/godzilla_pro/logo.png": b"x"})
    monkeypatch.setattr(ext4_mod, "Ext4Reader", lambda _f, _o, _s: games)
    lines = []
    n = engine.extract_boot_images(
        None, [(GAMES_BASE, 1)], str(tmp_path), games_base=None,
        log=lambda m, lvl="info": lines.append(m))
    assert n == 0
    assert not (tmp_path / "images").exists()
    assert any("No boot screen" in m for m in lines)


# ---- which edits Write sees -------------------------------------------------

def _extract(tmp_path):
    img = tmp_path / "images"
    (img / "boot_screen").mkdir(parents=True)
    (img / "godzilla_pro").mkdir()
    (img / "godzilla_pro" / "a.png").write_bytes(b"\x89PNG game")
    (img / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "godzilla_pro/a.png\t/godzilla_pro/a.png\t10\n", encoding="utf-8")
    (img / "boot_screen" / "SternLogo.png").write_bytes(STOCK)
    (img / "boot_screen" / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n%s\t%s\t%d\n"
        % (LOGO_ROW, LOGO, len(STOCK)), encoding="utf-8")
    generate_checksums(str(tmp_path))
    return img


def test_a_replaced_boot_screen_is_an_edit_of_its_own(tmp_path):
    img = _extract(tmp_path)
    staged = img / "boot_screen" / "SternLogo.png"
    staged.write_bytes(b"\x89PNG mine")
    baseline = read_checksums(str(tmp_path))
    assert engine._changed_boot_images(str(tmp_path), baseline) == [
        (LOGO_ROW, LOGO, str(staged))]
    # ...and never a games-partition image, which would be looked for on
    # the wrong partition.
    assert engine._changed_images(str(tmp_path), baseline) == []


def test_an_untouched_boot_screen_is_not_an_edit(tmp_path):
    _extract(tmp_path)
    baseline = read_checksums(str(tmp_path))
    assert engine._changed_boot_images(str(tmp_path), baseline) == []


def test_an_extract_from_before_the_boot_screen_has_none(tmp_path):
    assert engine._changed_boot_images(str(tmp_path), {}) == []


def test_an_override_set_leaves_the_boot_screen_out(tmp_path):
    """The emulator starts the game without boot_display, so Start on the
    Emulate tab must not trip over a boot screen it can't show."""
    img = _extract(tmp_path)
    (img / "boot_screen" / "SternLogo.png").write_bytes(b"\x89PNG mine")
    lines = []
    with pytest.raises(FileNotFoundError):
        engine._compute_patches(None, [], str(tmp_path),
                                lambda m, lvl="info": lines.append(m),
                                None, lambda: False, boot_screen=False)
    assert any("emulator" in m for m in lines)


# ---- Write ------------------------------------------------------------------

def _payload(writes):
    return b"".join(buf for _off, buf in sorted(writes))


def test_a_smaller_replacement_goes_into_the_files_own_blocks(tmp_path, card):
    staged = tmp_path / "mine.png"
    staged.write_bytes(b"\x89PNG small")
    writes, grow, n = engine._prepare_boot_screen_patches(
        None, card, GAMES_BASE, [(LOGO_ROW, LOGO, str(staged))],
        str(tmp_path), _quiet, lambda: False)
    assert n == 1 and grow is None
    body = b"\x89PNG small"
    assert _payload(writes) == body + b"\x00" * (len(STOCK) - len(body))
    # on sda2, not on the games partition every other image is patched on
    assert all(OS_BASE <= off < GAMES_BASE for off, _b in writes)


def test_a_bigger_replacement_is_copied_on_whole(tmp_path, card, monkeypatch):
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "test"))
    staged = tmp_path / "mine.png"
    staged.write_bytes(b"\x89PNG" + b"B" * 4000)
    writes, grow, n = engine._prepare_boot_screen_patches(
        None, card, GAMES_BASE, [(LOGO_ROW, LOGO, str(staged))],
        str(tmp_path), _quiet, lambda: False)
    assert writes == [] and n == 1
    assert grow == {"offset": OS_BASE,
                    "jobs": [(LOGO.lstrip("/"), str(staged))]}


def test_a_direct_sd_write_fits_a_bigger_one_instead(tmp_path, card,
                                                     monkeypatch):
    def _never():
        raise AssertionError("a direct-SD write can't grow a file")
    monkeypatch.setattr(ext4_grow, "available", _never)
    fitted = b"\x89PNG fitted" + b"\x00" * (len(STOCK) - 11)
    monkeypatch.setattr(engine, "_fit_image_payload",
                        lambda _s, target, _w, _l: fitted[:target])
    staged = tmp_path / "mine.png"
    staged.write_bytes(b"\x89PNG" + b"B" * 4000)
    writes, grow, n = engine._prepare_boot_screen_patches(
        None, card, GAMES_BASE, [(LOGO_ROW, LOGO, str(staged))],
        str(tmp_path), _quiet, lambda: False, dest_is_device=True)
    assert grow is None and n == 1
    assert _payload(writes) == fitted


def test_a_boot_screen_the_card_lacks_is_skipped_by_name(tmp_path, card):
    staged = tmp_path / "mine.png"
    staged.write_bytes(b"\x89PNG")
    lines = []
    writes, grow, n = engine._prepare_boot_screen_patches(
        None, card, GAMES_BASE,
        [("boot_screen/Other.png", "/usr/local/spike/Other.png", str(staged))],
        str(tmp_path), lambda m, lvl="info": lines.append(m), lambda: False)
    assert (writes, grow, n) == ([], None, 0)
    assert any("/usr/local/spike/Other.png" in m for m in lines)


def test_the_grow_mounts_the_os_partition(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ext4_grow, "grow_files",
        lambda image, offset, jobs, log=None: calls.append(
            (image, offset, jobs)) or len(jobs))
    plan = {"offset": GAMES_BASE, "jobs": [],
            "boot": {"offset": OS_BASE, "jobs": [(LOGO[1:], "mine.png")]}}
    assert engine._grow_boot_screen("card.raw", plan, _quiet) == 1
    assert calls == [("card.raw", OS_BASE, [(LOGO[1:], "mine.png")])]
    assert engine._grow_boot_screen("card.raw", None, _quiet) == 0
    assert engine._grow_boot_screen("card.raw", {"jobs": []}, _quiet) == 0
    assert len(calls) == 1


# ---- the Replace Images tab + Find in Partition Explorer --------------------

def test_find_in_partition_explorer_knows_where_it_lives(tmp_path):
    _extract(tmp_path)
    card, note = card_paths.image_card_path(str(tmp_path),
                                            "images/" + LOGO_ROW)
    assert card == LOGO
    assert "OS partition" in note
    # A Partitions-tab swap of it now does make this extract stale.
    assert card_paths.is_extract_source(str(tmp_path), LOGO)


def test_the_source_column_calls_it_the_boot_screen():
    from pinball_decryptor.gui.main_window import MainWindow
    label = MainWindow._image_source_label
    assert label("images/boot_screen/SternLogo.png") == "Boot screen"
    # a game's own folder that happens to share the name is still a file
    assert label("images/godzilla_pro/boot_screen/a.png") == "File"
