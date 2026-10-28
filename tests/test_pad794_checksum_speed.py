"""PAD-794: the post-extract baseline hashes on a few threads, reads a MiB at
a time, seeds the size+mtime hash cache, and the revert scan answers from
that cache.  Held to the one-at-a-time version it replaced: same baseline
bytes, same order, same skips, same answers."""

import hashlib
import os

import pytest

from pinball_decryptor.core import checksums, hashcache
from pinball_decryptor.core.checksums import CHECKSUMS_FILE


def _w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _old_generate(folder):
    """generate_checksums as it was: a serial walk, 64 KiB reads, no cache."""
    from pinball_decryptor.core.checksums import (NON_ASSET_DIRS,
                                                  TRACKING_SIDECARS,
                                                  is_other_extract)
    from pinball_decryptor.core.staged_originals import ORIG_DIR
    excluded = {ORIG_DIR} | set(NON_ASSET_DIRS)
    lines = []
    for dirpath, dirnames, filenames in os.walk(folder):
        rel_dir = os.path.relpath(dirpath, folder).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        dirnames[:] = [d for d in dirnames
                       if (f"{rel_dir}/{d}" if rel_dir else d) not in excluded
                       and not is_other_extract(os.path.join(dirpath, d))]
        for fn in filenames:
            if fn.startswith(".") or fn in TRACKING_SIDECARS:
                continue
            abs_path = os.path.join(dirpath, fn)
            if os.path.islink(abs_path):
                continue
            h = hashlib.md5()
            with open(abs_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            rel = os.path.relpath(abs_path, folder).replace("\\", "/")
            lines.append(f"{rel}\t{h.hexdigest()}\n")
    return "".join(lines)


def _tree(root, n=70):
    for i in range(n):
        rel = "d%d/sub%d/f%02d.%s" % (i % 3, i % 2, i, ("wav", "png")[i % 2])
        _w(os.path.join(root, rel), bytes([i % 251]) * (i * 40961 % 300007))
    _w(os.path.join(root, "build", "out.raw"), b"generated")
    _w(os.path.join(root, ".orig", "d0", "f00.wav"), b"snapshot")
    _w(os.path.join(root, "d1", ".hidden"), b"dot")
    _w(os.path.join(root, "callouts.csv"), b"sidecar")
    _w(os.path.join(root, "inner", CHECKSUMS_FILE), b"")      # another extract
    _w(os.path.join(root, "inner", "x.wav"), b"theirs")


def test_md5_file_matches_hashlib(tmp_path):
    p = tmp_path / "big.bin"
    body = os.urandom(3 * 1024 * 1024 + 12345)                # spans MiB reads
    p.write_bytes(body)
    assert checksums.md5_file(str(p)) == hashlib.md5(body).hexdigest()
    (tmp_path / "empty.bin").write_bytes(b"")
    assert checksums.md5_file(str(tmp_path / "empty.bin")) == hashlib.md5(b"").hexdigest()


def test_baseline_bytes_and_order_unchanged(tmp_path):
    """Hashing on threads must not reorder or reformat the baseline."""
    root = str(tmp_path)
    _tree(root)
    want = _old_generate(root)
    n = checksums.generate_checksums(root)
    got = (tmp_path / CHECKSUMS_FILE).read_text(encoding="utf-8")
    assert got == want
    assert n == want.count("\n") == 70


def test_generate_checksums_seeds_the_hash_cache(tmp_path, monkeypatch):
    root = str(tmp_path)
    _tree(root)
    checksums.generate_checksums(root)
    base = checksums.read_checksums(root)
    cache = hashcache.load(root)
    assert set(cache) == set(base)
    for rel, md5 in base.items():
        st = os.stat(os.path.join(root, *rel.split("/")))
        assert cache[rel] == [st.st_size, st.st_mtime_ns, md5]
    # the next scan is stats only: nothing is hashed again
    def _no_hash(path):
        raise AssertionError("re-hashed %s" % path)
    monkeypatch.setattr(checksums, "md5_file", _no_hash)
    assert checksums.changed_rels(root, list(base)) == set()
    assert checksums.all_changed(root) == set()


def test_all_changed_answers_from_the_cache_and_refreshes_it(tmp_path, monkeypatch):
    root = str(tmp_path)
    _tree(root)
    checksums.generate_checksums(root)
    edited = os.path.join(root, "d0", "sub0", "f00.wav")
    _w(edited, b"edited bytes")                         # size + mtime move
    hashed = []
    real = checksums.md5_file
    monkeypatch.setattr(checksums, "md5_file",
                        lambda p: (hashed.append(p), real(p))[1])
    assert checksums.all_changed(root) == {"d0/sub0/f00.wav"}
    assert hashed == [edited]                         # only the miss was read
    # the cache now carries the edited file, so the next scan reads nothing
    st = os.stat(edited)
    assert hashcache.load(root)["d0/sub0/f00.wav"] == [
        st.st_size, st.st_mtime_ns, hashlib.md5(b"edited bytes").hexdigest()]
    hashed.clear()
    assert checksums.all_changed(root) == {"d0/sub0/f00.wav"}
    assert hashed == []


def test_all_changed_without_a_cache_hashes_everything_once(tmp_path):
    """A folder extracted before PAD-794 has no cache: the scan still finds
    every edit, and leaves a cache behind for the next one."""
    root = str(tmp_path)
    _tree(root)
    checksums.generate_checksums(root)
    os.remove(os.path.join(root, hashcache.CACHE_FILE))
    _w(os.path.join(root, "d1", "sub1", "f01.png"), b"new png")
    os.remove(os.path.join(root, "d2", "sub0", "f02.wav"))    # gone = changed
    assert checksums.all_changed(root) == {"d1/sub1/f01.png", "d2/sub0/f02.wav"}
    cache = hashcache.load(root)
    assert "d1/sub1/f01.png" in cache and "d2/sub0/f02.wav" not in cache
    assert len(cache) == 69


def test_all_changed_capture_run_leaves_the_folder_alone(tmp_path, monkeypatch):
    root = str(tmp_path)
    _tree(root)
    checksums.generate_checksums(root)
    os.remove(os.path.join(root, hashcache.CACHE_FILE))
    monkeypatch.setenv("PAD_UI_CAPTURE", "1")
    assert checksums.all_changed(root) == set()
    assert not os.path.exists(os.path.join(root, hashcache.CACHE_FILE))


def test_all_changed_quick_still_skips_by_mtime_with_a_cache(tmp_path):
    root = str(tmp_path)
    _w(os.path.join(root, "audio", "old.wav"), b"A")
    _w(os.path.join(root, "audio", "new.wav"), b"B")
    checksums.generate_checksums(root)
    base_m = os.path.getmtime(os.path.join(root, CHECKSUMS_FILE))
    _w(os.path.join(root, "audio", "old.wav"), b"A-CHANGED")
    _w(os.path.join(root, "audio", "new.wav"), b"B-CHANGED")
    os.utime(os.path.join(root, "audio", "old.wav"), (base_m - 10, base_m - 10))
    os.utime(os.path.join(root, "audio", "new.wav"), (base_m + 10, base_m + 10))
    assert checksums.all_changed(root, quick=True) == {"audio/new.wav"}
    assert checksums.all_changed(root, quick=False) == {"audio/old.wav",
                                                        "audio/new.wav"}


def test_hash_files_keeps_order_reports_errors_and_cancels(tmp_path):
    paths = []
    for i in range(12):
        p = tmp_path / ("f%02d.bin" % i)
        p.write_bytes(bytes([i]) * (i * 1000 + 1))
        paths.append(str(p))
    paths.insert(5, str(tmp_path / "missing.bin"))
    got = list(checksums.hash_files(paths, threads=3))
    assert len(got) == 13
    for p, r in zip(paths, got):
        if p.endswith("missing.bin"):
            assert isinstance(r, OSError)
        else:
            st = os.stat(p)
            assert r == (st.st_size, st.st_mtime_ns,
                         hashlib.md5(open(p, "rb").read()).hexdigest())
    # cancel: nothing after the first result that sees it
    seen = []
    def _cancel():
        return len(seen) >= 2
    for r in checksums.hash_files(paths, cancel=_cancel):
        seen.append(r)
    assert len(seen) == 2


def test_generate_checksums_cancel_keeps_a_partial_baseline_and_no_cache(tmp_path):
    root = str(tmp_path)
    _tree(root)
    calls = []
    def _cancel():
        calls.append(1)
        return len(calls) > 3
    n = checksums.generate_checksums(root, cancel=_cancel)
    assert 0 <= n < 70
    assert not os.path.exists(os.path.join(root, hashcache.CACHE_FILE))


@pytest.mark.parametrize("threads", [1, 4])
def test_unreadable_files_are_skipped_in_order(tmp_path, monkeypatch, threads):
    root = str(tmp_path)
    _tree(root)
    monkeypatch.setattr(checksums, "HASH_THREADS", threads)
    real = checksums._stat_and_md5
    def _flaky(path):
        if path.endswith("f04.wav"):
            raise OSError("locked")
        return real(path)
    monkeypatch.setattr(checksums, "_stat_and_md5", _flaky)
    logs = []
    n = checksums.generate_checksums(root, log_cb=lambda t, l="info": logs.append(t))
    assert n == 69
    base = checksums.read_checksums(root)
    assert "d1/sub0/f04.wav" not in base and len(base) == 69
    assert any("Skipping (cannot read): d1/sub0/f04.wav" in t for t in logs)
    assert "d1/sub0/f04.wav" not in hashcache.load(root)
