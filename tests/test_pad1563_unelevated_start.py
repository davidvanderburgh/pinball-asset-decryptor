"""PAD-1563 (GitHub issue #46): PAD starts WITHOUT Administrator on Windows.

launcher.vbs used to elevate every launch (one UAC prompt each time) because
a Direct-SSD read or write runs wsl --mount.  Now the launch is plain, the
jobs that need Administrator ask for it themselves, and the Direct-SSD panels
offer Restart as administrator: the session is saved, an elevated copy is
started with ``--direct-ssd <tab>`` and reopens on that tab with From SSD
picked, and this copy closes.  The in-app update goes through the setup exe's
own UAC prompt rather than the in-place copy beside Program Files.
"""
import os
import sys
import types

import pytest

from tests.webui_harness import web_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -- the elevated copy's command line --------------------------------------

def test_restart_args_from_the_installed_launcher():
    from pinball_decryptor.core import admin
    pyw = r"C:\Program Files\Pinball Asset Decryptor\Pinball Asset Decryptor.pyw"
    # a card image double-clicked in Explorer was handed in already: dropped
    assert admin.restart_args([pyw, r"D:\cards\game.raw"], "write") == \
        [os.path.abspath(pyw), "--direct-ssd", "write"]
    # a second restart replaces the first one's flag, never doubles it
    assert admin.restart_args([pyw, "--direct-ssd", "write"], "extract") == \
        [os.path.abspath(pyw), "--direct-ssd", "extract"]


def test_restart_args_from_a_module_run_and_a_frozen_build(monkeypatch):
    from pinball_decryptor.core import admin
    main = os.path.join(ROOT, "pinball_decryptor", "__main__.py")
    # __main__.py cannot run as a plain script (relative imports)
    assert admin.restart_args([main], "extract") == \
        ["-m", "pinball_decryptor", "--direct-ssd", "extract"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert admin.restart_args(["PAD.exe"], "extract") == ["--direct-ssd", "extract"]


def test_relaunch_passes_the_arguments_and_the_working_folder(monkeypatch):
    from pinball_decryptor.core import admin
    calls = []

    def shell_execute(hwnd, verb, exe, params, cwd, show):
        calls.append((verb, exe, params, cwd, show))
        return 42
    fake = types.SimpleNamespace(windll=types.SimpleNamespace(
        shell32=types.SimpleNamespace(ShellExecuteW=shell_execute)))
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    monkeypatch.setattr(admin, "sys", types.SimpleNamespace(
        platform="win32", executable=r"C:\PAD\python\pythonw.exe", argv=["x.pyw"]))
    assert admin.relaunch_as_admin(["C:\\PAD\\x.pyw", "--direct-ssd", "write"]) is True
    verb, exe, params, cwd, show = calls[0]
    assert verb == "runas" and exe == r"C:\PAD\python\pythonw.exe" and show == 1
    assert params == '"C:\\PAD\\x.pyw" "--direct-ssd" "write"'
    # an elevated start lands in System32 without it
    assert cwd == os.getcwd()
    # a declined prompt (ShellExecute <= 32) is a False, never a raise
    fake.windll.shell32.ShellExecuteW = lambda *a: 5
    assert admin.relaunch_as_admin(["x"]) is False


def test_host_takes_the_tab_to_reopen_on():
    src = open(os.path.join(ROOT, "pinball_decryptor", "webui", "host.py"),
               encoding="utf-8").read()
    assert 'parser.add_argument("--direct-ssd", choices=("extract", "write")' in src
    assert "ctx.direct_ssd = args.direct_ssd" in src


# -- Restart as administrator ----------------------------------------------

@pytest.mark.parametrize("tab", ["extract", "write"])
def test_restart_as_admin_saves_starts_the_elevated_copy_and_closes(tmp_path, monkeypatch, tab):
    from pinball_decryptor.core import admin
    started, closed = [], []
    monkeypatch.setattr(admin, "relaunch_as_admin",
                        lambda args=None: started.append(args) or True)
    with web_app(tmp_path, mfr="jjp") as w:
        saved = []
        monkeypatch.setattr(w.app, "_save_session_state", lambda: saved.append(1))
        monkeypatch.setattr(w.app, "_close_for_update", lambda: closed.append(1))
        assert w.call("%s.restart_as_admin" % tab) is True
    assert started and started[0][-2:] == ["--direct-ssd", tab]
    assert saved and closed


def test_a_declined_prompt_leaves_this_copy_running(tmp_path, monkeypatch):
    from pinball_decryptor.core import admin
    closed = []
    monkeypatch.setattr(admin, "relaunch_as_admin", lambda args=None: False)
    with web_app(tmp_path, mfr="jjp") as w:
        monkeypatch.setattr(w.app, "_close_for_update", lambda: closed.append(1))
        assert w.call("extract.restart_as_admin") is False
        assert any("Not restarted" in str(a.get("title", "")) for a in w.asked), w.asked
    assert not closed


@pytest.mark.parametrize("tab", ["extract", "write"])
def test_the_elevated_copy_reopens_on_the_tab_with_from_ssd(tmp_path, tab):
    with web_app(tmp_path, mfr="jjp") as w:
        assert getattr(w.window, "%s_input_source_var" % tab).get() != "ssd"
        w.run(w.app._resume_direct_ssd, tab)
        w.drain()
        assert w.state("shell")["tab"] == tab
        assert getattr(w.window, "%s_input_source_var" % tab).get() == "ssd"


def test_the_panel_says_how(tmp_path):
    from pinball_decryptor.webui import extract_helpers as H
    from pinball_decryptor.webui.tabs.write import WriteTab
    for text in (H.admin_body_text(None), WriteTab._admin_body_text(None)):
        assert "Restart as administrator" in text and "right-click" not in text
    js = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")
    for name, ns in (("extract.js", "extract"), ("write.js", "write")):
        src = open(os.path.join(js, name), encoding="utf-8").read()
        assert 'call("%s.restart_as_admin")' % ns in src
        assert ">Restart as administrator<//>" in src


# -- the in-app update ------------------------------------------------------

def test_an_unelevated_run_leaves_the_update_to_the_setup_exe(tmp_path, monkeypatch):
    """The copy beside the install and the swap write Program Files: an
    unelevated run skips them, and Install update runs the setup exe, which
    asks for Administrator itself (one UAC prompt)."""
    from pinball_decryptor.core import admin, update_slots
    with web_app(tmp_path, mfr="jjp") as w:
        monkeypatch.setattr(update_slots, "installed_app_dir", lambda *a, **k: r"C:\PAD")
        inst = {"kind": "windows-installer"}
        monkeypatch.setattr(admin, "is_admin", lambda: False)
        assert w.app._staging_for(inst) is None
        monkeypatch.setattr(admin, "is_admin", lambda: True)
        assert w.app._staging_for(inst) == "windows"


def test_a_project_inside_the_install_folder_is_named_once(tmp_path, monkeypatch):
    """A project made in Program Files while every launch was elevated
    (PAD-1081) cannot be saved by an unelevated PAD: it says so on open."""
    from pinball_decryptor.core import admin, update_slots
    app_dir = tmp_path / "Pinball Asset Decryptor"
    inside = app_dir / "My Sonic"
    inside.mkdir(parents=True)
    with web_app(tmp_path, mfr="jjp") as w:
        monkeypatch.setattr(update_slots, "installed_app_dir", lambda *a, **k: str(app_dir))
        monkeypatch.setattr(admin, "is_admin", lambda: False)
        warn = w.app._warn_project_needs_admin
        assert w.run(warn, str(inside), "win32") is True
        assert any("install folder" in str(a.get("title", "")) for a in w.asked), w.asked
        assert w.run(warn, str(inside), "win32") is False          # once a session
        assert w.run(warn, str(tmp_path / "elsewhere"), "win32") is False
        assert w.run(warn, str(app_dir.parent / "Pinball Asset Decryptor 2" / "x"), "win32") is False
        assert w.run(warn, str(inside), "linux") is False
        monkeypatch.setattr(admin, "is_admin", lambda: True)
        assert w.run(warn, str(app_dir / "Other"), "win32") is False
