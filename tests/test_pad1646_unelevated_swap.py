"""PAD-1646: Restart to update is quick again in a run without Administrator.

David, on the "Updating to v1.637.1..." window: "after installing updates
and restarting, I'm seeing this screen for far too long.  i would have
thought that our new background install mechanics would significantly speed
up the app restart / installs ... I need the app restart to be near instant
after update like what Discord app does".

His log said why.  The app has started WITHOUT Administrator since PAD-1563,
and the background install wrote beside the app, in Program Files - so an
unelevated run did none of it, and every Restart to update ran the whole
setup program: 37 s from the click to the new version, against 6 s for the
swap of a version already installed.

Now an unelevated run gets the new version ready in the user's own folder
(the changed files route needs no Administrator), and the Restart click
starts the swap helper elevated - one consent prompt, as the setup program
raised - which takes the version from there.  A second helper, unelevated,
starts the app afterwards, so it runs as the user.  The swap itself, on a
copy of the real install in a folder the user cannot write: 0.3 s from the
app closing to the launcher running.
"""

import os
import subprocess
import sys
import time

import pytest

from pinball_decryptor.core import update_slots as us
from tests.test_pad1024_background_update import (   # noqa: F401
    _banner, _installer, _tree, _until, slots, staged)
from tests.webui_harness import web_app

APP = r"C:\Program Files\Pinball Asset Decryptor"


# ------------------------------------------------------------ where it stages
def test_the_users_staging_folder_is_on_the_apps_drive_or_nowhere():
    local = r"C:\Users\pat\AppData\Local"
    got = us.user_stage_dir(APP, local=local)
    assert got.startswith(local + "\\pinball_decryptor\\update\\")
    assert got.endswith("\\next")
    # one per install folder, however the folder is spelled
    assert us.user_stage_dir(APP.upper() + "\\", local=local) == got
    assert us.user_stage_dir(r"C:\Other\PAD", local=local) != got
    # another drive: the move would be a copy of the whole app at the click
    assert us.user_stage_dir(r"D:\Apps\PAD", local=local) is None


def test_a_version_in_the_users_folder_is_checked_like_one_beside_the_app(
        tmp_path):
    app = _tree(tmp_path / "PAD", "1.0.0")
    mine = _tree(tmp_path / "local" / "next", "9.9.9")
    assert not us.staged_install_ok(str(app), "9.9.9", staged=str(mine))
    (mine / us.MARKER).write_text('{"version": "9.9.9"}', encoding="utf-8")
    assert us.staged_install_ok(str(app), "9.9.9", staged=str(mine))
    assert not us.staged_install_ok(str(app), "9.9.9")      # not <app>.next
    assert us.staged_version(str(app), str(mine)) == "9.9.9"


def test_the_changed_files_route_fills_the_folder_it_is_given(tmp_path):
    app = _tree(tmp_path / "PAD", "1.0.0")
    mine = tmp_path / "local" / "update" / "next"

    def _fill(target, progress):
        _tree(tmp_path.__class__(target), "9.9.9")
        return None
    ok, _ = us.stage_delta_install(_fill, str(app), "9.9.9",
                                   target=str(mine),
                                   run=lambda *a, **k: None)
    assert ok
    assert us.staged_install_ok(str(app), "9.9.9", staged=str(mine))
    assert not (tmp_path / "PAD.next").exists()


def test_leftovers_include_a_stale_folder_of_the_users(tmp_path, monkeypatch):
    app = _tree(tmp_path / "PAD", "9.9.9")
    mine = _tree(tmp_path / "local" / "next", "9.9.9")
    (mine / us.MARKER).write_text('{"version": "9.9.9"}', encoding="utf-8")
    monkeypatch.setattr(us, "user_stage_dir", lambda a, local=None: str(mine))
    # newer than the running version: kept for its Restart to update
    assert us.clear_leftovers(str(app), "9.9.8") == ([], [])
    assert mine.exists()
    deleted, failed = us.clear_leftovers(str(app), "9.9.9")
    assert deleted == [str(mine)] and not failed
    # and one that never finished (no marker)
    half = _tree(tmp_path / "local" / "next", "9.9.10")
    deleted, _ = us.clear_leftovers(str(app), "9.9.9")
    assert deleted == [str(half)]


# ------------------------------------------------------------ the two scripts
def test_the_swap_takes_the_version_from_the_users_folder():
    text = us.swap_script(APP, "9.9.9", "", 7, r"C:\t\l.log",
                          staged=r"C:\Users\pat\next",
                          done_path=r"C:\t\done.txt", launch=False)
    assert r"$staged = 'C:\Users\pat\next'; $done = 'C:\t\done.txt'" in text
    assert "Move-Item -LiteralPath $staged -Destination $next" in text
    # it says how it ended on every way out, for the helper that starts the app
    for said in ("Done 'ok'", "Done 'none'", "Done 'inplace'",
                 "Done 'installer'"):
        assert said in text, said
    # what came from the user's folder gets the install folder's permissions,
    # after the new version is told to start
    assert text.index("Done 'ok'") < text.index("/setowner")
    assert "/reset /T /C /Q" in text and "*S-1-5-32-544" in text
    # a swap by an elevated app is what it was: nothing staged elsewhere,
    # nobody to tell
    plain = us.swap_script(APP, "9.9.9", "", 7, r"C:\t\l.log")
    assert "$staged = ''; $done = ''" in plain


def test_the_swap_one_level_down_is_tried_at_once():
    """It waited a second first, on every restart of a PC where another
    program sits in the app's folder (David's did on every swap)."""
    text = us.swap_script(APP, "9.9.9", "", 7, "l")
    assert "$i -ge 2" not in text
    assert "if (SwapInside) { $moved = $true; $inside = $true }" in text


def test_the_relaunch_helper_starts_the_app_unless_told_not_to():
    text = us.relaunch_script(APP, r"C:\t\done.txt", r"C:\t\l.log")
    assert "$done = 'C:\\t\\done.txt'" in text
    assert "$what -ne 'none' -and $what -ne 'installer' -and $true" in text
    assert "wscript.exe" in text and "launcher.vbs" in text
    quiet = us.relaunch_script(APP, "d", "l", launch=False)
    assert "-and $false" in quiet


# ------------------------------------------------------------ starting them
class _Popen:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)


def test_an_elevated_swap_is_asked_for_once_and_has_a_helper(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(us.tempfile, "gettempdir", lambda: str(tmp_path))
    popen, asked = _Popen(), []

    def _shell(hwnd, verb, exe, params, cwd, show):
        asked.append((verb, exe, params, cwd, show))
        return 42
    ok, log = us.start_swap(APP, "9.9.9", "", pid=7, popen=popen,
                            staged=r"C:\Users\pat\next", elevate=True,
                            shell_execute=_shell)
    assert ok and log == str(tmp_path / "pad_update_swap.log")
    (verb, exe, params, cwd, show), = asked
    assert (verb, exe, cwd, show) == ("runas", "powershell.exe",
                                      str(tmp_path), 0)
    assert "-File" in params and "pad-swap-" in params
    # the unelevated helper, and nothing else, through Popen
    (cmd,), = [popen.calls]
    assert cmd[0] == "powershell.exe" and "pad-relaunch-" in cmd[-1]
    swap = [p for p in tmp_path.iterdir() if p.name.startswith("pad-swap-")
            and p.suffix == ".ps1"][0].read_text(encoding="utf-8-sig")
    helper = open(cmd[-1], encoding="utf-8-sig").read()
    done = [ln for ln in helper.splitlines() if "$done = " in ln][0]
    done = done.split("$done = ")[1].strip()
    assert "$done = " + done in swap            # the same file, both sides
    assert r"$staged = 'C:\Users\pat\next'" in swap
    # the swap starts nothing itself: what it started would be elevated
    assert "if ($false) {\n  Start-Process -FilePath 'wscript.exe'" in swap
    # the setup program, should it come to that, is told an elevated
    # program started it (PAD-1635)
    assert "/NOREDIRECTIONGUARD" in swap


def test_no_at_the_prompt_starts_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(us.tempfile, "gettempdir", lambda: str(tmp_path))
    popen = _Popen()
    ok, why = us.start_swap(APP, "9.9.9", "", pid=7, popen=popen,
                            staged=r"C:\Users\pat\next", elevate=True,
                            shell_execute=lambda *a: 5)
    assert (ok, why) == (False, us.NOT_ALLOWED)
    # the swap script is gone, and the helper already waiting is told there
    # is nothing to start
    names = sorted(p.name for p in tmp_path.iterdir())
    assert not any(n.startswith("pad-swap-") and n.endswith(".ps1")
                   for n in names), names
    done, = [p for p in tmp_path.iterdir()
             if p.name.startswith("pad-swap-done-")]
    assert done.read_text(encoding="utf-8") == "none"
    ok, why = us.start_swap(APP, "9.9.9", "", pid=7, popen=_Popen(),
                            staged="s", elevate=True,
                            shell_execute=lambda *a: 2)
    assert not ok and "code 2" in why


@pytest.mark.skipif(os.name != "nt", reason="the swap helper is PowerShell")
def test_the_real_helpers_swap_from_the_users_folder_and_start_the_app(
        tmp_path):
    """Both real scripts over stand-in folders: the swap (started here as
    the consent prompt would, only without Administrator - tmp_path needs
    none) takes the version from the user's folder, and the unelevated
    helper runs the new version's launcher."""
    app = _tree(tmp_path / "pf" / "Pinball Asset Decryptor", "1.0.0",
                extra=("mine.txt",))
    mine = _tree(tmp_path / "local" / "next", "9.9.9")
    ran = tmp_path / "launched.txt"
    (mine / "launcher.vbs").write_text(
        'CreateObject("Scripting.FileSystemObject").CreateTextFile("%s")'
        '.Close\r\n' % ran, encoding="ascii")
    (mine / us.MARKER).write_text('{"version": "9.9.9"}', encoding="utf-8")
    log = tmp_path / "swap.log"
    holder = subprocess.Popen([sys.executable, "-c",
                               "import time; time.sleep(2)"])

    def _shell(hwnd, verb, exe, params, cwd, show):
        subprocess.Popen(exe + " " + params, cwd=cwd,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return 42
    try:
        ok, _ = us.start_swap(str(app), "9.9.9", "", pid=holder.pid,
                              staged=str(mine), elevate=True,
                              register=False, log_path=str(log),
                              failed_note=str(tmp_path / "failed.txt"),
                              shell_execute=_shell)
        assert ok
        end = time.time() + 60
        while time.time() < end and not ran.exists():
            time.sleep(0.1)
    finally:
        holder.kill()
    text = log.read_text(encoding="utf-8-sig") if log.exists() else ""
    assert ran.exists(), text
    assert us.tree_version(str(app)) == "9.9.9", text
    assert "swapped in v9.9.9" in text and "swap not done" not in text
    assert "started the app without Administrator" in text
    assert (app / "mine.txt").is_file()             # PAD-1081, still
    assert not mine.exists()


# ------------------------------------------------------------ the app
@pytest.fixture
def unelevated(tmp_path, slots, monkeypatch):
    """The ``slots`` stand-ins in a run WITHOUT Administrator, whose
    changed-files install fills the user's folder."""
    from pinball_decryptor import app as app_mod
    from pinball_decryptor.core import admin
    monkeypatch.setattr(admin, "is_admin", lambda: False)
    mine = tmp_path / "local" / "next"
    monkeypatch.setattr(us, "user_stage_dir", lambda a, local=None: str(mine))
    slots["mine"] = mine

    def _from_changes(self, bg, post):
        assert bg["stage_dir"] == str(mine)
        _tree(mine, bg["version"])
        (mine / us.MARKER).write_text('{"version": "%s"}' % bg["version"],
                                      encoding="utf-8")
        return str(mine), "3 changed files"
    monkeypatch.setattr(app_mod.App, "_stage_update_from_changes",
                        _from_changes)
    slots["swap_says"] = (True, "log")

    def _swap(app, version, setup, **k):
        slots["swaps"].append((app, version, k))
        return slots["swap_says"]
    monkeypatch.setattr(us, "start_swap", _swap)
    return slots


def _delta_installer():
    return _installer(delta={"name": "files.json", "url": "u"})


def test_without_administrator_it_installs_in_the_users_folder_and_swaps(
        tmp_path, unelevated):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.app._staging_for(_delta_installer()) == "windows"
        # no file list: the setup program at the click, as before
        assert w.app._staging_for(_installer()) is None
        w.run(w.app._offer_update, "9.9.9", "u", _delta_installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Update v9.9.9 is installed (3 changed files)" in t
                   for t in texts), texts
        assert unelevated["downloads"] == []        # no setup program fetched
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: unelevated["closed"])
        (app, version, kw), = unelevated["swaps"]
        assert (app, version) == (str(tmp_path / "PAD"), "9.9.9")
        assert kw == {"staged": str(unelevated["mine"]), "elevate": True}
        assert unelevated["launched"] == []         # and none run
        # the feed had just said 9.9.9 was the newest: not asked again
        assert unelevated["checks"] == []


def test_no_at_the_prompt_leaves_the_app_up_and_the_update_ready(
        tmp_path, unelevated):
    unelevated["swap_says"] = (False, us.NOT_ALLOWED)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _delta_installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: unelevated["swaps"])
        time.sleep(0.3)
        w.drain()
        assert unelevated["closed"] == 0
        assert unelevated["launched"] == []         # not the setup program
        texts = [e["text"] for e in w.window.log_history()]
        assert any("Administrator permission and it was not given" in t
                   for t in texts), texts
        assert "is ready" in _banner(w)["text"]
        # and the next click asks again
        unelevated["swap_says"] = (True, "log")
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: unelevated["closed"])


def test_an_old_answer_from_the_feed_is_asked_again(tmp_path, unelevated):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "9.9.9", "u", _delta_installer())
        assert _until(w, lambda: "is ready" in (_banner(w) or {}).get(
            "text", ""))
        w.app._update_offer_at = time.monotonic() - w.app.RECHECK_FRESH_S - 1
        unelevated["feed"] = ("9.9.9", "u", "notes", _delta_installer())
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: unelevated["closed"])
        assert len(unelevated["checks"]) == 1
