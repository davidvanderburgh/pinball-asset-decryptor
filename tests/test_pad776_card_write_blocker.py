"""PAD-776: updating a multi-boot card in place that is read-only, or held
open by another program, said only ``PermissionError: [Errno 13]`` after the
inject had already done its work.  Both the tool and the tab now ask up front
and say which of the two it is."""

import builtins
import os
import stat
import sys
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")


@pytest.fixture()
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


@pytest.fixture()
def core():
    from pinball_decryptor.webui import multiboot_core
    return multiboot_core


@pytest.fixture()
def card(tmp_path):
    p = tmp_path / "jp.multi.raw"
    p.write_bytes(b"\0" * 4096)
    yield str(p)
    os.chmod(str(p), stat.S_IREAD | stat.S_IWRITE)


def _make_read_only(path):
    os.chmod(path, stat.S_IREAD)        # on Windows: the Read-only attribute
    if os.name != "nt" and os.geteuid() == 0:
        pytest.skip("root writes a 0444 file anyway")


def _held_open(monkeypatch, module):
    """open() for writing refused the way another program's handle refuses it."""
    real = builtins.open

    def fake(path, mode="r", *a, **kw):
        if "+" in mode or "w" in mode:
            raise PermissionError(13, "Permission denied", path)
        return real(path, mode, *a, **kw)
    monkeypatch.setattr(module, "open", fake, raising=False)


def test_tool_free_card_passes(mk, card):
    assert mk.card_write_blocker(card) is None
    assert mk.check_card_writable(card) == card
    assert mk.card_write_blocker(card + ".missing") is None


def test_tool_read_only_card_refused(mk, card):
    _make_read_only(card)
    why = mk.card_write_blocker(card)
    assert "jp.multi.raw is marked read-only" in why and "Properties" in why
    with pytest.raises(mk.Refused, match="read-only"):
        mk.check_card_writable(card)


def test_tool_held_open_card_refused(mk, card, monkeypatch):
    _held_open(monkeypatch, mk)
    why = mk.card_write_blocker(card)
    assert "jp.multi.raw is open in another program" in why
    assert "read-only" not in why


def test_tab_free_card_passes(core, card):
    assert core.card_write_blocker(card) == ""


def test_tab_read_only_card(core, card):
    _make_read_only(card)
    why = core.card_write_blocker(card)
    assert "marked read-only" in why
    assert core.is_write_blocked(why)


def test_tab_held_open_card(core, card, monkeypatch):
    _held_open(monkeypatch, core)
    why = core.card_write_blocker(card)
    assert "open in another program" in why
    assert core.is_write_blocked(why)


def test_tab_knows_the_tools_sentences(core, mk, card, monkeypatch):
    """The update's done handler must not send a held-open card off to be
    rebuilt: the tab recognises the TOOL's wording as well as its own."""
    _held_open(monkeypatch, mk)
    assert core.is_write_blocked(mk.card_write_blocker(card))
    assert not core.is_write_blocked("p2 is type 0x0c, not Linux")


@pytest.mark.skipif(os.name != "nt", reason="a Windows sharing violation")
def test_tab_real_sharing_violation(core, card):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    # GENERIC_READ, FILE_SHARE_READ only: an image tool reading the card
    h = k32.CreateFileW(card, 0x80000000, 1, None, 3, 0x80, None)
    assert h not in (None, wintypes.HANDLE(-1).value)
    try:
        why = core.card_write_blocker(card)
    finally:
        k32.CloseHandle(h)
    assert "open in another program" in why
    assert core.card_write_blocker(card) == ""


def test_apply_blockers_names_it_before_any_run(core, card):
    """Apply and Update both refuse through _apply_blockers, before the media
    prepare or the inject start."""
    _make_read_only(card)
    panel = types.SimpleNamespace(_loaded_card=card)
    errs = core.MultibootPanel._apply_blockers(panel, core.MultibootForm(images=[]), False)
    assert any("Cannot update the card" in e and "read-only" in e for e in errs)
