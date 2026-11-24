"""PAD-1535: moving a compact card keeps it compact.

Explorer's move to another drive is a copy that writes a compact card's holes
back out (a 4 GB card holding 180 MB arrived taking 4 GB, in 50-70 s).
Right-click > Move with PAD (webui/open_image.py's verb, webui/
compact_window.py's --move window) moves it with core.sparse_card.move_card:
a rename on the same drive, only the data copied to another one.
"""
import os
import re
import uuid

import pytest

from pinball_decryptor.core import sparse_card as sc
from pinball_decryptor.webui import compact_window as cw
from pinball_decryptor.webui import open_image as oi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MB = 1024 * 1024
WINDOWS = os.name == "nt"
APP_DIR = r"C:\Program Files\Pinball Asset Decryptor"


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _card(path, zeros=6 * MB):
    with open(path, "wb") as f:
        f.write(os.urandom(100_000))
        f.write(bytes(zeros))
        f.write(os.urandom(70_000))
    return str(path)


def _bytes(p):
    with open(p, "rb") as f:
        return f.read()


@pytest.fixture
def other_drive(monkeypatch):
    """Every move is to 'another drive': the copy path, in one tmp dir."""
    monkeypatch.setattr(sc, "_same_volume", lambda a, b: False)


def _setup(tmp_path, compact=True):
    a, b = tmp_path / "c", tmp_path / "d"
    a.mkdir()
    b.mkdir()
    src = _card(a / "godzilla.raw")
    if compact:
        sc.compact_file(src)
    os.utime(src, ns=(1_700_000_000 * 10 ** 9, 1_700_000_000 * 10 ** 9))
    return src, str(b)


# ------------------------------------------------------------ move_card
def test_another_drive_copies_the_data_and_keeps_it_compact(tmp_path,
                                                            other_drive):
    src, dest = _setup(tmp_path)
    body, before = _bytes(src), sc.on_disk_size(src)
    r = sc.move_card(src, dest)
    dst = os.path.join(dest, "godzilla.raw")
    assert r.dst == dst and not r.renamed and not r.kept
    assert not os.path.exists(src)
    assert not os.path.exists(dst + ".part")
    assert _bytes(dst) == body
    assert os.stat(dst).st_mtime_ns == 1_700_000_000 * 10 ** 9
    if before + sc.MIN_HOLE <= r.size:          # this filesystem has holes
        assert r.after + sc.MIN_HOLE <= r.size
        assert r.sparse_ok
        assert "still compact" in cw.move_text(r)


def test_a_full_size_card_arrives_compact(tmp_path, other_drive):
    src, dest = _setup(tmp_path, compact=False)
    body = _bytes(src)
    r = sc.move_card(src, dest)
    assert _bytes(r.dst) == body
    if r.after + sc.MIN_HOLE <= r.size:
        assert "now compact" in cw.move_text(r)


def test_the_same_drive_is_a_rename(tmp_path):
    src, dest = _setup(tmp_path)
    copied = []
    r = sc.move_card(src, dest, copy=lambda *a, **k: copied.append(a))
    assert r.renamed and not copied
    assert os.path.isfile(r.dst) and not os.path.exists(src)
    assert "the very same file" in cw.move_text(r)


def test_refusals_leave_the_card_where_it_was(tmp_path, other_drive,
                                              monkeypatch):
    src, dest = _setup(tmp_path)
    with pytest.raises(sc.SameFolder):
        sc.move_card(src, os.path.dirname(src))
    _card(os.path.join(dest, "godzilla.raw"))
    with pytest.raises(FileExistsError):
        sc.move_card(src, dest)
    os.remove(os.path.join(dest, "godzilla.raw"))
    import shutil
    from collections import namedtuple
    du = namedtuple("du", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: du(9, 9, 10))
    with pytest.raises(sc.NoRoom) as e:
        sc.move_card(src, dest)
    assert "the card's data needs" in str(e.value)
    assert os.path.isfile(src) and os.listdir(dest) == []


def test_stopped_part_way_removes_the_part(tmp_path, other_drive):
    src, dest = _setup(tmp_path)

    class Stop(Exception):
        pass

    def cancel():
        raise Stop()

    with pytest.raises(Stop):
        sc.move_card(src, dest, cancel=cancel)
    assert os.path.isfile(src) and os.listdir(dest) == []


def test_an_original_in_use_is_kept(tmp_path, other_drive, monkeypatch):
    src, dest = _setup(tmp_path)
    real = os.remove

    def remove(p):
        if os.path.abspath(p) == os.path.abspath(src):
            raise PermissionError(13, "in use")
        real(p)

    monkeypatch.setattr(sc.os, "remove", remove)
    r = sc.move_card(src, dest)
    assert r.kept and os.path.isfile(src) and os.path.isfile(r.dst)
    assert "could not be removed" in cw.move_text(r)


# ------------------------------------------------------------ the window
def test_move_window_words(tmp_path, other_drive):
    src, dest = _setup(tmp_path)
    jobs = cw.MoveJobs(dest)
    jobs.add(src)
    jobs.wait(30)
    v = cw.view(jobs)
    assert not v["busy"] and not v["warn"]
    assert v["instruction"] == "godzilla.raw is in its new folder"
    # where it came from, not where it is now
    assert ("From %s" % os.path.dirname(src)) in v["content"]
    assert ("To %s" % dest) in v["content"]
    assert jobs.title == cw.MOVE_TITLE and jobs.note == cw.MOVE_NOTE


def test_move_window_list_and_failures(tmp_path, other_drive):
    src, dest = _setup(tmp_path)
    other = _card(tmp_path / "c" / "jaws.raw")
    _card(os.path.join(dest, "jaws.raw"))           # already there
    jobs = cw.MoveJobs(dest)
    jobs.add(src)
    jobs.add(other)
    jobs.wait(30)
    v = cw.view(jobs)
    assert v["warn"]
    assert v["instruction"] == ("1 of 2 card images moved to %s. 1 could "
                                "not be moved." % dest)
    assert "already has a file of that name" in v["content"]
    assert os.path.isfile(other)


def test_error_words():
    assert cw.move_error_text(sc.SameFolder("x")) == \
        "It is already in that folder."
    assert cw.move_error_text(FileNotFoundError("x")) == \
        "This file is no longer there."
    assert cw.move_error_text(sc.NoRoom("D:\\ has 1.0 GB free; x")) == \
        "Not moved: D:\\ has 1.0 GB free; x."


def test_command_line():
    argv = ["a.raw", "--to", "D:\\cards", "b.raw"]
    assert [os.path.basename(p) for p in cw.paths_arg(argv)] == \
        ["a.raw", "b.raw"]
    assert cw.to_arg(argv) == os.path.abspath("D:\\cards")
    assert cw.to_arg(["a.raw"]) is None


def test_plain_run_moves_with_to(tmp_path, other_drive, monkeypatch):
    src, dest = _setup(tmp_path)
    monkeypatch.setattr(cw.sys, "platform", "linux")
    assert cw.main_move([src, "--to", dest]) == 0
    assert os.path.isfile(os.path.join(dest, "godzilla.raw"))
    assert cw.main_move([src]) == 2                 # no folder, no picker


@pytest.mark.skipif(not WINDOWS, reason="the move window's mutex")
def test_cancelled_picker_moves_nothing(tmp_path, monkeypatch):
    src, _dest = _setup(tmp_path)
    monkeypatch.setattr(cw, "spool_dir",
                        lambda name="x": str(tmp_path / "spool"))
    monkeypatch.setattr(cw, "MOVE_MUTEX", "Local\\PADTest-%s"
                        % uuid.uuid4().hex)
    asked = []
    assert cw.main_move([src], pick=lambda start: asked.append(start)) == 0
    assert asked == [os.path.dirname(src)]
    assert os.path.isfile(src)


@pytest.mark.skipif(not WINDOWS, reason="hand-over between launches")
def test_cards_handed_over_while_picking_join_the_move(tmp_path,
                                                       monkeypatch):
    spool = str(tmp_path / "spool")
    second = _card(tmp_path / "jaws.raw")
    g = cw._Gatherer(spool)
    assert cw.hand_over([second], spool, wait=5)    # taken at once
    assert g.stop() == [second]


# ------------------------------------------------------------ the wiring
def test_move_verb_rows():
    table = {(k, n): d for k, n, d in oi.association_values(APP_DIR)}
    for ext in (".raw", ".img"):
        base = r"SystemFileAssociations\%s\shell\%s" % (ext, oi.MOVE_VERB)
        assert table[(base, "")] == "Move with PAD…"
        assert table[(base + r"\command", "")] == (
            'wscript.exe "%s\\launcher.vbs" "--move" "%%1"' % APP_DIR)
    assert oi.MOVE_FLAG == cw.MOVE_FLAG


@pytest.mark.skipif(not WINDOWS, reason="the Windows registry")
def test_register_and_unregister_the_move_verb():
    import winreg
    classes = r"Software\PADTest-%s\Classes" % uuid.uuid4().hex
    verb = r"SystemFileAssociations\.img\shell\%s" % oi.MOVE_VERB

    def there():
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           classes + "\\" + verb).Close()
            return True
        except OSError:
            return False

    try:
        assert oi.register_association(APP_DIR, classes=classes)
        assert there()
        oi.unregister_association(classes=classes)
        assert not there()
    finally:
        oi._del_tree(winreg.HKEY_CURRENT_USER,
                     r"Software\PADTest-%s" % classes.split("-")[1]
                     .split("\\")[0])


def test_launcher_does_not_elevate_a_move():
    vbs = _read("installer", "launcher.vbs")
    code = "\n".join(ln for ln in vbs.splitlines()
                     if not ln.lstrip().startswith("'"))
    assert re.search(r'If WScript\.Arguments\(0\) = "--move" Then '
                     r'compacting = True', code)


def test_both_entry_points_send_move_to_its_window():
    for parts in (("Pinball Asset Decryptor.pyw",),
                  ("pinball_decryptor", "__main__.py")):
        src = _read(*parts)
        at = src.index('sys.argv[1] == "--move"')
        assert at < src.index("dev_pick_checkout")
        assert "compact_window import main_move" in src[at:at + 200]


def test_uninstall_removes_the_move_verb_and_queue():
    iss = _read("installer", "pinball_decryptor.iss")
    body = iss.split("procedure RemoveTheFileAssociation;", 1)[1]
    body = body.split("\nend;", 1)[0]
    assert oi.MOVE_VERB in body
    assert r"{localappdata}\pinball_decryptor\move_queue" in body
