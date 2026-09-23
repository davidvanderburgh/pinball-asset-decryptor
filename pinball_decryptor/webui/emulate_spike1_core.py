"""Emulate tab for Stern **Spike 1** — run a DMD-era Spike 1 game on this PC.

A SIBLING of the Spike 2 and JJP rigs (:mod:`.emulate_core`,
:mod:`.emulate_jjp_core`), not an extension of either — the same reasoning as the JJP tab: the Spike 2 panel is
welded to that rig's vocabulary, and threading a second rig through it would
carry two of everything. What the panels genuinely share — how a Windows path is
spelled for WSL, how a rig script is invoked, how ``key=value`` status is
parsed — lives in :mod:`.rig`.

This tab deliberately mirrors the **Spike 2 tab's layout** (David: "use the same
layout … we will need the same features too"): the card row with Browse / Cache,
the control-button row (Start, Restart WSL, Reset windows, Check setup), a Save
states panel, a Status grid, and the shared footer progress ladder. Where a
feature needs rig support that Spike 1 does not have yet (save states, a full
card cache), the widgets are present and honest about it rather than absent.

WHAT MAKES SPIKE 1 DIFFERENT
----------------------------
The game is a *static* armel ELF (no ``LD_PRELOAD`` seam), so its peripherals are
modelled one level down — a patched ``qemu-user`` plus a CUSE device model — and
the whole thing needs root, which on Windows is ``wsl -u root`` (passwordless).
There is no dongle, and the game is EXTRACTED from the card once (not run off it,
the way Spike 2 is). The display is a 128x32 **DMD**, not an LCD, so the picture
is a small dot-matrix window rather than a GL surface. Sound reuses the Spike 2
speaker chain end to end (the i2s shim tees paced PCM into a FIFO; playaudio.sh
owns the sink), so the volume/mute knob here is the SAME knob — same control
file, same ``PAD_AUDIO_CTL`` hand-off — and moves both rigs' loudness.

WHY THE PANEL IS THIN
---------------------
Every step of the launch — build, extract, seed, responder, game, windows —
lives in ``tools/spike1_emu/start.sh`` in the one order that works. This panel
starts it, stops it, and reports truthfully what it is doing.

THIS MODULE is the Tk-free half of the old Tk panel (``gui/spike1_emulate_tab.py``
and ``gui/spike1_windows.py`` until the web UI cut-over): every module-level
function and constant the panel had, unchanged; the panel's numbers, words and
four pure helpers, which were class attributes and static methods of
``Spike1EmulatePanel``; and the run-dir reader the pop-out windows used
(:func:`wsl_unc`, :class:`_RunDirIO`, the switch grid's default nodes).  The
web Spike 1 Emulate tab (``webui/tabs/emulate_spike1.py``) and its viewer
(``webui/emulate_jjp_spike1view.py``) are the panel and windows now.
"""

import os
import pathlib
import re

from pinball_decryptor.webui import rig as _rig
from ..core import rigdata, runtime
from ..plugins.stern.spike1_emulate import HardwareState, StateBlock, SwitchInput
# The volume/mute control FILE and its load/store belong to the Spike 2 rig
# (item 56) and are deliberately shared, not copied: one knob value, one file,
# read by the one padplay.py speaker implementation both rigs launch.
from .emulate_core import (  # noqa: F401  (re-exported)
    AUDIO_CTL_FILE, _load_audio_ctl, _write_audio_ctl, windows_python)

#: The rig ships in the repo next to this package.  ``PAD_SPIKE1_EMU_DIR`` moves
#: it (parity with the JJP tab's ``PAD_JJP_EMU_DIR``).
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spike1_emu"
)


def rig_dir():
    return os.environ.get("PAD_SPIKE1_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Present? Checked by script, not by directory — a half-copied tools tree
    is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("start.sh", "stop.sh", "status.sh"))


#: WHICH LINUX THIS TAB TALKS TO.  The app can install a Linux of its own
#: (core/runtime.py) - pinned, built by us, and holding the emulator already.
#: When it is installed every command here runs in THAT distro; when it is not,
#: everything behaves exactly as it did before, in the machine's default.  The
#: choice is made in one place so no call site can disagree with another about
#: which machine it is looking at.
def rig_distro():
    return runtime.distro_for("spike1")


#: WHERE THE RIG'S WORK GOES, carried on every command rather than set once.
#: The rig reads S1_WORK per invocation - start.sh, status.sh, stop.sh and
#: prereqcheck.sh each work it out for themselves - so one of them left without
#: it would look at a different machine's worth of state than the others.
def _work_env(kw):
    d = rig_distro()
    ready = bool(d) and rigdata.exists()
    return list(kw.pop("env", ())) + rigdata.rig_env("spike1", ready)


def rig_cmd(*args, **kw):
    kw.setdefault("distro", rig_distro())
    kw["env"] = _work_env(kw)
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    kw.setdefault("distro", rig_distro())
    kw["env"] = _work_env(kw)
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


def _load_rig_module(name):
    """Import a rig module (``s1dmd``, ``s1alpha``) from the rig dir — it is a
    script tree next to the rig, not an installed package, so load by path."""
    import importlib.util
    p = os.path.join(rig_dir(), name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_gui", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_dmd_decoder():
    return _load_rig_module("s1dmd")


def _load_alpha():
    """``(decode_frame, render_image)`` for the 2012 home models' 16-segment
    displays (s1alpha), or None if the rig lacks it."""
    try:
        mod = _load_rig_module("s1alpha")
        return mod.decode_frame, mod.render_image
    except Exception:                                          # noqa: BLE001
        return None


def state_text(info):
    """(label, hint) for the State cell, from status.sh's key=value.

    Ordered the way a user hits the states: the FIRST thing that is not ready is
    what they are told about.
    """
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return ("WSL not answering",
                "The emulator is a Linux program and runs inside WSL.")
    if int(info.get("game_procs") or 0) > 0:
        if info.get("keeper") == "0":
            # a dead keeper wears the game's own clothes: the machine sits on
            # "LOCATING PINBALLS. PLEASE WAIT" forever, which reads as a hung
            # boot (David hit exactly this, 2026-08-31).  Name the real fault.
            return ("No ball keeper", (
                "The game is up but the invisible-ball keeper died, so the "
                "machine cannot find its pinballs (the LOCATING PINBALLS "
                "screen). Press Stop, then Start."))
        if info.get("nodes_registered") == "1":
            # "Game running", matching the Spike 2 tab's wording (David: the
            # two tabs' texts flapped in the shared footer — "choose one").
            return "Game running", ("Boards registered; the DMD shows the "
                                    "attract.")
        return "Booting…", "The game is coming up on the emulator."
    if info.get("qemu_built") != "1":
        return ("Setup needed",
                "The ARM emulator has to be built once (a few minutes). Press "
                "Start — the first run builds it, then launches the game.")
    if info.get("game_ready") != "1":
        return ("No game extracted",
                "Pick a Spike 1 card image and press Start; the game is "
                "extracted from it the first time.")
    return "Not running", ""


#: Rig event logs streamed into the app's log window while a run is up
#: (David: "the emulation needs to output logs of any events to the log
#: window").  Each entry is (file in the run dir, tag, keep) — ``keep`` is a
#: regex a line must match to be forwarded, or None for every line.  The
#: keeper's log IS the event stream (serve/launch/drain/coin/door/service),
#: so it goes through whole; emu.log and audio.log are chatty, so only their
#: event-shaped lines pass.
_EVENT_LOGS = (
    ("s1ball.log", "ball", None),
    ("emu.log", "emu",
     re.compile(r"GAME RUN|RUN \d+ exited|PAD/spike1|FATAL|ERROR|error")),
    # under a checkpointable boot (S1_PIVOT, item 87) the game's own stdout —
    # including qemu's PAD/spike1 lines — moves inside the rootfs; the
    # ``rootfs`` symlink in the run dir reaches it, and on a chroot run the
    # file simply is not there (the tailer skips absentees).
    ("rootfs/dump/game.out", "emu",
     re.compile(r"PAD/spike1|FATAL|Fatal|Segmentation")),
    ("audio.log", "audio",
     re.compile(r"\[play\]|\[padrelay\]|restarting|volume ->|underruns\s+[1-9]")),
)
#: Protective caps for the shared log pane (a flooded Text widget is a known
#: UI-thread freeze class): at most this many lines per file per poll, and
#: lines are clipped.
_EVENT_LINES_PER_POLL = 12
_EVENT_LINE_CLIP = 300
#: A file bigger than this when the tailer attaches (tab reopened mid-run)
#: streams from its END rather than replaying the whole history.
_EVENT_REPLAY_MAX = 64 * 1024


# ----------------------------------------------------------------------
# The panel's numbers and words (class attributes of the Tk Spike1EmulatePanel).

POLL_MS = 2000

POLL_IDLE_MS = 10000

POLL_FIRST_MS = 700

STATES_TIP = (
    "Save states snapshot the running game and jump back to it later — "
    "mid-ball, across emulator restarts.\n\n"
    "• Save now freezes the game for a second or two and writes a slot "
    "(~15-50 MB on the WSL disk)\n"
    "• Load replaces the running game with the selected slot — the "
    "emulator must be running the same title\n"
    "• slots survive rebuilds (each carries the binaries it depends on) "
    "and stay on disk until deleted\n\n"
    "A GUI-started run always boots checkpointable (S1_PIVOT); command-"
    "line runs opt in with S1_PIVOT=1.")

#: the PCM format to open the speaker at when the rig has not said.
DEFAULT_AUDIO = ("44100", "2")

#: The binaries this rig needs and does not build on a user's machine any
#: more.  Named here rather than inside the worker so the tests can ask the
#: panel what it will install without running anything.
PAYLOAD_KEYS = ("spike1-qemu", "spike1-hwshim")


# ----------------------------------------------------------------------
# Its pure helpers (static methods of the Tk Spike1EmulatePanel).

def fmt_size(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d %s" % (n, unit) if unit == "B" else \
                   "%.1f %s" % (n, unit)
        n /= 1024.0
    return "?"


def fmt_when(epoch):
    import datetime
    try:
        return datetime.datetime.fromtimestamp(
            int(epoch)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


def human_kb(kb):
    try:
        kb = float(kb)
    except (TypeError, ValueError):
        return "?"
    for unit in ("KB", "MB", "GB", "TB"):
        if kb < 1024 or unit == "TB":
            return "%.0f %s" % (kb, unit) if unit == "KB" \
                else "%.1f %s" % (kb, unit)
        kb /= 1024.0


def parse_cache(text):
    """cache.sh list -> (rows, disk_free_kb).  Rows are dicts."""
    rows, free = [], None
    for line in text.splitlines():
        f = line.split("\t")
        if f[0] == "entry" and len(f) >= 6:
            rows.append({"label": f[1], "kb": f[2], "boot": f[3],
                         "game": f[4], "active": f[5] == "1"})
        elif f[0] == "disk" and len(f) >= 2:
            free = f[1]
    rows.sort(key=lambda r: int(r["boot"] or 0), reverse=True)
    return rows, free


# ----------------------------------------------------------------------
# The run-dir reader the DMD and switch windows share (the Tk
# spike1_windows module's).

#: Node addresses a Spike 1 machine polls (from the ELF topology — see s1elf.py);
#: shown even before any state arrives so there is always something to click.
DEFAULT_NODES = (0, 1, 8, 9, 10, 11, 12)
#: node-local switch positions to show per node (boards address up to 64; the
#: low positions are where switches actually sit, and a 64-wide grid is unusable).
SWITCH_COLS = 16


def wsl_unc(distro, wsl_path):
    r"""``/home/david/s1emu/x`` -> ``\\wsl.localhost\<distro>\home\david\s1emu\x``."""
    if not distro:
        return None
    return "\\\\wsl.localhost\\" + distro + wsl_path.replace("/", "\\")


class _RunDirIO:
    """Reads/writes the emulator run-dir files over the WSL UNC path."""

    def __init__(self, run_dir_wsl, distro):
        self.run_dir_wsl = run_dir_wsl
        self.distro = distro

    def _unc(self, name):
        return wsl_unc(self.distro, self.run_dir_wsl.rstrip("/") + "/" + name)

    def tail_frame(self, name, frame_bytes):
        """The last whole *frame_bytes* block of a growing capture, or None."""
        p = self._unc(name)
        if not p:
            return None
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                n = size // frame_bytes
                if n == 0:
                    return None
                f.seek((n - 1) * frame_bytes)
                data = f.read(frame_bytes)
            return data if len(data) == frame_bytes else None
        except OSError:
            return None

    def read_state(self):
        """The shared StateBlock -> HardwareState, or an empty one."""
        st = HardwareState()
        p = self._unc("s1hw.state")
        if not p:
            return st
        try:
            with open(p, "rb") as f:
                buf = f.read(StateBlock.SIZE)
            StateBlock.unpack(buf, st)
        except (OSError, ValueError):
            pass
        return st

    def write_injected(self, closed_slots, seq):
        p = self._unc("s1sw.input")
        if not p:
            return
        try:
            with open(p, "wb") as f:
                f.write(SwitchInput.pack(closed_slots, seq))
        except OSError:
            pass

    def append_ball_cmd(self, line):
        """Queue a one-shot for the s1ball.py ball-keeper daemon (coin / start /
        drain…): append a line to s1ball.cmd in the run dir.  Best-effort — if
        the daemon is not running the line is simply never consumed."""
        p = self._unc("s1ball.cmd")
        if not p:
            return False
        try:
            with open(p, "a", encoding="ascii") as f:
                f.write(line + "\n")
            return True
        except OSError:
            return False

    def read_switch_names(self):
        """The title's ``{(node, index): name}`` switch map (s1switches.json —
        the curated map, or the live registry walk's).  ``{}`` if the file is
        missing/unreadable, so the window still works nameless."""
        import json
        p = self._unc("s1switches.json")
        if not p:
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return {}
        out = {}
        for key, name in raw.items():
            try:
                node_s, idx_s = key.split(",")
                out[(int(node_s), int(idx_s))] = name
            except (ValueError, AttributeError):
                continue
        return out

    def read_json(self, name):
        """A small JSON file of the run dir (e.g. ``s1font.json``), or None."""
        import json
        p = self._unc(name)
        if not p:
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def read_text(self, name):
        """A small text file of the run dir (e.g. ``s1display``), stripped;
        ``""`` when absent."""
        p = self._unc(name)
        if not p:
            return ""
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def read_ball_state(self):
        """The ball keeper's published state (s1ball.state JSON): trough
        count, ball-in-shooter, coin door.  ``{}`` when absent."""
        import json
        p = self._unc("s1ball.state")
        if not p:
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
