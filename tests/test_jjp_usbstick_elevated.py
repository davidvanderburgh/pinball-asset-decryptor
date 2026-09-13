"""The JJP stick maker's one-shot UAC step (plugins/jjp/usbstick.py _ps_elevated).

An unelevated source run formatted the stick and then crashed reading the
elevated child's result file: a plain mkdtemp is owner-only, and a file the
elevated child creates there is owned by Administrators (item 119, 2026-09-13).
The IPC directory now comes from core.elevated_flash._ipc_dir, which grants the
user first, and an unreadable result is a message, not a traceback."""
import os

from pinball_decryptor.core import elevated_flash
from pinball_decryptor.plugins.jjp import usbstick


def _fake_child(body):
    """A stand-in for Start-Process -Verb RunAs: 'the child' writes the result
    file named in the job script, and the launch returns 0."""
    def run(script, timeout=180):
        job = script.split("'-File','", 1)[1].split("'", 1)[0]
        result = os.path.join(os.path.dirname(job), "result.txt")
        with open(result, "w", encoding="utf-8") as f:
            f.write(body)
        return 0, ""
    return run


def test_the_elevated_step_uses_the_user_readable_ipc_dir(tmp_path, monkeypatch):
    made = []

    def ipc_dir(prefix):
        made.append(prefix)
        d = tmp_path / "ipc"
        d.mkdir()
        return str(d)
    monkeypatch.setattr(elevated_flash, "_ipc_dir", ipc_dir)
    monkeypatch.setattr(usbstick, "_ps", _fake_child("LETTER=F\nRC=0\n"))
    rc, out = usbstick._ps_elevated("'hello'")
    assert made == ["pad_jjp_usb_"]
    assert rc == 0 and out == "LETTER=F"


def test_an_unreadable_result_is_a_message_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(elevated_flash, "_ipc_dir",
                        lambda prefix: str(tmp_path))
    monkeypatch.setattr(usbstick, "_ps", _fake_child("LETTER=F\nRC=0\n"))
    real_open = open

    def denying_open(path, *a, **k):
        if str(path).endswith("result.txt") and "r" in (a[0] if a else k.get("mode", "r")):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *a, **k)
    monkeypatch.setattr(usbstick, "open", denying_open, raising=False)
    rc, out = usbstick._ps_elevated("'hello'")
    assert rc == 1
    assert "could not be read" in out and "unknown" in out
