"""Unit tests for core.host_temp — Windows %TEMP% PAD-leftover cleanup.

Uses a real (pytest) temp dir as the stand-in for ``%TEMP%`` so the scan/delete
paths exercise the actual filesystem, not mocks.
"""

import os

import pytest

from pinball_decryptor.core import host_temp


@pytest.fixture
def fake_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(host_temp.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def _mkfile(d, name, size):
    p = d / name
    p.write_bytes(b"\0" * size)
    return str(p)


def _mkdir_with(d, name, size):
    sub = d / name
    sub.mkdir()
    (sub / "blob").write_bytes(b"\0" * size)
    return str(sub)


# --- classification --------------------------------------------------------

@pytest.mark.parametrize("name,mfr", [
    ("spike2_abcd1234", "Stern Pinball"),
    ("williams_mp4_xx", "Williams DMD render"),
    ("cc_dcs_xx", "Chicago Gaming Company"),
    ("cc_anim_xx", "Chicago Gaming Company"),
    ("pad_aaiw_xx", "Dutch Pinball"),
    ("spooky_vid_xx", "Spooky Pinball"),
    ("jjp_release", "Jersey Jack Pinball"),
    ("pad-ffmpeg-xx", "Shared tooling"),
    ("pad_iso_xx", "Shared tooling"),
])
def test_classify(name, mfr):
    assert host_temp._classify(name)[0] == mfr


def test_cc_dcs_matched_before_generic_cc():
    # Order matters: cc_dcs_ must win over the broader cc_ prefix.
    assert host_temp._classify("cc_dcs_x")[1] == "Cactus Canyon DCS scratch"
    assert host_temp._classify("cc_x")[1] == "Cactus Canyon scratch"


@pytest.mark.parametrize("name,detail", [
    # New title-embedded form: spike2_<title>_<hex8>.
    ("spike2_Teenage_Mutant_Ninja_Turtles_a1b2c3d4",
     "Teenage Mutant Ninja Turtles"),
    ("spike2_Metallica_0011aabb", "Metallica"),
    ("spike2_revert_Godzilla_deadbeef", "Godzilla (revert)"),
    # Legacy bare-random form (no title) -> generic role.
    ("spike2_q7x", "audio extract / build staging"),
    ("spike2_revert_q7x", "audio extract / build staging"),
])
def test_spike2_title(name, detail):
    mfr, got = host_temp._classify(name)
    assert mfr == "Stern Pinball"
    assert got == detail


# --- scan ------------------------------------------------------------------

def test_scan_finds_prefixed_entries_sorted(fake_temp):
    _mkdir_with(fake_temp, "spike2_big", 3000)
    _mkfile(fake_temp, "pad-ffmpeg-tiny", 10)
    # Non-PAD entries must be ignored.
    _mkfile(fake_temp, "unrelated.tmp", 99999)
    (fake_temp / "some_other_dir").mkdir()

    entries = host_temp.scan()
    names = [os.path.basename(e["path"]) for e in entries]
    assert names == ["spike2_big", "pad-ffmpeg-tiny"]  # largest first
    assert entries[0]["size"] == 3000
    assert entries[0]["manufacturer"] == "Stern Pinball"


def test_scan_skips_zero_byte_entries(fake_temp):
    # Empty leftover dir + an empty file -> noise, must not show up.
    (fake_temp / "spike2_empty").mkdir()
    (fake_temp / "pad-ffmpeg-empty").write_bytes(b"")
    _mkfile(fake_temp, "spike2_real", 100)
    names = [os.path.basename(e["path"]) for e in host_temp.scan()]
    assert names == ["spike2_real"]


def test_scan_missing_tempdir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(host_temp.tempfile, "gettempdir",
                        lambda: str(tmp_path / "nope"))
    assert host_temp.scan() == []


# --- safety + delete -------------------------------------------------------

def test_is_safe(fake_temp):
    safe = _mkdir_with(fake_temp, "spike2_ok", 1)
    assert host_temp._is_safe(safe)
    # A prefixed name NOT directly under the temp dir is rejected.
    nested = fake_temp / "spike2_ok" / "spike2_inner"
    nested.mkdir()
    assert not host_temp._is_safe(str(nested))
    # A non-prefixed direct child is rejected.
    other = _mkfile(fake_temp, "random.tmp", 1)
    assert not host_temp._is_safe(other)


def test_delete_removes_and_reports(fake_temp):
    d = _mkdir_with(fake_temp, "spike2_big", 5000)
    f = _mkfile(fake_temp, "pad-ffmpeg-x", 7)
    freed = host_temp.delete([d, f])
    assert freed == 5007
    assert not os.path.exists(d)
    assert not os.path.exists(f)


def test_delete_refuses_unsafe(fake_temp):
    outside = fake_temp / "spike2_ok" / "deep"
    outside.mkdir(parents=True)
    with pytest.raises(host_temp.HostTempError):
        host_temp.delete([str(outside)])


def test_delete_empty_noop(fake_temp):
    assert host_temp.delete([]) == 0
