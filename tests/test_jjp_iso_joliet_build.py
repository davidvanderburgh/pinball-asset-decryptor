"""The modified JJP ISO must keep the long-name (Joliet) tree.

``xorriso -indev/-outdev`` writes Rock Ridge only unless told ``-joliet on``,
so the Build ISO phase was handing back an ISO whose files Windows shows as
``LIVE/VMLINUZ`` / ``SDA3_EXT4_PTCL_IMG_GZ.AA``.  The very next step — make a
USB install stick — then refuses that ISO (``usbstick.iso_has_joliet``), and a
stick copied from it by hand stops in GRUB on "file '/live/vmlinuz' not found"
(a tester's Pirates ISO, 2026-09-17).  Pure: a fake executor records the build
script, and the post-build check reads a synthetic volume descriptor set.
"""
import base64
import os

import pytest

from pinball_decryptor.plugins.jjp import pipeline as P

SECTOR = 2048


def _iso(path, joliet):
    """A volume descriptor set — all ``iso_has_joliet`` reads."""
    b = bytearray(SECTOR * 19)

    def vd(i, kind, esc=b""):
        o = i * SECTOR
        b[o] = kind
        b[o + 1:o + 6] = b"CD001"
        b[o + 6] = 1
        if esc:
            b[o + 88:o + 91] = esc
    vd(16, 1)
    if joliet:
        vd(17, 2, b"%/E")
        vd(18, 255)
    else:
        vd(17, 255)
    path.write_bytes(bytes(b))
    return str(path)


class _Executor:
    """Answers the handful of commands the build phase sends."""

    def __init__(self):
        self.script = ""

    def to_exec_path(self, p):
        return "/mnt/x/" + os.path.basename(str(p).replace("\\", "/"))

    def run(self, cmd, timeout=None):
        if cmd.startswith("ls -1 "):
            return ("/var/tmp/chunks/sda3.ext4-ptcl-img.gz.aa\n"
                    "/var/tmp/chunks/sda3.ext4-ptcl-img.gz.ab\n")
        if cmd.startswith("echo '"):
            b64 = cmd.split("'")[1]
            self.script = base64.b64decode(b64).decode()
            return ""
        if cmd.startswith("stat -c%s"):
            return "13000000000"
        return ""

    def stream(self, cmd, timeout=None):
        yield "Writing:  100.0% done"


def _build(tmp_path, joliet_out=True):
    ex = _Executor()
    pipe = object.__new__(P.ModPipeline)
    pipe.executor = ex
    pipe.assets_folder = str(tmp_path)
    pipe.image_path = str(tmp_path / "pirates.iso")
    pipe._chunks_dir = "/var/tmp/chunks"
    pipe._iso_mount = None
    pipe.cancelled = False
    logs = []
    pipe.log = lambda m, lvl="info": logs.append((lvl, m))
    pipe.on_progress = lambda *a, **k: None
    pipe._verify_iso_partition = lambda *a, **k: None
    # The built ISO the post-build check reads back.
    _iso(tmp_path / "pirates_modified.iso", joliet_out)
    pipe._phase_build_iso()
    return ex.script, logs


def test_the_build_keeps_the_long_names(tmp_path):
    script, _logs = _build(tmp_path)
    assert "-joliet on" in script, (
        "xorriso -indev/-outdev writes Rock Ridge only without it, and the "
        "stick maker then refuses the ISO this phase just built:\n" + script)
    # The boot records must still be replayed alongside it.
    assert "-boot_image any replay" in script
    assert script.index("-joliet on") < script.index("-boot_image any replay")


def test_a_joliet_iso_is_confirmed_in_the_log(tmp_path):
    _script, logs = _build(tmp_path, joliet_out=True)
    ok = [m for lvl, m in logs if lvl == "success" and "Joliet" in m]
    assert ok, [m for _l, m in logs]
    assert not [m for lvl, m in logs if lvl == "error"]


def test_a_joliet_less_iso_is_called_out(tmp_path):
    """Belt and braces: if a machine's xorriso ignores the flag, the log says
    so instead of leaving the user with an ISO the stick step refuses."""
    _script, logs = _build(tmp_path, joliet_out=False)
    bad = [m for lvl, m in logs if lvl == "error" and "Joliet" in m]
    assert bad, [m for _l, m in logs]
    assert "cannot install" in bad[0]


def test_the_check_is_never_fatal(tmp_path, monkeypatch):
    """A build that produced a real ISO must not fail on the check itself."""
    from pinball_decryptor.plugins.jjp import usbstick

    def boom(_p):
        raise RuntimeError("no")
    monkeypatch.setattr(usbstick, "iso_has_joliet", boom)
    monkeypatch.setattr(P.usbstick, "iso_has_joliet", boom)
    _script, logs = _build(tmp_path)
    assert not [m for lvl, m in logs if lvl == "error"]
