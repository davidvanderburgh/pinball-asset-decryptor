"""Windows extended-length paths.

A Spike 2 project keeps its glyph slices 120+ characters below the project
folder, and the Build writes wherever the user pointed it, so both go past
Windows' 260-character limit without looking unusual.  A tester's font import
applied and then the build failed with an error that reads as a missing file;
shortening the build path fixed it.

The string logic is tested everywhere; the round trip that actually proves it
only means anything on Windows.
"""

import os
import sys

import pytest

from pinball_decryptor.core import longpath

B = chr(92)          # a literal backslash, spelled out to keep the tests legible
WIN = sys.platform == "win32"


def test_ext_is_a_noop_off_windows_and_on_empty_input():
    assert longpath.ext("") == ""
    assert longpath.ext(None) is None
    if not WIN:
        assert longpath.ext("/tmp/x/y.png") == "/tmp/x/y.png"


@pytest.mark.skipif(not WIN, reason="Windows path syntax")
def test_ext_prefixes_drive_and_unc_paths():
    assert longpath.ext("C:" + B + "tmp" + B + "y.png") == (
        B * 2 + "?" + B + "C:" + B + "tmp" + B + "y.png")
    # \\server\share -> \\?\UNC\server\share (NAS project folders are normal here)
    assert longpath.ext("//server/share/a.png") == (
        B * 2 + "?" + B + "UNC" + B + "server" + B + "share" + B + "a.png")


@pytest.mark.skipif(not WIN, reason="Windows path syntax")
def test_ext_is_idempotent_and_absolute():
    """It is applied at call sites that may already have been given a prefixed
    path, and the extended form is passed to the filesystem verbatim — a
    relative path or a doubled prefix would simply fail to open."""
    once = longpath.ext("relative" + B + "thing.png")
    assert once == longpath.ext(once)
    assert once.startswith(B * 2 + "?" + B)
    assert os.path.isabs(once[4:])


def test_is_long_and_hint_only_fire_past_the_limit():
    short = os.path.abspath("short.png")
    assert longpath.is_long(short) is False
    assert longpath.hint(short) == ""
    deep = os.path.join(os.path.abspath(os.sep), *(["dir"] * 90))
    if WIN:
        assert longpath.is_long(deep) is True
        msg = longpath.hint(deep)
        assert "260" in msg and "shorter folder" in msg
    else:
        assert longpath.is_long(deep) is False


@pytest.mark.skipif(not WIN, reason="MAX_PATH is a Windows limit")
def test_a_file_past_max_path_round_trips(tmp_path):
    """A 280+ character path opens through the prefix.

    Deliberately NOT asserting that the plain path fails: a machine with
    ``LongPathsEnabled`` set opens it either way (this developer's does, which
    is why the bug only showed up on a tester's machine).  The prefix works on
    both, so the round trip is what there is to check."""
    deep = str(tmp_path)
    while len(deep) < longpath.MAX_PATH + 20:
        deep = os.path.join(deep, "glyphs_folder_name")
    target = os.path.join(deep, "U+0041_A.png")
    assert len(target) > longpath.MAX_PATH
    try:
        os.makedirs(longpath.ext(deep), exist_ok=True)
        with open(longpath.ext(target), "wb") as f:
            f.write(b"glyph")
        with open(longpath.ext(target), "rb") as f:
            assert f.read() == b"glyph"
        assert os.path.isfile(longpath.ext(target))
    finally:
        # Clean up through the prefix as well — pytest's own tmp_path teardown
        # uses plain paths and would choke on what we just made.
        try:
            os.remove(longpath.ext(target))
        except OSError:
            pass
        while len(deep) > len(str(tmp_path)):
            try:
                os.rmdir(longpath.ext(deep))
            except OSError:
                break
            deep = os.path.dirname(deep)


@pytest.mark.skipif(not WIN, reason="Windows device namespace")
def test_ext_leaves_device_paths_alone():
    """``\\.\PHYSICALDRIVE1`` is the Direct-SD write target.  It has no
    length limit, and rewriting it as UNC would address a share called ``.``
    that does not exist — i.e. it would break writing to a real card."""
    for dev in (B * 2 + "." + B + "PhysicalDrive1",
                B * 2 + "." + B + "PHYSICALDRIVE0",
                "//./PhysicalDrive2"):
        got = longpath.ext(dev)
        assert got.startswith(B * 2 + "." + B), got
        assert "UNC" not in got
        assert longpath.ext(got) == got
    assert longpath.is_long(B * 2 + "." + B + "PhysicalDrive1") is False
