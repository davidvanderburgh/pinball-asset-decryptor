"""resolve_mapped_drive — dead mapped-drive-letter → UNC translation.

Mapped network drives are per logon session on Windows, so a path saved as
``W:\\mods`` in a normal session stops resolving when PAD is run elevated
(monkeybug, running as admin for flash-image).  The helper translates such
paths through the user's persistent mapping (HKCU\\Network\\<letter>);
these tests drive the pure decision logic with the session/registry lookups
monkeypatched so they run identically on every platform and CI.
"""
import pytest

from pinball_decryptor.core import admin


@pytest.fixture
def win_session(monkeypatch):
    """Pretend we're on Windows with only C: visible and W: → \\\\plexnas\\Work
    persistently mapped (the letter itself invisible, i.e. elevated)."""
    monkeypatch.setattr(admin.sys, "platform", "win32")
    monkeypatch.setattr(admin, "_drive_visible",
                        lambda letter: letter.upper() == "C")
    monkeypatch.setattr(
        admin, "_persistent_mapping",
        lambda letter: r"\\plexnas\Work" if letter.upper() == "W" else None)


def test_dead_mapped_letter_translates(win_session):
    assert (admin.resolve_mapped_drive(r"W:\Led Zeppelin\Redux")
            == r"\\plexnas\Work\Led Zeppelin\Redux")
    # Forward slashes after the drive spec are kept as typed.
    assert (admin.resolve_mapped_drive("w:/mods/out")
            == r"\\plexnas\Work" + "/mods/out")
    # The bare root maps to the share root (separator kept as typed).
    assert admin.resolve_mapped_drive("W:\\") == "\\\\plexnas\\Work\\"


def test_visible_or_unmapped_paths_untouched(win_session):
    for p in (
        r"C:\Users\david\out",       # letter visible in this session
        r"X:\nothing\mapped",        # dead letter but no persistent mapping
        r"\\plexnas\Work\already",   # already UNC
        "W:relative\\odd",           # drive-relative, not a real mapped path
        "not a path at all",
        "",
        None,
    ):
        assert admin.resolve_mapped_drive(p) == p


def test_non_windows_is_a_no_op(monkeypatch):
    monkeypatch.setattr(admin.sys, "platform", "darwin")
    monkeypatch.setattr(admin, "_persistent_mapping",
                        lambda letter: pytest.fail("registry consulted"))
    assert admin.resolve_mapped_drive("W:\\x") == "W:\\x"


def test_lookup_failure_leaves_path_alone(win_session, monkeypatch):
    # _drive_visible answering "can't tell" (True) must not translate.
    monkeypatch.setattr(admin, "_drive_visible", lambda letter: True)
    assert admin.resolve_mapped_drive(r"W:\x") == r"W:\x"
