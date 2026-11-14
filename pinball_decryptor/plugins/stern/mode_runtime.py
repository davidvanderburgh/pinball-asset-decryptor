"""Where the app's PINNED mode runtime and the game ports are (item 127; item 149 uses it).

A mode the Modes tab authors is a mode FILE (:mod:`.mode_project`), and what reads it inside
the game is one object: the Mode SDK runtime (``pad_mode_runtime.c``) with the mode-file
interpreter (``mode_file.c``). No user ever builds anything, so that object is built once
by ``tools/spike2_emu/modes/sdk/build_prebuilt.sh`` and committed as
``sdk/prebuilt/mode.so``, with ``sdk/prebuilt/SOURCES.sha256`` recording the sources it came
from. Try it (the emulator) and Write (a card) both copy it from here.

A PORT tells the runtime where one game build's functions are
(``sdk/ports/<game_dir>-<version>.port``, or one derived on this machine for a card's build:
:func:`port_dirs`); the runtime refuses to hook a game whose code does not match its port, so
handing it the wrong one leaves the game stock, never broken.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sys

#: The files the pinned object is made from, in SOURCES.sha256's order.
SOURCES = ("pad_mode.h", "pad_stock.h", "pad_mode_runtime.c", "mode_file.c", "build_mode.sh")
#: PAD-1269: the 64-bit ARM object the Spike 3 machine loads (prebuilt/mode64.so) adds the
#: 64-bit hook layer pad_mode_runtime.c includes there.
SOURCES_A64 = ("pad_mode.h", "pad_stock.h", "hook_a64.h", "pad_mode_runtime.c", "mode_file.c",
               "build_mode.sh")
BUILDER = "tools/spike2_emu/modes/sdk/build_prebuilt.sh"


#: sdk_dir()'s answer once the folder was found: every port lookup asks it (thousands of
#: times while the Modes and Write tabs fill at start-up), and resolving the path from disk
#: each time cost over a second there (PAD-610)
_SDK_DIR = None


def sdk_dir():
    """``tools/spike2_emu/modes/sdk`` - beside the package in a checkout or an install, or
    under PyInstaller's bundle root in a frozen build (the Linux/macOS builds add
    ``tools/spike2_emu`` as data)."""
    global _SDK_DIR
    if _SDK_DIR is not None:
        return _SDK_DIR
    here = pathlib.Path(__file__).resolve().parents[3] / "tools" / "spike2_emu" / "modes" / "sdk"
    if here.is_dir():
        _SDK_DIR = str(here)
        return _SDK_DIR
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        frozen = pathlib.Path(bundle) / "tools" / "spike2_emu" / "modes" / "sdk"
        if frozen.is_dir():
            _SDK_DIR = str(frozen)
            return _SDK_DIR
    return str(here)


def prebuilt_object(arch="arm"):
    """The pinned mode runtime object (the runtime + the mode-file interpreter), as a path:
    ``mode.so`` for Spike 2 (32-bit ARM) or, for ``arch="a64"``, ``mode64.so`` for Spike 3
    (64-bit ARM). Raises FileNotFoundError, naming the builder, when it is missing."""
    name = "mode64.so" if arch == "a64" else "mode.so"
    path = os.path.join(sdk_dir(), "prebuilt", name)
    if not os.path.isfile(path):
        raise FileNotFoundError("the pinned mode runtime %s is missing - rebuild it with %s%s"
                                % (path, BUILDER, " -a a64" if arch == "a64" else ""))
    return path


def sources_file(arch="arm"):
    name = "SOURCES64.sha256" if arch == "a64" else "SOURCES.sha256"
    return os.path.join(sdk_dir(), "prebuilt", name)


def port_dirs():
    """The folders ports are read from, in the order a lookup tries them: the SDK's shipped
    ``ports`` folder, then this machine's derived ports (:func:`.port_derive.user_ports_dir`,
    where a card's build gets a port when none is shipped for it)."""
    dirs = [os.path.join(sdk_dir(), "ports")]
    try:
        from .port_derive import user_ports_dir
        dirs.append(user_ports_dir())
    except OSError:                       # the cache folder cannot be made: shipped ports only
        pass
    return dirs


def port_paths():
    """Every port as ``(game_dir, version, path)``, shipped ones first, each folder sorted. A
    derived port that is no longer current (:func:`.port_derive.derived_current`: another
    drafting revision, or its reference ports changed) is left out until the card is read
    again.

    The answer is kept until a file in the port folders or the recipes changes
    (:func:`_ports_stamp`): every lookup asks this, and working it out stats every reference
    of every derived port (thousands of files at start-up, PAD-610)."""
    dirs = port_dirs()
    stamp = _ports_stamp(dirs)
    cached = _PORT_PATHS.get("v")
    if cached is not None and cached[0] == stamp:
        return list(cached[1])
    out = []
    for n, d in enumerate(dirs):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            m = re.match(r"^(.+)-(\d+\.\d+(?:\.\d+)?)\.port$", name)
            path = os.path.join(d, name)
            if not m or not os.path.isfile(path):
                continue
            if n > 0:
                from .port_derive import derived_current
                if not derived_current(path):
                    continue
            out.append((m.group(1), m.group(2), path))
    _PORT_PATHS["v"] = (stamp, out)
    return list(out)


#: port_paths()'s last answer, with the _ports_stamp it was worked out at
_PORT_PATHS = {}



def _ports_stamp(dirs):
    """What port_paths() depends on, cheaply: every file's name, size and mtime in the port
    folders and the shipped recipes (one directory listing each; on Windows the listing
    carries the stats), the text of each derived port's sidecar (what derived_current reads:
    a sidecar rewritten in the same clock tick at the same size must still count as changed),
    the drafting revision, and which derived_current is in force."""
    from . import port_derive, portgen
    stamp = [tuple(dirs), portgen.REVISION, port_derive.derived_current]
    folders = (list(dirs) + [os.path.join(dirs[0], "recipes")]) if dirs else []
    for n, d in enumerate(folders):
        derived = 0 < n < len(dirs)
        try:
            with os.scandir(d) as it:
                entries = []
                for e in it:
                    try:
                        st = e.stat()
                    except OSError:
                        continue
                    ent = (e.name, st.st_size, st.st_mtime_ns)
                    if derived and e.name.endswith(".json"):
                        try:
                            with open(e.path, "rb") as f:
                                ent += (f.read(),)
                        except OSError:
                            pass
                    entries.append(ent)
        except OSError:
            entries = None
        stamp.append((d, tuple(sorted(entries)) if entries is not None else None))
    return tuple(stamp)


def port_file(game_dir, version):
    """The port for one game build, ``<game_dir>-<version>.port``, or None when there is none
    (then no mode can run on that build). The SDK's shipped ports win; a port derived on this
    machine (:func:`port_dirs`) is found after them.

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
    for game, named, path in port_paths():
        if game == game_dir and version_key(named) == want:
            return path
    return None


def ports():
    """Every ``(game_dir, version)`` there is a port for (shipped or derived here), sorted."""
    return sorted({(g, v) for g, v, _p in port_paths()})


def _sha256_lf(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r", b"")).hexdigest()


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def recorded(arch="arm"):
    """The arch's SOURCES file as ``({name: sha256}, compiler line)``."""
    sums, compiler = {}, ""
    with open(sources_file(arch), "r", encoding="utf-8") as f:
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


def stale_reasons(arch="arm"):
    """Why the arch's pinned object may not match the SDK's sources, as sentences that name
    the builder. Empty = current. The sources are hashed with CRs stripped, as the
    builder hashes them, so a CRLF checkout of unchanged sources is still current."""
    sdk = sdk_dir()
    sources = SOURCES_A64 if arch == "a64" else SOURCES
    obj_name = "mode64.so" if arch == "a64" else "mode.so"
    sums_name = "SOURCES64.sha256" if arch == "a64" else "SOURCES.sha256"
    flag = " -a a64" if arch == "a64" else ""
    try:
        sums, _compiler = recorded(arch)
    except OSError:
        return ["prebuilt/%s is missing - run %s%s" % (sums_name, BUILDER, flag)]
    out = []
    for name in sources:
        path = os.path.join(sdk, name)
        if name not in sums:
            out.append("%s does not list %s - run %s%s" % (sums_name, name, BUILDER, flag))
        elif not os.path.isfile(path):
            out.append("the SDK has no %s" % name)
        elif _sha256_lf(path) != sums[name]:
            out.append("%s changed since prebuilt/%s was built - run %s%s and commit "
                       "prebuilt/" % (name, obj_name, BUILDER, flag))
    obj = os.path.join(sdk, "prebuilt", obj_name)
    if not os.path.isfile(obj):
        out.append("prebuilt/%s is missing - run %s%s" % (obj_name, BUILDER, flag))
    elif sums.get(obj_name) != _sha256(obj):
        out.append("prebuilt/%s is not the object %s records - run %s%s"
                   % (obj_name, sums_name, BUILDER, flag))
    return out


def prebuilt_is_current(arch="arm"):
    """True when the arch's pinned object was built from the SDK sources as they are now."""
    return not stale_reasons(arch)
