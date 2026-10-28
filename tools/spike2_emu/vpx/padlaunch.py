#!/usr/bin/env python3
"""padlaunch.py - start a Spike 2 run for a Visual Pinball table, and stop it.

Visual Pinball opens a patched table, the table creates PAD.Controller and
names its title, and the controller looks for a run of that title on the rig
board. When there is none, this starts one - no app in the loop:

  * the CARD for the title: PAD_VPX_CARD, else the card `padvpx patch --card`
    (or `padvpx card`) recorded for the title in ~/.pad-vpx.json, else the
    newest `<title>-*.sdcard.raw` in the kit's library directory
    (PAD_VPX_LIBRARY or the kit's `library`);
  * the Linux it runs in: PAD_WSL_DISTRO, else the kit's `distro`, else
    PAD-Runtime when that distro is installed, else the machine's default;
  * a rig slot of its own, taken with riglock.sh (`PAD-VPX` as its holder),
    so the app's and a session's rigs are never disturbed;
  * `watch.sh` as the desktop user, VISIBLE (the LCD window on the desktop)
    and with SOUND, since this run is for playing, and the Windows Python
    beside this one for the sound bridge (PAD-95) when there is one.

What this started, Controller.Stop stops (killgame.sh, then the slot is
released); a run the user started another way is left alone.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import padpath    # noqa: E402

KIT = os.path.join(os.path.expanduser("~"), ".pad-vpx.json")
LABEL = "PAD-VPX"
RUNTIME_DISTRO = "PAD-Runtime"
LOG = os.path.join(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp",
                   "padcontroller.log")
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s launch: %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass


# ---------------------------------------------------------------- the kit --

def kit_load():
    try:
        with open(KIT, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def kit_save(d):
    tmp = KIT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, sort_keys=True)
    os.replace(tmp, KIT)


def remember_card(title, card):
    d = kit_load()
    d.setdefault("cards", {})[title] = card
    kit_save(d)


def _version_key(path):
    """`rush_le-1_19_0.Release.16G.sdcard.raw` -> (1, 19, 0): newest last."""
    m = re.search(r"-(\d+)_(\d+)_(\d+)", os.path.basename(path))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def card_for(title):
    """The card image to boot for `title`, or None with the places looked."""
    env = os.environ.get("PAD_VPX_CARD")
    if env and os.path.isfile(env):
        return env
    kit = kit_load()
    card = (kit.get("cards") or {}).get(title)
    if card and os.path.isfile(card):
        return card
    lib = os.environ.get("PAD_VPX_LIBRARY") or kit.get("library")
    if lib and os.path.isdir(lib):
        found = glob.glob(os.path.join(lib, "%s-*.sdcard.raw" % title))
        if found:
            return max(found, key=_version_key)
    return None


def card_places(title):
    kit = kit_load()
    return ("PAD_VPX_CARD, ~/.pad-vpx.json cards[%s]%s, the library %s"
            % (title, "" if not (kit.get("cards") or {}).get(title) else " (missing file)",
               os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or "(none set)"))


def distros():
    try:
        out = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=20,
                             creationflags=_CREATE_NO_WINDOW).stdout
    except Exception:                                       # noqa: BLE001
        return []
    text = out.decode("utf-16-le", "replace") if b"\x00" in out else out.decode("utf-8", "replace")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def distro():
    """Which WSL distro runs the game: the env, the kit, our runtime, default."""
    env = os.environ.get("PAD_WSL_DISTRO")
    if env:
        return env
    kit = kit_load().get("distro")
    if kit:
        return kit
    if RUNTIME_DISTRO in distros():
        return RUNTIME_DISTRO
    return None


def rig_dir():
    """The rig (watch.sh and friends) as Windows sees it: the kit's `rig`
    (an installed app's tools/spike2_emu), else the one beside this file."""
    return kit_load().get("rig") or RIG


def win_python():
    """`python.exe` beside the interpreter running us, for the sound bridge."""
    if sys.platform != "win32":
        return None
    d = os.path.dirname(sys.executable)
    for name in ("python.exe",):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def wsl_head(dist=None, root=False):
    head = ["wsl.exe"]
    if dist:
        head += ["-d", dist]
    if root:
        head += ["-u", "root"]
    return head


_ACCOUNT = {}


def account(dist=None):
    """(user, home) of the account wsl.exe logs into with no -u, asked of
    `whoami` and `getent` (no shell variables: wsl.exe re-parses its line and
    a `$HOME` comes out empty). ('', '') when WSL does not answer."""
    if dist in _ACCOUNT:
        return _ACCOUNT[dist]
    user = home = ""
    try:
        user = _text(_run(wsl_head(dist) + ["-e", "whoami"], timeout=30).stdout).strip()
        if user:
            row = _text(_run(wsl_head(dist) + ["-e", "getent", "passwd", user], timeout=30).stdout)
            parts = row.strip().split(":")
            if len(parts) >= 6:
                home = parts[5]
    except Exception:                                       # noqa: BLE001
        pass
    _ACCOUNT[dist] = (user, home)
    return _ACCOUNT[dist]


def _run(args, timeout=60):
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          creationflags=_CREATE_NO_WINDOW)


def _text(b):
    return (b or b"").decode("utf-8", "replace")


# ------------------------------------------------------------- the launch --

class Launch:
    """One run started for a table: a slot, a watch.sh, and the stop for it."""

    def __init__(self, title, card, dist=None, minutes=240):
        self.title = title
        self.card = card
        self.distro = dist if dist is not None else distro()
        self.minutes = minutes
        self.slot = None
        self.proc = None
        self.as_root = False
        self.rig_wsl =padpath.to_wsl(rig_dir()) if padpath.is_windows_path(rig_dir()) else rig_dir()
        self.logfile = os.path.join(os.path.dirname(LOG), "padvpx-%s.log" % title)

    def take_slot(self):
        """A slot of the kit's own: the kit's `slot` when it names one (`use`
        keeps it if it is already PAD-VPX's, takes it if free), else the first
        free one."""
        want = kit_load().get("slot")
        what = "%s for Visual Pinball" % self.title
        if want:
            cmd = wsl_head(self.distro) + ["-e", "bash", "%s/riglock.sh" % self.rig_wsl,
                                           "use", str(int(want)), LABEL, what]
        else:
            cmd = wsl_head(self.distro) + ["-e", "bash", "%s/riglock.sh" % self.rig_wsl,
                                           "take", "--any", LABEL, what]
        r = _run(cmd)
        out = _text(r.stdout) + _text(r.stderr)
        m = re.search(r"slot=(\d+)", out)
        if want and r.returncode == 0 and not m:
            self.slot = int(want)
            return self.slot
        if want and not m:
            # the kit's slot is somebody else's now: any free one, then
            log("slot %s is not ours (%s); taking any" % (want, out.strip()[-120:]))
            r = _run(wsl_head(self.distro) + ["-e", "bash", "%s/riglock.sh" % self.rig_wsl,
                                              "take", "--any", LABEL, what])
            out = _text(r.stdout) + _text(r.stderr)
            m = re.search(r"slot=(\d+)", out)
        if not m:
            raise RuntimeError("no rig slot free for %s: %s" % (self.title, out.strip()[-200:]))
        self.slot = int(m.group(1))
        return self.slot

    def env(self):
        card = padpath.to_wsl(self.card) if padpath.is_windows_path(self.card) else self.card
        # visible (the LCD window) and audible, but NO virtual playfield
        # window: Visual Pinball is the playfield, and the rig's own would
        # take the keyboard from it the moment it opened
        # ... unless the kit asked for the playfield window (padvpx playfield)
        playfield = "1" if kit_load().get("playfield") else "0"
        env = ["PAD_SLOT=%d" % self.slot, "PAD_LABEL=%s" % LABEL,
               "PAD_HIDDEN=0", "PAD_PLAYFIELD=%s" % playfield, "PAD_AUDIO=1", "PAD_CARD=%s" % card]
        py = win_python()
        if py:
            env.append("PAD_WINPYTHON=%s" % padpath.to_wsl(py))
        return env

    def head(self):
        """The app's own Windows launch shape (emulate_core.watch_cmd): `wsl
        -u root` with the desktop user's HOME and PAD_PIVOT=1, which boots
        the guest as root (checkpointable: save states work) and drops every
        helper back to the user, whose WSLg and sound session they need. A
        distro whose account has no home gets the plain user launch."""
        user, home = account(self.distro)
        if home and user:
            return wsl_head(self.distro, root=True) + ["-e", "env", "HOME=" + home, "PAD_PIVOT=1"], True
        return wsl_head(self.distro) + ["-e", "env"], False

    def start(self):
        if self.slot is None:
            self.take_slot()
        head, self.as_root = self.head()
        cmd = head + self.env() + ["bash", "%s/watch.sh" % self.rig_wsl, str(self.minutes)]
        out = open(self.logfile, "ab")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                     creationflags=_CREATE_NO_WINDOW)
        log("started %s on slot %d from %s (distro %s, log %s)"
            % (self.title, self.slot, self.card, self.distro or "default", self.logfile))
        return self.slot

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.slot is None:
            return
        try:
            head, _ = self.head() if getattr(self, "as_root", False) else (wsl_head(self.distro) + ["-e", "env"], False)
            _run(head + ["PAD_SLOT=%d" % self.slot, "PAD_LABEL=%s" % LABEL,
                         "bash", "%s/killgame.sh" % self.rig_wsl], timeout=120)
            _run(wsl_head(self.distro) + ["-e", "bash", "%s/riglock.sh" % self.rig_wsl,
                                          "release", str(self.slot), LABEL], timeout=30)
            log("stopped %s on slot %d" % (self.title, self.slot))
        except Exception as exc:                            # noqa: BLE001
            log("stop of slot %d failed: %s" % (self.slot, exc))
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except Exception:                               # noqa: BLE001
                pass
        self.slot = None
