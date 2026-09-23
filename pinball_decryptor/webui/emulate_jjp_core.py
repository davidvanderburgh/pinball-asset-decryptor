"""Emulate tab for Jersey Jack Pinball — run a JJP game on this PC.

A SIBLING OF ``emulate_tab``, NOT AN EXTENSION OF IT.  That module is 3,446
lines welded to the Stern Spike 2 rig in a dozen places that are not cosmetic:
its rig directory, its ``qemu-user-static`` / ``gcc-arm-linux-gnueabihf``
prerequisite vocabulary, its state words, its Stern SD-card filename regex, its
``PAD_CARD=`` launch environment.  Threading a second rig through all of that
would carry two prerequisite vocabularies and two state vocabularies in one
file, against three existing test files, for no user-visible gain.  What the
two genuinely share — how a Windows path is spelled for WSL, how a rig script
is invoked, how ``key=value`` status is parsed — lives in :mod:`.rig`, so
there is still exactly one definition of each.

WHAT MAKES JJP DIFFERENT FROM SPIKE 2
-------------------------------------
Simpler in the big ways: the game is a native x86-64 Linux binary, so there is
no ``qemu-user``; it draws through GLX so there is no GL bridge; it decodes its
own WebM with libavcodec so there is no video bridge.  Those are the three
largest subsystems of the Spike 2 rig and none of them exist here.

Harder in one way that has no Spike 2 analogue: **the purple Sentinel USB key
is mandatory and cannot be faked.**  The game binary is Sentinel LDK Envelope
protected — 7,086 of its 8,566 functions are ciphertext at rest — and the
dongle supplies the AES key that decrypts them.  There is no branch to patch.
Without it the game prints ``Sentinel key not found (H0007)`` and exits 1,
which is exactly what a real machine shows, so this panel reports it as a
first-class state rather than as a crash.

The key is also per-title: a key for another JJP game will H0007 on this one.

WHY THE PANEL IS THIN
---------------------
Every step of the launch — mount, jail, dongle, audio, boards, display, game —
lives in ``tools/jjp_emu/watch.sh``, in the one order that works.  This panel
starts it, stops it, and says truthfully what it is doing.  Putting the
sequence here instead would be a second definition of it, and the order is
exactly the part that was learned the hard way.

THIS MODULE is the Tk-free half of the old Tk panel (``gui/jjp_emulate_tab.py``
until the web UI cut-over): every module-level function and constant it had,
unchanged, and the panel's poll periods and launch-ladder table, which were
class attributes of ``JJPEmulatePanel``.  The web JJP Emulate tab
(``webui/tabs/emulate_jjp.py``) is the panel now.
"""

import os
import pathlib
import re
import subprocess
import sys

from pinball_decryptor.webui import rig as _rig
# The Volume / Mute knob is the other Emulate tabs' own: one control file for
# every rig, so the level is the same whichever tab starts a game (item 118).
from .emulate_core import (  # noqa: F401  (re-exported)
    AUDIO_CTL_FILE, _load_audio_ctl, _write_audio_ctl)

#: The rig ships in the repo next to this package, so it survives a reboot and
#: there is exactly one copy of it.  Resolved from this file so a checkout
#: anywhere works.  ``PAD_JJP_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "jjp_emu"
)


def rig_dir():
    return os.environ.get("PAD_JJP_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Is the rig actually present?  Checked by script, not by directory:
    a half-copied tools tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh"))


def rig_cmd(*args, **kw):
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


#: usbipd lives here on a default install; found on PATH first.
USBIPD_FALLBACK = r"C:\Program Files\usbipd-win\usbipd.exe"

#: The Sentinel HL key.  Aladdin/SafeNet vendor id, and the same for every JJP
#: title — it is the LICENCE on the key that is per-title, not the hardware.
HASP_VID_PID = "0529:0001"


def usbipd_path():
    from shutil import which
    return which("usbipd") or (USBIPD_FALLBACK
                               if os.path.isfile(USBIPD_FALLBACK) else None)


def rdp_client_running():
    """Is WSLg's window layer connected - an ``msrdc.exe`` on this desktop?

    WSLg shows every Linux window through one RDP client process.  With it
    gone the rig runs perfectly and NOTHING appears: the game draws into
    Xephyr, Xephyr draws into an X server nobody is looking at, and the CPU
    climbs while the desktop stays empty (David, 2026-09-13: "i don't see any
    of the display windows ... i just hear my cpu go crazy" - the client had
    been killed hours earlier to close a ghost window, and PulseAudio's RDP
    sink went with it).  ``wsl --shutdown`` (the Fix stuck state button)
    brings it back.  None when the question cannot be asked (not Windows,
    no tasklist)."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["tasklist.exe", "/FI", "IMAGENAME eq msrdc.exe", "/NH"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=20, creationflags=_rig.CREATE_FLAGS)
    except Exception:                                      # noqa: BLE001
        return None
    return b"msrdc.exe" in out.stdout.lower()


#: The titles the JJP rig's own windows carry on the Windows desktop: the
#: nested display (display.sh: "JJP <Title> - emulated") and the switch matrix
#: (jjpsw.py), each with the distro name WSLg appends ("... (Ubuntu)").
_RIG_WINDOW_RE = re.compile(r"^JJP (?:.+ - emulated|switch matrix)(?: \(.*\))?$")


def rig_ghosts(windows):
    """The rig's windows WSLg is still showing, from ``[(hwnd, title, exe,
    visible)]``: VISIBLE, one of the rig's titles, and owned by msrdc.exe.
    Only asked right after a Stop that reported no display and no matrix
    running, so nothing named here has a live program behind it."""
    return [h for h, title, exe, visible in windows
            if visible and (exe or "").lower() == "msrdc.exe"
            and _RIG_WINDOW_RE.match(title or "")]


def stop_left_nothing(text):
    """Did stop.sh report the display AND the matrix gone?  Its last line reads
    ``game=0 matrix=0 xephyr=0 cuse=0``; anything else leaves windows alone."""
    return bool(re.search(r"\bmatrix=0\b", text or "")
                and re.search(r"\bxephyr=0\b", text or ""))


def _desktop_windows():
    """``[(hwnd, title, exe, visible)]`` for every top-level window (Windows)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    exe_of = {}

    def exe(pid):
        if pid not in exe_of:
            name = ""
            h = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value)
                kernel32.CloseHandle(h)
            exe_of[pid] = name
        return exe_of[pid]

    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append((int(hwnd), buf.value, exe(pid.value),
                          bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(each, 0)
    return found


def hide_rig_ghosts(windows=None, hide=None):
    """Hide the windows a stopped rig left on the desktop; how many.

    WSLg sometimes keeps the frame of a Linux window whose program has exited:
    the game display and the switch matrix stayed on David's desktop after a
    Stop with nothing running behind them (2026-09-13: "the windows are hanging
    forever").  A close request does nothing to such a frame - measured, both
    ignored WM_CLOSE - and ending msrdc.exe, the process that holds it, takes
    every Linux window and PulseAudio down with it.  Hiding is the one safe
    thing; the frames go for good at the next WSL restart."""
    if sys.platform != "win32":
        return 0
    try:
        hwnds = rig_ghosts(_desktop_windows() if windows is None else windows)
        if hide is None:
            import ctypes
            user32 = ctypes.WinDLL("user32")

            def hide(h):
                user32.ShowWindowAsync(ctypes.c_void_p(h), 0)   # SW_HIDE
        for h in hwnds:
            hide(h)
        return len(hwnds)
    except Exception:                                      # noqa: BLE001
        return 0


def attach_dongle_cmd():
    """Hand the Sentinel key to WSL.

    ``usbipd`` needs a WSL session ALREADY RUNNING or it fails with "There is
    no WSL 2 distribution running" — which is why the panel pokes WSL awake
    first rather than trusting that something else has.
    """
    exe = usbipd_path()
    if not exe:
        return None
    return [exe, "attach", "--wsl", "--hardware-id", HASP_VID_PID]


def key_on_pc():
    """Is the Sentinel key plugged into the PC, whatever WSL can see?

    ``status.sh``'s ``dongle_present`` is a WSL question - it reads sysfs
    INSIDE the distro - so a key sitting in the machine but not passed through
    by usbipd reads as absent, and the panel said "No security key" at a user
    looking straight at the key.  Those are different faults: one needs a key,
    the other needs an attach, and the panel already knows how to do the second.

    Returns True / False, or None when usbipd cannot be asked at all.
    """
    exe = usbipd_path()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "list"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=20,
                             creationflags=_rig.CREATE_FLAGS)
    except Exception:                                      # noqa: BLE001
        return None
    return HASP_VID_PID in out.stdout.decode("utf-8", "replace").lower()


def key_failure(line):
    """(headline, hint) if this rig line is a key verdict, else None.

    H0007 — "Sentinel key not found" — covers TWO faults with opposite fixes,
    and the panel used to report only the first.  On 2026-08-20 that cost an
    hour: it said "wrong key, plug in the GunsNRoses key" while the truth was
    that the licence daemon could see NO key at all, so every title failed the
    same way, including the one whose key WAS plugged in.  ``run_game.sh`` now
    distinguishes them and this reads its verdict rather than guessing one.
    """
    if line.startswith("NO KEY:"):
        return ("No security key",
                "No Sentinel key is visible inside WSL — the passthrough is "
                "not up, or it dropped. Plug the key in and press Start; the "
                "panel re-attaches it for you.")
    if line.startswith("KEY NOT ACCEPTED:"):
        return ("Key not accepted",
                "The key is visible in WSL but the game could not open it. "
                "Either it is another JJP title's key — they are per-title — "
                "or the licence daemon never picked it up, which no key swap "
                "fixes. The log line below says how to tell the two apart.")
    # The pre-2026-08-20 wording, still understood so an older rig script in a
    # half-updated checkout does not silently stop being reported.
    if "WRONG KEY" in line:
        return ("Wrong key for this game",
                "The plugged-in key runs a different JJP title. JJP keys are "
                "per-title — plug in this game's own key.")
    return None


def state_text(info):
    """(label, hint) for the panel's headline, from status.sh's key=value.

    The order of these tests is the order a user hits them, so the FIRST thing
    that is wrong is what they are told about — a run with no key is not
    "stopped", it is "no security key", and saying "stopped" would send them
    looking in the wrong place.
    """
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return "WSL not answering", "The rig is a Linux program and runs inside WSL."
    procs = int(info.get("game_procs") or 0)
    if procs:
        bits = []
        rss = int(info.get("game_rss_kb") or 0)
        if rss:
            bits.append("%.1f GB" % (rss / 1024.0 / 1024.0))
        up = int(info.get("game_uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        if info.get("frames_in", "0") != "0":
            bits.append("%s frames in" % info["frames_in"])
        if info.get("board_nodes", "0") == "0":
            bits.append("NO BOARDS — no switches or LEDs")
        return "Running", "  ·  ".join(bits)
    if info.get("dongle_present") != "1":
        # The key can be IN the PC and still invisible to the rig: usbipd has
        # to hand it to WSL first.  Saying "no security key" to someone looking
        # at the key in the port is how this presented.
        if info.get("key_on_pc") == "1":
            return ("Key not passed through yet",
                    "The key is in this PC but WSL cannot see it yet — it has "
                    "to be handed over by usbipd. Doing that now; it takes a "
                    "few seconds.")
        return ("No security key",
                "Plug in the purple JJP USB key. The game's code is encrypted "
                "with it — this is not a check that can be skipped.")
    if info.get("image_mounted") != "1":
        return "No image mounted", "Pick a JJP ISO and press Start."
    return "Stopped", ""


# ----------------------------------------------------------------------
# The panel's numbers and tables (class attributes of the Tk JJPEmulatePanel).

#: Status poll period while something is running.  Each poll is one
#: ``wsl.exe`` round trip.
POLL_MS = 2000

#: Poll period when the rig is idle.  A machine with no emulator on it is
#: not worth a WSL spawn every two seconds for as long as the app is open —
#: that is 1,800 round trips an hour to be told "off", and after a Windows
#: reboot the first of them boots the whole WSL VM.  This is the same guard
#: the Spike 2 panel carries, and a second polling tab in the same app
#: doubles the exposure it exists for.
POLL_IDLE_MS = 10000

#: Fast retry until the FIRST answer, so a freshly opened tab settles
#: quickly instead of showing "Checking…" for ten seconds.
POLL_FIRST_MS = 700

#: The launch's section headers (watch.sh prints one per step) -> the
#: footer ladder's slot, as MainWindow.set_emulate_progress names them:
#: copy = the first chip (Restore image), boot = the second, techalerts =
#: the third (Game: the game, or the multi-boot menu before it), run =
#: Ready.  Item 118, David 2026-09-13: the JJP tab showed Stern's ladder
#: and never moved it.
FOOTER_STEPS = (("== mount image ==", "copy", 0, "Restoring the image…"),
                ("== jail ==", "boot", None, "Booting: the jail…"),
                ("== dongle ==", "boot", None, "Booting: the security key…"),
                ("== audio ==", "boot", None, "Booting: audio…"),
                ("== boards ==", "boot", None, "Booting: the boards…"),
                ("== display ==", "boot", None, "Booting: the display…"),
                ("== game", "techalerts", None, "Starting the game…"))
#: mount.sh's restore progress: "  sda3: 40%".
RESTORE_PCT = re.compile(r"^\s*(sda\d+): (\d+)%$")
