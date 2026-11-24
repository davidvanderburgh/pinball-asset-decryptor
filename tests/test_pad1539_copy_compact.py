"""PAD-1539: copying a compact card keeps the copy compact, and a place
that cannot hold a compact card gets it as a zip.

Explorer's copy writes a compact card's holes back out (a 4 GB card holding
180 MB made a 4 GB copy on D:, in 29 s).  Right-click > Copy with PAD
(webui/open_image.py's verb, webui/compact_window.py's --copy window) copies
only the data with core.sparse_card.copy_card and leaves the original alone.

Google Drive (G:, which answers as FAT32 with no sparse files), a cloud
folder or an exFAT stick cannot hold a compact card at all: there Copy and
Move with PAD write ``<name>.zip`` (sparse_card.zip_card), the size of the
card's data, which sparse_card.import_card unpacks to the same card.
"""
import os
import re
import uuid
import zipfile

import pytest

from pinball_decryptor.core import sparse_card as sc
from pinball_decryptor.webui import compact_window as cw
from pinball_decryptor.webui import open_image as oi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MB = 1024 * 1024
WINDOWS = os.name == "nt"
APP_DIR = r"C:\Program Files\Pinball Asset Decryptor"
STAMP = 1_700_000_000 * 10 ** 9


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


@pytest.fixture(autouse=True)
def plain_folders(monkeypatch):
    """No test folder is a cloud folder unless the test says so."""
    monkeypatch.setattr(sc, "zip_reason", lambda d: "")


def _setup(tmp_path, compact=True):
    a, b = tmp_path / "c", tmp_path / "d"
    a.mkdir()
    b.mkdir()
    src = _card(a / "godzilla.raw")
    if compact:
        sc.compact_file(src)
    os.utime(src, ns=(STAMP, STAMP))
    return src, str(b)


# ------------------------------------------------------------ copy_card
def test_the_copy_is_compact_and_the_original_untouched(tmp_path):
    src, dest = _setup(tmp_path)
    body, before = _bytes(src), sc.on_disk_size(src)
    r = sc.copy_card(src, dest)
    dst = os.path.join(dest, "godzilla.raw")
    assert r.dst == dst and r.kept and not r.renamed and not r.zipped
    assert _bytes(src) == body and sc.on_disk_size(src) == before
    assert os.stat(src).st_mtime_ns == STAMP
    assert _bytes(dst) == body
    assert os.stat(dst).st_mtime_ns == STAMP
    assert not os.path.exists(dst + ".part")
    if before + sc.MIN_HOLE <= r.size:          # this filesystem has holes
        assert r.after + sc.MIN_HOLE <= r.size and r.sparse_ok
        assert "the copy is compact too" in cw.move_text(r, copied=True)
        assert "could not be removed" not in cw.move_text(r, copied=True)


def test_a_full_size_cards_copy_is_compact(tmp_path):
    src, dest = _setup(tmp_path, compact=False)
    r = sc.copy_card(src, dest)
    assert _bytes(r.dst) == _bytes(src)
    if r.after + sc.MIN_HOLE <= r.size:
        assert "the copy is compact" in cw.move_text(r, copied=True)


def test_a_copy_beside_the_original_is_named_as_explorer_names_one(tmp_path):
    src, _dest = _setup(tmp_path)
    here = os.path.dirname(src)
    r1 = sc.copy_card(src, here)
    r2 = sc.copy_card(src, here)
    assert os.path.basename(r1.dst) == "godzilla - Copy.raw"
    assert os.path.basename(r2.dst) == "godzilla - Copy (2).raw"
    assert _bytes(r2.dst) == _bytes(src)


def test_copy_refusals_write_nothing(tmp_path, monkeypatch):
    src, dest = _setup(tmp_path)
    _card(os.path.join(dest, "godzilla.raw"))
    with pytest.raises(FileExistsError):
        sc.copy_card(src, dest)
    os.remove(os.path.join(dest, "godzilla.raw"))
    import shutil
    from collections import namedtuple
    du = namedtuple("du", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: du(9, 9, 10))
    with pytest.raises(sc.NoRoom):
        sc.copy_card(src, dest)
    assert os.path.isfile(src) and os.listdir(dest) == []


def test_a_stopped_copy_removes_the_part(tmp_path):
    src, dest = _setup(tmp_path)

    class Stop(Exception):
        pass

    def cancel():
        raise Stop()

    for why in ("", "Google Drive"):
        with pytest.raises(Stop):
            sc.copy_card(src, dest, cancel=cancel, zipped=why)
        assert os.path.isfile(src) and os.listdir(dest) == []


# ------------------------------------------------------------ the zip
def test_a_place_without_compact_files_gets_a_zip(tmp_path):
    src, dest = _setup(tmp_path)
    body = _bytes(src)
    seen = []
    r = sc.copy_card(src, dest, zipped="Google Drive",
                     progress=lambda d, t: seen.append((d, t)))
    assert r.dst == os.path.join(dest, "godzilla.raw.zip")
    assert r.zipped == "Google Drive" and r.kept and r.sparse_ok
    assert r.after == os.path.getsize(r.dst)
    # the 6 MB of zeros went to next to nothing
    assert r.after < 400_000
    assert seen[-1] == (len(body), len(body))
    with zipfile.ZipFile(r.dst) as z:
        (m,) = z.infolist()
        assert m.filename == "godzilla.raw" and m.file_size == len(body)
        assert z.read(m) == body
        assert z.testzip() is None
    text = cw.move_text(r, copied=True)
    assert text.startswith("Copied as a zip: ")
    assert "Google Drive cannot keep a card compact" in text


def test_the_zip_comes_back_as_the_same_compact_card(tmp_path):
    src, dest = _setup(tmp_path)
    body = _bytes(src)
    r = sc.copy_card(src, dest, zipped="this exFAT drive")
    back = tmp_path / "back"
    back.mkdir()
    card = sc.import_card(r.dst, str(back))
    assert os.path.basename(card) == "godzilla.raw"
    assert _bytes(card) == body


def test_a_full_size_card_zips_small_too(tmp_path):
    src, dest = _setup(tmp_path, compact=False)
    r = sc.copy_card(src, dest, zipped="Dropbox")
    assert r.after < 400_000
    with zipfile.ZipFile(r.dst) as z:
        assert z.read("godzilla.raw") == _bytes(src)


def test_a_move_to_such_a_place_zips_then_removes_the_original(tmp_path):
    src, dest = _setup(tmp_path)
    body = _bytes(src)
    r = sc.move_card(src, dest, zipped="Google Drive")
    assert r.dst.endswith("godzilla.raw.zip") and not r.kept
    assert not r.renamed                # never a rename, same drive or not
    assert not os.path.exists(src)
    with zipfile.ZipFile(r.dst) as z:
        assert z.read("godzilla.raw") == body
    assert cw.move_text(r).startswith("Moved as a zip: ")


def test_a_zip_already_there_is_not_replaced(tmp_path):
    src, dest = _setup(tmp_path)
    there = os.path.join(dest, "godzilla.raw.zip")
    with open(there, "wb") as f:
        f.write(b"mine")
    with pytest.raises(FileExistsError):
        sc.move_card(src, dest, zipped="Google Drive")
    assert os.path.isfile(src) and _bytes(there) == b"mine"


def test_the_folder_decides(tmp_path, monkeypatch):
    src, dest = _setup(tmp_path)
    monkeypatch.setattr(sc, "zip_reason",
                        lambda d: "Google Drive" if d == dest else "")
    assert sc.copy_card(src, dest).dst.endswith(".raw.zip")
    assert sc.copy_card(src, os.path.dirname(src)).dst.endswith(
        " - Copy.raw")


# ------------------------------------------------------------ which places
def test_zip_reason_words(monkeypatch, tmp_path):
    monkeypatch.undo()                              # the real zip_reason
    facts = {}
    monkeypatch.setattr(sc, "volume_facts", lambda d: facts["v"])
    monkeypatch.setattr(sc, "cloud_roots", lambda: [
        (str(tmp_path / "OneDrive"), "OneDrive")])
    facts["v"] = ("Google Drive", "FAT32", False)
    assert sc.zip_reason("G:\\My Drive") == "Google Drive"
    facts["v"] = ("STICK", "exFAT", False)
    assert sc.zip_reason("F:\\") == "this exFAT drive"
    facts["v"] = ("Windows", "NTFS", True)
    assert sc.zip_reason(str(tmp_path / "cards")) == ""
    assert sc.zip_reason(str(tmp_path / "OneDrive" / "cards")) == "OneDrive"
    assert sc.zip_reason(str(tmp_path / "OneDrive")) == "OneDrive"
    assert sc.zip_reason(str(tmp_path / "OneDriveNot")) == ""


def test_a_mirrored_google_drive_folder_is_found(monkeypatch, tmp_path):
    import sqlite3
    monkeypatch.undo()
    local = tmp_path / "local"
    (local / "Google" / "DriveFS").mkdir(parents=True)
    mirror = tmp_path / "My Drive"
    con = sqlite3.connect(str(local / "Google" / "DriveFS"
                              / "root_preference_sqlite.db"))
    con.execute("create table roots (root_path text, "
                "last_seen_absolute_path text)")
    con.execute("insert into roots values (?, ?)", ("x", str(mirror)))
    con.commit()
    con.close()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "none"))
    assert sc.cloud_roots() == [(str(mirror), "Google Drive")]


def test_cloud_roots_never_raises(monkeypatch, tmp_path):
    monkeypatch.undo()
    local = tmp_path / "local"
    (local / "Google" / "DriveFS").mkdir(parents=True)
    (local / "Google" / "DriveFS" / "root_preference_sqlite.db"
     ).write_bytes(b"not a database")
    (local / "Dropbox").mkdir()
    (local / "Dropbox" / "info.json").write_text("{broken")
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "none"))
    assert sc.cloud_roots() == []


@pytest.mark.skipif(not WINDOWS, reason="the Windows volume flags")
def test_this_pcs_own_drive_holds_compact_files(monkeypatch):
    monkeypatch.undo()
    label, fs, sparse = sc.volume_facts(os.environ["SystemRoot"])
    assert fs == "NTFS" and sparse


# ------------------------------------------------------------ the window
def test_copy_window_words(tmp_path):
    src, dest = _setup(tmp_path)
    jobs = cw.CopyJobs(dest)
    jobs.add(src)
    jobs.wait(30)
    v = cw.view(jobs)
    assert not v["busy"] and not v["warn"]
    assert v["instruction"] == "godzilla.raw has its copy"
    assert ("From %s" % os.path.dirname(src)) in v["content"]
    assert ("To %s" % dest) in v["content"]
    assert jobs.title == cw.COPY_TITLE and jobs.note == cw.COPY_NOTE
    assert os.path.isfile(src)
    assert os.path.isfile(os.path.join(dest, "godzilla.raw"))


def test_copy_window_list_and_failures(tmp_path):
    src, dest = _setup(tmp_path)
    other = _card(tmp_path / "c" / "jaws.raw")
    _card(os.path.join(dest, "jaws.raw"))           # already there
    jobs = cw.CopyJobs(dest)
    jobs.add(src)
    jobs.add(other)
    jobs.wait(30)
    v = cw.view(jobs)
    assert v["warn"]
    assert v["instruction"] == ("1 of 2 card images copied to %s. 1 could "
                                "not be copied." % dest)
    assert "Nothing was copied." in v["content"]


def test_copy_window_says_it_is_a_zip(tmp_path, monkeypatch):
    src, dest = _setup(tmp_path)
    monkeypatch.setattr(sc, "zip_reason", lambda d: "Google Drive")
    for make, word in ((cw.CopyJobs, "Copied"), (cw.MoveJobs, "Moved")):
        jobs = make(dest)
        jobs.add(src)
        jobs.wait(30)
        v = cw.view(jobs)
        assert not v["warn"]
        assert ("%s as a zip: " % word) in v["content"]
        assert "Google Drive cannot keep a card compact" in v["content"]
        os.remove(os.path.join(dest, "godzilla.raw.zip")) \
            if make is cw.CopyJobs else None


def test_copy_error_words():
    assert cw.move_error_text(sc.NoRoom("G:\\ has 1.0 GB free; x"),
                              copied=True) == \
        "Not copied: G:\\ has 1.0 GB free; x."
    assert cw.move_error_text(PermissionError(13, "x"), copied=True
                              ).startswith("Could not copy it: ")
    assert cw.move_error_text(FileExistsError("x"), "D:\\cards", True) == \
        "D:\\cards already has a file of that name. Nothing was copied."


def test_plain_run_copies_with_to(tmp_path, monkeypatch):
    src, dest = _setup(tmp_path)
    monkeypatch.setattr(cw.sys, "platform", "linux")
    assert cw.main_copy([src, "--to", dest]) == 0
    assert os.path.isfile(os.path.join(dest, "godzilla.raw"))
    assert os.path.isfile(src)
    assert cw.main_copy([src]) == 2                 # no folder, no picker


@pytest.mark.skipif(not WINDOWS, reason="the copy window's mutex")
def test_cancelled_picker_copies_nothing(tmp_path, monkeypatch):
    src, dest = _setup(tmp_path)
    monkeypatch.setattr(cw, "spool_dir",
                        lambda name="x": str(tmp_path / "spool"))
    monkeypatch.setattr(cw, "COPY_MUTEX", "Local\\PADTest-%s"
                        % uuid.uuid4().hex)
    asked = []
    assert cw.main_copy([src], pick=lambda *a: asked.append(a)) == 0
    assert asked == [(os.path.dirname(src),
                      "Copy with PAD: choose the folder", "Copy here")]
    assert os.listdir(dest) == []


def test_copy_and_move_have_windows_of_their_own():
    assert cw.COPY_MUTEX != cw.MOVE_MUTEX != cw.MUTEX
    assert cw.COPY_QUEUE != cw.MOVE_QUEUE


# ------------------------------------------------------------ the wiring
def test_copy_verb_rows():
    table = {(k, n): d for k, n, d in oi.association_values(APP_DIR)}
    for ext in (".raw", ".img"):
        base = r"SystemFileAssociations\%s\shell\%s" % (ext, oi.COPY_VERB)
        assert table[(base, "")] == "Copy with PAD…"
        assert table[(base + r"\command", "")] == (
            'wscript.exe "%s\\launcher.vbs" "--copy" "%%1"' % APP_DIR)
    assert oi.COPY_FLAG == cw.COPY_FLAG


@pytest.mark.skipif(not WINDOWS, reason="the Windows registry")
def test_register_and_unregister_the_copy_verb():
    import winreg
    classes = r"Software\PADTest-%s\Classes" % uuid.uuid4().hex
    verb = r"SystemFileAssociations\.img\shell\%s" % oi.COPY_VERB

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


def test_launcher_does_not_elevate_a_copy():
    with open(os.path.join(ROOT, "installer", "launcher.vbs"),
              encoding="latin-1") as f:
        vbs = f.read()
    code = "\n".join(ln for ln in vbs.splitlines()
                     if not ln.lstrip().startswith("'"))
    # PAD-1563: no launch is elevated any more, this one included
    assert '"runas"' not in code
    assert 'pythonw.exe", params, appDir, "open", 1' in code


def test_both_entry_points_send_copy_to_its_window():
    for parts in (("Pinball Asset Decryptor.pyw",),
                  ("pinball_decryptor", "__main__.py")):
        src = _read(*parts)
        at = src.index('sys.argv[1] == "--copy"')
        assert at < src.index("dev_pick_checkout")
        assert "compact_window import main_copy" in src[at:at + 200]


def test_uninstall_removes_the_copy_verb_and_queue():
    with open(os.path.join(ROOT, "installer", "pinball_decryptor.iss"),
              encoding="latin-1") as f:
        iss = f.read()
    body = iss.split("procedure RemoveTheFileAssociation;", 1)[1]
    body = body.split("\nend;", 1)[0]
    assert oi.COPY_VERB in body
    assert r"{localappdata}\pinball_decryptor\copy_queue" in body
