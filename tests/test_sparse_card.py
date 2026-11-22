"""PAD-1507: card images stored compact (sparse) - same path, same bytes."""

import bz2
import gzip
import hashlib
import lzma
import os
import zipfile

import pytest

from pinball_decryptor.core import sparse_card as sc

MB = 1 << 20


def _card(path):
    """A small stand-in card: data, a long zero run, data, a short zero run
    (under MIN_HOLE: stays data), a long zero run, an unaligned tail."""
    with open(path, "wb") as f:
        f.write(os.urandom(100_000))
        f.write(bytes(6 * MB))
        f.write(os.urandom(70_000))
        f.write(bytes(256 * 1024))
        f.write(b"\x07" * 4096)
        f.write(bytes(5 * MB))
        f.write(b"\x01" * 3)
    return path


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _sparse_fs(tmp_path):
    """Can this test folder's filesystem hold holes at all?"""
    p = tmp_path / "probe"
    with open(p, "wb") as f:
        f.write(b"x")
    r = sc.compact_file(str(p))
    os.remove(p)
    return r.sparse_ok


def test_compact_in_place_keeps_every_byte(tmp_path):
    p = _card(tmp_path / "a.raw")
    h = _sha(p)
    size = os.path.getsize(p)
    r = sc.compact_file(str(p))
    assert _sha(p) == h
    assert os.path.getsize(p) == size
    if not r.sparse_ok:
        pytest.skip("this filesystem keeps no holes")
    assert r.holes == 2              # the 256 KiB run is under MIN_HOLE
    assert r.after < 2 * MB < r.before
    assert r.after == sc.on_disk_size(str(p))


def test_second_compact_reads_only_the_data(tmp_path):
    p = _card(tmp_path / "a.raw")
    if not sc.compact_file(str(p)).sparse_ok:
        pytest.skip("this filesystem keeps no holes")
    seen = []
    r = sc.compact_file(str(p), progress=lambda d, t: seen.append(t))
    assert r.holes == 0
    # only the allocated ranges were read, not the 11 MB the file is long
    assert seen and max(seen) < 2 * MB


def test_allocated_ranges_skip_the_holes(tmp_path):
    p = _card(tmp_path / "a.raw")
    if not sc.compact_file(str(p)).sparse_ok:
        pytest.skip("this filesystem keeps no holes")
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        ranges = sc.allocated_ranges(f, size)
        assert ranges[0][0] == 0
        assert sum(n for _o, n in ranges) < 2 * MB
        # outside every range the file reads as zeros
        prev = 0
        for off, n in ranges + [(size, 0)]:
            f.seek(prev)
            assert f.read(off - prev) == bytes(off - prev)
            prev = off + n


def test_sparse_copy_same_bytes_and_compact(tmp_path):
    src = _card(tmp_path / "a.raw")
    dst = tmp_path / "b.raw"
    got = []
    sc.sparse_copy(str(src), str(dst), progress=lambda d, t: got.append((d, t)))
    assert _sha(dst) == _sha(src)
    assert got[-1] == (os.path.getsize(src),) * 2
    if _sparse_fs(tmp_path):
        assert sc.on_disk_size(str(dst)) < 2 * MB


def test_sparse_copy_of_a_compact_card_reads_only_data(tmp_path):
    src = _card(tmp_path / "a.raw")
    if not sc.compact_file(str(src)).sparse_ok:
        pytest.skip("this filesystem keeps no holes")
    n = sc.sparse_copy(str(src), str(tmp_path / "b.raw"))
    assert n < 2 * MB
    assert _sha(tmp_path / "b.raw") == _sha(src)


@pytest.mark.parametrize("kind", ["zip", "xz", "gz", "bz2"])
def test_import_a_download_compact(tmp_path, kind):
    src = _card(tmp_path / "card.raw")
    h = _sha(src)
    data = src.read_bytes()
    if kind == "zip":
        arc = tmp_path / "dl.zip"
        with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("folder/card.raw", data)
            z.writestr("folder/readme.txt", b"hi")
    else:
        arc = tmp_path / ("card.raw." + kind)
        opener = {"xz": lzma.open, "gz": gzip.open, "bz2": bz2.open}[kind]
        with opener(arc, "wb") as f:
            f.write(data)
    lib = tmp_path / "lib"
    lib.mkdir()
    out = sc.import_card(str(arc), str(lib))
    assert os.path.basename(out) == "card.raw"
    assert _sha(out) == h
    assert not os.path.exists(out + ".part")
    if _sparse_fs(tmp_path):
        assert sc.on_disk_size(out) < 2 * MB
    with pytest.raises(FileExistsError):
        sc.import_card(str(arc), str(lib))


def test_import_refuses_a_zip_of_two_cards(tmp_path):
    arc = tmp_path / "two.zip"
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("a.raw", b"1")
        z.writestr("b.img", b"2")
    with pytest.raises(ValueError):
        sc.import_card(str(arc), str(tmp_path))


def test_folder_tool_compacts_images_not_subfolders(tmp_path, capsys):
    _card(tmp_path / "a.raw")
    _card(tmp_path / "b.img")
    (tmp_path / "padkeys.json").write_text("{}")
    old = tmp_path / "older versions"
    old.mkdir()
    _card(old / "c.raw")
    before = sc.on_disk_size(str(old / "c.raw"))
    rc = sc.main([str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a.raw" in out and "b.img" in out and "c.raw" not in out
    assert "GB freed" in out
    assert sc.on_disk_size(str(old / "c.raw")) == before
    assert (tmp_path / "padkeys.json").read_text() == "{}"


def test_folder_tool_imports_with_into(tmp_path, capsys):
    src = _card(tmp_path / "new.raw")
    lib = tmp_path / "lib"
    lib.mkdir()
    assert sc.main([str(src), "--into", str(lib)]) == 0
    assert _sha(lib / "new.raw") == _sha(src)
