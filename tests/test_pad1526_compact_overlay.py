"""PAD-1526: the compact badge is an icon OVERLAY, so an open Explorer window
follows a card being compacted.

Explorer keeps the icon it was given for a file for as long as the file's
name, size and modified time stay the same, and compacting or expanding a
card changes none of them: the icon that carried the badge stayed wrong until
Explorer restarted.  An overlay is asked again whenever Explorer is told the
file changed.  These tests ask the built handler (tools/padicon) the way
Explorer does and check the rows that list it.
"""
import ctypes
import os
import re
import sys
import threading
import time

import pytest

from pinball_decryptor.core import sparse_card as sc
from pinball_decryptor.webui import compact_window as cw
from pinball_decryptor.webui import open_image as oi
from pinball_decryptor.webui import shell_icon as si

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = sys.platform == "win32"
MB = 1024 * 1024
HANDLER = pytest.mark.skipif(not WINDOWS or sys.maxsize < 2 ** 32,
                             reason="the 64-bit Windows icon handler")
S_OK, S_FALSE = 0, 1
P = ctypes.c_void_p
HRESULT = ctypes.c_long


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _card(path, zeros=6 * MB):
    with open(path, "wb") as f:
        f.write(os.urandom(MB))
        f.write(bytes(zeros))
        f.write(os.urandom(MB))
    return str(path)


def _sparse_fs(tmp_path):
    probe = _card(tmp_path / "probe.bin")
    try:
        sc.compact_file(probe)
        return sc.takes_less(probe)
    finally:
        os.remove(probe)


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


def _method(obj, slot, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(P))[0]
    fn = ctypes.cast(vtbl, ctypes.POINTER(P))[slot]
    return ctypes.WINFUNCTYPE(HRESULT, P, *argtypes)(fn)


def _release(obj):
    vtbl = ctypes.cast(obj, ctypes.POINTER(P))[0]
    ctypes.WINFUNCTYPE(ctypes.c_ulong, P)(
        ctypes.cast(vtbl, ctypes.POINTER(P))[2])(obj)


def _create(dll, iid_text):
    """One object of the handler's class, as the interface *iid_text*."""
    clsid = _GUID.of(si.CLSID)
    iid_factory = _GUID.of("{00000001-0000-0000-C000-000000000046}")
    iid = _GUID.of(iid_text)
    dll.DllGetClassObject.restype = HRESULT
    dll.DllGetClassObject.argtypes = [P, P, ctypes.POINTER(P)]
    factory = P()
    assert dll.DllGetClassObject(ctypes.byref(clsid),
                                 ctypes.byref(iid_factory),
                                 ctypes.byref(factory)) == 0
    obj = P()
    assert _method(factory, 3, P, P, ctypes.POINTER(P))(
        factory, None, ctypes.byref(iid), ctypes.byref(obj)) == 0
    return obj


IID_OVERLAY = "{0C6C4200-C589-11D0-999A-00C04FD655E1}"
IID_PERSIST = "{0000010B-0000-0000-C000-000000000046}"
IID_EXTRACT = "{000214FA-0000-0000-C000-000000000046}"


def _icon_named(dll, path):
    persist = _create(dll, IID_PERSIST)
    assert _method(persist, 5, ctypes.c_wchar_p, ctypes.c_uint32)(
        persist, path, 0) == 0
    extract = P()
    iid = _GUID.of(IID_EXTRACT)
    assert _method(persist, 0, P, ctypes.POINTER(P))(
        persist, ctypes.byref(iid), ctypes.byref(extract)) == 0
    buf = ctypes.create_unicode_buffer(520)
    index, flags = ctypes.c_int(-1), ctypes.c_uint(0)
    assert _method(extract, 3, ctypes.c_uint, ctypes.c_wchar_p,
                   ctypes.c_uint, ctypes.POINTER(ctypes.c_int),
                   ctypes.POINTER(ctypes.c_uint))(
        extract, 0, buf, 520, ctypes.byref(index), ctypes.byref(flags)) == 0
    _release(extract)
    _release(persist)
    return os.path.basename(buf.value)


@HANDLER
def test_the_overlay_follows_a_card_compacted_and_expanded(tmp_path):
    if not _sparse_fs(tmp_path):
        pytest.skip("this folder's drive keeps no holes")
    staged = si.stage(root=str(tmp_path / "stage"))
    assert staged
    dll = ctypes.WinDLL(staged)
    card = _card(tmp_path / "card.raw")
    img = _card(tmp_path / "card.IMG")
    other = _card(tmp_path / "notes.bin")
    stamp = os.stat(card).st_mtime_ns
    overlay = _create(dll, IID_OVERLAY)
    member = _method(overlay, 3, ctypes.c_wchar_p, ctypes.c_uint32)
    assert member(overlay, card, 0) == S_FALSE
    sc.compact_file(card)
    sc.compact_file(img)
    sc.compact_file(other)
    # the same question, a different answer, and the card's date never moved:
    # this is what an icon could not do
    assert os.stat(card).st_mtime_ns == stamp
    assert member(overlay, card, 0) == S_OK
    assert member(overlay, img, 0) == S_OK
    # only a card image: a compact file of another kind has no badge
    assert sc.takes_less(other) is True
    assert member(overlay, other, 0) == S_FALSE
    assert member(overlay, str(tmp_path / "gone.raw"), 0) == S_FALSE
    assert member(overlay, "", 0) == S_FALSE
    assert member(overlay, None, 0) == S_FALSE
    sc.expand_file(card)
    assert member(overlay, card, 0) == S_FALSE
    # the picture: the badge beside the DLL
    buf = ctypes.create_unicode_buffer(520)
    index, flags = ctypes.c_int(-1), ctypes.c_uint32(0)
    assert _method(overlay, 4, ctypes.c_wchar_p, ctypes.c_int,
                   ctypes.POINTER(ctypes.c_int),
                   ctypes.POINTER(ctypes.c_uint32))(
        overlay, buf, 520, ctypes.byref(index), ctypes.byref(flags)) == 0
    assert os.path.normcase(buf.value) == os.path.normcase(
        os.path.join(os.path.dirname(staged), si.ICON_BADGE))
    assert os.path.isfile(buf.value)
    assert index.value == 0 and flags.value == 1          # ISIOI_ICONFILE
    # no room for the name: refused, nothing written past the buffer
    small = ctypes.create_unicode_buffer(8)
    assert _method(overlay, 4, ctypes.c_wchar_p, ctypes.c_int,
                   ctypes.POINTER(ctypes.c_int),
                   ctypes.POINTER(ctypes.c_uint32))(
        overlay, small, 8, ctypes.byref(index), ctypes.byref(flags)) != 0
    priority = ctypes.c_int(-1)
    assert _method(overlay, 5, ctypes.POINTER(ctypes.c_int))(
        overlay, ctypes.byref(priority)) == 0
    assert priority.value == 0
    _release(overlay)
    dll.DllCanUnloadNow.restype = ctypes.c_long
    assert dll.DllCanUnloadNow() == 0


@HANDLER
def test_the_icon_leaves_the_badge_to_a_live_overlay(tmp_path):
    """Where Explorer has the overlay, the icon is the plain card whatever
    the card's state (a kept icon can then never be the wrong one); where it
    has not, the icon carries the badge as it did."""
    if not _sparse_fs(tmp_path):
        pytest.skip("this folder's drive keeps no holes")
    staged = si.stage(root=str(tmp_path / "stage"))
    dll = ctypes.WinDLL(staged)
    dll.PadIconOverlayLive.argtypes = [ctypes.c_int]
    dll.PadIconOverlayLive.restype = ctypes.c_int
    compact = _card(tmp_path / "compact.raw")
    sc.compact_file(compact)
    full = _card(tmp_path / "full.raw")
    try:
        assert dll.PadIconOverlayLive(1) == 1
        assert _icon_named(dll, compact) == si.ICON
        assert _icon_named(dll, full) == si.ICON
        assert dll.PadIconOverlayLive(0) == 0
        assert _icon_named(dll, compact) == si.ICON_COMPACT
        assert _icon_named(dll, full) == si.ICON
    finally:
        dll.PadIconOverlayLive(-1)


def test_the_overlay_is_listed_under_one_name_everywhere():
    c = _read("tools", "padicon", "padicon.c")
    name = re.search(r'OVERLAY_NAME\[\] = L"([^"]+)"', c).group(1)
    assert name == si.OVERLAY_NAME
    # sorted early: Windows takes the list in name order until it is full
    assert name.startswith("     ") and name.strip() == "PinballCardCompact"
    listed = "".join(re.findall(r'L"([^"]*)"', c[c.index("OVERLAY_LIST[]"):
                                                  c.index("OVERLAY_NAME[]")]))
    assert listed.replace("\\\\", "\\") == si.OVERLAY_KEY
    assert si.overlay_values() == [
        (si.OVERLAY_KEY + "\\" + si.OVERLAY_NAME, "", si.CLSID)]
    assert si.ICON_BADGE in c
    iss = _read("installer", "pinball_decryptor.iss")
    assert "ShellIconOverlayIdentifiers" in iss
    assert "'" + si.OVERLAY_NAME + "'" in iss
    # the extensions the overlay answers for are the ones Compact is on
    for ext in oi.COMPACT_EXTENSIONS:
        assert 'L"%s"' % ext in c
    assert len(re.findall(r'lstrcmpiW\(path \+ n - 4, L"\.', c)) == len(
        oi.COMPACT_EXTENSIONS)


def test_the_badge_is_staged_with_the_handler(tmp_path):
    names = [n for n, _p in si.sources()]
    assert si.ICON_BADGE in names
    for _name, path in si.sources():
        assert os.path.isfile(path), path


def test_the_badge_keeps_to_a_corner_at_small_sizes():
    """A small icon's overlay is drawn over all of it: a disc that filled the
    picture hid the card in a details list."""
    Image = pytest.importorskip("PIL.Image")
    path = dict(si.sources())[si.ICON_BADGE]
    with Image.open(path) as im:
        sizes = sorted(im.info["sizes"])
    assert (16, 16) in sizes and (256, 256) in sizes
    for size in sizes:
        with Image.open(path) as im:
            im.size = size
            im.load()
            rgba = im.convert("RGBA")
        s = size[0]
        corner = rgba.getpixel((s // 4, s - 1 - s // 4))[3]
        top_right = rgba.getpixel((s - 1 - s // 4, s // 4))[3]
        assert corner == 255, size
        if s <= 32:
            assert top_right == 0, size
        else:
            assert top_right == 255, size


def test_the_overlay_row_is_written_once_and_taken_away(monkeypatch):
    """The key's date tells the handler whether Explorer started with it, so
    a key that is already right is not written again."""
    winreg = pytest.importorskip("winreg")
    calls = {"create": 0, "delete": []}
    store = {}
    path = si.OVERLAY_KEY + "\\" + si.OVERLAY_NAME

    class _Key:
        def __init__(self, p):
            self.p = p

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def open_key(root, p, *a):
        assert root == winreg.HKEY_LOCAL_MACHINE
        if p not in store:
            raise OSError(2, "no key")
        return _Key(p)

    def create_key(root, p, *a):
        assert root == winreg.HKEY_LOCAL_MACHINE
        calls["create"] += 1
        store.setdefault(p, {})
        return _Key(p)

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(winreg, "CreateKeyEx", create_key)
    monkeypatch.setattr(winreg, "QueryValueEx",
                        lambda k, n: (store[k.p][n], 1))
    monkeypatch.setattr(winreg, "SetValueEx",
                        lambda k, n, r, t, d: store[k.p].__setitem__(n, d))
    oi._machine_overlay()
    assert store == {path: {"": si.CLSID}} and calls["create"] == 1
    oi._machine_overlay()
    assert calls["create"] == 1
    # a run without the rights changes nothing and says nothing

    def refused(*a):
        raise PermissionError(5, "denied")

    store.clear()
    monkeypatch.setattr(winreg, "CreateKeyEx", refused)
    oi._machine_overlay()
    assert store == {}


# ------------------------------------------------- the offer to restart Explorer

class _Res:
    def __init__(self, size, before, after, sparse_ok=True):
        self.size, self.before, self.after = size, before, after
        self.sparse_ok = sparse_ok
        self.saved = max(0, before - after)


def _done_jobs(tmp_path, n=1):
    jobs = cw.Jobs(compact=lambda p, progress=None: _Res(10 * MB, 10 * MB,
                                                         4 * MB))
    for i in range(n):
        jobs.add(_card(tmp_path / ("card%d.raw" % i), zeros=MB))
    jobs.wait(10)
    return jobs


def test_explorer_started_before_the_badge_was_listed_waits(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    explorer = (1234, 5000)
    assert si.badge_waits_for_explorer(written=6000, explorer=explorer)
    assert not si.badge_waits_for_explorer(written=4000, explorer=explorer)
    # not listed (no Administrator run yet, or past the slots Windows
    # loads): nothing a restart would change, so nothing is offered
    monkeypatch.setattr(si, "_overlay_written", lambda: None)
    assert not si.badge_waits_for_explorer(explorer=explorer)
    monkeypatch.setattr(si, "_explorer", lambda: None)
    assert not si.badge_waits_for_explorer(written=6000)
    monkeypatch.setattr(sys, "platform", "linux")
    assert not si.badge_waits_for_explorer(written=6000, explorer=explorer)
    assert si.restart_explorer(explorer=explorer) is False


def test_the_finished_window_offers_the_restart_once(tmp_path):
    jobs = _done_jobs(tmp_path)
    plain = cw.view(jobs)
    assert plain["offer"] == cw.NO_OFFER
    v = cw.view(jobs, cw.OFFER)
    assert v["offer"] == cw.OFFER
    assert v["content"] == plain["content"] + "\n\n" + cw.OFFER_TEXT[cw.OFFER]
    asked, restarted = [], []
    win = cw.TaskWindow(jobs, poll_spool=False,
                        badge_waits=lambda: asked.append(1) or True,
                        restart=lambda: restarted.append(1) or True)
    assert win._view()["offer"] == cw.OFFER
    assert win._view()["offer"] == cw.OFFER
    assert len(asked) == 1 and not restarted        # asked once, never run
    # Explorer already has the badge: the window is as it always was
    live = cw.TaskWindow(jobs, poll_spool=False, badge_waits=lambda: False)
    assert live._view() == plain
    # a question that fails offers nothing

    def broken():
        raise OSError("no registry")

    assert cw.TaskWindow(jobs, poll_spool=False,
                         badge_waits=broken)._view() == plain


def test_no_offer_while_working_or_when_nothing_was_compacted(tmp_path):
    gate = []

    def slow(path, progress=None):
        while not gate:
            time.sleep(0.02)
        raise OSError("held by another program")

    jobs = cw.Jobs(compact=slow)
    jobs.add(_card(tmp_path / "a.raw", zeros=MB))
    win = cw.TaskWindow(jobs, poll_spool=False, badge_waits=lambda: True)
    assert win._view()["offer"] == cw.NO_OFFER and win.offer is None
    assert cw.view(jobs, cw.OFFER)["offer"] == cw.NO_OFFER
    gate.append(1)
    jobs.wait(10)
    assert jobs.jobs[0].state == cw.FAILED
    assert win._view()["offer"] == cw.NO_OFFER


@pytest.mark.skipif(not WINDOWS, reason="the Windows task dialog")
def test_the_restart_button_runs_the_restart_and_the_window_stays(tmp_path):
    """The real dialog, off screen, with a stand-in restart: the finished
    page has the second button, pressing it runs the restart once and the
    window stays to say what came of it."""
    jobs = _done_jobs(tmp_path)
    pages, restarted = [], []

    def created(hwnd):
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(hwnd), None, -6000, 200, 0, 0, 0x1 | 0x4 | 0x10)

    def page(_hwnd, v):
        pages.append(v["offer"])
        if v["offer"] == cw.OFFER:
            threading.Thread(target=lambda: win._send(
                cw._TDM_CLICK_BUTTON, cw._OFFER_BUTTON, 0)).start()
        elif v["offer"] != cw.RESTARTING:
            win.close()

    def created_then_page(hwnd):
        created(hwnd)
        # the first page is drawn by run() itself, with no NAVIGATED
        page(hwnd, win._shown)

    win = cw.TaskWindow(jobs, poll_spool=False, on_created=created_then_page,
                        on_page=page, badge_waits=lambda: True,
                        restart=lambda: time.sleep(0.5) or restarted.append(1) or True)
    assert win.run() is True
    # the restart runs off the window's thread: it says so meanwhile
    assert pages == [cw.OFFER, cw.RESTARTING, cw.RESTARTED]
    assert restarted == [1]
    assert cw.OFFER_TEXT[cw.RESTARTED] in win._shown["content"]
    # a restart that fails says so and keeps the window too
    assert cw.view(jobs, cw.NOT_RESTARTED)["content"].endswith(
        cw.OFFER_TEXT[cw.NOT_RESTARTED])
