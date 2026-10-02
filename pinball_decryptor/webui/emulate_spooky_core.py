"""Emulate tab for Spooky Pinball - the Tk-free facts of the rig in
``tools/spooky_emu`` (the tab itself is ``webui/tabs/emulate_spooky.py``).

Spooky's games since Halloween are native x86-64 Linux programs (Unity or
Godot), so like Barrels of Fun there is no CPU to emulate and no key: the
rig stands in for the one board each talks to over USB serial (Spooky's
"Warden" playfield controller, or Halloween's and Ultraman's "Pinotaur").
See ``tools/spooky_emu/README.md``.  Rick and Morty and Alice Cooper's
Nightmare Castle are Python games on a P3-ROC: the rig's ``proc/`` half
runs them on ``tools/proc_emu``'s board (PAD-269), and the rig's scripts
send their files there, so this tab drives them the same way (PAD-319).

``SUPPORTED`` is every title the rig runs, told apart by the update file's
name the way the machine tells them apart (PAD-316).  The tab names them up
front and refuses any other file with that answer, rather than failing
inside the rig.

Everything that knows the rig's layout lives here, as the BoF tab's does in
``emulate_bof_core``; how a script is invoked and how status is parsed is
``webui/rig.py``'s, shared by every rig.
"""

import fnmatch
import json
import os
import pathlib
import sys

from pinball_decryptor.core import rigslot, runtime
from pinball_decryptor.webui import rig as _rig

#: The rig ships next to this package.  ``PAD_SPOOKY_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spooky_emu"
)

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: The Spooky games the emulator runs: (display name, the rig's title key
#: (tools/spooky_emu/spktitles.py; proc/prepare.py's TITLES for the P-ROC
#: games), the update file's name patterns, lower case).  A .pkg is told
#: apart by its name, as the machine and the Spooky plugin's
#: PKG_FILENAME_PATTERNS do; a Write-tab build keeps that name.
SUPPORTED = (
    ("Beetlejuice", "bj", ("*.beetlejuice",)),
    ("Scooby-Doo", "scooby", ("*.scooby",)),
    ("Texas Chainsaw Massacre", "tcm", ("tcm-*.pkg",)),
    ("Evil Dead", "ed", ("*.ed",)),
    ("Looney Tunes", "looney", ("*.looney",)),
    ("Halloween", "h78", ("code_h78*.pkg",)),
    ("Ultraman", "um", ("code_um*.pkg",)),
    ("Rick and Morty", "rm", ("rm-gamecode*.pkg",)),
    ("Alice Cooper's Nightmare Castle", "ac", ("ac-gamecode*.pkg",)),
    # the DMD games (PAD-320): Ben Heck's pinHeck boards, emulated in
    # tools/pinheck_emu - the update zip as Spooky ships it, or its PRG
    ("Jetsons", "jet", ("jetsons_code*.zip", "jet_v*.prg")),
    ("Domino's Spectacular Pinball Adventure", "dom", ("dom_v*.zip", "dom_v*.prg")),
    ("Rob Zombie's Spookshow International", "rzo", ("rzupdate_v*.zip", "rzo_v*.prg")),
)

#: The P-ROC games' title keys (tools/spooky_emu/proc).
PROC_KEYS = ("rm", "ac")

#: The pinHeck DMD games' title keys: no WSL rig - the game runs in a window
#: of its own on this PC's Python (tools/pinheck_emu/window.py).
PINHECK_KEYS = ("jet", "dom", "rzo")

#: tools/pinheck_emu, beside the Spooky rig.  ``PAD_PINHECK_EMU_DIR`` moves it.
DEFAULT_PINHECK_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "pinheck_emu"
)

#: The file picker's filter: every pattern above, once.
FILE_PATTERNS = " ".join(sorted({"*." + p.rsplit(".", 1)[1]
                                 for _n, _k, pats in SUPPORTED
                                 for p in pats}))

#: watch.sh's step headers -> the footer ladder (copy = first chip).
FOOTER_STEPS = (("== Unpack ==", "copy", 0, "Unpacking the game…"),
                ("== Board ==", "boot", None, "Starting the board…"),
                ("== Game ==", "techalerts", None,
                 "Starting the game (a minute or two)…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Unpack", "Board", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on.
EXIT_TEXT = {
    3: "Not enough free space in the app's Linux to unpack this update.",
    4: "This file is not an update of a Spooky game the emulator runs, or "
       "it is damaged.",
    5: "The file opened but holds no game program.",
    6: "The game did not reach attract mode.",
    7: "Setting up the emulator failed - it downloads the game's Python the "
       "first time, so check the internet connection and Start again.",
}


def supported_names():
    return [name for name, _key, _pats in SUPPORTED]


def title_of(path):
    """The display name of the game *path* is an update of, or "".  By the
    file's name, the way the machine itself tells its update files apart."""
    base = os.path.basename((path or "").replace("\\", "/")).lower()
    for name, _key, pats in SUPPORTED:
        if any(fnmatch.fnmatchcase(base, p) for p in pats):
            return name
    return ""


def supported_file(path):
    """Is *path* an update of a game the emulator runs?"""
    return bool(title_of(path))


def key_of(path):
    """The title key of the game *path* is an update of, or ""."""
    title = title_of(path)
    return next((k for n, k, _p in SUPPORTED if n == title), "")


def is_pinheck(path):
    """Is *path* one of the pinHeck DMD games (a window, not the WSL rig)?"""
    return key_of(path) in PINHECK_KEYS


def pinheck_dir():
    return os.environ.get("PAD_PINHECK_EMU_DIR") or DEFAULT_PINHECK_DIR


def pinheck_available():
    d = pinheck_dir()
    return all(os.path.isfile(os.path.join(d, f))
               for f in ("window.py", "machine.py", "pic32.py", "page/index.html"))


def pinheck_cmd(py, path, audio_ctl):
    """The pinHeck game window's command line: the game runs in it, so the
    window IS the run; ``--parent-pipe`` closes it when the app closes its
    stdin (Stop)."""
    return [py, os.path.join(pinheck_dir(), "window.py"), path, "--parent-pipe",
            "--audio-ctl", audio_ctl]


def rig_dir():
    return os.environ.get("PAD_SPOOKY_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh", "cancel.sh",
                         "cache.sh", "ctl.sh", "spkshim.so", "spkwarden.py",
                         "spkswitches.py", "spkpf.py", "spkvol.py",
                         "spktitles.py", "proc/watch.sh", "proc/prepare.py",
                         "proc/run_game.sh", "proc/sppctl.py",
                         "proc/sppswitches.py"))


def platform_ok():
    """watch.sh runs as root, and only WSL gives the app a root without a
    password prompt (``webui/rig.rig_cmd_root``) - so Windows only.  A
    function, not an inline test, so tests stub THIS rather than faking
    ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    """The app's own Linux when it is installed (it carries gpg, Xvfb and
    Mesa, and has room for a 5 GB game), else the machine's default."""
    return runtime.distro_for("spooky")


def _rig_kw(kw):
    """*kw* for webui/rig.py: the distro, and the rig slot this app drives
    first in the env (``rigslot.rig_env``: empty on an ordinary install -
    rig 0 - and PAD_SLOT / PAD_LABEL for an app a ticket started, so its runs
    stay off rig 0, as the Stern and PB tabs' do; PAD-319)."""
    kw.setdefault("distro", rig_distro())
    kw["env"] = rigslot.rig_env() + list(kw.get("env") or ())
    return kw


def rig_cmd(*args, **kw):
    return _rig.rig_cmd(rig_dir(), *args, **_rig_kw(kw))


def rig_cmd_root(*args, **kw):
    return _rig.rig_cmd_root(rig_dir(), *args, **_rig_kw(kw))


def state_text(info):
    """(label, hint) for the headline, first problem first."""
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The game runs inside WSL, the app's Linux.")
    if info.get("running") == "1":
        name = game_name(info)
        if info.get("attract") != "1":
            return ("Starting", "%s is loading…" % name)
        bits = [name]
        if info.get("version"):
            bits.append(info["version"])
        rss = int(info.get("rss_kb") or 0)
        if rss:
            bits.append("%.1f GB" % (rss / 1048576.0))
        up = int(info.get("uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        return "Running", "  ·  ".join(bits)
    return "Stopped", ""


def game_name(info):
    """The running game's name, from status.sh's title_name (or its key)."""
    if info.get("title_name"):
        return info["title_name"]
    key = info.get("title") or "bj"
    return next((n for n, k, _p in SUPPORTED if k == key), "the game")


def parse_cache(text):
    """``cache.sh --list`` -> ``(entries, disk)``: the AP rig's protocol, so
    its parser (and the AP tab's Cache window) serve this tab too."""
    from .emulate_ap_core import parse_cache as _parse
    return _parse(text)


def cache_label(entry):
    """What the Cache window calls an entry: bj_v2026.09.15.11 ->
    Beetlejuice v2026.09.15.11 (a build is <title key>_<version>)."""
    name = entry["name"]
    key, _, version = name.partition("_")
    title = next((n for n, k, _p in SUPPORTED if k == key), "")
    return "%s %s" % (title, version) if title and version else name
