"""PAD-1201: every buffer of a Spike 3 screen is shown, not one in three.

Fallout (and any title that triple-buffers a screen) gets a gbm bo's dma-buf
fd, makes its EGL image and CLOSES the fd before asking for the next bo's. The
fake KMS (s3kms.c) matched an image's fd to its bo by the fd NUMBER, and dup()
hands the next bo the number just closed - so every image became bo 1's, bos
2 and 3 never had a texture, and two flips in three were dropped: 20 fps of
the game's 60 on each screen. The fd is now matched by the file behind it.

s3kms.c is aarch64 guest code, but it is plain Linux C: built natively here
and driven through ctypes in the game's own order."""
import ctypes
import os
import re
import shutil
import subprocess
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu")
S3KMS = os.path.join(TOOLS, "s3kms.c")
S3RUN = os.path.join(TOOLS, "s3run.sh")


@pytest.fixture(scope="module")
def kms(tmp_path_factory):
    if not sys.platform.startswith("linux") or not shutil.which("gcc"):
        pytest.skip("s3kms.c is Linux C (memfd); needs gcc on Linux")
    so = str(tmp_path_factory.mktemp("s3kms") / "s3kms_t.so")
    r = subprocess.run(["gcc", "-shared", "-fPIC", "-O1", "-o", so, S3KMS, "-ldl", "-lpthread"],
                       capture_output=True, text=True)
    if r.returncode:
        pytest.skip("s3kms.c did not build natively: " + r.stderr[-400:])
    lib = ctypes.CDLL(so)
    lib.gbm_bo_create.restype = ctypes.c_void_p
    lib.gbm_bo_create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.c_uint32]
    lib.gbm_bo_get_fd.argtypes = [ctypes.c_void_p]
    lib.gbm_bo_destroy.argtypes = [ctypes.c_void_p]
    lib.pad_s3_bo_by_fd.restype = ctypes.c_uint32
    lib.pad_s3_bo_by_fd.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32),
                                    ctypes.POINTER(ctypes.c_uint32)]
    return lib


def _lookup(lib, fd):
    w, h = ctypes.c_uint32(), ctypes.c_uint32()
    return lib.pad_s3_bo_by_fd(fd, ctypes.byref(w), ctypes.byref(h)), w.value, h.value


def test_each_bo_of_a_triple_buffered_screen_is_its_own(kms):
    xr24 = 0x34325258
    bos = [kms.gbm_bo_create(None, 1920, 1080, xr24, 5) for _ in range(3)]
    try:
        seen = []
        for bo in bos:
            # the game's order: fd, image, close - then the next bo's fd,
            # which dup() gives the number just closed
            fd = kms.gbm_bo_get_fd(bo)
            seen.append(_lookup(kms, fd))
            os.close(fd)
        handles = [s[0] for s in seen]
        assert len(set(handles)) == 3 and 0 not in handles, handles
        assert all(s[1:] == (1920, 1080) for s in seen)
    finally:
        for bo in bos:
            kms.gbm_bo_destroy(bo)


def test_an_fd_that_is_no_bo_is_not_ours(kms):
    r, wfd = os.pipe()
    try:
        assert _lookup(kms, r)[0] == 0
    finally:
        os.close(r); os.close(wfd)


def test_the_window_gets_the_display_setting_unless_hidden():
    """The Emulate tab's display setting (full screen, a rectangle,
    borderless: display.conf on the rig board) reaches the Spike 3 renderer
    as it does Spike 2's (watch.sh); a hidden run's private display does not
    read it."""
    with open(S3RUN, encoding="utf-8") as f:
        src = f.read()
    assert re.search(r'PAD_DISPLAY_CONF="\$\(pad_board_dir\)/display\.conf"', src)
    assert re.search(r'"\$\{PAD_HIDDEN:-0\}" != 1', src)
    renv = re.search(r"RENV=\(PAD_GL_WINDOW=1[^)]*\)", src)
    assert renv and "PAD_DISPLAY_CONF=" in renv.group(0)
    # the window's remembered spot is per rig slot (~/.pad_windows.rig<N>);
    # without the slot every Spike 3 run wrote the base rig's file
    assert 'PAD_SLOT="$SLOT"' in renv.group(0)
