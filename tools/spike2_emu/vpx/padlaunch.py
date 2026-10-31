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
    so the app's and a session's rigs are never disturbed - on the app's own
    board (.pad-rig in the Windows profile, where the controller looks for
    the run)
    and in the app's own rig (its data disk, when the app keeps one);
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
#: The board as Windows opens it: the one the app (core/rigslot.py) and the
#: controller (padcontroller.BOARD) read. Every rig command gets it as
#: PAD_BOARD, because riglock.sh and watch.sh would otherwise guess it from
#: where the rig is - and an INSTALLED rig, under Program Files, makes them
#: guess the Linux home's ~/.pad-rig: a board nobody on Windows reads, and one
#: the app's own runs (root) leave root's, so a plain-user take there found
#: every slot "in use" while it listed them all free (PAD-803).
BOARD = os.path.join(os.path.expanduser("~"), ".pad-rig")


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
            # of one version, the stock Release build over a custom one beside
            # it (turtles_pro-1_59_0.1987-upscaled tied with the Release and
            # was taken - PAD-811); `padvpx card` names a custom one
            return max(found, key=lambda p: (_version_key(p), ".Release." in os.path.basename(p)))
    return None


def card_places(title):
    kit = kit_load()
    return ("PAD_VPX_CARD, ~/.pad-vpx.json cards[%s]%s, the library %s"
            % (title, "" if not (kit.get("cards") or {}).get(title) else " (missing file)",
               os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or "(none set)"))


def distros():
    try:
        r = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=20,
                           creationflags=_CREATE_NO_WINDOW)
    except Exception:                                       # noqa: BLE001
        return []
    if r.returncode != 0:
        # with no WSL (or no distro) its lines are the complaint, not names
        return []
    out = r.stdout
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


#: What Play and the launcher say when this PC has no Linux to run the game
#: in. It used to come out as "no rig slot free for <title>: <wsl.exe's own
#: words>", which read like a game already running (PAD-806).
NO_LINUX = ("The game cannot start: the emulator runs in WSL, and WSL is not "
            "installed on this PC yet. Click 'Install Missing' above the app's "
            "tabs (it asks for one Windows restart), then play again.")


#: What the table says when the emulator was never set up on this PC: every
#: Visual Pinball run is a slot layered over the ordinary rig, which the
#: Emulate tab's first game builds (PAD-882).
NO_RIG = ("The game cannot start: the emulator is not set up on this PC yet. "
          "Start a game once on the app's Emulate tab, then open the table again.")


def registered():
    """The WSL distros Windows has registered (HKCU ...\\Lxss), read without
    wsl.exe: [] when there is no Lxss key at all (WSL never set up), None
    off Windows or when the registry cannot be read (then nobody knows, and
    nothing is refused on it)."""
    try:
        import winreg
    except ImportError:
        return None
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Lxss") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as dk:
                        names.append(winreg.QueryValueEx(dk, "DistributionName")[0])
                except OSError:
                    continue
    except FileNotFoundError:
        return []
    except OSError:
        return None
    return names


def no_linux(dist=None):
    """Why a run cannot start in `dist` (None: the machine's default) before
    any wsl.exe is asked, or "" when it can - or when that cannot be told."""
    names = registered()
    if names is None:
        return ""
    if not names:
        return NO_LINUX
    if dist and dist.lower() not in [n.lower() for n in names]:
        return ("The game cannot start: the Linux it runs in (%s) is not installed "
                "on this PC. Set it up on the app's Emulate tab, then play again." % dist)
    return ""


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


def app_home(dist):
    """The app's PAD_HOME for a run in `dist`, or "" for the rig's own default.

    The app keeps the Spike 2 rig on its data disk when it runs in its own
    runtime and that disk exists (emulate_core._rig_env, core/rigdata.py), and
    attaches the disk again after a WSL restart before a run. A run started
    here has to land in that same rig - its rootfs, cards and NVRAM - so this
    asks rigdata the same question, from the app's package beside the kit."""
    if sys.platform != "win32" or dist != RUNTIME_DISTRO:
        return ""
    app = os.path.dirname(os.path.dirname(os.path.abspath(rig_dir())))
    if app not in sys.path:
        sys.path.append(app)
    try:
        from pinball_decryptor.core import rigdata
    except Exception as exc:                                # noqa: BLE001
        log("no app package beside the rig (%s): the rig's own PAD_HOME" % exc)
        return ""
    if not rigdata.exists():
        return ""
    try:
        rigdata.ensure(dist, log=log)
    except Exception as exc:                                # noqa: BLE001
        log("the app's data disk did not attach (%s): the rig's own PAD_HOME" % exc)
        return ""
    return rigdata.work_dir("spike2") or ""


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
    # wsl.exe's own complaints (no distro, WSL not answering) are UTF-16;
    # what bash prints is UTF-8 and never carries a NUL
    b = b or b""
    return b.decode("utf-16-le" if b"\x00" in b else "utf-8", "replace")


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
        # every path below is for THIS run's distro, so that distro converts
        # it, not the machine's default (PAD-882)
        self.rig_wsl = padpath.to_wsl(rig_dir(), self.distro)
        self.logfile = os.path.join(os.path.dirname(LOG), "padvpx-%s.log" % title)
        self.home = None        # app_home(), asked once

    def rig_head(self):
        """How every riglock.sh call starts: as root, the way the run itself
        starts (head()), on the app's board and in the app's rig. Root because
        the board may be root's already (the app's runs are root) and because
        taking a slot >= 1 also mounts its rootfs, which only root can
        (riglock.sh, "RUN IT AS ROOT"). A distro whose account has no home
        gets the plain user, as head() does."""
        user, home = account(self.distro)
        if home and user:
            head = wsl_head(self.distro, root=True) + ["-e", "env", "HOME=" + home]
        else:
            head = wsl_head(self.distro) + ["-e", "env"]
        return head + self.board_env() + ["bash", "%s/riglock.sh" % self.rig_wsl]

    def board_env(self):
        """PAD_BOARD (see BOARD) and the app's PAD_HOME (see app_home)."""
        out = []
        if sys.platform == "win32":
            out.append("PAD_BOARD=%s" % padpath.to_wsl(BOARD, self.distro))
        if self.home is None:
            self.home = app_home(self.distro)
        if self.home:
            out.append("PAD_HOME=%s" % self.home)
        return out

    def take_slot(self):
        """A slot of the kit's own: the kit's `slot` when it names one (`use`
        keeps it if it is already PAD-VPX's, takes it if free), else the first
        free one."""
        want = kit_load().get("slot")
        what = "%s for Visual Pinball" % self.title
        if want:
            cmd = self.rig_head() + ["use", str(int(want)), LABEL, what]
        else:
            cmd = self.rig_head() + ["take", "--any", LABEL, what]
        r = _run(cmd)
        out = _text(r.stdout) + _text(r.stderr)
        m = re.search(r"slot=(\d+)", out)
        if want and r.returncode == 0 and not m:
            self.slot = int(want)
            return self.slot
        if want and not m:
            # the kit's slot is somebody else's now: any free one, then
            log("slot %s is not ours (%s); taking any" % (want, out.strip()[-120:]))
            r = _run(self.rig_head() + ["take", "--any", LABEL, what])
            out = _text(r.stdout) + _text(r.stderr)
            m = re.search(r"slot=(\d+)", out)
        if not m:
            # the LAST lines say why (riglock.sh's own word), the slot table
            # above them only what it saw
            raise RuntimeError("no rig slot free for %s: %s" % (self.title, out.strip()[-300:]))
        self.slot = int(m.group(1))
        return self.slot

    def env(self):
        card = padpath.to_wsl(self.card, self.distro)
        # visible (the LCD window) and audible, but NO virtual playfield
        # window: Visual Pinball is the playfield, and the rig's own would
        # take the keyboard from it the moment it opened
        # ... unless the kit asked for the playfield window (padvpx playfield)
        playfield = "1" if kit_load().get("playfield") else "0"
        env = self.board_env() + ["PAD_SLOT=%d" % self.slot, "PAD_LABEL=%s" % LABEL,
               "PAD_HIDDEN=0", "PAD_PLAYFIELD=%s" % playfield, "PAD_AUDIO=1", "PAD_CARD=%s" % card]
        py = win_python()
        if py:
            env.append("PAD_WINPYTHON=%s" % padpath.to_wsl(py, self.distro))
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

    def base_rig(self):
        """The ordinary rig every slot is layered over (padpath.sh's
        PAD_BASE_ROOT: $PAD_HOME/spike2root), or "" when it cannot be told."""
        self.board_env()
        home = self.home or account(self.distro)[1]
        return home + "/spike2root" if home else ""

    def start(self):
        why = no_linux(self.distro)
        if why:
            log(why)
            raise RuntimeError(why)
        # PAD-882: on a PC whose Emulate tab never ran a game there is no rig
        # to layer this run's slot over; the run died a second in with that
        # said only in its log, and the table sat there. Said here instead,
        # where the table shows it. `test` answers 1 for "not there"; any
        # other failure (WSL not answering) refuses nothing.
        base = self.base_rig()
        if base and _run(wsl_head(self.distro, root=True) + ["-e", "test", "-d", base],
                         timeout=60).returncode == 1:
            log("no rig at %s" % base)
            raise RuntimeError(NO_RIG)
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
            _run(head + self.board_env() + ["PAD_SLOT=%d" % self.slot, "PAD_LABEL=%s" % LABEL,
                                            "bash", "%s/killgame.sh" % self.rig_wsl], timeout=120)
            _run(self.rig_head() + ["release", str(self.slot), LABEL], timeout=30)
            log("stopped %s on slot %d" % (self.title, self.slot))
        except Exception as exc:                            # noqa: BLE001
            log("stop of slot %d failed: %s" % (self.slot, exc))
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except Exception:                               # noqa: BLE001
                pass
        self.slot = None
