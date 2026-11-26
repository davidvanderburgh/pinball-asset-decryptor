"""Every name the app gives what it leaves in the temp folder (PAD-1596).

The space keeper (core/space_keeper.py) and Settings > Manage disk space
(core/host_temp.py) find the app's leftovers in ``%TEMP%`` by name.  Their
list once held ten prefixes while the app made some sixty more, so a crash
or a cancel left those for good and nothing showed them (255 ``pad-modes-*``,
350 ``pad-scenes-*`` and a GB-scale ``spike1_`` image on David's PC).  This
is the one list: host_temp reads it, and tests/test_pad_temp.py fails when a
``mkdtemp(prefix=...)``, ``mkstemp``, ``TemporaryDirectory`` or a folder
joined onto ``tempfile.gettempdir()`` anywhere in the app or its tools uses a
name that is not here.

WHO IS STILL USING IT.  :func:`mkdtemp` is ``tempfile.mkdtemp`` that also
notes, beside the temp folder (``pad_temp_owners``), the process that made
the folder.  The keeper never takes a folder whose maker is still running
(an open tab's scratch, a build that has been going for hours), and takes
one whose maker has died after an hour (:func:`owner_state`) instead of the
day it gives a folder it knows nothing about: nine 1.26 GB King Kong build
folders sat a day after their builds died.

RULES.  A name is *scratch* unless it says otherwise: once its folder has
not changed for a day (an hour when its maker is gone) it is a leftover.
``kept`` folders are caches the app keeps on purpose; they are listed in the
window but never removed whole by the keeper, and ``child_days`` lets the
keeper drop the cache's entries nobody has used for that long.
"""

import json
import os
import re
import sys
import tempfile
from collections import namedtuple

Name = namedtuple("Name", "prefix maker detail exact kept child_days")


def _n(prefix, maker, detail, exact=False, kept=False, child_days=None):
    return Name(prefix, maker, detail, exact, kept, child_days)


STERN = "Stern Pinball"
SHARED = "Shared tooling"
APP = "PAD"
TOOLS = "Emulator tools"

#: The folder beside the app's temp folders that says who made each one.
OWNERS = "pad_temp_owners"

NAMES = (
    # -- Stern ------------------------------------------------------------
    _n("spike2_", STERN, "audio extract / build staging"),
    _n("spike2_card_cache", STERN, "card copies kept for faster rebuilds",
       exact=True, kept=True, child_days=30),
    _n("spike2_clip_cache", STERN, "video clips kept for faster rebuilds",
       exact=True, kept=True, child_days=30),
    _n("spike2_code_cache", STERN, "compiled objects kept for faster rebuilds",
       exact=True, kept=True, child_days=30),
    _n("pinball_spike2_params", STERN, "build settings kept for faster rebuilds",
       exact=True, kept=True, child_days=30),
    # PAD-1598: a cache, not scratch - Stern's card lists, menus read off a card, and a Spooky
    # update's unpacked layer and member list (one per update, keyed by its content).  As
    # scratch the keeper took it whole a day after the last build, and the next plan of a
    # Stern multi-boot read every card again
    _n("pinball_spike2_multiboot", SHARED,
       "Multi-boot card lists and unpacked updates kept for faster rebuilds",
       exact=True, kept=True, child_days=30),
    _n("spike1_", STERN, "Spike 1 flat image staging"),
    _n("pad_engine_", STERN, "Emulate tab game staging"),
    _n("pad-network-", STERN, "network settings staging"),
    _n("pad_network_", STERN, "network settings hand-over"),
    _n("pad_srcfind_", STERN, "Find originals video staging"),
    _n("pad_spk_", STERN, "Spike 3 speaker staging"),
    _n("pad_s3_snd_", STERN, "Spike 3 sound staging"),
    _n("image_sound_selftest_", STERN, "Spike 3 sound self-test"),
    _n("pad-modes-", STERN, "Modes tab scratch"),
    _n("pad-card-modes-", STERN, "modes read from a card"),
    _n("pad_testcard_", STERN, "Test card staging"),
    # Simon (2026-11-26): the Multi-boot tab's TEST CARD entry - the Test card tab's list staged for the build
    _n("pad_multiboot_testcard", STERN, "Multi-boot TEST CARD entry staging", exact=True),
    _n("pad_cabstock_", STERN, "cabinet lights staging"),
    _n("pad_cabrec_", STERN, "cabinet lights recording"),
    _n("pad_sidx_", STERN, "sound index hand-over"),
    _n("pad_game_", STERN, "title read staging"),
    _n("pad_card_size_", STERN, "card size check"),
    _n("pad_scbin_", STERN, "scene code copy"),
    _n("pad-film-cut-", STERN, "Film cut staging"),
    _n("pad_soundlog_stage_", STERN, "Emulate sound log staging"),
    _n("pad-rules-sheet", STERN, "rules sheet PDFs", exact=True),
    _n("pad_card_preview", STERN, "card menu previews",
       exact=True, kept=True, child_days=7),
    _n("pad-webui-multiboot", STERN, "Multi-boot pictures", exact=True,
       kept=True),
    _n("pad_speak_", STERN, "spoken scores staging"),
    _n("pad_attract_quiet.wav", STERN, "quiet attract sound", exact=True),
    # -- other makers -----------------------------------------------------
    _n("williams_", "Williams DMD render", "DMD / video render"),
    _n("cc_", "Chicago Gaming Company", "Cactus Canyon scratch"),
    _n("cc_dcs_", "Chicago Gaming Company", "Cactus Canyon DCS scratch"),
    _n("cc_anim_", "Chicago Gaming Company", "Cactus Canyon video render"),
    _n("pad_cgc_libs_", "Chicago Gaming Company", "game library staging"),
    _n("pad_cc_usb_", "Chicago Gaming Company", "USB stick staging"),
    _n("pad_aaiw_", "Dutch Pinball", "Alice in Wonderland staging"),
    _n("spooky_", "Spooky Pinball", "build scratch"),
    _n("pad_spkmulti", "Spooky Pinball", "Multi-boot update index",
       exact=True, kept=True),
    _n("jjp_", "Jersey Jack Pinball", "staging"),
    _n("pad-ra-", "Jersey Jack Pinball", "remote access staging"),
    _n("pad_jjp_usb_", "Jersey Jack Pinball", "USB stick hand-over"),
    _n("pad_jjp_pic_", "Jersey Jack Pinball", "replacement image recompress"),
    _n("pad_sam_", "Williams / Stern SAM", "ROM capture staging"),
    _n("pad_ap_playfield.log", "American Pinball", "playfield log",
       exact=True),
    # -- the app's own ----------------------------------------------------
    _n("pad-ffmpeg-", SHARED, "ffmpeg helper"),
    _n("pad_iso_", SHARED, "ISO mount"),
    _n("pad_flash_", SHARED, "card write hand-over"),
    _n("pad_read_", SHARED, "card read hand-over"),
    _n("pad_remote_", SHARED, "remote set-up hand-over"),
    _n("pad-remote-", SHARED, "remote set-up staging"),
    _n("pad-share-", SHARED, "shared build staging"),
    _n("pad-ssh-", SHARED, "card over the network staging"),
    _n("pad_grow_", SHARED, "card grow staging"),
    _n("pad_luks_", SHARED, "encrypted card staging"),
    _n("pad_pinned_", SHARED, "card grow check"),
    _n("pad-game-", APP, "game file export"),
    _n("pad-game-code-", APP, "game file code staging"),
    _n("pad_vidbudget_", APP, "video fitting staging"),
    _n("pad-encprobe-", APP, "video encoder check"),
    _n("pad-decprobe-", APP, "video decoder check"),
    _n("pad-audio-", APP, "Audio tab scratch"),
    _n("pad-fonts-", APP, "Text fonts scratch"),
    _n("pad-scenes-", APP, "Scenes tab scratch"),
    _n("pad-card-", APP, "card file association"),
    _n("pad_pex_", APP, "Partition Explorer preview"),
    _n("pad_diskpart_", APP, "WSL disk script"),
    _n("pad_bof_", "Barrels of Fun", "game program staging"),
    _n("pad-update-", APP, "update download staging"),
    _n("pad-swap-", APP, "update swap staging"),
    _n("pad-splash-", APP, "update splash"),
    _n("pad_prereq_", APP, "installer staging"),
    _n("pad_prereqs_started_", APP, "installer started marker"),
    _n("pad_colour_luts", APP, "color profile tables", exact=True, kept=True),
    _n("pad-video-preview", APP, "video previews", exact=True, kept=True),
    _n("pad-webui-screen", APP, "machine screen pictures", exact=True),
    _n("pad_vpx_register.log", APP, "Visual Pinball set-up log", exact=True),
    _n("pad_update_swap_failed.txt", APP, "why the last update did not finish",
       exact=True, kept=True),
    _n("pad_playfield_rig", APP, "Emulate playfield log"),
    _n("pad-vpx-fetched", TOOLS, "Visual Pinball fetched files", exact=True),
    # -- the emulator tools (most run in the Linux side's /tmp) -------------
    _n("mkmulticard.", TOOLS, "Spike 2 multi-boot build"),
    _n("mkjjpmulti_", TOOLS, "JJP multi-boot build"),
    _n("mkjjpmodes_", TOOLS, "JJP modes build"),
    _n("padmodes_rt_", TOOLS, "JJP modes runtime"),
    _n("clip_sounds_", TOOLS, "clip sounds"),
    _n("ledgridtest_", TOOLS, "LED grid test"),
    _n("ledratetest_", TOOLS, "LED rate test"),
    _n("menuprobe_", TOOLS, "service menu probe"),
    _n("padpf-", TOOLS, "playfield view"),
    _n("spkinspect.", TOOLS, "Spooky multi-boot check"),
    _n("spkgpg.", TOOLS, "Spooky signing"),
    _n("i420check", TOOLS, "video check", exact=True),
    _n("vidcheck_shm", TOOLS, "video check", exact=True),
    _n(OWNERS, APP, "who made each temp folder", exact=True, kept=True),
)

_EXACT = {n.prefix: n for n in NAMES if n.exact}
_PREFIXED = sorted((n for n in NAMES if not n.exact),
                   key=lambda n: len(n.prefix), reverse=True)


def lookup(name):
    """The :data:`NAMES` entry *name* (a temp folder's base name) belongs
    to - an exact name first, then the longest prefix - or ``None``."""
    hit = _EXACT.get(name)
    if hit is not None:
        return hit
    for n in _PREFIXED:
        if name.startswith(n.prefix):
            return n
    return None


def temp_dir():
    return tempfile.gettempdir()


# ---------------------------------------------------------------------------
# Who made it
# ---------------------------------------------------------------------------

def owners_dir():
    return os.path.join(temp_dir(), OWNERS)


def _started(pid):
    """When process *pid* started (an opaque number, the same every time it
    is asked), or ``None`` when that cannot be told."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, int(pid))
            if not h:
                return None
            try:
                ft = [wintypes.FILETIME() for _ in range(4)]
                if not k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                    return None
                return (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
            finally:
                k32.CloseHandle(h)
        with open("/proc/%d/stat" % int(pid), "rb") as f:
            stat = f.read()
        return int(stat.rsplit(b")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def pid_alive(pid, started=None):
    """Process *pid* is running - and, when *started* is given and can be
    read, is the same process that was (a pid can be reused).  Never sends
    a signal: on Windows ``os.kill(pid, 0)`` ends the process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            # 5 = access denied: a process is there, it is just not ours
            return ctypes.get_last_error() == 5 and started is None
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            if code.value != 259:                       # STILL_ACTIVE
                return False
        finally:
            k32.CloseHandle(h)
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        except OSError:
            return False
    if started is not None:
        now = _started(pid)
        if now is not None and now != started:
            return False
    return True


def mark_owner(path, pid=None):
    """Note that process *pid* (this one) made *path*, a folder in the temp
    folder.  Best effort: a failure only means the keeper waits the day."""
    pid = os.getpid() if pid is None else int(pid)
    try:
        os.makedirs(owners_dir(), exist_ok=True)
        rec = os.path.join(owners_dir(), os.path.basename(path.rstrip("\\/")))
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "started": _started(pid)}, f)
    except OSError:
        pass


def forget_owner(name):
    try:
        os.remove(os.path.join(owners_dir(), os.path.basename(name)))
    except OSError:
        pass


def owner_state(name):
    """``"alive"`` while the process that made temp folder *name* runs,
    ``"dead"`` once it has ended, ``None`` when nobody said (made before
    PAD-1596, by a tool, or by ``tempfile`` directly)."""
    try:
        with open(os.path.join(owners_dir(), os.path.basename(name)),
                  encoding="utf-8") as f:
            rec = json.load(f)
        pid = rec["pid"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return "alive" if pid_alive(pid, rec.get("started")) else "dead"


def prune_owners():
    """Drop the notes of folders that are gone.  Returns how many."""
    d, td, gone = owners_dir(), temp_dir(), 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for n in names:
        if not os.path.lexists(os.path.join(td, n)):
            try:
                os.remove(os.path.join(d, n))
                gone += 1
            except OSError:
                pass
    return gone


def _in_temp(dir):
    if dir is None:
        return True
    try:
        return (os.path.normcase(os.path.realpath(dir))
                == os.path.normcase(os.path.realpath(temp_dir())))
    except (OSError, TypeError, ValueError):
        return False


def mkdtemp(suffix=None, prefix=None, dir=None):
    """``tempfile.mkdtemp`` for the app: *prefix* must be one of
    :data:`NAMES` (the test says so), and a folder made in the temp folder
    is noted as this process's (:func:`mark_owner`)."""
    path = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
    if _in_temp(dir):
        mark_owner(path)
    return path


#: A cache entry being written beside its final name (``<key>.tmp<pid>``).
_TMP_PID = re.compile(r"\.tmp\.?(\d+)$")     # <key>.tmp<pid>, or the multi-boot tools' <key>.tmp.<pid>


def tmp_writer(name):
    """The pid in a ``<name>.tmp<pid>`` (or ``.tmp.<pid>``) half-written cache entry, or None."""
    m = _TMP_PID.search(name)
    return int(m.group(1)) if m else None
