"""Blue-green updates on Windows: install the new version beside the running
one, then swap the two folders on Restart to update (PAD-1024).

daveyvandy: "One button push to restart the app and it quickly loads the new
version.  Background downloads / installs to speed things up."  The in-app
update ran the setup exe over the top of the install, and only once the app
had closed - so Restart waited on copying a few hundred MB of bundled Python,
repairing its permissions and compiling ~400 modules.  None of that needs
the app closed if it happens somewhere else.  So:

* **Stage** (in the background, while the user works).  The downloaded setup
  exe runs silently with ``/STAGED=1 /DIR=<app>.next``: a whole install of
  the new version in a sibling folder.  ``/STAGED`` (pinball_decryptor.iss,
  ``IsStaged``) leaves out everything that points outside that folder - the
  shortcuts, the uninstall entry, the Visual Pinball controller's
  registration - because the folder is about to be renamed.  Then what the
  user's install has that a fresh one lacks is copied in: the uninstaller
  (the staged install has none, and the one in place still lists the right
  paths) and whatever pip added to the bundled Python since
  (``install_prerequisites.ps1`` puts faster-whisper and sounddevice there,
  and a user may have added their own).  Last, the same ACL repair the
  installer runs, over the whole new Python.
* **Swap** (Restart to update).  A detached PowerShell helper waits for the
  app to exit, renames ``<app>`` to ``<app>.old`` and ``<app>.next`` to
  ``<app>`` - two renames on one volume, a fraction of a second - brings the
  uninstall entry's version up to date, registers the Visual Pinball
  controller from the new folder and starts the app through ``launcher.vbs``
  as the shortcuts do.  The shortcuts never change: they name ``<app>``.

ANY FAILURE FALLS BACK TO THE INSTALLER.  Staging that fails leaves Restart to
update running the downloaded setup exe the way the app always has.  A swap
that cannot rename (something still has a file open in the app's folder)
puts the folder back and runs that same installer, whose
``/FORCECLOSEAPPLICATIONS`` deals with the straggler.  The user ends up on
the new version either way; blue-green only makes it quick.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

#: the staged install's sibling folder, and the one the swap moves the
#: running version to (deleted once the new one has started)
NEXT_SUFFIX = ".next"
OLD_SUFFIX = ".old"
#: written into the staged folder once it is whole: what version it holds
MARKER = ".pad_staged.json"

#: the setup exe's switches for the background install
STAGE_ARGS = ('/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCLOSEAPPLICATIONS '
              '/STAGED=1 /MERGETASKS="!runprereqs,!desktopicon" /DIR="%s"')
#: how long the background install may take before it is given up on
STAGE_TIMEOUT = 20 * 60

#: Inno's uninstall entry for the app's AppId (pinball_decryptor.iss)
UNINSTALL_KEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\{B8E2D4F6-9A3C-5E7B-CAF1-4A6B8D2E0F3C}_is1")

#: what a whole install of the app has (relative to its folder)
_LAYOUT = (os.path.join("python", "pythonw.exe"),
           os.path.join("python", "python.exe"),
           "launcher.vbs", "Pinball Asset Decryptor.pyw",
           os.path.join("pinball_decryptor", "__init__.py"))
_SITE = os.path.join("python", "Lib", "site-packages")
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


def installed_app_dir(executable=None, platform=None):
    """The installed app's folder when this process runs from one, else None.

    The bundled Python is ``<app>\\python\\pythonw.exe``, and an install made
    by the setup exe has its ``launcher.vbs`` and an Inno uninstaller beside
    it.  A source checkout, or anything else, has no business being swapped,
    so it keeps the plain over-the-top update.
    """
    if (platform or sys.platform) != "win32":
        return None
    exe = os.path.abspath(executable or sys.executable)
    app = os.path.dirname(os.path.dirname(exe))
    if os.path.basename(os.path.dirname(exe)).lower() != "python":
        return None
    if not os.path.isfile(os.path.join(app, "launcher.vbs")):
        return None
    try:
        names = os.listdir(app)
    except OSError:
        return None
    if not any(n.lower().startswith("unins") and n.lower().endswith(".exe")
               for n in names):
        return None
    return app


def next_dir(app_dir):
    return app_dir + NEXT_SUFFIX


def old_dir(app_dir):
    return app_dir + OLD_SUFFIX


def tree_version(folder):
    """The ``__version__`` an app folder holds, or None."""
    try:
        with open(os.path.join(folder, "pinball_decryptor", "__init__.py"),
                  encoding="utf-8") as f:
            m = _VERSION_RE.search(f.read())
    except OSError:
        return None
    return m.group(1) if m else None


def _layout_problem(folder, version):
    for rel in _LAYOUT:
        if not os.path.isfile(os.path.join(folder, rel)):
            return "the new install has no %s" % rel
    got = tree_version(folder)
    if got != version:
        return "the new install is v%s, not v%s" % (got, version)
    return None


def staged_version(app_dir):
    """The version waiting in ``<app>.next``, or None when there is no whole
    one (no marker: staging never finished, or never started)."""
    try:
        with open(os.path.join(next_dir(app_dir), MARKER),
                  encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data.get("version") if isinstance(data, dict) else None


def staged_install_ok(app_dir, version):
    """True when ``<app>.next`` holds a whole, finished install of
    *version*."""
    return (staged_version(app_dir) == version
            and _layout_problem(next_dir(app_dir), version) is None)


def _dist_name(entry):
    """The project a ``*.dist-info`` / ``*.egg-info`` folder belongs to,
    normalised (PEP 503), or None for anything else."""
    low = entry.lower()
    if not (low.endswith(".dist-info") or low.endswith(".egg-info")):
        return None
    return re.sub(r"[-_.]+", "-", entry.rsplit(".", 1)[0].split("-")[0]
                  ).lower()


def carry_over(app_dir, new_dir):
    """Copy into *new_dir* what the running install has and a fresh one does
    not.  Returns the relative paths copied.

    * The Inno uninstaller files (``unins000.exe`` / ``.dat``): the staged
      install made none, and the ones in place record this folder's paths,
      which the swap keeps.
    * site-packages entries the new bundle lacks: what pip added since.  A
      package the new bundle ships in any version is never copied over it -
      its ``*.dist-info`` is skipped by project name, and its package folder
      already exists - so an upgrade is not undone by an old copy.
    * ``python\\Scripts`` entries the new bundle lacks (pip's console
      scripts for those packages).
    """
    copied = []

    def _copy(src, dst, rel):
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                "__pycache__"))
        else:
            shutil.copy2(src, dst)
        copied.append(rel)

    for name in os.listdir(app_dir):
        if name.lower().startswith("unins"):
            src = os.path.join(app_dir, name)
            dst = os.path.join(new_dir, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                _copy(src, dst, name)
    for sub in (_SITE, os.path.join("python", "Scripts")):
        old_sub = os.path.join(app_dir, sub)
        new_sub = os.path.join(new_dir, sub)
        if not os.path.isdir(old_sub) or not os.path.isdir(new_sub):
            continue
        new_names = set(os.listdir(new_sub))
        new_dists = {_dist_name(n) for n in new_names} - {None}
        for name in sorted(os.listdir(old_sub)):
            if name in new_names or name == "__pycache__":
                continue
            dist = _dist_name(name)
            if dist is not None and dist in new_dists:
                continue
            _copy(os.path.join(old_sub, name), os.path.join(new_sub, name),
                  os.path.join(sub, name))
    return copied


def _repair_acls(folder, run):
    """The installer's bundled-Python ACL repair (pinball_decryptor.iss
    [Run]), over the staged copy, so what carry_over copied is readable by
    the unelevated user too.  Best effort, as it is there."""
    py = os.path.join(folder, "python")
    icacls = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "icacls.exe")
    for args in (["/reset", "/T", "/C", "/Q"],
                 ["/grant", "*S-1-5-32-545:(OI)(CI)RX", "/T", "/C", "/Q"]):
        try:
            run([icacls, py] + args, capture_output=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:                               # noqa: BLE001
            pass


#: one background install at a time: a newer release found while one runs
#: cancels it, but its setup exe finishes its copy before the cancel is seen,
#: and the next must not clear the folder under it
_STAGE_LOCK = threading.Lock()


def stage_install(setup_path, app_dir, version, run=None, cancel_cb=None,
                  progress_cb=None):
    """See :func:`_stage_install`; serialised by :data:`_STAGE_LOCK`."""
    with _STAGE_LOCK:
        if cancel_cb and cancel_cb():
            raise InterruptedError("staging canceled")
        return _stage_install(setup_path, app_dir, version, run, cancel_cb,
                              progress_cb)


def _stage_install(setup_path, app_dir, version, run=None, cancel_cb=None,
                   progress_cb=None):
    """Install *version* from *setup_path* into ``<app>.next`` without
    touching the running app.  Returns ``(True, carried)`` or
    ``(False, reason)``, with no half-staged folder left behind on failure.

    *cancel_cb* is checked between the steps; a cancel removes the folder
    and raises InterruptedError.  *progress_cb* is told how far along it
    is, 0-100 (see :func:`_watch_progress`).
    """
    run = run or subprocess.run
    target = next_dir(app_dir)
    shutil.rmtree(target, ignore_errors=True)
    if os.path.exists(target):
        return False, "%s could not be cleared" % target
    ok, info = _stage_into(setup_path, app_dir, target, version, run,
                           cancel_cb, progress_cb or (lambda pct: None))
    if not ok:
        shutil.rmtree(target, ignore_errors=True)
    return ok, info


def folder_bytes(folder):
    """The bytes of every file under *folder* (0 when it is not there);
    files that vanish or cannot be read mid-walk are skipped."""
    total = 0
    stack = [folder]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                else:
                    total += e.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    return total


#: how far the bar goes while the setup exe copies; carrying over and the
#: ACL repair take it the rest of the way
COPY_SHARE = 90
#: how often the copy is measured (seconds)
WATCH_EVERY = 1.0


def _watch_progress(app_dir, target, progress_cb, stop):
    """While the setup exe runs: report how much of the new folder is
    written, against the size of the running install (PAD-1029, David:
    "while it's installing in the background, I want to see a progress
    circle / bar").  The silent setup exe says nothing while it works, and
    the new version is about as big as the one in place, so its folder
    filling up is the honest measure.  Never past COPY_SHARE - 1: the copy
    is not done until the setup exe says so."""
    whole = folder_bytes(app_dir) or 1
    last = -1
    while not stop.wait(WATCH_EVERY):
        pct = min(COPY_SHARE - 1,
                  int(folder_bytes(target) * COPY_SHARE / whole))
        if pct > last:
            last = pct
            progress_cb(pct)


def _stage_into(setup_path, app_dir, target, version, run, cancel_cb,
                progress_cb):
    try:
        progress_cb(0)
        stop = threading.Event()
        watcher = threading.Thread(
            target=_watch_progress, args=(app_dir, target, progress_cb, stop),
            daemon=True, name="update-stage-progress")
        watcher.start()
        try:
            r = run('"%s" %s' % (setup_path, STAGE_ARGS % target),
                    capture_output=True, timeout=STAGE_TIMEOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            # 740 = ERROR_ELEVATION_REQUIRED: the setup exe asks for
            # administrator and this process is not elevated
            if getattr(e, "winerror", None) == 740:
                return False, "it needs administrator rights"
            return False, "the installer did not start (%s)" % e
        except subprocess.TimeoutExpired:
            return False, "the installer took too long"
        finally:
            stop.set()
            watcher.join()
        code = getattr(r, "returncode", 1)
        if code != 0:
            return False, "the installer stopped with code %s" % code
        if cancel_cb and cancel_cb():
            raise InterruptedError("staging canceled")
        problem = _layout_problem(target, version)
        if problem:
            return False, problem
        progress_cb(COPY_SHARE)
        carried = carry_over(app_dir, target)
        if cancel_cb and cancel_cb():
            raise InterruptedError("staging canceled")
        progress_cb(COPY_SHARE + 3)
        _repair_acls(target, run)
        with open(os.path.join(target, MARKER), "w", encoding="utf-8") as f:
            json.dump({"version": version, "setup": str(setup_path)}, f)
        progress_cb(100)
        return True, carried
    except BaseException as e:
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(e, (InterruptedError, KeyboardInterrupt, SystemExit)):
            raise
        return False, "%s: %s" % (type(e).__name__, e)


def clear_leftovers(app_dir, current_version):
    """Delete ``<app>.old`` (the version a swap replaced) and a staged
    ``<app>.next`` that is not newer than the running app.  Returns
    ``(deleted, failed)`` like old_versions' pruning."""
    from .old_versions import _version
    deleted, failed = [], []
    targets = [old_dir(app_dir)]
    staged = staged_version(app_dir)
    if staged and _version(staged) <= _version(str(current_version)):
        targets.append(next_dir(app_dir))
    for path in targets:
        if not os.path.isdir(path):
            continue
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            failed.append((path, "still in use"))
        else:
            deleted.append(path)
    return deleted, failed


def _psq(text):
    """A PowerShell single-quoted string literal."""
    return "'" + str(text).replace("'", "''") + "'"


#: The swap, run detached once the app has exited.  Every step that can
#: fail before the new folder is in place undoes itself and hands over to
#: the installer, so the worst case is the old, slow update.
_SWAP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$log = %(log)s
function Say($m) { try { Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) } catch {} }
$app = %(app)s; $next = %(next)s; $old = %(old)s
function Fallback($why) {
  Say ('swap not done: ' + $why + ' - running the installer instead')
  if (%(setup)s) { Start-Process -FilePath %(setup)s -ArgumentList %(setup_args)s }
  exit 1
}
Say 'waiting for the app (pid %(pid)d) to close'
try { Wait-Process -Id %(pid)d -Timeout 180 -ErrorAction SilentlyContinue } catch {}
if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path -LiteralPath $old) { Fallback ($old + ' is still there') }
if (-not (Test-Path -LiteralPath (Join-Path $next %(marker)s))) { Fallback 'the new version is not staged' }
$moved = $false
for ($i = 0; $i -lt 30 -and -not $moved; $i++) {
  try { Rename-Item -LiteralPath $app -NewName (Split-Path $old -Leaf); $moved = $true }
  catch { Start-Sleep -Milliseconds 500 }
}
if (-not $moved) { Fallback 'a file in the app folder is still in use' }
try { Rename-Item -LiteralPath $next -NewName (Split-Path $app -Leaf) }
catch {
  try { Rename-Item -LiteralPath $old -NewName (Split-Path $app -Leaf) } catch {}
  Fallback ('the new folder would not move: ' + $_)
}
Remove-Item -LiteralPath (Join-Path $app %(marker)s) -Force -ErrorAction SilentlyContinue
Say 'swapped in v%(version)s'
foreach ($k in @(%(keys)s)) {
  try {
    # only the entry of THIS install: Inno writes its folder as InstallLocation
    $loc = ''
    if (Test-Path -LiteralPath $k) { $loc = [string](Get-ItemProperty -LiteralPath $k).InstallLocation }
    if ($loc -and ($loc.TrimEnd('\') -eq $app.TrimEnd('\'))) {
      Set-ItemProperty -LiteralPath $k -Name DisplayVersion -Value %(version_q)s
      Set-ItemProperty -LiteralPath $k -Name DisplayName -Value %(display_q)s
    }
  } catch { Say ('uninstall entry not updated: ' + $_) }
}
if (%(register)s) {
  try {
    $vpx = Join-Path $app 'tools\spike2_emu\vpx\padvpx.py'
    if (Test-Path -LiteralPath $vpx) {
      Start-Process -FilePath (Join-Path $app 'python\python.exe') -ArgumentList ('"' + $vpx + '" register') -WorkingDirectory $app -WindowStyle Hidden -Wait
    }
  } catch { Say ('Visual Pinball controller not registered: ' + $_) }
}
if (%(launch)s) {
  Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + (Join-Path $app 'launcher.vbs') + '"') -WorkingDirectory $app
  Say 'started the new version'
}
Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $old) { Say ($old + ' is left for the next start to delete') }
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""


def swap_script(app_dir, version, setup_path, pid, log_path, launch=True,
                register=True, setup_args=None):
    """The PowerShell text of the swap (see module docstring)."""
    from .updater import INSTALLER_ARGS
    keys = ", ".join(_psq("HKLM:\\" + k) for k in (
        UNINSTALL_KEY,
        UNINSTALL_KEY.replace("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\", 1)))
    return _SWAP_SCRIPT % {
        "log": _psq(log_path), "app": _psq(app_dir),
        "next": _psq(next_dir(app_dir)), "old": _psq(old_dir(app_dir)),
        "setup": _psq(setup_path or ""),
        "setup_args": _psq(setup_args if setup_args is not None
                           else INSTALLER_ARGS),
        "pid": int(pid), "marker": _psq(MARKER), "version": version,
        "version_q": _psq(version),
        "display_q": _psq("Pinball Asset Decryptor v%s" % version),
        "keys": keys, "register": "$true" if register else "$false",
        "launch": "$true" if launch else "$false"}


def start_swap(app_dir, version, setup_path, pid=None, popen=None,
               launch=True, register=True, log_path=None):
    """Write the swap script to the temp folder and start it detached.
    Returns ``(True, log_path)`` or ``(False, reason)``.

    Started from the temp folder, never from inside the app's: a process
    whose working directory is in the folder holds it open, and the rename
    would fail on our own helper.

    NEVER WITH DETACHED_PROCESS (PAD-1029, David: "Pressing restart to
    update is not restarting the app").  Windows PowerShell started with no
    console at all exits 0 at once without running a line of the script -
    no log, no swap, no relaunch - so the app closed and nothing brought it
    back.  CREATE_NO_WINDOW gives it a console nobody sees, and a child
    outlives its parent on Windows anyway; the new process group keeps the
    app's Ctrl+C / Ctrl+Break from reaching it.
    """
    popen = popen or subprocess.Popen
    tmp = tempfile.gettempdir()
    log_path = log_path or os.path.join(tmp, "pad_update_swap.log")
    fd, script = tempfile.mkstemp(prefix="pad-swap-", suffix=".ps1")
    with os.fdopen(fd, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(swap_script(app_dir, version, setup_path,
                            pid if pid is not None else os.getpid(),
                            log_path, launch=launch, register=register))
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        popen(["powershell.exe", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
               "-File", script], cwd=tmp, creationflags=flags,
              close_fds=True, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        try:
            os.unlink(script)
        except OSError:
            pass
        return False, str(e)
    return True, log_path
