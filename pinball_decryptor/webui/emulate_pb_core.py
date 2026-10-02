"""Emulate tab for Pinball Brothers - the Tk-free facts of its two rigs,
``tools/pb_emu`` (Predator) and ``tools/pbio_emu`` (Alien, ABBA; PAD-315;
Queen, PAD-326).
The tab itself is ``webui/tabs/emulate_pb.py``.

Predator is two native x86-64 Linux programs (pinprog, the rules; vidprog,
the screen), so like Barrels of Fun and Spooky there is no CPU to emulate and
no key: the rig stands in for the boards the game talks to over USB serial
(a FAST Neuron with its I/O nodes and expansion boards).  See
``tools/pb_emu/README.md``.

TWO RIGS, ONE TAB.  Predator is Pinball Brothers' only FAST machine; Alien,
ABBA and Queen run on PB's own I/O boards (the hardware PB inherited from
Heighway), a different rig - the same idea (the game's own two programs, an
emulated board), a different board: ``tools/pbio_emu/README.md``.  The file a
person picks says which rig runs it (``kind_of``); the rest of the tab is the
same.  Queen's updates are deltas over its restore image
(clonezilla-live-queen20d.iso), which carries its media; the rig stacks
them.  ABBA runs with its screens dark: its updates carry the program and
the sound, not the factory image's pictures and videos (``TITLE_NOTES``).

A PB update is a FULL .upd and then DELTAS over it; a person picks the
version they want and the rig finds the rest of the chain beside it
(``tools/pb_emu/pbupdates.py``; ``tools/pbio_emu/pbiofiles.py``, which also
takes a restore ISO - the whole machine).

Everything that knows the rigs' layout lives here, as the Spooky tab's does
in ``emulate_spooky_core``; how a script is invoked and how status is parsed
is ``webui/rig.py``'s, shared by every rig.
"""

import ntpath
import os
import pathlib
import re
import sys

from pinball_decryptor.core import rigslot, runtime
from pinball_decryptor.webui import rig as _rig

#: The rigs ship next to this package.  ``PAD_PB_EMU_DIR`` moves Predator's,
#: ``PAD_PBIO_EMU_DIR`` the I/O-board one.
_TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools"
DEFAULT_RIG_DIR = str(_TOOLS / "pb_emu")
DEFAULT_PBIO_DIR = str(_TOOLS / "pbio_emu")

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: The Pinball Brothers games the emulator runs: (display name, the rig,
#: how their files are named).  Alien and ABBA share "pbap"; the major
#: version tells them apart (Alien 4.x, ABBA 1.x: pbiofiles.py).
SUPPORTED = (
    ("Predator", "pb", re.compile(r"^pbpp_predator_game_.*\.upd$", re.I)),
    ("Alien", "pbio",
     re.compile(r"^(pbap4\w*\.upd|clonezilla-live-.*alien.*\.iso)$", re.I)),
    ("ABBA", "pbio",
     re.compile(r"^(pbap1\w*\.upd|clonezilla-live-.*abba.*\.iso)$", re.I)),
    ("Queen", "pbio",
     re.compile(r"^(pbq\w*\.upd|clonezilla-live-.*queen.*\.iso)$", re.I)),
)
#: Said when the game starts, and on the page while it runs.
TITLE_NOTES = {
    "Queen": ("Queen has no Launch button: both flippers launch the ball, "
              "and start the song picked on the song select each ball "
              "begins with."),
    "ABBA": ("ABBA plays, but its screens stay dark: its update files carry "
             "the program and the sound, not the pictures and videos the "
             "factory installed. Play it from the playfield window."),
}

#: watch.sh's step headers -> the footer ladder (copy = first chip).
FOOTER_STEPS = (("== Setup ==", "copy", 0,
                 "Setting up the emulator (once, about 700 MB)…"),
                ("== Unpack ==", "copy", 0, "Unpacking the game…"),
                ("== Board ==", "boot", None, "Starting the board…"),
                ("== Game ==", "techalerts", None,
                 "Starting the game (under a minute)…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Unpack", "Board", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on - Predator's
#: rig (``exit_text`` picks; ``PBIO_EXIT_TEXT`` is Alien's and ABBA's).
EXIT_TEXT = {
    3: "Not enough free space in the app's Linux to unpack this update.",
    4: "This file is not one of the Pinball Brothers games the emulator "
       "runs (Predator, Alien, ABBA, Queen): pick the game's .upd update, "
       "or a restore image (clonezilla-live-alien40.iso, "
       "clonezilla-live-queen20d.iso).",
    5: "The update could not be unpacked, or holds no game program - if you "
       "picked a delta (pbpp_predator_game_1_0_1.upd), the full update it "
       "builds on (pbpp_predator_game_1_0.upd) must be in the same folder.",
    6: "The game did not reach attract mode.",
    7: "The emulator's one-time setup did not finish (it downloads about "
       "700 MB) - check the connection and press Start again.",
}
PBIO_EXIT_TEXT = {
    3: "Not enough free space in the app's Linux to unpack this game "
       "(Alien's restore image needs about 4 GB, Queen's about 22 GB "
       "while it unpacks and 10 GB after, a full update about 2.5 GB).",
    4: EXIT_TEXT[4],
    5: "The game could not be unpacked, or these files hold no complete "
       "game. A small follow-up update (pbap412.upd, pbap145.upd) needs the "
       "full update it builds on (pbap411.upd, pbap141.upd) in the same "
       "folder - and the first start needs Alien's restore image "
       "(clonezilla-live-alien40.iso) there too: it is the machine's own "
       "Linux, which every one of these games runs on. Queen's updates "
       "(pbq….upd) need Queen's own restore image "
       "(clonezilla-live-queen20d.iso) beside them: it holds Queen's "
       "pictures, videos and sound.",
    6: "The game did not reach attract mode.",
}

SETUP_LABEL = "Set up emulator…"
SETUP_BUSY = "Setting up…"

_VERSION = re.compile(r"_game_(\d+(?:_\d+)*)\.upd$", re.I)


def _base(path):
    """The file's name, whichever separator the path uses: a Windows path
    (a file picked on Select card) must read the same in a test on Linux."""
    return ntpath.basename(path or "")


def supported_names():
    return [name for name, _kind, _pat in SUPPORTED]


def _match(path):
    base = _base(path)
    return next(((name, kind) for name, kind, pat in SUPPORTED
                 if pat.match(base)), ("", ""))


def supported_file(path):
    """Is *path* a file of a game the emulator runs?  By name, the way
    Pinball Brothers names its updates and restore images."""
    return bool(_match(path)[0])


def title_of(path):
    """The game a supported file is for, else ""."""
    return _match(path)[0]


def kind_of(path):
    """The rig that runs *path*: "pb" (Predator: tools/pb_emu), "pbio"
    (Alien, ABBA, Queen: tools/pbio_emu), else ""."""
    return _match(path)[1]


def exit_text(kind, rc):
    return (PBIO_EXIT_TEXT if kind == "pbio" else EXIT_TEXT).get(rc, "")


def version_of(path):
    """pbpp_predator_game_1_0_1.upd -> "1.0.1" (else "")."""
    m = _VERSION.search(_base(path))
    return m.group(1).replace("_", ".") if m else ""


def rig_dir(kind="pb"):
    if kind == "pbio":
        return os.environ.get("PAD_PBIO_EMU_DIR") or DEFAULT_PBIO_DIR
    return os.environ.get("PAD_PB_EMU_DIR") or DEFAULT_RIG_DIR


#: what each rig must have, by script
_RIG_FILES = {
    "pb": ("watch.sh", "stop.sh", "status.sh", "cancel.sh", "cache.sh",
           "ctl.sh", "setup.sh", "prepare.sh", "run_game.sh", "pbshim.so",
           "pbfast.py", "pbctl.py", "pbswitches.py", "pbpf.py", "pbvol.py",
           "pbtitles.py", "pbupdates.py"),
    "pbio": ("watch.sh", "stop.sh", "status.sh", "cancel.sh", "cache.sh",
             "ctl.sh", "prepare.sh", "run_game.sh", "killgame.sh",
             "pbiopath.sh", "pbioboard.py", "pbioctl.py", "pbiotitles.py",
             "pbiofiles.py", "pbioswitches.py", "pbioaudio.py", "pbioshim.so"),
}


def rig_available(kind=None):
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches.  The switch window and the volume
    holder live in the AP and Spooky rigs; the I/O-board rig's window is
    Predator's (pbpf.py --rig pbio).  No *kind*: both rigs."""
    for k in ((kind,) if kind else ("pb", "pbio")):
        d = rig_dir(k)
        if not all(os.path.isfile(os.path.join(d, s)) for s in _RIG_FILES[k]):
            return False
    tools = os.path.dirname(rig_dir("pb"))
    return (os.path.isfile(os.path.join(rig_dir("pb"), "pbpf.py"))
            and os.path.isfile(os.path.join(tools, "ap_emu", "appf.py"))
            and os.path.isfile(os.path.join(tools, "spooky_emu", "spkvol.py")))


def platform_ok():
    """watch.sh runs as root, and only WSL gives the app a root without a
    password prompt (``webui/rig.rig_cmd_root``) - so Windows only.  A
    function, not an inline test, so tests stub THIS rather than faking
    ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    """The app's own Linux when it is installed, else the machine's
    default."""
    return runtime.distro_for("pb")


def _rig_kw(kw):
    """The rig's folder, and *kw* for webui/rig.py: the distro, and the rig
    slot this app drives first in the env (``rigslot.rig_env``: empty on an
    ordinary install - rig 0 - and PAD_SLOT / PAD_LABEL for an app a
    ticket started, so its runs stay off rig 0 as the Stern tab's do)."""
    d = rig_dir(kw.pop("kind", "pb"))
    kw.setdefault("distro", rig_distro())
    kw["env"] = rigslot.rig_env() + list(kw.get("env") or ())
    return d, kw


def rig_cmd(*args, **kw):
    """A rig script's command line: Predator's rig, or ``kind="pbio"`` for
    Alien's and ABBA's."""
    d, kw = _rig_kw(kw)
    return _rig.rig_cmd(d, *args, **kw)


def rig_cmd_root(*args, **kw):
    d, kw = _rig_kw(kw)
    return _rig.rig_cmd_root(d, *args, **kw)


def mem_text(kb):
    """The game's memory: pinprog is small (tens of MB), so MB below 1 GB."""
    kb = int(kb or 0)
    if not kb:
        return ""
    if kb < 1048576:
        return "%d MB" % max(1, round(kb / 1024.0))
    return "%.1f GB" % (kb / 1048576.0)


def state_text(info):
    """(label, hint) for the headline, first problem first."""
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The game runs inside WSL, the app's Linux.")
    if info.get("running") == "1":
        name = info.get("title_name") or "The game"
        if info.get("attract") != "1":
            return ("Starting", "%s is loading…" % name)
        bits = [name]
        if info.get("version"):
            bits.append(info["version"])
        if mem_text(info.get("rss_kb")):
            bits.append(mem_text(info.get("rss_kb")))
        up = int(info.get("uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        return "Running", "  ·  ".join(bits)
    return "Stopped", ""


def setup_notice(info, rt_state, can_install=True):
    """``(text, button)`` for the tab's setup notice, as the AP tab's
    (``emulate_ap_core.setup_notice``): what is not set up, and whether "Set
    up emulator…" can fix it.  ``("", False)`` when nothing is wrong (or
    nothing is known yet).  Only Predator's rig has libraries to download
    (its status says ``ready=``); Alien's and ABBA's run on the machine's
    own, restored from its image."""
    if rt_state == "foreign":
        from . import runtime_prompt
        return runtime_prompt.notice("foreign", ""), False
    if rt_state in ("absent", "stale") and can_install:
        what = ("is not on this PC yet" if rt_state == "absent"
                else "is from an older version of this app")
        return ("Not set up: the Linux this app installs for its emulators "
                "%s, so the game would run in this PC's own WSL distro "
                "instead, which this emulator is not built for. Press "
                "“Set up emulator…” to install it and the libraries "
                "the game runs on (one-time downloads, about 1.2 GB)." % what,
                True)
    if (info or {}).get("wsl") == "1" and info.get("ready") == "0":
        return ("Not set up yet: the emulator still needs the libraries the "
                "game runs on (about 700 MB, once). Press “Set up "
                "emulator…” now, or the first Start does it.", True)
    return "", False


def parse_cache(text):
    """``cache.sh --list`` -> ``(entries, disk)``: the AP rig's protocol, so
    its parser (and the AP tab's Cache window) serve this tab too."""
    from .emulate_ap_core import parse_cache as _parse
    return _parse(text)


def cache_label(entry):
    """What the Cache window calls an entry: predator_1_0_1-028700ac ->
    Predator 1.0.1; the setup -> the libraries; the I/O-board rig's
    os-clonezilla-live-alien40 -> "Alien machine image (….iso)", upd-pbap145
    -> "ABBA update (pbap145.upd)"."""
    name = entry["name"]
    if entry.get("kind") == "setup" or name == "setup":
        return "Emulator setup (Predator's libraries)"
    if entry.get("kind") in ("os", "update"):
        src = entry.get("src") or name.split("-", 1)[-1]
        title = title_of(src) or "Pinball Brothers"
        what = "machine image" if entry["kind"] == "os" else "update"
        return "%s %s (%s)" % (title, what, src)
    m = re.match(r"^([a-z]+)_([0-9_]+)-[0-9a-f]+$", name)
    if m:
        return "%s %s" % (m.group(1).title(), m.group(2).replace("_", "."))
    return name
