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
import fnmatch
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
USER_MAPS = os.path.join(os.path.expanduser("~"), ".pad-vpx", "maps")
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


#: PAD-964: whether a run copies its card into the emulator's cache first
#: (the kit's `card_cache`, on unless turned off: `padvpx cache off`, the
#: Visual Pinball tab's box). Off, the game reads the image where it lies
#: (PAD_CARD_CACHE=0): nothing lands on the disk, and a first start is slow -
#: Batman 1.14 took 148 s to attract off D: through 9p against 36 s cached.
CACHE_KEY = "card_cache"


def cache_on(kit=None):
    kit = kit_load() if kit is None else kit
    return kit.get(CACHE_KEY, True) is not False


def set_cache_on(on):
    d = kit_load()
    if on:
        d.pop(CACHE_KEY, None)
    else:
        d[CACHE_KEY] = False
    kit_save(d)
    return cache_on(d)


def gb(kb):
    """`6.6 GB` for a size in KB, as the tab and the loading window say it."""
    return "%.1f GB" % (float(kb) / 1048576.0)


def parse_check(text):
    """`cardmount.sh --cache-check` read: ({state, need_kb, free_kb, keep_kb,
    evict_n, evict_kb, kind, host, label, img} per `check` line, keyed by
    image path, and the `cache` line as {dir, kind, avail_kb, size_kb,
    limit_gb, used_kb} under "cache"). Lines it does not know are skipped."""
    out = {"checks": {}, "cache": None}
    for line in (text or "").splitlines():
        p = line.rstrip("\r\n").split("\t")
        try:
            if p[0] == "check" and len(p) >= 11:
                out["checks"][p[10]] = {
                    "state": p[1], "need_kb": int(p[2] or 0), "free_kb": int(p[3] or 0),
                    "keep_kb": int(p[4] or 0), "evict_n": int(p[5] or 0), "evict_kb": int(p[6] or 0),
                    "kind": p[7], "host": p[8], "label": p[9], "img": p[10]}
            elif p[0] == "cache" and len(p) >= 7:
                out["cache"] = {"dir": p[1], "kind": p[2], "avail_kb": int(p[3] or 0),
                                "size_kb": int(p[4] or 0), "limit_gb": int(p[5] or 0),
                                "used_kb": int(p[6] or 0)}
        except ValueError:
            continue
    return out


def space_words(chk):
    """What starting the game costs the disk, in one sentence, from a `check`
    record: the launch's log line, the loading window's step and the tab's
    tip say the same thing. (state, words)."""
    state = chk.get("state") or ""
    need, free = chk.get("need_kb") or 0, chk.get("free_kb") or 0
    where = "the Windows drive behind WSL (%s)" % chk["host"] if chk.get("host") else "the cache"
    if state == "cached":
        words = "The card image is in the emulator's cache"
    elif state == "off":
        words = ("Caching is off: the game reads the card image (%s) where it lies, a slow start"
                 % gb(need))
    elif state == "copying":
        words = "The card image (%s) is being copied into the emulator's cache now" % gb(need)
    elif state == "room":
        words = ("Copying the card image (%s) into the emulator's cache, this first start only (%s free there)"
                 % (gb(need), gb(free)))
    elif state == "evict":
        n = chk.get("evict_n") or 0
        words = ("Copying the card image (%s) into the emulator's cache once %d older card%s (%s) make%s room, "
                 "this first start only" % (gb(need), n, "" if n == 1 else "s", gb(chk.get("evict_kb") or 0),
                                             "s" if n == 1 else ""))
    elif state == "full":
        words = ("No room in %s for the card image (%s needed with %s kept free, %s free): the game reads it "
                 "where it lies, a slow start" % (where, gb(need), gb(chk.get("keep_kb") or 0), gb(free)))
    else:
        words = "What the card image costs the disk could not be told"
    return state, words


def _version_key(path):
    """`rush_le-1_19_0.Release.16G.sdcard.raw` -> (1, 19, 0): newest last.
    A Spike 1 card's two parts (`GOT_LE-1_37.iso`) or dots
    (`transformers_pin-1.0.18.iso`) read the same way (PAD-943)."""
    m = re.search(r"-(\d+)[._](\d+)(?:[._](\d+))?", os.path.basename(path))
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


#: what a title's map says it runs on (`platform`), and the rig that is
PLATFORM_NAMES = {"spike2": "Spike 2", "spike1": "Spike 1", "spooky": "Spooky"}
#: the card images a platform's library holds, by glob after `<title>-`
CARD_GLOBS = {"spike2": ("*.sdcard.raw",), "spike1": ("*.iso",)}
#: PAD-952: a Spooky title boots its UPDATE file (tools/spooky_emu prepares
#: it), named by Spooky, not after the title: the rig's title key -> globs.
#: PAD-954: Alice Cooper's game-code package, which the same watch.sh hands
#: to the P-ROC rig (tools/spooky_emu/proc)
SPOOKY_UPDATES = {"h78": ("code_H78*.pkg",), "um": ("code_UM*.pkg",), "ac": ("ac-gamecode*.pkg",)}
#: the Spooky titles that run on the P-ROC rig, not the Warden board: their
#: rig profile is the machine yaml in the prepared build (PAD-954)
SPOOKY_PROC = {"ac": "config/alice.yaml"}


def game_for(title):
    """A map variant's native game identity; existing maps use their title.
    Look in the same user/kit map locations and order as PAD.Controller."""
    if not title:
        return title
    for directory in (USER_MAPS, HERE):
        for suffix in (".vpxmap.json", ".shadow.json"):
            path = os.path.join(directory, title + suffix)
            try:
                with open(path, encoding="utf-8") as f:
                    m = json.load(f)
            except (OSError, ValueError):
                continue
            game = m.get("game")
            return game if isinstance(game, str) and game else title
    return title


def card_for(title, platform="spike2"):
    """The card image to boot for `title`, or None with the places looked.
    A Spike 1 title's card is its .iso (GOT_LE-1_37.iso), looked for the same
    way (PAD-943)."""
    env = os.environ.get("PAD_VPX_CARD")
    if env and os.path.isfile(env):
        return env
    kit = kit_load()
    game = game_for(title)
    for key in dict.fromkeys((title, game)):
        card = (kit.get("cards") or {}).get(key)
        if card and os.path.isfile(card):
            return card
    for lib in libraries(platform, kit):
        # by name in any case, as Windows does: a Spike 1 card is GOT_LE-1_37.iso
        # for got_le, and Linux/macOS glob tells the cases apart (PAD-951)
        if platform == "spooky":
            pats = [g.lower() for g in SPOOKY_UPDATES.get(game, ())]
        else:
            pats = [("%s-%s" % (game, g)).lower() for g in CARD_GLOBS.get(platform, CARD_GLOBS["spike2"])]
        found = [os.path.join(lib, n) for n in sorted(os.listdir(lib))
                 if any(fnmatch.fnmatchcase(n.lower(), p) for p in pats)]
        if found:
            # of one version, the stock Release build over a custom one beside
            # it (turtles_pro-1_59_0.1987-upscaled tied with the Release and
            # was taken - PAD-811); `padvpx card` names a custom one
            return max(found, key=lambda p: (_version_key(p), ".Release." in os.path.basename(p)))
    return None


def libraries(platform="spike2", kit=None):
    """The card folders a platform's title is looked for in, in order: the
    environment's, the kit's `libraries[platform]`, the kit's `library`, and
    for Spike 1 that library's sibling named `spike1` (David's library keeps
    the platforms side by side: Stern/spike2, Stern/spike1) (PAD-943)."""
    kit = kit_load() if kit is None else kit
    out = []
    env = os.environ.get("PAD_VPX_LIBRARY")
    if env:
        out.append(env)
    per = (kit.get("libraries") or {}).get(platform)
    if per:
        out.append(per)
    lib = kit.get("library")
    if lib:
        out.append(lib)
        if platform == "spooky":
            # PAD-952: the maker's own folder beside Stern's (David's library:
            # images/Stern/spike2 and images/Spooky)
            out.append(os.path.join(os.path.dirname(os.path.dirname(lib.rstrip("\\/"))), "Spooky"))
        elif platform != "spike2":
            out.append(os.path.join(os.path.dirname(lib.rstrip("\\/")), platform))
    return [d for d in out if os.path.isdir(d)]


def launch_for(platform, title, card):
    """The launch for a title's platform: Spike 2's Launch, Spike1Launch or
    SpookyLaunch."""
    if platform == "spike1":
        return Spike1Launch(title, card)
    if platform == "spooky":
        return SpookyLaunch(title, card)
    return Launch(title, card)


def card_places(title, platform="spike2"):
    kit = kit_load()
    libs = libraries(platform, kit)
    return ("PAD_VPX_CARD, ~/.pad-vpx.json cards[%s]%s, the librar%s %s"
            % (title, "" if not (kit.get("cards") or {}).get(title) else " (missing file)",
               "y" if len(libs) < 2 else "ies", ", ".join(libs) if libs else
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
    """The rig (watch.sh and friends) as Windows sees it: PAD_VPX_RIG (a
    checkout's rig under test, PAD-943), the kit's `rig` (an installed app's
    tools/spike2_emu), else the one beside this file."""
    return os.environ.get("PAD_VPX_RIG") or kit_load().get("rig") or RIG


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


def _app_module(name, why):
    """A module of the app's core (`rigdata`, `wsl_disk`), from the app's
    package beside the kit, or None (logged with `why`) where there is none."""
    app = os.path.dirname(os.path.dirname(os.path.abspath(rig_dir())))
    if app not in sys.path:
        sys.path.append(app)
    try:
        import importlib
        return importlib.import_module("pinball_decryptor.core." + name)
    except Exception as exc:                                # noqa: BLE001
        log("no app package beside the rig (%s): %s" % (exc, why))
        return None


def _rigdata(why):
    """The app's core/rigdata.py, from the app's package beside the kit, or
    None (logged with `why`) where there is none."""
    return _app_module("rigdata", why)


_HOST_DRIVE = {}


def host_drive(dist):
    """PAD_HOST_DRIVE for a run in `dist`: the Windows drive the distro's
    ext4.vhdx is on, as WSL mounts it (`/mnt/c`), or "" when it cannot be
    told. The app's Emulate tab passes it to every run (emulate_core
    _host_drive_env, PAD-816): inside WSL df reports the virtual disk's size,
    so without it cardmount.sh once started a 14.7 GB copy onto a C: with a
    few GB left and the whole distro went read-only. A table's launch never
    passed it (PAD-964). Asked once; the drive comes from the app's one
    reader of the registry (core/wsl_disk)."""
    if sys.platform != "win32":
        return ""
    if dist not in _HOST_DRIVE:
        drive = ""
        wsl_disk = _app_module("wsl_disk", "no host drive floor")
        if wsl_disk is not None:
            try:
                _name, vhdx = wsl_disk._default_distro_vhdx()
                letter = os.path.splitdrive(vhdx or "")[0]
                if re.fullmatch(r"[A-Za-z]:", letter):
                    drive = padpath.to_wsl(letter + "\\", dist).rstrip("/")
            except Exception as exc:                        # noqa: BLE001
                log("host drive not told (%s): the copier checks as before" % exc)
                drive = ""
        _HOST_DRIVE[dist] = drive
    return _HOST_DRIVE[dist]


def app_home(dist):
    """The app's PAD_HOME for a run in `dist`, or "" for the rig's own default.

    The app keeps the Spike 2 rig on its data disk when it runs in its own
    runtime and that disk exists (emulate_core._rig_env, core/rigdata.py), and
    attaches the disk again after a WSL restart before a run. A run started
    here has to land in that same rig - its rootfs, cards and NVRAM - so this
    asks rigdata the same question, from the app's package beside the kit."""
    if sys.platform != "win32" or dist != RUNTIME_DISTRO:
        return ""
    rigdata = _rigdata("the rig's own PAD_HOME")
    if rigdata is None or not rigdata.exists():
        return ""
    try:
        rigdata.ensure(dist, log=log)
    except Exception as exc:                                # noqa: BLE001
        log("the app's data disk did not attach (%s): the rig's own PAD_HOME" % exc)
        return ""
    return rigdata.work_dir("spike2") or ""


def card_store(dist):
    """Attach the shared Spike 2 card store (PAD-651) when this PC has one and
    a WSL restart left it off, as the app's Emulate tab does before every run.
    Without it cardmount.sh falls back to the distro's own cache, and when
    that has no room for the card the game boots off the Windows drive
    through 9p: Batman 1.14 took 148 s to attract that way, the table sitting
    on "Startup In Progress" (PAD-963). Never a refusal: the run goes on."""
    if sys.platform != "win32":
        return
    rigdata = _rigdata("no card store")
    if rigdata is None or not rigdata.cards_exists():
        return
    dist = dist or next(iter(distros()), None)
    if not dist:
        return
    try:
        rigdata.ensure_cards(dist, log=log)
    except Exception as exc:                                # noqa: BLE001
        log("the card store did not attach (%s): the card is read where it lies" % exc)


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
        self.title = game_for(title)
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
        self.check = None       # cache_check(): what the card costs the disk (PAD-964)

    def rig_cmd(self, script, env=()):
        """How a rig script is called from here: as root, the way the run
        itself starts (head()), on the app's board and in the app's rig,
        `env` entries before it. Root because the board may be root's already
        (the app's runs are root) and because taking a slot >= 1 also mounts
        its rootfs, which only root can (riglock.sh, "RUN IT AS ROOT"). A
        distro whose account has no home gets the plain user, as head()
        does."""
        user, home = account(self.distro)
        if home and user:
            head = wsl_head(self.distro, root=True) + ["-e", "env", "HOME=" + home]
        else:
            head = wsl_head(self.distro) + ["-e", "env"]
        return head + self.board_env() + list(env) + ["bash", "%s/%s" % (self.rig_wsl, script)]

    def rig_head(self):
        """How every riglock.sh call starts (rig_cmd)."""
        return self.rig_cmd("riglock.sh")

    def cache_env(self):
        """What the card cache is told for this run: the Windows drive behind
        WSL (host_drive) and, with caching off in the kit, PAD_CARD_CACHE=0."""
        env = []
        drive = host_drive(self.distro)
        if drive:
            env.append("PAD_HOST_DRIVE=%s" % drive)
        if not cache_on():
            env.append("PAD_CARD_CACHE=0")
        return env

    def cache_check(self, cards=None):
        """What the card (or each of `cards`) costs the disk before the run:
        `cardmount.sh --cache-check`, a dry run of the copier's own room rule
        in the run's distro and rig, nothing copied (PAD-964). The record for
        this run's card (parse_check), or None when WSL did not answer - a
        start is never refused on it. With `cards`, every record by image path
        and the cache's own line: {"checks", "cache"}."""
        imgs = padpath.to_wsl_many(list(cards) if cards is not None else [self.card], self.distro)
        cmd = self.rig_cmd("cardmount.sh", self.cache_env()) + [imgs[0], "--cache-check"] + imgs[1:]
        try:
            r = _run(cmd, timeout=120)
        except Exception as exc:                            # noqa: BLE001
            log("cache check not answered: %s" % exc)
            return None
        got = parse_check(_text(r.stdout))
        if not got["checks"]:
            log("cache check said nothing (%s): %s" % (r.returncode, (_text(r.stderr) or "").strip()[-200:]))
            return None
        if cards is not None:
            return got
        return got["checks"].get(imgs[0]) or next(iter(got["checks"].values()))

    def note(self, line):
        """A line of this run's own log (the loading window reads it)."""
        try:
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

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
        env += self.cache_env()
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
        card_store(self.distro)
        # PAD-964: what the card costs the disk, said in the run's log before
        # anything is copied - the loading window shows it, and a start with
        # no room for the copy (the game reads the image where it lies, 2.5
        # minutes to attract instead of 40 s) says so instead of "Reading the
        # card image" for all of them. Never a refusal: a slow game beats none.
        self.check = self.cache_check()
        if self.check:
            state, words = space_words(self.check)
            self.note("[card-check] %s: %s" % (state, words))
            log("card check for %s: %s: %s" % (self.title, state, words))
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


# ---------------------------------------------------------------- Spike 1 --

def app_work(dist, rig="spike2"):
    """app_home() for any rig the app keeps on its data disk: "spike2" is
    PAD_HOME, "spike1" the S1_WORK that tools/spike1_emu reads (PAD-943)."""
    if sys.platform != "win32" or dist != RUNTIME_DISTRO:
        return ""
    rigdata = _rigdata("the rig's own work dir")
    if rigdata is None or not rigdata.exists():
        return ""
    try:
        rigdata.ensure(dist, log=log)
    except Exception as exc:                                # noqa: BLE001
        log("the app's data disk did not attach (%s): the rig's own work dir" % exc)
        return ""
    return rigdata.work_dir(rig) or ""


class Spike1Launch:
    """One Spike 1 run started for a table (PAD-943): tools/spike1_emu's
    start.sh with the title's card, the way the app's Spike 1 Emulate tab
    starts one (`wsl -u root`, S1_WORK on the app's data disk when it has
    one, S1_PIVOT=1 so save states work), visible and with sound, on the
    app's board. There is ONE Spike 1 rig - no slots - so a run of another
    title already up is refused rather than replaced, and stop.sh stops
    what this started.

    The game's DMD is not a window of the rig's own: the app's Spike 1 tab
    draws it (spike1_windows.py) from the run's spi0.cap, so a player keeps
    the app open beside Visual Pinball to see it; the tribute's own scripted
    display keeps running as the shadow game's."""

    def __init__(self, title, card, dist=None, minutes=240):
        self.title = game_for(title)
        self.card = card
        self.distro = dist if dist is not None else distro()
        self.minutes = minutes
        self.slot = 0
        self.proc = None
        self.as_root = True
        self.rig_wsl = padpath.to_wsl(os.path.join(os.path.dirname(rig_dir()), "spike1_emu"),
                                      self.distro)
        self.logfile = os.path.join(os.path.dirname(LOG), "padvpx-%s.log" % title)
        self.work = None

    def work_dir(self):
        """S1_WORK for this run: the app's data disk, else the rig's default."""
        if self.work is None:
            self.work = app_work(self.distro, "spike1") or ""
        return self.work

    def env(self):
        card = padpath.to_wsl(self.card, self.distro)
        env = ["PAD_LABEL=%s" % LABEL, "PAD_HIDDEN=0", "PAD_AUDIO=1", "S1_PIVOT=1"]
        if sys.platform == "win32":
            env.append("PAD_BOARD=%s" % padpath.to_wsl(BOARD, self.distro))
        if self.work_dir():
            env.append("S1_WORK=%s" % self.work_dir())
        return env, card

    def head(self):
        user, home = account(self.distro)
        head = wsl_head(self.distro, root=True) + ["-e", "env"]
        if home:
            head.append("HOME=" + home)
        return head

    def other_run(self):
        """The Spike 1 run already up, when it is not this title's."""
        import s1bridge
        rec = s1bridge.board_record()
        if rec and (rec.get("game") or "").lower() != (self.title or "").lower():
            return rec
        return None

    def take_slot(self):
        return 0

    def start(self):
        why = no_linux(self.distro)
        if why:
            log(why)
            raise RuntimeError(why)
        other = self.other_run()
        if other:
            raise RuntimeError("the Spike 1 rig is running %s (%s); stop it first - there is one "
                               "Spike 1 rig" % (other.get("game"), other.get("label") or "the app"))
        env, card = self.env()
        cmd = self.head() + env + ["bash", "%s/start.sh" % self.rig_wsl, card]
        out = open(self.logfile, "ab")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                     creationflags=_CREATE_NO_WINDOW)
        log("started %s on the Spike 1 rig from %s (distro %s, log %s)"
            % (self.title, self.card, self.distro or "default", self.logfile))
        return 0

    def alive(self):
        """start.sh returns at READY (the game up) and the run lives on, so a
        finished start is alive while the board says so."""
        if self.proc is not None and self.proc.poll() is None:
            return True
        import s1bridge
        return s1bridge.board_record(self.title) is not None

    def stop(self):
        try:
            env = ["S1_WORK=%s" % self.work_dir()] if self.work_dir() else []
            _run(self.head() + env + ["bash", "%s/stop.sh" % self.rig_wsl], timeout=120)
            log("stopped %s on the Spike 1 rig" % self.title)
        except Exception as exc:                            # noqa: BLE001
            log("stop of the Spike 1 run failed: %s" % exc)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except Exception:                               # noqa: BLE001
                pass
        self.proc = None


# ----------------------------------------------------------------- Spooky --

class SpookyLaunch(Spike1Launch):
    """One Spooky run started for a table (PAD-952): tools/spooky_emu's
    watch.sh with the title's update file (code_H78.pkg), as the app's
    Spooky Emulate tab starts one (`wsl -u root`), visible and with sound,
    on a rig slot no other Spooky run holds. The game draws its own screen
    in its own window; watch.sh returns at attract and the run lives on."""

    #: the Spooky rig's slots the kit takes, the highest first (the app's
    #: Emulate tab starts at 0)
    SLOTS = (7, 6, 5, 4)

    def __init__(self, title, card, dist=None, minutes=240):
        super().__init__(title, card, dist, minutes)
        self.slot = None
        self.rig_wsl = padpath.to_wsl(os.path.join(os.path.dirname(rig_dir()), "spooky_emu"),
                                      self.distro)

    def other_run(self):
        """A Spooky run of this title already up that is not the kit's: one
        title runs once (its rig folder is per slot, its saved game is not)."""
        import spkbridge
        rec = spkbridge.board_record(self.title)
        if rec and rec.get("label") != LABEL:
            return rec
        return None

    def take_slot(self):
        import spkbridge
        for n in self.SLOTS:
            if spkbridge.board_record(slot=n) is None:
                self.slot = n
                return n
        raise RuntimeError("every Spooky rig slot the kit uses (%s) is running a game; stop one "
                           "first" % ", ".join(str(n) for n in self.SLOTS))

    def env(self):
        card = padpath.to_wsl(self.card, self.distro)
        env = ["PAD_LABEL=%s" % LABEL, "PAD_VISIBLE=1", "PAD_AUDIO=1", "PAD_SLOT=%d" % self.slot]
        if sys.platform == "win32":
            env.append("PAD_BOARD=%s" % padpath.to_wsl(BOARD, self.distro))
        return env, card

    def start(self):
        why = no_linux(self.distro)
        if why:
            log(why)
            raise RuntimeError(why)
        other = self.other_run()
        if other:
            raise RuntimeError("%s is running on the Spooky rig's slot %s (%s); stop it first"
                               % (other.get("title") or self.title, other.get("slot"),
                                  other.get("label") or "the app"))
        if self.slot is None:
            self.take_slot()
        env, card = self.env()
        cmd = self.head() + env + ["bash", "%s/watch.sh" % self.rig_wsl, card]
        out = open(self.logfile, "ab")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                     creationflags=_CREATE_NO_WINDOW)
        log("started %s on the Spooky rig's slot %d from %s (distro %s, log %s)"
            % (self.title, self.slot, self.card, self.distro or "default", self.logfile))
        return self.slot

    def alive(self):
        if self.proc is not None and self.proc.poll() is None:
            return True
        import spkbridge
        return spkbridge.board_record(self.title, slot=self.slot) is not None

    def stop(self):
        try:
            _run(self.head() + ["PAD_SLOT=%d" % (self.slot or 0), "bash", "%s/stop.sh" % self.rig_wsl],
                 timeout=120)
            log("stopped %s on the Spooky rig's slot %s" % (self.title, self.slot))
        except Exception as exc:                            # noqa: BLE001
            log("stop of the Spooky run failed: %s" % exc)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except Exception:                               # noqa: BLE001
                pass
        self.proc = None
