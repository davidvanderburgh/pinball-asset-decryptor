"""Windows extended-length paths.

Windows' plain path APIs stop at 260 characters (``MAX_PATH``).  This project
routinely goes past that without anything looking unusual: a Spike 2 project
folder holds glyph slices at

    <project>/images/scene_textures/glyphs/<atlas stem>/U+0041_A.png

which is 120+ characters of suffix on its own, and the Build's output sits
under whatever folder the user picked.  Peter hit exactly this — his font
import applied, then the build failed, and shortening the build path fixed it
with no error saying why.

Prefixing a fully-qualified path with ``\\\\?\\`` opts that one call out of
``MAX_PATH``.  It is a SYSCALL-BOUNDARY thing: pass :func:`ext` output straight
to ``open`` / ``os.makedirs`` / ``shutil`` / ``PIL``, and never store it, log
it, or write it into a manifest — the prefix is not a path users should ever
see.

No-op on POSIX (which has no such limit), so call sites stay platform-free.
"""

import os
import sys

#: Longest path the plain Windows APIs accept (drive letter + 259 + NUL).
MAX_PATH = 260

_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\?\\UNC\\"
#: Win32 device namespace — ``\\.\PHYSICALDRIVE1`` and friends.
_DEVICE_PREFIX = "\\\\.\\"


def ext(path):
    """*path* in a form the OS will accept however long it is.

    Returns it unchanged on non-Windows, when it is empty, when it already
    carries the prefix, or when it names a DEVICE (``\\\\.\\PHYSICALDRIVE1``,
    which Direct-SD writes to) — the device namespace has no length limit and
    rewriting it as UNC would address a share called ``.`` that doesn't exist.

    Otherwise the result is absolute and normalized, because the
    extended-length form is passed to the filesystem verbatim — ``..``, ``/``
    and relative segments are NOT resolved for it, so a raw prefix on a
    relative path would simply fail to open."""
    if sys.platform != "win32" or not path:
        return path
    p = str(path)
    if p.startswith(_PREFIX) or p.startswith(_DEVICE_PREFIX):
        return p
    p = os.path.abspath(p)
    if p.startswith(_DEVICE_PREFIX):
        return p                      # abspath can normalise // into \\.\ too
    if p.startswith("\\\\"):
        # UNC: \\server\share\... -> \\?\UNC\server\share\...
        return _UNC_PREFIX + p[2:]
    return _PREFIX + p


def is_long(path):
    """Whether *path* is past what the plain Windows APIs accept.  Always
    False elsewhere — used only to explain a failure, never to refuse work."""
    if sys.platform != "win32" or not path:
        return False
    return len(os.path.abspath(str(path))) >= MAX_PATH


def hint(path):
    """A sentence naming the length problem, or ``""`` when there isn't one.

    Worth saying out loud: a too-long path fails with a bare "cannot find the
    file" that reads as a missing file, which is what sent Peter looking in the
    wrong place."""
    if not is_long(path):
        return ""
    return ("This path is %d characters, past Windows' %d-character limit — "
            "use a shorter folder." % (len(os.path.abspath(str(path))),
                                       MAX_PATH))
