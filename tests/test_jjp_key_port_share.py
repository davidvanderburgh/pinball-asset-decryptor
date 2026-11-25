"""PAD-1573: a JJP security key on a USB port usbipd has not shared.

A usbipd binding belongs to the USB PORT.  The key in a socket it was never
shared from makes `usbipd attach` answer "Device is not shared", and only an
administrator can bind.  The Emulate tab ran a plain bind, Windows refused it
with no word in the log, and every Start met the same refusal: "key attached
but not visible yet" forever, at a user with the key in the PC.
"""
from types import SimpleNamespace

import pytest

from pinball_decryptor.webui import emulate_jjp_core as core
from pinball_decryptor.webui.tabs import emulate_jjp as jjp_web
from pinball_decryptor.webui.tabs.emulate_jjp import EmulateJJPTab

NOT_SHARED = (b"usbipd: error: Device is not shared; run 'usbipd bind "
              b"--busid 3-2' as administrator first.")


class _Attacher:
    _usbipd_attach = EmulateJJPTab._usbipd_attach
    _bind_dongle = EmulateJJPTab._bind_dongle
    _attach_dongle = EmulateJJPTab._attach_dongle

    def __init__(self):
        self.lines, self.visible = [], False

    def _remote(self):
        return None

    def _log(self, text):
        self.lines.append(text)

    def _key_visible_in_wsl(self):
        return self.visible

    def _wait_for_key(self, tries=12):
        return self.visible


def _usbipd(monkeypatch, tab, replies):
    """Script subprocess.run: each usbipd / powershell call takes the next
    (rc, output, key visible afterwards) of its kind; `wsl.exe` succeeds."""
    calls = []
    monkeypatch.setattr(core, "usbipd_path", lambda: "usbipd")

    def run(cmd, *a, **kw):
        calls.append(list(cmd))
        if cmd[0] == "wsl.exe":
            return SimpleNamespace(returncode=0, stdout=b"")
        kind = "bind" if cmd[0].startswith("powershell") else "attach"
        rc, out, then_visible = replies[kind].pop(0)
        if then_visible:
            tab.visible = True
        return SimpleNamespace(returncode=rc, stdout=out)

    monkeypatch.setattr(jjp_web.subprocess, "run", run)
    return calls


def _binds(calls):
    return [c for c in calls if c[0].startswith("powershell")]


def test_start_binds_an_unshared_port_as_administrator(monkeypatch):
    tab = _Attacher()
    calls = _usbipd(monkeypatch, tab, {
        "attach": [(1, NOT_SHARED, False), (0, b"", True)],
        "bind": [(0, b"", False)]})
    assert tab._attach_dongle()
    bind = _binds(calls)
    assert len(bind) == 1
    script = bind[0][-1]
    assert "-Verb " + "Run" + "As" in script
    assert "'bind','--hardware-id','0529:0001'" in script
    assert any("Windows asks for permission" in l for l in tab.lines)
    assert tab.lines[-1] == "JJP: security key attached and visible in WSL."


def test_the_unasked_attach_never_raises_a_permission_prompt(monkeypatch):
    tab = _Attacher()
    calls = _usbipd(monkeypatch, tab, {"attach": [(1, NOT_SHARED, False)],
                                       "bind": []})
    assert not tab._attach_dongle(elevate=False)
    assert not _binds(calls)
    assert "Press Start" in tab.lines[-1]


def test_a_declined_prompt_is_named(monkeypatch):
    tab = _Attacher()
    _usbipd(monkeypatch, tab, {
        "attach": [(1, NOT_SHARED, False)],
        "bind": [(1, b"Start-Process : This command cannot be run due to the "
                    b"error: The operation was canceled by the user.", False)]})
    assert not tab._attach_dongle()
    assert "declined" in tab.lines[-1]


def test_usbipd_s_own_words_reach_the_log(monkeypatch):
    tab = _Attacher()
    fw = (b"usbipd: warning: A firewall appears to be blocking the "
          b"connection; ensure TCP port 3240 is allowed.")
    _usbipd(monkeypatch, tab, {"attach": [(1, fw, False), (1, fw, False)],
                               "bind": []})
    assert not tab._attach_dongle()
    assert any(l.startswith("JJP: usbipd said:") and "firewall" in l
               for l in tab.lines)


def test_a_key_already_shared_attaches_without_a_prompt(monkeypatch):
    tab = _Attacher()
    calls = _usbipd(monkeypatch, tab, {"attach": [(0, b"", True)],
                                       "bind": []})
    assert tab._attach_dongle()
    assert not _binds(calls)


@pytest.mark.parametrize("text,kind", [
    (NOT_SHARED.decode(), "notshared"),
    ("usbipd: error: No devices found with hardware-id '0529:0001'.", "nokey"),
    ("usbipd: error: Access denied; this operation requires administrator "
     "privileges.", "admin"),
    ("usbipd: error: Device with busid '3-2' is already attached to a "
     "client.", "already"),
    ("usbipd: info: Using WSL distribution 'Ubuntu' to attach", ""),
])
def test_attach_verdict_reads_usbipd_5(text, kind):
    assert core.attach_verdict(text) == kind


# ---------------------------------------------- the extract's `usbipd list` --

def _pipeline(run_win):
    from pinball_decryptor.plugins.jjp import pipeline as pl
    p = pl.DecryptionPipeline.__new__(pl.DecryptionPipeline)
    p.executor = SimpleNamespace(run_win=run_win)
    p.log = lambda *a, **k: None
    return p, pl


def test_extract_names_what_usbipd_said(monkeypatch):
    p, pl = _pipeline(lambda args, timeout=0: (
        1, "", "usbipd: error: The service is not running."))
    with pytest.raises(pl.PipelineError) as e:
        p._attach_local_dongle()
    assert "The service is not running" in str(e.value)
    assert "exit 1" in str(e.value)


def test_extract_goes_on_when_the_list_shows_the_key(monkeypatch):
    """A non-zero exit from a list that DID name the key is not a missing
    usbipd: the extract carries on to the bind and attach."""
    seen = []

    def run_win(args, timeout=0):
        seen.append(args[1:2])
        if args[1:2] == ["list"]:
            return 1, "3-2  0529:0001  Sentinel HASP Key  Shared\n", ""
        return 0, "", ""

    p, pl = _pipeline(run_win)
    monkeypatch.setattr(pl.time, "sleep", lambda s: None)
    monkeypatch.setattr(p, "_bind_dongle", lambda u: None, raising=False)
    monkeypatch.setattr(p, "_wsl_attach", lambda u: [u, "attach"],
                        raising=False)
    p._attach_local_dongle()
    assert ["attach"] in seen
