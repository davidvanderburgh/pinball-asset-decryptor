"""PAD-1507: Settings > Manage disk space > Card images - store card images
compact and make them full size again from the app."""

import hashlib
import os
import time
import zipfile

from pinball_decryptor.core import sparse_card as sc
from tests.webui_harness import web_app

MB = 1 << 20


def until(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _card(path):
    with open(path, "wb") as f:
        f.write(os.urandom(100_000))
        f.write(bytes(6 * MB))
        f.write(os.urandom(70_000))
        f.write(bytes(5 * MB))
        f.write(b"\x01" * 3)
    return path


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _cards(w):
    return w.state("shellx")["disk"]["cards"]


def _open(w):
    w.call("shellx.disk_open")
    assert until(w, lambda: not w.state("shellx")["disk"]["busy"])
    c = _cards(w)
    assert "compact" in c["note"] and c["status"] == "" and not c["busy"]


def _done(w):
    assert until(w, lambda: not _cards(w)["busy"] and _cards(w)["status"])
    return _cards(w)["status"]


def test_compact_a_folder_then_cards(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    a, b = _card(lib / "a.raw"), _card(lib / "b.img")
    (lib / "padkeys.json").write_text("{}")
    sums = _sha(a), _sha(b)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w)
        w.answers.append(str(lib))
        assert w.call("shellx.cards_compact_folder") is True
        text = _done(w)
        assert text.startswith("2 card images compact:") and "freed" in text
        assert (_sha(a), _sha(b)) == sums
        if sc.is_compact(str(a)):
            assert sc.on_disk_size(str(a)) < 2 * MB
        # again on the picked files: nothing more to free
        w.answers.append([str(a)])
        assert w.call("shellx.cards_compact_files") is True
        assert _done(w).startswith("1 card image compact:")
        assert w.call("shellx.disk_close") is True


def test_a_folder_without_cards_says_so(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _open(w)
        w.answers.extend([str(tmp_path), "ok"])
        assert w.call("shellx.cards_compact_folder") is False
        assert "no .raw or .img" in w.asked[-1]["message"]


def test_add_a_download_compact(tmp_path):
    src = _card(tmp_path / "new.raw")
    arc = tmp_path / "new.zip"
    with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "new.raw")
    lib = tmp_path / "lib"
    lib.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w)
        w.answers.extend([[str(arc)], str(lib)])
        assert w.call("shellx.cards_add") is True
        assert _done(w).startswith("new.raw added:")
        assert _sha(lib / "new.raw") == _sha(src)


def test_expand_to_a_copy_and_in_place(tmp_path):
    a = _card(tmp_path / "a.raw")
    h = _sha(a)
    sc.compact_file(str(a))
    out = tmp_path / "usb" / "a.raw"
    out.parent.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w)
        # Yes: a full-size copy elsewhere
        w.answers.extend([str(a), "yes", str(out)])
        assert w.call("shellx.cards_expand") is True
        assert _done(w).startswith("Full-size copy written:")
        assert _sha(out) == h
        assert not sc.is_compact(str(out))
        assert sc.is_compact(str(a)) or not sc.compact_file(str(a)).sparse_ok
        # No: the card itself
        w.answers.extend([str(a), "no"])
        assert w.call("shellx.cards_expand") is True
        assert "full size again" in _done(w)
        assert _sha(a) == h
        assert not sc.is_compact(str(a))
        # Cancel: nothing
        w.answers.extend([str(a), "cancel"])
        assert w.call("shellx.cards_expand") is False


def test_expand_refuses_without_room(tmp_path, monkeypatch):
    a = _card(tmp_path / "a.raw")
    import shutil
    from collections import namedtuple
    U = namedtuple("U", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(1, 1, 0))
    with web_app(tmp_path, mfr="stern") as w:
        _open(w)
        w.answers.extend([str(a), "yes", str(tmp_path / "b.raw"), "ok"])
        assert w.call("shellx.cards_expand") is True
        assert until(w, lambda: not _cards(w)["busy"])
        assert "free" in w.asked[-1]["message"]
        assert not (tmp_path / "b.raw").exists()
