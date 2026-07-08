"""Tests for plugins.stern.explorer — the read-only card-image browser behind
the Partition Explorer tab (monkeybug wishlist #3).

The real ext4 read layer (Ext4Reader) is exercised elsewhere + on real cards; a
tiny in-memory fake filesystem (tests/_ext4_fake.py) covers the explorer's
composition logic (partition classification, path resolution, listing/sort,
preview cap, extract layout) without a multi-GB card fixture."""

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
