"""Emulate tab for American Pinball - the Tk-free facts of the rig in
``tools/ap_emu`` (the tab itself is ``webui/tabs/emulate_ap.py``).

AP's games are SkeletonGame (PyProcGameHD) Python programs with the
framework's own simulator built in (FakePinPROC), so there is no CPU to
emulate and no licence check: the rig supplies what the machine's OS did -
Python 2.7 (3.14 for Galactic Tank Force's 2026 build) and its libraries,
built once by ``setup.sh`` inside the app's Linux, a machine at rest (a full
trough, the coin door shut), a window, sound, and a way to press every
switch.  Hot Wheels and Galactic Tank Force draw through AP's own ``apiav``,
which the rig starts too.  See tools/ap_emu/README.md.

The tab takes the game-code ``.pkg`` - the file the machine installs, or one
the Write tab built - so a mod can be played before it goes on a USB stick.
The rig decrypts it with the AP plugin's key into a cache inside the app's
Linux; the ``.pkg`` is only ever read.

Everything that knows the rig's layout lives here, as the BoF tab's does in
``emulate_bof_core``; how a script is invoked and how status is parsed is
``webui/rig.py``'s, shared by every rig.
"""

import os
import pathlib
import sys

from pinball_decryptor.core import runtime
from pinball_decryptor.webui import rig as _rig
from ..core import wsl_up as _wsl_up

#: The rig ships next to this package.  ``PAD_AP_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "ap_emu"
)

POLL_MS = 2000
POLL_IDLE_MS = 10000
POLL_FIRST_MS = 700

#: watch.sh's step headers -> the footer ladder (copy = first chip; the
#: one-time setup shares it with the unpack, and says so in the status).
FOOTER_STEPS = (("== Setup ==", "copy", 0, "Checking the emulator…"),
                ("note: first start", "copy", 0,
                 "Setting the emulator up (once, a few minutes)…"),
                ("== Prepare ==", "copy", 0, "Unpacking the game…"),
                ("== Game ==", "boot", None, "Starting the game…"),
                ("== Ready ==", "run", None, "Game running"))
PHASES = ("Unpack", "Game", "Ready")

#: watch.sh's exit codes that mean something a user can act on.
EXIT_TEXT = {
    2: "The .pkg could not be read.",
    3: "Not enough free space in the app's Linux to unpack this game.",
    4: "This file is not an American Pinball game-code package the emulator "
       "knows (Houdini, Oktoberfest, Hot Wheels, Legends of Valhalla, "
       "Galactic Tank Force), or it is damaged.",
    6: "The game did not start.",
    7: "Setting up the emulator failed - it downloads its Python the first "
       "time, so check the internet connection and Start again.",
    8: "The game started, then exited during start-up.",
    9: "Hot Wheels and Galactic Tank Force run one at a time - another one "
       "is already running.",
    10: "Barry-O's BBQ Challenge does not run in this tab yet.",
}


def rig_dir():
    return os.environ.get("PAD_AP_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present?  Checked by script, not by directory - a half-copied tools
    tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh", "ctl.sh",
                         "setup.sh", "appf.py", "cache.sh"))


def platform_ok():
    """watch.sh runs as root (it gives each game its own /game), and only
    WSL gives the app a root without a password prompt - so Windows only.
    A function, so tests stub THIS rather than faking ``sys.platform``."""
    return sys.platform == "win32"


def rig_distro():
    return runtime.distro_for("ap")


def rig_cmd(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    kw.setdefault("distro", rig_distro())
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def is_pkg(path):
    return (path or "").lower().endswith(".pkg")


#: Titles the AP plugin knows that this rig does not run: Barry-O's BBQ
#: Challenge needs the apiav-era rig (tools/ap_emu/apiav, PAD-265), which
#: this tab does not drive yet.
NOT_HERE = ("bbq",)


def game_info(path):
    """(key, name) of the game a .pkg holds, by the AP plugin's own
    detection - ("lov", "Legends of Valhalla") - or ("", "") when it cannot
    tell (a renamed file it could not confirm)."""
    try:
        from pinball_decryptor.plugins.ap.formats import detect_game
        from pinball_decryptor.plugins.ap.games import GAME_DB
        gf = detect_game(path)
    except Exception:                                   # noqa: BLE001
        return "", ""
    if gf is None:
        return "", ""
    info = GAME_DB.get(gf.game_key) if gf.game_key else None
    return (gf.game_key or "",
            (info or {}).get("display") or (gf.game_name if gf.game_key else "")
            or "")


def title_name(info):
    """The running game's name, or its build folder's."""
    info = info or {}
    return info.get("title") or info.get("build") or ""


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
    if info.get("ready") == "0":
        return ("Stopped",
                "The first Start sets the emulator up: it downloads its "
                "Python (about 1 GB, a few minutes, once).")
    return "Stopped", ""


#: The Set up emulator… button's label, and while it works.
SETUP_LABEL = "Set up emulator…"
SETUP_BUSY = "Setting up…"


def setup_notice(info, rt_state, can_install=True):
    """``(text, button)`` for the tab's setup notice: what is not set up as
    the emulator expects, and whether "Set up emulator…" can fix it.  ``("",
    False)`` when nothing is wrong (or nothing is known yet).

    UNLIKE THE SPIKE 2 TAB, a missing runtime is flagged, not only a stale
    one (webui/runtime_prompt.UNPROMPTED says why Spike 2 stays quiet: its
    rig ran in people's own distros for years).  This rig was only ever
    proven in the app's own Linux, and a PC without it ran the game in the
    default distro, where the switch window never opened (PAD-295)."""
    if rt_state == "foreign":
        from . import runtime_prompt
        return runtime_prompt.notice("foreign", ""), False
    if rt_state in ("absent", "stale") and can_install:
        what = ("is not on this PC yet" if rt_state == "absent"
                else "is from an older version of this app")
        return ("Not set up: the Linux this app installs for its emulators "
                "%s, so the game would run in this PC's own WSL distro "
                "instead, which this emulator is not built for. Press "
                "“Set up emulator…” to install it and the Python "
                "the games run on (one-time downloads, about 1.5 GB)." % what,
                True)
    if (info or {}).get("wsl") == "1" and info.get("ready") == "0":
        return ("Not set up yet: the emulator still needs the Python the games "
                "run on (about 1 GB, once). Press “Set up emulator…” "
                "now, or the first Start does it.", True)
    return "", False


def parse_cache(text):
    """``cache.sh --list`` -> ``(entries, disk)``: entries are dicts with
    name, kind ("build" / "envs"), kb, used (epoch), src; disk is
    ``(free_kb, total_kb)`` or None."""
    entries, disk = [], None
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("disk="):
            try:
                free, total = line[5:].split()
                disk = (int(free), int(total))
            except ValueError:
                pass
            continue
        if not line.startswith("entry="):
            continue
        # src= is last and may hold spaces (a Windows folder name)
        head, _, src = line.partition(" src=")
        kv = dict(w.split("=", 1) for w in head.split() if "=" in w)
        try:
            entries.append({"name": kv["entry"], "kind": kv.get("kind", "build"),
                            "kb": int(kv.get("kb") or 0),
                            "used": int(kv.get("used") or 0), "src": src.strip()})
        except (KeyError, ValueError):
            continue
    return entries, disk


def cache_label(entry):
    """What the Cache window calls an entry."""
    if entry["kind"] == "envs":
        return "Emulator setup (Python, GStreamer)"
    return entry["name"]
