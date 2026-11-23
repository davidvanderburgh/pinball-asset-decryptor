"""PAD-1522: right-click a card image in Explorer > Compact with PAD, and a
compact card's own icon.

The verb and the icon handler are registered with PAD-1514's association
(webui/open_image.py); the verb runs webui/compact_window.py in a window of
its own; the icon is answered per file by pinball_decryptor/shell/
padicon64.dll (tools/padicon), which these tests load and ask the way
Explorer does.
"""
import ctypes
import json
import os
import re
import sys
import threading
import time
import uuid

import pytest

from pinball_decryptor.core import sparse_card as sc
from pinball_decryptor.webui import compact_window as cw
from pinball_decryptor.webui import open_image as oi
from pinball_decryptor.webui import shell_icon as si

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MB = 1024 * 1024
WINDOWS = os.name == "nt"
APP_DIR = r"C:\Program Files\Pinball Asset Decryptor"


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _card(path, zeros=6 * MB):
    """Data, a long zero run, data: a card with something to free."""
    with open(path, "wb") as f:
        f.write(os.urandom(100_000))
        f.write(bytes(zeros))
        f.write(os.urandom(70_000))
    return str(path)


def _sparse_fs(tmp_path):
    p = tmp_path / "probe"
    with open(p, "wb") as f:
        f.write(b"x" + bytes(2 * sc.MIN_HOLE) + b"x")
    r = sc.compact_file(str(p))
    os.remove(p)
    return r.sparse_ok and r.holes > 0


# ---------------------------------------------------------------- the verb

def test_compact_verb_is_on_raw_and_img_only():
    rows = oi.association_values(APP_DIR)
    table = {(k, n): d for k, n, d in rows}
    for ext in (".raw", ".img"):
        base = r"SystemFileAssociations\%s\shell\%s" % (ext, oi.COMPACT_VERB)
        assert table[(base, "")] == "Compact with PAD"
        assert table[(base + r"\command", "")] == (
            'wscript.exe "%s\\launcher.vbs" "--compact" "%%1"' % APP_DIR)
    assert not any(".iso" in k and oi.COMPACT_VERB in k for k, _n, _d in rows)
    # the extensions are the ones the compact code calls a card image
    assert oi.COMPACT_EXTENSIONS == sc.IMAGE_SUFFIXES
    assert oi.COMPACT_FLAG == cw.FLAG


def test_launcher_does_not_elevate_a_compact():
    vbs = _read("installer", "launcher.vbs")
    code = "\n".join(ln for ln in vbs.splitlines()
                     if not ln.lstrip().startswith("'"))
    assert re.search(r'If WScript\.Arguments\(0\) = "--compact" Then '
                     r'compacting = True', code)
    # the compact launch is plain and ends the script; every other launch
    # is still the elevated one, shown (the last argument is 1)
    plain = code.index('pythonw.exe", params, appDir, "open", 1')
    quit_at = code.index("WScript.Quit")
    elevated = code.index('pythonw.exe", params, appDir, "runas", 1')
    assert code.index("If compacting Then") < plain < quit_at < elevated


def test_both_entry_points_send_compact_to_its_window():
    for parts in (("Pinball Asset Decryptor.pyw",),
                  ("pinball_decryptor", "__main__.py")):
        src = _read(*parts)
        at = src.index('sys.argv[1] == "--compact"')
        # before the app (and the dev checkout picker) is even imported
        assert at < src.index("dev_pick_checkout")
        assert "compact_window import main" in src[at:at + 200]


def test_uninstall_removes_the_verb_and_the_icon_class():
    iss = _read("installer", "pinball_decryptor.iss")
    body = iss.split("procedure RemoveTheFileAssociation;", 1)[1]
    body = body.split("\nend;", 1)[0]
    assert oi.COMPACT_VERB in body
    assert body.count(si.CLSID) == 2                # per user, per machine
    assert "HKEY_LOCAL_MACHINE" in body
    assert r"{localappdata}\pinball_decryptor\shell" in body


def test_icon_rows_only_with_a_handler():
    plain = {(k, n): d for k, n, d in oi.association_values(APP_DIR)}
    assert plain[(oi.PROGID + r"\DefaultIcon", "")].endswith(".ico")
    assert not any("CLSID" in k or "IconHandler" in k for k, _n in plain)
    rows = oi.association_values(APP_DIR, r"C:\stage\padicon64.dll")
    table = {(k, n): d for k, n, d in rows}     # the later row is kept
    assert table[(oi.PROGID + r"\DefaultIcon", "")] == "%1"
    assert table[(oi.PROGID + r"\ShellEx\IconHandler", "")] == si.CLSID
    assert table[("CLSID\\%s\\InprocServer32" % si.CLSID, "")] == \
        r"C:\stage\padicon64.dll"
    assert table[("CLSID\\%s\\InprocServer32" % si.CLSID,
                  "ThreadingModel")] == "Apartment"


@pytest.mark.skipif(not WINDOWS, reason="the Windows registry")
def test_register_and_unregister_round_trip_with_the_handler():
    import winreg
    classes = r"Software\PADTest-%s\Classes" % uuid.uuid4().hex
    hk = winreg.HKEY_CURRENT_USER

    def _get(sub, name=""):
        try:
            with winreg.OpenKey(hk, classes + "\\" + sub) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    verb = r"SystemFileAssociations\.raw\shell\%s" % oi.COMPACT_VERB
    clsid = "CLSID\\" + si.CLSID
    try:
        assert oi.register_association(
            APP_DIR, classes=classes, icon_dll=r"C:\stage\padicon64.dll")
        assert _get(verb) == "Compact with PAD"
        assert '"--compact" "%1"' in _get(verb + r"\command")
        assert _get(oi.PROGID + r"\DefaultIcon") == "%1"
        assert _get(oi.PROGID + r"\ShellEx\IconHandler") == si.CLSID
        assert _get(clsid + r"\InprocServer32") == r"C:\stage\padicon64.dll"
        # nothing to write the second time
        assert oi.register_association(
            APP_DIR, classes=classes,
            icon_dll=r"C:\stage\padicon64.dll") is False
        assert oi.unregister_association(classes) is True
        assert _get(verb) is None
        assert _get(clsid) is None
        assert _get(clsid + r"\InprocServer32") is None
        assert _get(oi.PROGID + r"\ShellEx\IconHandler") is None
    finally:
        root = classes.rsplit("\\", 1)[0]

        def _rm(path):
            try:
                with winreg.OpenKey(hk, path, 0, winreg.KEY_READ
                                    | winreg.KEY_WRITE) as k:
                    while True:
                        try:
                            _rm(path + "\\" + winreg.EnumKey(k, 0))
                        except OSError:
                            break
                winreg.DeleteKey(hk, path)
            except OSError:
                pass
        _rm(root)


def test_write_is_listed_once_on_a_raw_that_opens_with_pad():
    """Windows lists a verb once per NAME.  The double-click verb used to be
    "open" beside the right-click's own, and a .raw that opened with PAD
    showed "Write to a card with PAD" twice; now both carry one name."""
    rows = oi.association_values(APP_DIR)
    table = {(k, n): d for k, n, d in rows}
    assert table[(oi.PROGID + r"\shell", "")] == oi.VERB
    assert oi.OPEN_KEY == "\\shell\\" + oi.VERB
    assert table[(oi.PROGID + oi.OPEN_KEY + r"\command", "")] == \
        table[(r"SystemFileAssociations\.raw\shell\%s\command" % oi.VERB, "")]
    assert not any(k.startswith(oi.PROGID + oi.LEGACY_OPEN_KEY)
                   for k, _n, _d in rows)


@pytest.mark.skipif(not WINDOWS, reason="the Windows registry")
def test_an_older_registration_is_brought_over():
    """v1.573-v1.575 registered the double-click as shell\\open: it still
    counts as registered, and the next start replaces it."""
    import winreg
    classes = r"Software\PADTest-%s\Classes" % uuid.uuid4().hex
    hk = winreg.HKEY_CURRENT_USER
    old = classes + "\\" + oi.PROGID + oi.LEGACY_OPEN_KEY
    try:
        with winreg.CreateKeyEx(hk, old + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "old")
        assert oi.is_registered(classes) is True
        assert oi.register_association(APP_DIR, classes=classes) is True
        with pytest.raises(OSError):
            winreg.OpenKey(hk, old)
        assert oi.is_registered(classes) is True
        assert oi.register_association(APP_DIR, classes=classes) is False
        oi.unregister_association(classes)
        assert oi.is_registered(classes) is False
    finally:
        oi._del_tree(hk, classes.rsplit("\\", 1)[0])


# ---------------------------------------------------------------- the icon

def test_the_committed_dll_is_built_from_these_sources():
    """The DLL is prebuilt; a source edit without a rebuild fails here
    (python tools/padicon/build.py, commit the DLL and its .json)."""
    sys.path.insert(0, os.path.join(ROOT, "tools", "padicon"))
    try:
        import build as padicon_build
    finally:
        sys.path.pop(0)
    with open(os.path.join(ROOT, "pinball_decryptor", "shell",
                           "padicon64.json"), encoding="utf-8") as f:
        stamp = json.load(f)
    assert stamp["sources"] == padicon_build.source_hash()
    import hashlib
    with open(os.path.join(ROOT, "pinball_decryptor", "shell", si.DLL),
              "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == stamp["dll"]


def test_the_class_id_is_one_everywhere():
    c = _read("tools", "padicon", "padicon.c")
    m = re.search(r"CLSID_PadCardIcon =\s*\{0x([0-9a-f]+), 0x([0-9a-f]+), "
                  r"0x([0-9a-f]+), \{([^}]+)\}\}", c)
    tail = [int(x, 16) for x in m.group(4).split(",")]
    built = "{%08X-%04X-%04X-%02X%02X-%s}" % (
        int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16),
        tail[0], tail[1], "".join("%02X" % b for b in tail[2:]))
    assert built == si.CLSID
    assert si.ICON in c and si.ICON_COMPACT in c
    for _name, path in si.sources():
        assert os.path.isfile(path), path


def test_takes_less_follows_compact_and_expand(tmp_path):
    if not _sparse_fs(tmp_path):
        pytest.skip("this folder's drive keeps no holes")
    card = _card(tmp_path / "card.raw")
    assert sc.takes_less(card) is False
    assert si.icon_for(card) == si.ICON
    sc.compact_file(card)
    assert sc.takes_less(card) is True
    assert si.icon_for(card) == si.ICON_COMPACT
    sc.expand_file(card)
    assert sc.takes_less(card) is False
    assert sc.takes_less(str(tmp_path / "gone.raw")) is False


def test_stage_copies_once_and_drops_old_versions(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "shell").mkdir(parents=True)
    (pkg / "shell" / si.DLL).write_bytes(b"dll-one")
    (pkg / si.ICON).write_bytes(b"ico")
    (pkg / si.ICON_COMPACT).write_bytes(b"ico-compact")
    root = tmp_path / "stage"
    one = si.stage(str(pkg), str(root))
    assert os.path.basename(one) == si.DLL
    folder = os.path.dirname(one)
    assert sorted(os.listdir(folder)) == sorted(
        [si.DLL, si.ICON, si.ICON_COMPACT])
    assert si.stage(str(pkg), str(root)) == one        # the same files
    (pkg / "shell" / si.DLL).write_bytes(b"dll-two")
    two = si.stage(str(pkg), str(root))
    assert two != one
    assert os.listdir(root) == [os.path.basename(os.path.dirname(two))]
    # a build without the DLL stages nothing and says so with None
    os.remove(pkg / "shell" / si.DLL)
    assert si.stage(str(pkg), str(root)) is None
    si.unstage(str(root))
    assert not os.path.exists(root)


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        import uuid as _uuid
        return cls.from_buffer_copy(_uuid.UUID(text).bytes_le)


def _ask_handler(dll, path):
    """Ask the handler for *path*'s icon the way Explorer does: class
    factory > CreateInstance > IPersistFile::Load > IExtractIcon::
    GetIconLocation.  Returns (icon file, index, flags)."""
    HRESULT, P = ctypes.c_long, ctypes.c_void_p

    def method(obj, slot, *argtypes):
        vtbl = ctypes.cast(obj, ctypes.POINTER(P))[0]
        fn = ctypes.cast(vtbl, ctypes.POINTER(P))[slot]
        return ctypes.WINFUNCTYPE(HRESULT, P, *argtypes)(fn)

    clsid = _GUID.of(si.CLSID)
    iid_factory = _GUID.of("{00000001-0000-0000-C000-000000000046}")
    iid_persist = _GUID.of("{0000010B-0000-0000-C000-000000000046}")
    iid_extract = _GUID.of("{000214FA-0000-0000-C000-000000000046}")
    dll.DllGetClassObject.restype = HRESULT
    dll.DllGetClassObject.argtypes = [P, P, ctypes.POINTER(P)]
    factory = P()
    assert dll.DllGetClassObject(ctypes.byref(clsid),
                                 ctypes.byref(iid_factory),
                                 ctypes.byref(factory)) == 0
    persist = P()
    assert method(factory, 3, P, P, ctypes.POINTER(P))(
        factory, None, ctypes.byref(iid_persist), ctypes.byref(persist)) == 0
    assert method(persist, 5, ctypes.c_wchar_p, ctypes.c_uint32)(
        persist, path, 0) == 0                          # Load
    extract = P()
    assert method(persist, 0, P, ctypes.POINTER(P))(
        persist, ctypes.byref(iid_extract), ctypes.byref(extract)) == 0
    buf = ctypes.create_unicode_buffer(520)
    index, flags = ctypes.c_int(-1), ctypes.c_uint(0)
    hr = method(extract, 3, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint,
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint))(
        extract, 0, buf, 520, ctypes.byref(index), ctypes.byref(flags))
    assert hr == 0
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, P)
    for obj in (extract, persist):
        vtbl = ctypes.cast(obj, ctypes.POINTER(P))[0]
        release(ctypes.cast(vtbl, ctypes.POINTER(P))[2])(obj)
    return buf.value, index.value, flags.value


@pytest.mark.skipif(not WINDOWS or sys.maxsize < 2 ** 32,
                    reason="the 64-bit Windows icon handler")
def test_the_handler_names_the_compact_icon_for_a_compact_card(tmp_path):
    if not _sparse_fs(tmp_path):
        pytest.skip("this folder's drive keeps no holes")
    staged = si.stage(root=str(tmp_path / "stage"))
    assert staged
    dll = ctypes.WinDLL(staged)
    full = _card(tmp_path / "full.raw")
    compact = _card(tmp_path / "compact.raw")
    sc.compact_file(compact)
    folder = os.path.dirname(staged)
    GIL_PERINSTANCE = 0x2
    for path, want in ((full, si.ICON), (compact, si.ICON_COMPACT),
                       (str(tmp_path / "gone.raw"), si.ICON)):
        icon, index, flags = _ask_handler(dll, path)
        assert os.path.normcase(icon) == os.path.normcase(
            os.path.join(folder, want)), path
        assert os.path.isfile(icon)
        assert index == 0 and flags & GIL_PERINSTANCE
        # C and Python go by one rule
        assert want == si.icon_for(path)
    dll.PadIconTakesLess.argtypes = [ctypes.c_wchar_p]
    assert dll.PadIconTakesLess(compact) == 1
    assert dll.PadIconTakesLess(full) == 0
    # everything handed out was given back: Explorer may unload it
    dll.DllCanUnloadNow.restype = ctypes.c_long
    assert dll.DllCanUnloadNow() == 0
    # a class that is not ours is refused
    other = _GUID.of("{00000000-0000-0000-0000-000000000001}")
    iid = _GUID.of("{00000001-0000-0000-C000-000000000046}")
    out = ctypes.c_void_p()
    assert dll.DllGetClassObject(ctypes.byref(other), ctypes.byref(iid),
                                 ctypes.byref(out)) != 0


# ---------------------------------------------------------------- the window

class _Res:
    def __init__(self, size, before, after, sparse_ok=True):
        self.size, self.before, self.after = size, before, after
        self.sparse_ok = sparse_ok
        self.saved = max(0, before - after)


def test_result_wording():
    GB = 1024 ** 3
    assert cw.result_text(_Res(60 * GB, 60 * GB, 4 * GB)) == (
        "Compact: 4.00 GiB on disk for a 60.00 GiB card, 56.00 GiB freed.")
    assert cw.result_text(_Res(60 * GB, 4 * GB, 4 * GB)) == (
        "Already compact: 4.00 GiB on disk for a 60.00 GiB card.")
    assert cw.result_text(_Res(8 * GB, 8 * GB, 8 * GB)) == (
        "Nothing to free: this 8.00 GiB card is full of data.")
    assert "cannot hold compact files" in cw.result_text(
        _Res(8 * GB, 8 * GB, 8 * GB, sparse_ok=False))
    assert "another program is using" in cw.error_text(PermissionError(13))
    assert cw.error_text(FileNotFoundError(2)) == \
        "This file is no longer there."


def test_paths_on_the_command_line(tmp_path):
    a, b = str(tmp_path / "a.raw"), str(tmp_path / "b.img")
    assert cw.paths_arg(['"%s"' % a, "--x", b, a]) == [a, b]
    assert cw.paths_arg([]) == []
    assert cw.main([]) == 2


def _drain(jobs):
    out = []
    while not jobs.events.empty():
        out.append(jobs.events.get_nowait())
    return out


def test_jobs_run_in_turn_and_say_what_each_came_to(tmp_path):
    a = _card(tmp_path / "a.raw")
    b = _card(tmp_path / "b.raw")
    seen = []

    def fake(path, progress=None):
        seen.append(path)
        progress(1, 2)
        progress(2, 2)
        if path == b:
            raise PermissionError(13, "in use")
        return _Res(10 * MB, 10 * MB, 4 * MB)

    jobs = cw.Jobs(compact=fake)
    assert jobs.add(a) and jobs.add(b)
    jobs.add(str(tmp_path / "gone.raw"))
    jobs.wait(10)
    assert seen == [a, b]
    ja, jb, jc = jobs.jobs
    assert (ja.state, ja.pct, ja.saved) == (cw.DONE, 100, 6 * MB)
    assert ja.text.startswith("Compact: 4.0 MiB on disk")
    assert jb.state == cw.FAILED and "another program" in jb.text
    assert jc.state == cw.FAILED and "no longer there" in jc.text
    assert not jobs.busy
    assert jobs.summary() == ("1 of 3 card images done, 6.0 MiB freed. "
                              "2 could not be compacted.")
    whats = [w for j, w in _drain(jobs) if j is ja]
    assert whats[0] == "added" and whats[-1] == "end" and "progress" in whats
    # a card done once can be asked for again; one still waiting cannot
    assert jobs.add(a) is True
    jobs.wait(10)


def test_the_same_card_twice_is_one_job_and_stop_leaves_it_alone(tmp_path):
    a = _card(tmp_path / "a.raw")
    gate, entered = threading.Event(), threading.Event()

    def slow(path, progress=None):
        entered.set()
        gate.wait(10)
        progress(1, 2)                      # raises Stopped once stopping
        return _Res(10 * MB, 10 * MB, 4 * MB)

    jobs = cw.Jobs(compact=slow)
    assert jobs.add(a) is True
    assert entered.wait(10)
    assert jobs.add(a) is False
    b = _card(tmp_path / "b.raw")
    assert jobs.add(b) is True
    jobs.stop()
    gate.set()
    jobs.wait(10)
    assert [j.state for j in jobs.jobs] == [cw.STOPPED, cw.STOPPED]
    assert "as it was" in jobs.jobs[0].text


def test_a_real_card_is_compacted_where_it_is(tmp_path):
    if not _sparse_fs(tmp_path):
        pytest.skip("this folder's drive keeps no holes")
    import hashlib
    card = _card(tmp_path / "card.raw")
    with open(card, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    mtime = os.path.getmtime(card)
    jobs = cw.Jobs()
    jobs.add(card)
    jobs.wait(30)
    job = jobs.jobs[0]
    assert job.state == cw.DONE and job.saved >= 5 * MB
    assert job.text.startswith("Compact: ")
    with open(card, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == sha
    assert os.path.getmtime(card) == mtime
    assert sc.takes_less(card)
    # again: nothing more to free, and it says so
    jobs.add(card)
    jobs.wait(30)
    assert jobs.jobs[1].text.startswith("Already compact: ")


def test_a_later_launch_hands_its_card_to_the_window(tmp_path):
    spool = str(tmp_path / "queue")
    got = []

    def window():
        end = time.monotonic() + 5
        while time.monotonic() < end and not got:
            got.extend(cw.take_handed(spool))
            time.sleep(0.02)

    t = threading.Thread(target=window)
    t.start()
    assert cw.hand_over([r"C:\cards\a.raw", r"C:\cards\b.raw"], spool,
                        wait=5) is True
    t.join(10)
    assert got == [r"C:\cards\a.raw", r"C:\cards\b.raw"]
    # no window to take it: False, and nothing left for a later one to find
    assert cw.hand_over([r"C:\cards\c.raw"], spool, wait=0.2) is False
    assert cw.take_handed(spool) == []


@pytest.mark.skipif(not WINDOWS, reason="Explorer's one launch per file")
def test_only_one_window_at_a_time(monkeypatch):
    monkeypatch.setattr(cw, "MUTEX", "Local\\PADTest-" + uuid.uuid4().hex)
    first = cw.claim()
    try:
        assert first is not None
        assert cw.claim() is None
    finally:
        cw.release(first)
    again = cw.claim()
    assert again is not None
    cw.release(again)


def test_what_the_window_says_for_one_card_and_for_several(tmp_path):
    a = _card(tmp_path / "a.raw")
    b = _card(tmp_path / "b.raw")
    gate, entered = threading.Event(), threading.Event()

    def fake(path, progress=None):
        progress(43, 100)
        if path == a:
            entered.set()
            gate.wait(10)
        if path == b:
            raise PermissionError(13, "in use")
        return _Res(10 * MB, 10 * MB, 4 * MB)

    jobs = cw.Jobs(compact=fake)
    jobs.add(a)
    assert entered.wait(10)
    v = cw.view(jobs)
    assert v["busy"] and v["pct"] == 43 and not v["warn"]
    assert v["instruction"] == "Compacting a.raw"
    assert v["content"] == "%s\n\nReading the card… 43%%" % tmp_path
    gate.set()
    jobs.wait(10)
    v = cw.view(jobs)
    assert not v["busy"] and not v["warn"]
    assert v["instruction"] == "a.raw is stored compact"
    assert v["content"].endswith("Compact: 4.0 MiB on disk for a 10.0 MiB "
                                 "card, 6.0 MiB freed.")
    # a second card joins (a later launch handed it over) and fails
    jobs.add(b)
    jobs.wait(10)
    v = cw.view(jobs)
    assert v["warn"] and not v["busy"]
    assert v["instruction"] == ("1 of 2 card images done, 6.0 MiB freed. "
                                "1 could not be compacted.")
    lines = v["content"].split("\n")
    assert lines[0] == "✓  a.raw" and lines[2] == "✕  b.raw"
    assert "another program" in lines[3]


def test_no_window_elsewhere_prints_each_card(tmp_path):
    import io
    a = _card(tmp_path / "a.raw")
    jobs = cw.Jobs(compact=lambda p, progress=None: _Res(10 * MB, 10 * MB,
                                                         4 * MB))
    jobs.add(a)
    out = io.StringIO()
    assert cw.run_plain(jobs, out) == 0
    assert out.getvalue().startswith("a.raw: Compact: 4.0 MiB on disk")


@pytest.mark.skipif(not WINDOWS, reason="the Windows task dialog")
def test_the_dialog_shows_working_then_done_and_closes(tmp_path):
    """The real dialog, off screen: it is built, turns from its working
    page to its done page when the card is, and its button closes it.  The
    shipped Python has no Tk, so this is all ctypes; the struct must be the
    size Windows expects or nothing shows at all."""
    _Button, Config, _cb = cw._structs()
    assert ctypes.sizeof(Config) == (160 if sys.maxsize > 2 ** 32 else 96)
    a = _card(tmp_path / "a.raw")
    spool = str(tmp_path / "queue")
    b = _card(tmp_path / "b.raw")

    def fake(path, progress=None):
        for i in range(1, 4):
            time.sleep(0.1)
            progress(i, 3)
        return _Res(10 * MB, 10 * MB, 4 * MB)

    jobs = cw.Jobs(compact=fake)
    pages, sent = [], []

    def created(hwnd):
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(hwnd), None, -6000, 200, 0, 0, 0x1 | 0x4 | 0x10)

    def page(_hwnd, v):
        pages.append(v)
        if v["busy"]:
            return
        if not sent:
            # a later launch hands a second card to this window
            sent.append(threading.Thread(
                target=lambda: sent.append(cw.hand_over([b], spool, wait=10))))
            sent[0].start()
        else:
            win.close()

    win = cw.TaskWindow(jobs, spool=spool, on_created=created, on_page=page)
    jobs.add(a)
    assert win.run() is True
    sent[0].join(10)
    assert sent[1] is True
    assert [p["busy"] for p in pages] == [False, True, False]
    assert pages[0]["instruction"] == "a.raw is stored compact"
    assert pages[-1]["instruction"] == "2 of 2 card images done, 12.0 MiB freed."
    assert [j.state for j in jobs.jobs] == [cw.DONE, cw.DONE]
