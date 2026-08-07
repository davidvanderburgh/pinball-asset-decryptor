"""Tests for plugins.stern.explorer — the read-only card-image browser behind
the Partition Explorer tab (a tester wishlist #3).

The real ext4 read layer (Ext4Reader) is exercised elsewhere + on real cards; a
tiny in-memory fake filesystem (tests/_ext4_fake.py) covers the explorer's
composition logic (partition classification, path resolution, listing/sort,
preview cap, extract layout) without a multi-GB card fixture."""

import time

import pytest

from pinball_decryptor.plugins.stern import explorer
from pinball_decryptor.plugins.stern.explorer import CardImage

from tests._ext4_fake import GOOD_OFF, install_fake_reader, write_fake_card


@pytest.fixture
def card(tmp_path, monkeypatch):
    install_fake_reader(monkeypatch)
    img = write_fake_card(tmp_path / "card.raw")
    with CardImage(img) as c:
        yield c


def test_partition_classification(card):
    parts = {p.index: p for p in card.partitions()}
    assert parts[0].kind == "fat" and not parts[0].browsable
    assert parts[1].kind == "ext" and parts[1].browsable
    # An ext-typed partition the reader can't open is flagged not-browsable.
    assert parts[2].kind == "ext" and not parts[2].browsable
    assert parts[3].kind == "extended" and not parts[3].browsable
    assert parts[1].offset == GOOD_OFF and parts[1].size == 100 * 512


def test_list_dir_sorts_dirs_first_then_name(card):
    names = [(e.name, e.is_dir) for e in card.list_dir(1, "/")]
    # dirs (alpha) then non-dirs (alpha); the 'game' symlink sorts with files.
    assert names == [("etc", True), ("spk", True), ("zeta", True),
                     ("game", False), ("readme.txt", False)]


def test_list_dir_symlink_target(card):
    entries = {e.name: e for e in card.list_dir(1, "/spk/index")}
    link = entries["turtles.link"]
    assert link.is_symlink and link.link_target == "turtles.sidx"
    assert link.path == "/spk/index/turtles.link"


def test_list_dir_nonbrowsable_partition_raises(card):
    with pytest.raises(ValueError):
        card.list_dir(0, "/")           # the FAT partition


def test_list_dir_missing_path_raises(card):
    with pytest.raises(FileNotFoundError):
        card.list_dir(1, "/nope/here")


def test_preview_file_dir_and_cap(card, monkeypatch):
    assert card.preview(1, "/etc/init.d/game") == b"#!/bin/sh\necho hi\n"
    assert card.preview(1, "/spk") is None          # a directory
    monkeypatch.setattr(explorer, "PREVIEW_CAP", 4)
    assert card.preview(1, "/readme.txt") is None   # over the cap


def test_extract_file_writes_bytes(card, tmp_path):
    out = tmp_path / "sub" / "out.sidx"
    n = card.extract_file(1, "/spk/index/turtles.sidx", str(out))
    assert n == 8 and out.read_bytes() == b"SIDXdata"   # parent dir created


def test_extract_tree_directory_mirrors_layout(card, tmp_path):
    n_files, n_bytes = card.extract_tree(1, "/zeta", str(tmp_path / "dst"))
    assert (n_files, n_bytes) == (2, 6)
    assert (tmp_path / "dst" / "zeta" / "a.bin").read_bytes() == b"AA"
    assert (tmp_path / "dst" / "zeta" / "b.bin").read_bytes() == b"BBBB"


def test_extract_tree_single_file(card, tmp_path):
    n_files, n_bytes = card.extract_tree(1, "/readme.txt", str(tmp_path / "d"))
    assert (n_files, n_bytes) == (1, 11)
    assert (tmp_path / "d" / "readme.txt").read_bytes() == b"hello world"


def test_extract_tree_whole_partition_skips_symlinks(card, tmp_path):
    n_files, _ = card.extract_tree(1, "/", str(tmp_path / "all"))
    # 5 regular files; the two symlinks are not extracted.
    assert n_files == 5
    assert (tmp_path / "all" / "root" / "spk" / "index"
            / "turtles.sidx").exists()
    assert not (tmp_path / "all" / "root" / "game").exists()


def test_extract_tree_top_name_override(card, tmp_path):
    """A whole-partition extract can land under a caller-chosen folder
    ("Partition 1") instead of the generic "root" — two partitions extracted
    into one destination used to mix together (feedback batch 10)."""
    n_files, _ = card.extract_tree(1, "/", str(tmp_path / "all"),
                                   top_name="Partition 1")
    assert n_files == 5
    assert (tmp_path / "all" / "Partition 1" / "readme.txt").exists()
    assert not (tmp_path / "all" / "root").exists()


def test_interactive_reads_are_serialised(card, monkeypatch):
    """Two reads at once must not interleave their seeks on the one shared
    file handle.

    The GUI renders image/font previews on a worker thread, so arrowing down
    a folder of PNGs overlaps the next read with the one still running (and
    with the Tk thread's own directory fills).  Unserialised, the loser came
    back with a bogus FileNotFoundError — or a short struct unpack — for a
    file that is plainly on the card.
    """
    import threading

    depth = 0
    overlapped = False
    guard = threading.Lock()
    real_resolve = CardImage._resolve

    def tracking_resolve(self, reader, path):
        nonlocal depth, overlapped
        with guard:
            depth += 1
            if depth > 1:
                overlapped = True
        try:
            time.sleep(0.002)      # widen the window a real read would have
            return real_resolve(self, reader, path)
        finally:
            with guard:
                depth -= 1

    monkeypatch.setattr(CardImage, "_resolve", tracking_resolve)

    errors = []
    sizes = []

    def read_it():
        try:
            sizes.append(card.preview(1, "/readme.txt"))
        except Exception as exc:                        # pragma: no cover
            errors.append(exc)

    def list_it():
        try:
            card.list_dir(1, "/")
        except Exception as exc:                        # pragma: no cover
            errors.append(exc)

    threads = ([threading.Thread(target=read_it) for _ in range(6)]
               + [threading.Thread(target=list_it) for _ in range(4)])
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert not overlapped
    assert sizes == [b"hello world"] * 6
