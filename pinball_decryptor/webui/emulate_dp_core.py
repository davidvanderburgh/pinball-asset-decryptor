"""Emulate tab for Dutch Pinball - the Tk-free facts of the rig in
``tools/dp_emu`` (the tab itself is ``webui/tabs/emulate_dp.py``).

Two games, two programs.  The Big Lebowski is an x86-64 Linux program on
Dutch Pinball's own P-ROC framework, and it ships its own simulator: started
with ``fakepinproc`` it drives no hardware, so the rig gives it only what the
machine's disk gave it (base assets, the installed version), a window, sound
and a key for every switch.  Alice's Adventures in Wonderland is a native
C++ program with no simulator; the rig runs it in a chroot of its own root
and answers it as its P-ROC (tools/dp_emu/aaiw).  See tools/dp_emu/README.md.

The tab takes the machine's DISK IMAGE (the base assets exist nowhere else)
and, for The Big Lebowski, optionally an update .zip laid over it - the
factory's, or one the Write tab built - so a mod can be played before it
goes on a USB stick.

Everything that knows the rig's layout lives here, as the BoF tab's does in
``emulate_bof_core``; how a script is invoked and how status is parsed is
``webui/rig.py``'s, shared by every rig.
"""

import json
import os
import pathlib
import sys

from pinball_decryptor.core import runtime
from pinball_decryptor.webui import rig as _rig
from ..core import wsl_up as _wsl_up

#: The rig ships next to this package.  ``PAD_DP_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "dp_emu"
)

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: watch.sh's step headers -> the footer ladder (copy = first chip).
FOOTER_STEPS = (("== Prepare ==", "copy", 0, "Preparing the game…"),
                ("== Game ==", "boot", None, "Starting the game…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Prepare", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on.
EXIT_TEXT = {
    2: "The disk image or update file could not be read.",
    3: "Not enough free space in the app's Linux to unpack this game.",
    4: "This disk image holds no Dutch Pinball game (/home/dp/game).",
    5: "The update does not install onto the version on this disk image - "
       "clear the Update field to play the image as it is.",
    6: "The game did not start.",
    8: "The game started, then exited during start-up.",
}


def rig_dir():
    return os.environ.get("PAD_DP_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh", "ctl.sh",
                         "dpinput.c", "dppf.py"))


def platform_ok():
    """watch.sh runs as root (it loop-mounts the disk image), and only WSL
    gives the app a root without a password prompt - so Windows only.  A
    function, so tests stub THIS rather than faking ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    return runtime.distro_for("dp")


def rig_cmd(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def is_image(path):
    return (path or "").lower().endswith((".img", ".bin", ".raw"))


def is_update(path):
    return (path or "").lower().endswith(".zip")


def state_text(info):
    """(label, hint) for the headline."""
    if not info:
        return "Checking…", ""
    if info.get(_wsl_up.ASLEEP_KEY):
        return _wsl_up.ASLEEP_STATE
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The game runs inside WSL, the app's Linux.")
    if info.get("running") == "1":
        bits = [title_name(info)]
        rss = int(info.get("rss_kb") or 0)
        if rss:
            bits.append("%.1f GB" % (rss / 1048576.0))
        up = int(info.get("uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        return "Running", "  ·  ".join(b for b in bits if b)
    return "Stopped", ""


def ended_text(code):
    """The log line for a game that ended while nobody pressed Stop.
    ``code`` is status.sh's last_exit: the game program's exit status (Alice;
    The Big Lebowski's run has none)."""
    code = (code or "").strip()
    what = {"0": "it quit by itself",
            "134": "it aborted (a crash inside the game)",
            "139": "it crashed (segmentation fault)",
            "137": "it was killed from outside (SIGKILL) - not the game's own doing",
            "143": "it was stopped from outside (SIGTERM)"}.get(code)
    if what:
        return "the game ended - %s (exit %s)." % (what, code)
    if code:
        return "the game ended (exit %s)." % code
    return "the game ended."


def title_name(info):
    """"The Big Lebowski" - the game's own name, without the "Pinball" its
    machine.yaml adds."""
    t = (info or {}).get("title") or ""
    if t.endswith(" Pinball"):
        t = t[:-len(" Pinball")]
    return t


def load_switches(path):
    """The rig's switches.json (dpswitches.py) as a dict, or {}."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
