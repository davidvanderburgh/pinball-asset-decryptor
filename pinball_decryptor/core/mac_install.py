"""Install a Mac's missing host tools with the package manager it has.

Install Missing on the prerequisites strip used to be hidden on macOS, and
the gear menu's entry showed a box that said ``brew install gnupg ffmpeg``
and left the typing to the user.  A Mac that is handed a command to type is
being asked to do the app's job (David, 2026-08-19, on the Emulate tab's
"Set up emulator…"), so this does the work itself: the missing rows that
name a Mac package (:attr:`..core.prereqs.Prerequisite.mac_pkg`) become one
``brew install`` / ``port install`` run in the app's own log.

CHOSEN BY WHAT IS ALREADY ON THIS MAC.  Homebrew first because it never
runs as root and needs no password; MacPorts when that is what the machine
has (it installs system-wide, so macOS asks for the password once, in its
own dialog).  Neither is installed for the user here - without one there is
no plan, and the caller keeps its advice box.

The first Mac that needed this was cooltoy's, on Barrels of Fun (PAD-220):
gpg missing, the strip green, the Extract Failed box blaming the .fun file.

A MACPORTS THAT WILL NOT RUN IS FOUND OUT BEFORE THE PASSWORD.  The same
Mac came back the next day (PAD-221): its MacPorts had been installed for
macOS 15 and the Mac had since moved to macOS 26, so ``port`` refused every
command with "OS platform mismatch ... Please run 'sudo port migrate'".
The app asked for the password first and then only wrote MacPorts' refusal
to the log, which read as "it errors and does nothing".  Now
:func:`macports_health` runs ``port version`` (no password) before any plan
is shown; a MacPorts that needs migrating gets the migration as the first
consent step and the first command of the same one-password run, and a
MacPorts that is broken some other way blocks the plan with its own words
in a box instead of a password dialog.
"""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time

from .prereqs import MAC_TOOL_DIRS
from . import pad_temp

HOMEBREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
MACPORTS_PATHS = ("/opt/local/bin/port",)

#: Homebrew formula -> MacPorts port, where the two spell a tool differently.
PORT_NAMES = {"gnupg": "gnupg2"}

#: Darwin kernel major -> the macOS it ships with, for the words in the
#: consent dialog ("darwin 25" means nothing to the person reading it).
DARWIN_MACOS = {19: "10.15", 20: "11", 21: "12", 22: "13", 23: "14",
                24: "15", 25: "26"}

_PLATFORM_MISMATCH = re.compile(
    r'Current platform "(?P<current>[^"]+)" does not match expected '
    r'platform "(?P<expected>[^"]+)"')


def package_manager():
    """``(name, tool, admin)`` for the package manager this Mac has, or
    None: Homebrew (never root) ahead of MacPorts (needs admin)."""
    for p in HOMEBREW_PATHS:
        if os.path.isfile(p):
            return "Homebrew", p, False
    for p in MACPORTS_PATHS:
        if os.path.isfile(p):
            return "MacPorts", p, True
    return None


def macos_name(platform):
    """``"darwin 24"`` -> ``"macOS 15 (darwin 24)"``; anything else is
    returned as it came."""
    m = re.match(r"darwin (\d+)", platform or "")
    if m and int(m.group(1)) in DARWIN_MACOS:
        return "macOS %s (%s)" % (DARWIN_MACOS[int(m.group(1))], platform)
    return platform


def macports_health(tool, run=subprocess.run):
    """Can this MacPorts run at all?  None when ``port version`` works.

    Otherwise a dict: ``kind`` is ``"migrate"`` when MacPorts was installed
    for an older macOS than the one it is on (``current`` / ``expected`` are
    its two platform strings and ``port migrate`` is the cure), or
    ``"broken"`` for any other refusal; ``lines`` are the ``Error:`` lines
    it printed, ``text`` the one-paragraph explanation for a box.

    ``port version`` needs no password and takes about a second, so it is
    cheap enough to run before the consent dialog, which is the whole point:
    the password dialog must not come before the app knows the install can
    start.
    """
    try:
        proc = run([tool, "version"], stdout=subprocess.PIPE,
                   stderr=subprocess.STDOUT, env=_env(), timeout=60)
        rc, out = proc.returncode, proc.stdout or b""
    except subprocess.TimeoutExpired:
        rc, out = -1, b"port version did not answer within 60 s"
    except OSError as exc:
        rc, out = -1, str(exc).encode()
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    if rc == 0:
        return None
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    errors = [l for l in lines if l.startswith("Error")] or lines[:3]
    m = _PLATFORM_MISMATCH.search(out)
    if m:
        cur, exp = m.group("current"), m.group("expected")
        return {
            "kind": "migrate", "current": cur, "expected": exp,
            "lines": errors,
            "text": ("MacPorts on this Mac was installed for %s and this "
                     "Mac now runs %s, so it refuses to install anything "
                     "until it is migrated to this macOS."
                     % (macos_name(exp), macos_name(cur))),
        }
    return {
        "kind": "broken", "lines": errors,
        "text": ("MacPorts on this Mac cannot run (%s said: %s)."
                 % (tool, " / ".join(errors) if errors
                    else "exit %s" % rc)),
    }


def plan_for(missing):
    """The plan Install Missing runs for *missing*: the package manager
    this Mac has, checked (MacPorts) before anything is promised.  None
    when there is nothing to install or no manager (the caller keeps its
    advice box)."""
    mgr = package_manager()
    if mgr is None:
        return None
    health = macports_health(mgr[1]) if mgr[0] == "MacPorts" else None
    return install_plan(missing, manager=mgr, health=health)


def install_plan(missing, manager=None, health=None):
    """What Install Missing will DO for the *missing* prerequisites, or None
    when none of them names a Mac package or this Mac has no package
    manager.

    Like the Emulate tab's ``engine_setup_plan``, the consent list and the
    work are ONE object: ``commands`` are the argvs in order, ``steps`` the
    sentences the dialog shows, and the package names tie the two together
    (``install`` is the last command, the install itself).

    *health* is :func:`macports_health`'s answer for a MacPorts manager:
    ``"migrate"`` puts ``port -N migrate`` ahead of the install, in the
    same run and under the same one password; ``"broken"`` returns a plan
    whose ``blocked`` is the text to show instead of asking anything.
    """
    packages = []
    for p in missing:
        pkg = getattr(p, "mac_pkg", "") or ""
        if pkg and pkg not in packages:
            packages.append(pkg)
    if not packages:
        return None
    mgr = manager or package_manager()
    if mgr is None:
        return None
    name, tool, admin = mgr
    commands = []
    steps = []
    if name == "MacPorts":
        packages = [PORT_NAMES.get(p, p) for p in packages]
        # -N: no question this app cannot see gets asked half way through.
        install = [tool, "-N", "install"] + packages
    else:
        install = [tool, "install"] + packages
    label = " and ".join(packages)
    if name == "MacPorts" and health:
        if health.get("kind") != "migrate":
            return {"manager": name, "packages": packages, "label": label,
                    "admin": admin, "install": install, "commands": [],
                    "steps": [], "blocked": health.get("text", "")}
        commands.append([tool, "-N", "migrate"])
        steps.append(
            "%s Migrate it first (port migrate): MacPorts reinstalls "
            "itself for this macOS and then reinstalls every port it has "
            "installed. That can take a long time, and it needs the Xcode "
            "Command Line Tools for this macOS." % health.get("text", ""))
    commands.append(install)
    steps.append("Install %s with %s. Nothing already on this Mac is "
                 "changed or removed." % (label, name))
    if admin:
        steps.append("macOS will ask for your password once, in its own "
                     "dialog, because %s installs system-wide." % name)
    steps.append("Check the prerequisites again once it is done.")
    return {"manager": name, "packages": packages, "label": label,
            "admin": admin, "install": install, "commands": commands,
            "steps": steps, "migrate": bool(len(commands) > 1)}


def plan_command_line(plan):
    """The plan's commands as one line for the log."""
    cmds = plan.get("commands") or [plan["install"]]
    return " && ".join(" ".join(c) for c in cmds)


def failure_lines(lines):
    """The lines of an install's output that say why it failed: the
    ``Error:`` lines, else the last few.  What the failure box quotes."""
    errors = [l for l in lines if l.lstrip().startswith("Error")]
    return errors or [l for l in lines if l.strip()][-4:]


def run_plan(plan, log, popen=subprocess.Popen):
    """Run *plan*'s commands in order, every line of their output to
    ``log(line)``.  True when all finished with exit 0.  Blocks; call it
    off the UI thread.  MacPorts (admin) runs them all in ONE elevated
    shell so macOS asks for the password once."""
    commands = [list(c) for c in (plan.get("commands") or [plan["install"]])]
    try:
        if plan.get("admin"):
            for argv in commands:
                log(" ".join(shlex.quote(a) for a in argv))
            rc = _run_admin(commands, log, popen)
        else:
            rc = 0
            for argv in commands:
                log(" ".join(shlex.quote(a) for a in argv))
                rc = _run_plain(argv, log, popen)
                if rc:
                    break
    except OSError as exc:
        log("could not start %s: %s" % (commands[0][0], exc))
        return False
    if rc:
        log("%s did not finish (exit %s)." % (plan["label"], rc))
    return rc == 0


def _env():
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(MAC_TOOL_DIRS + (env.get("PATH", ""),))
    # Homebrew asks nothing when it knows nobody is there to answer.
    env["NONINTERACTIVE"] = "1"
    env["HOMEBREW_NO_ENV_HINTS"] = "1"
    return env


def _run_plain(argv, log, popen):
    proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 env=_env())
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip() if isinstance(
            raw, bytes) else str(raw).rstrip()
        if line:
            log(line)
    return proc.wait()


def _run_admin(commands, log, popen):
    """The MacPorts case: macOS's own password dialog via osascript, the
    output tailed from a file since the elevated shell has no pipe to us.
    Several commands run one after the other in the same script (``&&``),
    each announced by its own line, so one password covers them all and
    the log shows which one is running."""
    work = pad_temp.mkdtemp(prefix="pad_prereq_")
    script = os.path.join(work, "install.sh")
    out = os.path.join(work, "install.log")
    body = ["#!/bin/sh", "export PATH=%s:$PATH"
            % shlex.quote(":".join(MAC_TOOL_DIRS))]
    for i, argv in enumerate(commands):
        line = " ".join(shlex.quote(a) for a in argv)
        if len(commands) > 1:
            body.append("echo %s" % shlex.quote("==> " + line))
        body.append(line if i == len(commands) - 1 else line + " || exit $?")
    with open(script, "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")
    shell = "/bin/sh %s > %s 2>&1" % (shlex.quote(script), shlex.quote(out))
    osa = ('do shell script "%s" with administrator privileges'
           % shell.replace("\\", "\\\\").replace('"', '\\"'))
    try:
        proc = popen(["osascript", "-e", osa], stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE)
        seen = 0
        while proc.poll() is None:
            seen = _tail(out, seen, log)
            time.sleep(0.5)
        _tail(out, seen, log)
        err = (proc.stderr.read() or b"")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        if proc.returncode and err.strip():
            log(err.strip())
        return proc.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _tail(path, seen, log):
    try:
        with open(path, "rb") as f:
            f.seek(seen)
            data = f.read()
    except OSError:
        return seen
    for line in data.decode("utf-8", "replace").splitlines():
        if line.strip():
            log(line.rstrip())
    return seen + len(data)
