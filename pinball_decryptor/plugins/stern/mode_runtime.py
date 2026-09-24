"""Where the app's PINNED mode runtime and the game ports are (item 127; item 149 uses it).

A mode the Modes tab authors is a mode FILE (:mod:`.mode_project`), and what reads it inside
the game is one object: the Mode SDK runtime (``pad_mode_runtime.c``) with the mode-file
interpreter (``mode_file.c``). No user ever builds anything, so that object is built once
by ``tools/spike2_emu/modes/sdk/build_prebuilt.sh`` and committed as
``sdk/prebuilt/mode.so``, with ``sdk/prebuilt/SOURCES.sha256`` recording the sources it came
from. Try it (the emulator) and Write (a card) both copy it from here.

A PORT tells the runtime where one game build's functions are
(``sdk/ports/<game_dir>-<version>.port``); the runtime refuses to hook a game whose code
does not match its port, so handing it the wrong one leaves the game stock, never broken.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sys

#: The files the pinned object is made from, in SOURCES.sha256's order.
SOURCES = ("pad_mode.h", "pad_stock.h", "pad_mode_runtime.c", "mode_file.c", "build_mode.sh")
BUILDER = "tools/spike2_emu/modes/sdk/build_prebuilt.sh"


def sdk_dir():
    """``tools/spike2_emu/modes/sdk`` - beside the package in a checkout or an install, or
    under PyInstaller's bundle root in a frozen build (the Linux/macOS builds add
    ``tools/spike2_emu`` as data)."""
    here = pathlib.Path(__file__).resolve().parents[3] / "tools" / "spike2_emu" / "modes" / "sdk"
    if here.is_dir():
        return str(here)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        frozen = pathlib.Path(bundle) / "tools" / "spike2_emu" / "modes" / "sdk"
        if frozen.is_dir():
            return str(frozen)
    return str(here)


def prebuilt_object():
    """The pinned ``mode.so`` (the runtime + the mode-file interpreter), as a path.
    Raises FileNotFoundError, naming the builder, when it is missing."""
    path = os.path.join(sdk_dir(), "prebuilt", "mode.so")
    if not os.path.isfile(path):
        raise FileNotFoundError("the pinned mode runtime %s is missing - rebuild it with %s"
                                % (path, BUILDER))
    return path


def sources_file():
    return os.path.join(sdk_dir(), "prebuilt", "SOURCES.sha256")


def port_file(game_dir, version):
    """The port for one game build, ``sdk/ports/<game_dir>-<version>.port``, or None when
    the SDK has no port for it (then no mode can run on that build).

    ``1.15``, ``1_15``, ``1.15.0`` and ``1_15_0`` are all the port version ``1.15``, and a
    nonzero third part is kept, so ``1.15.1`` never silently takes ``1.15``'s port. The
    match is by VALUE (:func:`.mode_project.version_key`, the family's one comparison),
    not by the spelling of the file name: ``jaws_le-1.02.port`` is the port for a card
    whose index says ``1_02_0``."""
    if not game_dir or not version:
        return None
    from .mode_project import version_key
    want = version_key(version)
    if not want:
        return None
    for game, named in ports():
        if game == game_dir and version_key(named) == want:
            path = os.path.join(sdk_dir(), "ports", "%s-%s.port" % (game, named))
            return path if os.path.isfile(path) else None
    return None


def ports():
    """Every ``(game_dir, version)`` the SDK has a port for, sorted."""
    out = []
    try:
        names = os.listdir(os.path.join(sdk_dir(), "ports"))
    except OSError:
        return out
    for name in names:
        m = re.match(r"^(.+)-(\d+\.\d+(?:\.\d+)?)\.port$", name)
        if m:
            out.append((m.group(1), m.group(2)))
    return sorted(out)


def _sha256_lf(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r", b"")).hexdigest()


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def recorded():
    """SOURCES.sha256 as ``({name: sha256}, compiler line)``."""
    sums, compiler = {}, ""
    with open(sources_file(), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("compiler "):
                compiler = line[len("compiler "):]
                continue
            digest, _, name = line.partition("  ")
            if digest and name:
                sums[name.strip()] = digest.strip()
    return sums, compiler


def stale_reasons():
    """Why the pinned object may not match the SDK's sources, as sentences that name
    the builder. Empty = current. The sources are hashed with CRs stripped, as the
    builder hashes them, so a CRLF checkout of unchanged sources is still current."""
    sdk = sdk_dir()
    try:
        sums, _compiler = recorded()
    except OSError:
        return ["prebuilt/SOURCES.sha256 is missing - run %s" % BUILDER]
    out = []
    for name in SOURCES:
        path = os.path.join(sdk, name)
        if name not in sums:
            out.append("SOURCES.sha256 does not list %s - run %s" % (name, BUILDER))
        elif not os.path.isfile(path):
            out.append("the SDK has no %s" % name)
        elif _sha256_lf(path) != sums[name]:
            out.append("%s changed since prebuilt/mode.so was built - run %s and commit "
                       "prebuilt/" % (name, BUILDER))
    obj = os.path.join(sdk, "prebuilt", "mode.so")
    if not os.path.isfile(obj):
        out.append("prebuilt/mode.so is missing - run %s" % BUILDER)
    elif sums.get("mode.so") != _sha256(obj):
        out.append("prebuilt/mode.so is not the object SOURCES.sha256 records - run %s" % BUILDER)
    return out


def prebuilt_is_current():
    """True when the pinned object was built from the SDK sources as they are now."""
    return not stale_reasons()
