"""Emulate tab for Barrels of Fun - the Tk-free facts of the rig in
``tools/bof_emu`` (the tab itself is ``webui/tabs/emulate_bof.py``).

A BoF game is a native x86-64 Godot export, so like JJP there is no CPU to
emulate - and unlike JJP there is no key either: the only thing between the
game and a PC is the hardware it talks to over USB serial (a FAST Neuron, its
expansion LED bus, and on Dune and Winchester BoF's own "BICS" board).  The rig
answers those protocols; see ``docs/plans/bof_emulator.md``.

The tab takes a ``.fun`` - the file the machine itself installs, or one the
Write tab just built - so a mod can be played before it goes on a USB stick.
The rig decrypts it into a cache inside the app's Linux; the ``.fun`` is only
ever read.

Everything that knows the rig's layout lives here, as the JJP tab's does in
``emulate_jjp_core``; how a script is invoked and how status is parsed is
``webui/rig.py``'s, shared by every rig.
"""

import json
import os
import pathlib
import sys

from pinball_decryptor.core import runtime
from pinball_decryptor.webui import rig as _rig
from ..core import wsl_up as _wsl_up

#: The rig ships next to this package.  ``PAD_BOF_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "bof_emu"
)

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: watch.sh's step headers -> the footer ladder (copy = first chip).
FOOTER_STEPS = (("== Decrypt ==", "copy", 0, "Decrypting the game…"),
                ("== Boards ==", "boot", None, "Starting the boards…"),
                ("== Game ==", "techalerts", None, "Starting the game…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Decrypt", "Boards", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on.
EXIT_TEXT = {
    3: "Not enough free space in the app's Linux to unpack this build.",
    4: "This file is not a Barrels of Fun build the emulator knows "
       "(Dune, Winchester Mystery House or Labyrinth), or it is damaged.",
    5: "The .fun opened but holds no game program.",
    6: "The game did not start.",
    8: "The game started, then exited during start-up.",
    9: "The game is running but never found its boards.",
}


def rig_dir():
    return os.environ.get("PAD_BOF_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh", "ctl.sh",
                         "bofhwshim.so"))


def platform_ok():
    """watch.sh runs as root, and only WSL gives the app a root without a
    password prompt (``webui/rig.rig_cmd_root``) - so Windows only.  A
    function, not an inline test, so tests stub THIS rather than faking
    ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    """The app's own Linux when it is installed (it carries gpg, Xvfb and
    Mesa, and has room for a 4 GB game), else the machine's default."""
    return runtime.distro_for("bof")


def rig_cmd(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def title_keys():
    """``title:passphrase,...`` for watch.sh, from the BoF plugin's own game
    table - the rig never hard-codes a passphrase.  Only the GPG-symmetric
    titles have a passphrase; Bon Jovi ships a signed disk image with no key,
    so it is skipped here."""
    from pinball_decryptor.plugins.bof.games import GAME_DB
    return ",".join("%s:%s" % (k, v["passphrase"])
                    for k, v in sorted(GAME_DB.items())
                    if v.get("passphrase"))


def title_name(key):
    from pinball_decryptor.plugins.bof.games import GAME_DB
    return GAME_DB.get(key, {}).get("display", key or "")


def hw_state(info):
    """The boards' JSON from status.sh's ``hw=`` line, or {}."""
    try:
        return json.loads(info.get("hw") or "{}")
    except ValueError:
        return {}


def load_profile(title):
    """The title's switch table and anchors (tools/bof_emu/profiles), or {}."""
    path = os.path.join(rig_dir(), "profiles", "%s.json" % (title or ""))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def state_text(info):
    """(label, hint) for the headline, first problem first."""
    if not info:
        return "Checking…", ""
    if info.get(_wsl_up.ASLEEP_KEY):
        return _wsl_up.ASLEEP_STATE
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The game runs inside WSL, the app's Linux.")
    if info.get("running") == "1":
        hw = hw_state(info)
        st = hw.get("status") or {}
        if not st.get("hardware_connected"):
            return ("Starting",
                    "%s is up and finding its boards…" %
                    title_name(info.get("title")))
        bits = [title_name(info.get("title"))]
        rss = int(info.get("rss_kb") or 0)
        if rss:
            bits.append("%.1f GB" % (rss / 1048576.0))
        up = int(info.get("uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        return "Running", "  ·  ".join(bits)
    return "Stopped", ""


def boards_text(hw):
    """"Neuron, 4 expansion, BICS" - what answered."""
    st = hw.get("status") or {}
    if not st:
        return "—"
    parts = []
    if st.get("net_id"):
        parts.append("Neuron")
    if st.get("exp"):
        parts.append("%d expansion" % len(st["exp"]))
    if st.get("bics_id"):
        parts.append("BICS")
    return ", ".join(parts) or "none yet"


def balls_text(hw):
    b = hw.get("balls") or {}
    if not b:
        return "—"
    return "%d in trough, %d in play%s" % (
        b.get("trough", 0), b.get("in_play", 0),
        ", 1 in shooter lane" if b.get("shooter") else "")
