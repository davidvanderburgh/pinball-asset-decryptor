"""Plumbing shared by the emulator control panels, parameterised on a rig.

There are two emulator rigs now - ``tools/spike2_emu`` for Stern Spike 2 and
``tools/jjp_emu`` for Jersey Jack - and both are Linux programs reached the
same way from Windows.  The parts that do not care WHICH rig they are talking
to live here so the two panels cannot drift apart on them.

That matters more than it sounds: the Spike 2 rig's own hardest-won rule is
*never let two scripts define the same fact* (``plans/TODO.md``), and it was
learned from ``alive.sh`` and ``killgame.sh`` disagreeing about what a running
rig is.  Two GUI panels each with their own idea of how to spell a WSL path is
the same mistake one level up.

What is deliberately NOT here: anything that knows a rig's directory, its
script names, its status vocabulary, or how it is launched.  Those genuinely
differ - Spike 2 runs a chroot under qemu-user and reaches macOS through a
container, JJP runs a native x86-64 binary and needs a USB dongle - and
pretending otherwise would produce a shared function with two unrelated halves.
"""

import subprocess
import sys

#: Never flash a console window when a helper runs.  A control surface that
#: blinks a black rectangle every poll is worse than one that is a little slow.
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def wsl_path(win_path):
    """``c:\\repo\\tools\\jjp_emu`` -> ``/mnt/c/repo/tools/jjp_emu``.

    A POSIX path has no drive letter and passes through untouched, so this is
    also correct on a Linux desktop where there is no translation to do.
    """
    p = (win_path or "").replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def rig_cmd(rig_dir, script, *args, env=()):
    """Run one of ``rig_dir``'s scripts as the ordinary user.

    ``env`` is a list of ``NAME=value`` strings applied with ``env(1)`` rather
    than by a shell, because ``wsl.exe`` RE-PARSES its argument line: a ``$var``
    or ``$(subst)`` written into the command reaches the far side already
    expanded to nothing.  Every rig script that needs a value gets it this way.
    """
    if sys.platform == "win32":
        head = ["wsl.exe", "-e"]
        path = "%s/%s" % (wsl_path(rig_dir), script)
    else:
        head = []
        path = "%s/%s" % (rig_dir, script)
    if env:
        head = head + ["env"] + [str(e) for e in env]
    return head + ["bash", path] + [str(a) for a in args]


def rig_cmd_root(rig_dir, script, *args, env=()):
    """The same script as root.  Windows only, and that is honest rather than
    a limitation settled for.

    ``wsl -u root`` is uid 0 with no password, because the Windows side is what
    launches the distro.  On a Linux desktop the equivalent is sudo, which
    wants a password a GUI app has nowhere to ask for without becoming an
    invisible hang.

    Kept separate from :func:`rig_cmd` rather than being a flag on it: the two
    are different privilege levels and a wrong argument must not be able to
    flip one into the other.
    """
    if sys.platform != "win32":
        raise RuntimeError("rig_cmd_root is WSL-only")
    head = ["wsl.exe", "-u", "root", "-e"]
    if env:
        head = head + ["env"] + [str(e) for e in env]
    return head + ["bash", "%s/%s" % (wsl_path(rig_dir), script)] + \
        [str(a) for a in args]


def parse_status(text):
    """Parse a rig ``status.sh``'s ``key=value`` output into a dict.

    Both rigs speak key=value for exactly this reason: a control surface must
    never have to parse prose.  Lines without an ``=`` are ignored rather than
    guessed at, so a script that prints a warning does not corrupt the reading.
    """
    info = {}
    for line in (text or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            info[key.strip()] = value.strip()
    return info
