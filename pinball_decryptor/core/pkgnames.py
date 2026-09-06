"""Debian package names, and what they are called on Arch.

The app names Linux packages in three places.  The Linux prerequisite
installer (installer/install_prerequisites_linux.sh) carries its own copy of
this table in shell - MFR_PACMAN_PACKAGES - because it runs without Python.
The prerequisite strip's hover hints are each plugin's
``Prerequisite.install_hint``, written in apt's spelling with "(in WSL)" after
it back when Windows was the only desktop.  And the Emulate tab's "Run this,
then start again" advice on a Linux desktop lists apt names too.

On Arch and its spins (Omarchy, CachyOS, EndeavourOS, Manjaro) the apt
spelling is pacman's "target not found", so the second and third are
translated here at the moment they are shown, and a test holds this table
and the installer's together so the two cannot drift apart.

Names verified against Arch's package database on 2026-09-06.
"""
import functools
import re
import shutil
import sys

#: apt name -> pacman name(s).  "" means the capability needs no package on
#: Arch (glibc ships its headers, so libc6-dev is nothing there).  Two names
#: where Arch splits what Debian ships as one: the binfmt registration is its
#: own package there, and the rig needs the registration, not only the
#: emulator.  Anything not listed is spelled the same on both.
ARCH_NAMES = {
    "python3-zstandard": "python-zstandard",
    "xvfb": "xorg-server-xvfb",
    "webp": "libwebp",
    "xorriso": "libisoburn",
    "xxd": "tinyxxd",
    "libc6-dev": "",
    "python3-tk": "tk",
    "qemu-user-static": "qemu-user-static qemu-user-static-binfmt",
    "busybox-static": "busybox",
}

#: apt name -> the AUR package that carries it.  The AUR is not a repository,
#: it is recipes: pacman cannot install from it, so these are named on a line
#: of their own, with the helper that can.
AUR_NAMES = {
    "gcc-arm-linux-gnueabihf": "arm-linux-gnueabihf-gcc",
}


def to_pacman(names):
    """``(pacman, aur)`` for a sequence of apt names.

    Each entry may hold several names ("gcc libc6-dev" is one capability in
    the Emulate tab's table).  Order is kept and duplicates dropped, so the
    command built from the answer reads in the order the caller asked.
    """
    pacman, aur = [], []
    for entry in names:
        for name in str(entry).split():
            if name in AUR_NAMES:
                if AUR_NAMES[name] not in aur:
                    aur.append(AUR_NAMES[name])
                continue
            for mapped in ARCH_NAMES.get(name, name).split():
                if mapped not in pacman:
                    pacman.append(mapped)
    return pacman, aur


def pacman_commands(names):
    """The lines a Linux desktop is told to run for these apt names, spelled
    for pacman: one ``pacman -S --needed`` for everything the repositories
    have, and one AUR line after it when something is only there."""
    pacman, aur = to_pacman(names)
    cmds = []
    if pacman:
        cmds.append("sudo pacman -S --needed " + " ".join(pacman))
    if aur:
        cmds.append("yay -S " + " ".join(aur)
                    + "    # from the AUR (or paru -S); pacman cannot")
    return cmds


def arch_label(name):
    """One apt entry as an Arch user should read it in a list: the pacman
    names, then any AUR one marked as such - "gcc" for "gcc libc6-dev",
    "arm-linux-gnueabihf-gcc (AUR)" for the cross compiler.  A name the
    table does not know (criu, which is built from source) is itself."""
    pacman, aur = to_pacman([name])
    return " ".join(pacman + ["%s (AUR)" % a for a in aur]) or name


def binfmt_advice(pm):
    """The one command that registers the 32-bit ARM handler, when the rig's
    own advice is absent - an older setupcheck.sh, or a probe that timed out
    before that line."""
    if pm == "pacman":
        return "sudo pacman -S --needed qemu-user-static qemu-user-static-binfmt"
    return "sudo apt install qemu-user-static"


@functools.lru_cache(maxsize=None)
def linux_package_manager():
    """``"apt"``, ``"pacman"`` or ``None``: what this Linux installs packages
    with.  ``None`` off Linux, and on a Linux with neither.  apt wins when
    both are present, the same order the installer decides in."""
    if not sys.platform.startswith("linux"):
        return None
    if shutil.which("apt-get"):
        return "apt"
    if shutil.which("pacman"):
        return "pacman"
    return None


_APT_INSTALL = re.compile(r"apt-get install ((?:[\w.+-]+)(?: [\w.+-]+)*)")
_IN_WSL = re.compile(r"[ \t]*\(in WSL\)")


def localize_hint(hint, pm=None):
    """A plugin's install hint, spelled for this Linux.

    The hints were written for Windows: ``apt-get install X (in WSL)``.  On a
    Linux desktop "(in WSL)" is wrong on every distro, and on Arch the name is
    too.  Off Linux, or when nothing is known about this one, the hint is
    returned as written - a hint that names no apt package is never touched.
    """
    if not hint:
        return hint
    pm = pm or linux_package_manager()
    if not pm:
        return hint

    def _spell(m):
        names = m.group(1).split()
        if pm != "pacman":
            return "apt-get install " + " ".join(names)
        pacman, aur = to_pacman(names)
        out = "sudo pacman -S --needed " + " ".join(pacman) if pacman else ""
        if aur:
            out += (" and " if out else "") + " ".join(aur) + " from the AUR"
        return out

    return _IN_WSL.sub("", _APT_INSTALL.sub(_spell, hint))
