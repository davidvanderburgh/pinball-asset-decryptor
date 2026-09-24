"""Emulate tab — run the Stern Spike 2 game on this PC and watch its health.

The emulator is a rig of shell scripts, an ``LD_PRELOAD`` hardware shim and a
native GL host, in ``tools/spike2_emu``.  It SHIPS WITH THE APP (this used to
say it lived outside the repo, in ``c:\\tmp\\spike2_emu``, which stopped being
true twice over).  ``PAD_EMU_DIR`` moves it.  This panel is a *control surface*
for that rig: start it, stop it, and say truthfully what it is doing.  It
deliberately does not reimplement any of it.

WHERE IT RUNS.  The rig is a Linux program: the chroot, qemu-user, the node bus
and the GL host have nothing Windows-specific in them.  On a Linux desktop it is
simply run; from Windows it is reached through WSL, and everything that looks
Windows-flavoured in it - the playfield window as a Windows process, the audio
bridge - is a WORKAROUND for what WSL lacks, not a design choice.  ``rig_cmd()``
is the one place that knows which of the two applies.

Three things about it are worth knowing before changing anything here:

* **It runs a card image, and only a card image.**  The image is mounted READ
  ONLY and run in place: nothing is extracted, and nothing can write to it.  The
  user picks the file; whether that is a stock card or their own build is their
  business, and this tab does not guess.

  Two other sources were offered briefly and both were wrong.  An "extracted
  folder" cannot work: PAD extracts ASSETS, and the rig needs a title directory
  (a ``game`` binary with ``assets/`` and the node ``.hex`` files beside it),
  which is a different shape — pointing it at an extract folder could only fail.
  A "rig's own copy" option exposed whatever happened to be unpacked inside the
  rig on this machine, which is internal state no user can create or reason
  about.

  **The card can be ASKED TO CARRY THE USER'S EDITS, though, and that is not a
  second source** (PAD-103).  With the opt-in ticked, the app patches the card
  files those edits live in — ``image.bin`` and its ``.sidx`` record, for a
  replaced sound — into a small OVERRIDE SET, and the rig bind-mounts those
  files over the same read-only mount.  Still one card, still opened read only;
  the rule above is unchanged, and so is the image on disk.  What it replaces
  is the two full-size copies that trying an edit used to cost: the build's
  copy of the card, and then this tab's own copy of that new card onto the WSL
  disk.  Measured on a jurassic_park_le 1.16.0 card, the set is 9 seconds.

  **A replacement PICKED on a Replace tab is one of those edits** (PAD-121).
  The set is computed by diffing the project folder against its extract
  baseline, and a Replace tab holds an assignment in memory until a build
  writes it over the folder's own file — so the box used to see nothing at all
  until the user had built the card image this feature exists to save them.
  Start now applies them first (``App.stage_pending_replacements``, the same
  three calls a Write makes before it repacks) and says so in the log, because
  it changes the project folder and the user did not press Build.

* **The LAUNCH is root on Windows now, and that is item 13's doing.**  This
  module's original rule was "normal WSL user, never root - root breaks WSLg
  and the audio path", and that stopped being true when ``watch.sh`` learned
  the drop dance: a ``PAD_PIVOT=1`` root launch boots the GUEST as root (the
  only shape criu can checkpoint, so the only shape the playfield's
  Save/Load state buttons work in) and drops every helper back to the desktop
  user, whose WSLg and audio session they need.  ``watch_cmd()`` owns the
  launch, ``kill_cmd()`` the teardown (a root guest needs a root kill), and
  ``wsl_home()`` the one fact both need beyond ``rig_cmd()``.  Helpers,
  status polls and everything else still run as the normal user, which is
  still why this module calls ``wsl.exe`` directly instead of reusing the
  executor.

* **Stopping must be verified, never assumed.**  An orphaned guest spins at
  ~140% CPU forever and ignores polite signals, so Stop runs the rig's own
  ``killgame.sh`` (SIGKILL for all five processes) and then re-reads the status
  until it reports zero.  The panel shows the process count for exactly this
  reason.
"""

import json
import ntpath
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from ..core import config, pkgnames, prereqs, rigdata, runtime
# PAD-161's "which card is the set prepared FROM" moved to the plugin so Try
# it (mode_write.build_tryit_set) can share it without importing Tk; both
# names stay importable from here for the tests and callers that read them
# off this module.
from ..plugins.stern.cards import _title_label, override_base_card  # noqa: F401
from . import rig as _rig
from . import runtime_prompt as _runtime_ui

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

#: The rig ships in the repo, next to this package, rather than in the temp
#: directory it was developed in - so it survives a reboot and there is exactly
#: one copy of it.  Resolved from this file so a checkout anywhere works.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spike2_emu"
)

#: Item 56: master PC-side volume + Mute for the emulator's OWN sound - "our
#: level, not the game's" (David).  One small JSON plays two roles at once,
#: deliberately: it is BOTH the remembered setting (read once, at panel
#: construction, so the slider already shows what a fresh run will play) AND
#: the LIVE control channel a running padplay.py polls every ~250 ms (see its
#: poll_gain()) - so dragging the slider or hitting Mute reaches the speakers
#: with no restart, which is the whole of what this item asked for beyond a
#: plain preference. One shared file alongside settings.json, same idiom as
#: AUDIO_NAMES_FILE / CARD_EDITS_FILE / LIBRARY_FILE.
#: Shape: {"gain": 0.0-1.0, "muted": bool}.
AUDIO_CTL_FILE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                              "audio_ctl.json")


def _load_audio_ctl():
    """The remembered volume/mute, defaulting to unity/unmuted — today's
    behaviour, unchanged, for a machine that has never touched the knob."""
    try:
        with open(AUDIO_CTL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        gain = float(data.get("gain", 1.0))
        muted = bool(data.get("muted", False))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 1.0, False
    return max(0.0, min(1.0, gain)), muted


def _write_audio_ctl(gain, muted):
    """Persist AND live-publish.  Atomic (temp + ``os.replace``) so padplay.py's
    poll never catches a half-written file — the file is small and this is
    called on every slider tick, but a torn read would only ever cost one
    250 ms poll's worth of stale gain, never a corrupt one."""
    try:
        os.makedirs(os.path.dirname(AUDIO_CTL_FILE), exist_ok=True)
        tmp = AUDIO_CTL_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"gain": gain, "muted": muted}, f)
        os.replace(tmp, AUDIO_CTL_FILE)
    except OSError:
        pass

#: How the rig's ``state=`` word is shown to a human.  ``techalerts`` is not a
#: fault: the game boots to its Tech Alerts screen and waits there for an
#: operator, exactly as the real machine does.  Reading that as "stuck" cost a
#: whole pass of this project, so the wording here is deliberate.
_STATE_TEXT = {
    "off": ("Not running", ""),
    "booting": ("Starting…", "Loading scenes and bringing up the node bus."),
    # "At", not "Waiting at": since item 63 a boot steps past this screen on
    # its own, so the waiting word was a lie in the common case (David,
    # 2026-08-24) — state_text swaps in "Passing Tech Alerts…" while the
    # helper is actually pressing.
    "techalerts": ("At Tech Alerts",
                   "Press a switch in the game window to carry on — this is "
                   "the machine's operator screen, not a fault."),
    # "Game running", not "In attract mode": the rig deliberately does not
    # tell attract from the operator menu or from a game in play (see
    # gamestate.sh), and calling a game you are PLAYING "attract" was the
    # misleading half of that honesty (David, 2026-08-24).
    "attract": ("Game running", "Attract loop, operator menu, or a game "
                                "in play."),
    # Kept: what status.sh emitted before it learned to say `attract`, so an
    # older rig against a newer app still reads as something rather than as a
    # bare word.  The rename happened because the old word was reached by a
    # test that had quietly stopped working - see gamestate.sh.
    "running": ("Game running", "Attract loop, operator menu, or a game "
                                "in play."),
}

#: Replaces the Tech Alerts hint while the rig's own auto-advance helper is
#: still working.  The default hint tells the user to press something; saying
#: that while something else is already pressing invites two operators fighting
#: over the same screen.
_ADVANCING_HINT = ("The game is checking its node boards and stops on its "
                   "Tech Alerts readout; the emulator waits for the bus to "
                   "finish bringing up, then presses past it to attract on "
                   "its own. Nothing to do here; scripted runs can set "
                   "PAD_AUTO_ATTRACT=0 to drive the boot by hand.")

#: Shown when the auto-advance helper ran out of presses and stopped.  It names
#: the service menu because that is the failure this cannot see: the menu opens
#: no video clip, so from the outside it reads exactly like Tech Alerts.
_GAVEUP_HINT = ("Auto-advance pressed Service Back several times and the "
                "screen did not change. If an earlier press DID take, the game "
                "is probably on the SERVICE MENU, which looks the same from "
                "out here. Click the game window and press Esc: from the menu "
                "it leaves toward attract, from Tech Alerts it clears them.")

#: Replaces the Tech Alerts hint when auto-advance stood down because Power
#: is "50 Hz mains, US machine" (PAD-173).  Its press used to land before the
#: game had measured the mains, and the game went to attract instead of
#: refusing.  The Guided Setup sentence is measured: the rig's saved machines
#: open it on every boot, and a locked game ignores its buttons there.
_MAINSLOCK_HINT = ("Power is set to 50 Hz mains with a US machine, and a US "
                   "game refuses to run on 50 Hz power: “This machine "
                   "will not operate in this country”. The emulator "
                   "leaves the game locked instead of pressing past it. Its "
                   "service buttons stop working, and on some games its "
                   "Guided Setup screen comes up over the message. To play, "
                   "set Power to 60 Hz mains or a European machine and Start "
                   "again.")

#: The token killgame.sh prints (WSL only) when leftovers survived everything
#: it can do from inside the VM - the measured case is a dead guest held as a
#: zombie by a WSL interop relay, which ignores SIGKILL from inside.  Stop
#: watches for it and offers the Windows-side cure, because without that the
#: wedge is a locked room: the leftovers keep ``procs`` nonzero, which keeps
#: the button on Stop (which kills nothing) and greys out "Restart WSL…"
#: (which reads nonzero procs as a live run it must not interrupt).  A user
#: met exactly that on 2026-08-09, with the answer sitting in the log pane.
_NEEDS_WSL_RESTART = "PAD_STOP_NEEDS_WSL_RESTART"

#: The token watch.sh prints when it cannot open the virtual playfield window
#: itself, with everything needed to open it from here.
#:
#: THE MACHINE THAT NEEDS IT.  The playfield is a WINDOWS process — this WSL
#: has no Tk of any kind — so watch.sh launches it through interop, and a user
#: reported on 2026-08-11 that his never appeared.  His ``/etc/wsl.conf`` has
#: ``[interop] enabled=false``, so his Linux cannot execute a Windows binary
#: at all: the window could not open itself, and the rig's only answer was to
#: print a command for him to type before every run.
#:
#: AND THE ASYMMETRY THAT FIXES IT.  Interop is LINUX → WINDOWS.  Windows →
#: Linux (``wsl.exe``) is untouched by that switch, so everything the window
#: does once it is up — reading ``dump/padled``, running ``swpoke.py``, asking
#: ``wslpath`` — keeps working.  Only the LAUNCH cannot cross.  PAD is already
#: standing on the far side: it is a Windows process running a Python with
#: pywebview (it is drawing its own window with it), so it opens the playfield
#: and watch.sh gets on with the run.
_PLAYFIELD_LAUNCH = "PAD_PLAYFIELD_WINDOWS_LAUNCH"

#: Why a first boot says "Copying card": the state label's hover tip and the
#: hint line under the status grid both carry this while a copy narrates
#: (item 78 follow-up — David asked for the why, the where, and the
#: only-once, next to the words).
_COPY_EXPLAIN = (
    "First boot of this card: it is being copied to the fast local cache "
    "(~/cardcache on the WSL disk), because reading it straight off the "
    "Windows drive makes every boot minutes-slow. This happens once per "
    "card build — later boots start from the copy in seconds, and "
    "rebuilding the image (a changed video, a new export) re-copies it "
    "once, replacing the old copy. The Cache… button beside Browse shows "
    "and manages what is kept.")

#: PAD-103: what the state says while the app is turning the user's edits into
#: an override set, before anything is launched.  Its own explanation rather
#: than the copy's, because it is a different wait for a different reason —
#: this one is the re-encode, and it is the price of not rebuilding the card.
_OVERRIDE_EXPLAIN = (
    "Your replaced assets are being patched into copies of the card files "
    "they live in, so the emulator can read them without a new card image "
    "being built. It is the same work a Write does, minus the copy of the "
    "card itself: a replaced sound has to be re-encoded, which is where the "
    "time goes. The set is kept: an unchanged one is reused where it "
    "stands, and a changed one is patched where it changed rather than "
    "built again, so a second run only costs what you have edited since.")

#: Item 127 / feature/emulate-prepare: the same badge while the Modes tab's
#: Try it is preparing its set.  Its own paragraph because the slow part is a
#: different one - not a re-encode of the user's sounds, but the staging of the
#: card's sound bank the first time a mode's own sound changes.
_MODES_EXPLAIN = (
    "Your modes are built exactly as Write would put them on a card, then the "
    "card starts with them. A mode's own sound is the slow part: the sound "
    "bank is staged and checked again the first time a sound changes, about "
    "a minute on Godzilla, and reused after that.")

#: PAD-121: what a multi-image card is told when it runs with the edits on
#: top.  DragonRR asked it exactly: "In a multiboot image - which image does
#: the replacement assets replace? How do you decide or is it both?"
#:
#: THE ANSWER IS ONE IMAGE, AND NOT A CHOSEN ONE.  Everything that writes a
#: Spike 2 card goes through ``engine._locate``, which walks the card's
#: PRIMARY ext partitions largest first and takes the first one holding an
#: ``image.bin`` with a game beside it.  On every layout ``mkmulticard.py``
#: writes that is p3 - the FIRST image, the one the card was built around;
#: the extras are logical partitions it never enumerates, or ``imgN``
#: directories its search reaches later (see ``plugins.stern.multiimage``,
#: PAD-122, which counts them).  The set built from that image is then bound
#: over whichever image the boot menu starts.  So it is said, on the run
#: where it can be wrong, rather than left for the user to work out from a
#: callout that did not change.
MULTI_IMAGE_NOTE = (
    "[emulate] this card carries a boot menu, and your edits were prepared "
    "from ONE image on it — the first game image on the card, which is the "
    "one every extract and write on this card uses. They are applied over "
    "whichever image you pick at the menu, so pick that one. To edit a "
    "different image, build it on its own first and rebuild the multi-boot "
    "card from the built image.")

#: Item 74: cardmount.sh narrates a first-boot copy one line every 2 s —
#: ``[card] copying <name>: 3121 / 7497 MB (41%)``.  Parsed off the drain so
#: the state label can show the copy instead of "Not running" while the guest
#: deliberately waits for it.  Groups: name, done-MB, total-MB, percent.
_CARD_COPY_RE = re.compile(
    r"^\[card\] copying (.+): (\d+) / (\d+) MB \((\d+)%\)$")


def card_copy_progress(line):
    """The state-label text for a card-copy progress line, or None.

    Pure, like :func:`playfield_launch`, and for the same reason: the format
    can be tested without a WSL, a Tk root or a 7 GB card.
    """
    m = _CARD_COPY_RE.match(line)
    if not m:
        return None
    name, done, total, pct = m.groups()
    return "Copying card: %s / %s MB (%s%%)" % (done, total, pct)


def parse_cache_list(text):
    """Parse ``cardmount.sh --cache-list`` into ``(entries, disk)`` (item 77).

    ``entries``: dicts of ``label / real_kb / apparent_kb / boot / src``,
    sorted by real size descending — the what-is-eating-my-disk order the
    dialog opens in.  ``disk``: ``(avail_kb, size_kb)`` or None.  Lines are
    tab-separated with the source LAST because labels and source paths may
    carry spaces.  Pure, like :func:`playfield_launch`, so the format is
    testable without a WSL or a 7 GB card.
    """
    entries, disk = [], None
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if parts[0] == "entry" and len(parts) >= 6:
            try:
                entries.append({
                    "label": parts[1],
                    "real_kb": int(parts[2]),
                    "apparent_kb": int(parts[3]),
                    "boot": int(parts[4]),
                    "src": "\t".join(parts[5:]),
                })
            except ValueError:
                continue
        elif parts[0] == "disk" and len(parts) >= 3:
            try:
                disk = (int(parts[1]), int(parts[2]))
            except ValueError:
                pass
    entries.sort(key=lambda e: e["real_kb"], reverse=True)
    return entries, disk


def human_size(kb):
    """KiB -> "6.3 GB" / "890 MB".  One decimal only where it earns it."""
    if kb >= 1048576:
        return "%.1f GB" % (kb / 1048576.0)
    return "%d MB" % round(kb / 1024.0)


def cache_boot_text(epoch):
    """The Last-booted cell: "never" for 0 (no sidecar yet), else local time."""
    if not epoch:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


# ----------------------------------------------------------------------
# PAD-103: running the user's own edits without rebuilding the card.
#
# The app builds an OVERRIDE SET - the card files an edit touches, patched,
# and nothing else (stern.engine.write_overrides) - and the rig binds them
# over the read-only card mount.  These three are the app's side of the
# policy: where a set is kept, and when the one that is there can be reused.
# Pure, like parse_cache_list and playfield_launch above and for the same
# reason: none of it needs a WSL, a card or a Tk root to be tested.
# ----------------------------------------------------------------------

def overrides_dir():
    """Where the override set is staged on THIS side (the rig copies it on).

    The host temp dir, under a ``spike2_`` name, because that is already where
    this plugin does its host-side build staging and ``core.host_temp`` knows
    the prefix - so the set shows up in the app's own "what is PAD leaving
    behind" list and can be deleted from there like any other scratch.  A
    STABLE name rather than a ``mkdtemp``: the whole point is that a set which
    is still current does not have to be built again.
    """
    return os.path.join(tempfile.gettempdir(), "spike2_overrides")


def assets_fingerprint(assets_dir):
    """``"<files> <newest-mtime>"`` for everything under *assets_dir*.

    Cheap on purpose - a stat walk, no hashing - because it runs on every
    Start and the folder is a whole extract (thousands of WAVs).  It is the
    "have the edits moved?" question, not the "what changed?" one; the engine
    answers that properly, against the .checksums.md5 baseline, when a set is
    actually built.

    Compared for EQUALITY rather than "is anything newer", because building a
    set writes back into the assets folder itself (the hash cache), so the
    recorded value has to be the one taken AFTER that write - and then a file
    restored from an older copy moves the fingerprint too, where a newest-wins
    test would call it unchanged.
    """
    newest, count = 0, 0
    for root, _dirs, files in os.walk(assets_dir):
        for name in files:
            count += 1
            try:
                m = os.stat(os.path.join(root, name)).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return "%d %.6f" % (count, newest)


def _is_card(rec, st, path):
    """Does a manifest's ``{path, size, mtime}`` name the card at *path*?"""
    return (os.path.normcase(str(rec.get("path") or ""))
            == os.path.normcase(os.path.abspath(path))
            and rec.get("size") == st.st_size
            and int(rec.get("mtime") or 0) == int(st.st_mtime))


def overrides_reason(manifest, card_path, assets_dir, fingerprint,
                     run_card=None):
    """Why the staged override set cannot be reused, or ``""`` if it can.

    A sentence rather than a bool: every one of these is worth saying out loud
    in the log, and "rebuilding your edits" with no reason is what makes a
    30-second wait look like the app doing nothing.

    *run_card* is the card the set is bound over, when that is not
    *card_path* (the one it is prepared from): the set's game program carries
    that card's own (PAD-172), so a set prepared to run on one card is not
    reused on another.  A set from before that was recorded ran on the card
    it came from.
    """
    if not manifest:
        return "there is no set staged yet"
    card = manifest.get("card") or {}
    try:
        st = os.stat(card_path)
    except OSError:
        return "the card image could not be read"
    if not _is_card(card, st, card_path):
        return "it was built from a different card image"
    if run_card is not None:
        try:
            run_st = os.stat(run_card)
        except OSError:
            return "the card image could not be read"
        if not _is_card(manifest.get("run_card") or card, run_st, run_card):
            return "it was prepared to run on a different card"
    if os.path.normcase(str(manifest.get("assets") or "")) \
            != os.path.normcase(os.path.abspath(assets_dir)):
        return "it was built from a different assets folder"
    if str(manifest.get("assets_fingerprint") or "") != fingerprint:
        return "your assets folder has changed since it was built"
    return ""


def preview_modes_reason(manifest, assets_dir, on=None):
    """Why a set of a project that HOLDS modes cannot be reused since the mode maker's
    preview switch changed (core/preview.py), or ``""``. The set records the switch it was
    built under (``modes_preview``, written only for such a project), and its files differ
    by it: on, the modes' screens and clips; off, none. A project without modes never
    rebuilds for this. *on* defaults to this run's switch."""
    if not manifest:
        return ""
    try:
        from ..plugins.stern import mode_write
        if not mode_write.held_modes(assets_dir):
            return ""
        if on is None:
            on = mode_write.preview_on()
    except Exception:                                   # noqa: BLE001
        return ""
    if bool(manifest.get("modes_preview")) == bool(on):
        return ""
    # neutral words: a copy without a code names no preview feature
    return ("a preview feature was switched %s since it was built (Settings > Preview "
            "features)" % ("on" if on else "off"))


def playfield_launch(line):
    """Parse a ``_PLAYFIELD_LAUNCH`` line into its fields, or None.

    ``key=value`` pairs, split on the KEYS rather than on whitespace: two of
    the values are paths (``\\\\wsl.localhost\\…``), and a path is entitled to
    contain a space even though this rig's own never has.

    Pure, and separate from the launching, so the format can be tested without
    a WSL, a Tk root or a game.
    """
    if not line or _PLAYFIELD_LAUNCH not in line:
        return None
    rest = line.split(_PLAYFIELD_LAUNCH, 1)[1].strip()
    out = {}
    for part in re.split(r"\s+(?=[a-z_]+=)", rest):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out if out.get("game") else None


def _which_on_path(name):
    """``shutil.which``, minus its dependence on ``sys.platform``.

    Same reason as :func:`windows_python`'s ntpath note: this function is
    reached from a Linux and a macOS CI runner, by tests that fake
    ``sys.platform`` to walk the Windows branch.  ``shutil.which`` answers a
    faked ``"win32"`` by dereferencing ``_winapi`` — which is ``None`` off
    Windows — and raises ``AttributeError`` from inside the standard library,
    so the whole Windows launch shape went untested on two of the three
    runners the moment this call appeared in it.

    Every name asked for here is already spelled with its extension, so
    PATHEXT never comes into it and a plain walk of PATH is what
    ``shutil.which`` would have done anyway.  Nothing changes on a real
    Windows box.
    """
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        if not d:
            continue
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
    return None


def windows_python(console=False):
    """The interpreter to run ``playfield.py`` with, on Windows.

    ``sys.executable`` IS THE ANSWER AND IS ALSO A TRAP, so it is not used
    bare.  The Windows app runs on the Python bundled beside it
    (``{app}\\python\\pythonw.exe`` — launcher.vbs starts it that way), and
    that interpreter has pywebview and Pillow, which is exactly what the
    playfield's web window needs (the Tk window it replaced wanted tkinter
    and Pillow from the same interpreter).  But in a FROZEN build ``sys.executable`` is the app's own
    .exe, and handing it a script path would start a second copy of PAD.

    So: prefer the windowed twin of whatever is running us (no console window
    beside the playfield), accept the running interpreter itself, and only
    then look for a Python on PATH.  None when there is nothing to run it
    with, and the caller says so rather than launching something wrong.

    ``console`` asks for ``python.exe`` instead, and the SOUND BRIDGE is why
    (PAD-95).  That one is a stdio program - WSL pipes the guest's PCM into it
    - and ``python.exe`` is also the spelling every other candidate in the
    rig's own search carries (``py -0p`` lists python.exe), so the path this
    hands the rig and the path the rig reports back are the same string.
    """
    # ntpath, NOT os.path, for the path arithmetic: this function reasons
    # about WINDOWS paths by contract (its one caller returns early off
    # Windows), and os.path is posixpath on the Linux and macOS CI runners,
    # where dirname(r"C:\Py\python.exe") is "" because a backslash is not a
    # separator there.  On Windows ntpath IS os.path, so this changes nothing
    # where the code runs and unbreaks the test everywhere it is tested.
    first, second = (("python.exe", "pythonw.exe") if console else
                     ("pythonw.exe", "python.exe"))
    cands = []
    exe = sys.executable or ""
    if exe and not getattr(sys, "frozen", False):
        base = ntpath.dirname(exe)
        cands += [ntpath.join(base, first), exe]
    elif exe:
        # Frozen: the bundled interpreter sits in `python\` beside the app.
        cands.append(ntpath.join(ntpath.dirname(exe), "python", first))
    for name in (first, second):
        found = _which_on_path(name)
        if found:
            cands.append(found)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def rig_win_python_env():
    """``("PAD_WINPYTHON=/mnt/c/…",)`` — PAD's own Python, for the rig.

    THE RIG CANNOT FIND THIS ONE BY ITSELF, and PAD-95 is what that costs.  It
    hunts for a Python the USER installed (the ``py`` launcher's list, then a
    few known directories); a PC with none is told there is no Windows Python
    for the sound to go through and sent to python.org — while a perfectly
    good interpreter sits in the same folder as the app printing the message.
    Every packaged Windows install ships one: ``{app}\\python\\python.exe``,
    an embeddable CPython with pip, which WSL runs straight off ``/mnt/c``
    like any other .exe.

    So the app says where it is, on every rig call.  ``PAD_WINPYTHON`` is the
    override ``padpath.sh`` has always read first, so nothing in the rig had to
    learn a new fact — and a hand-run script still gets the old search.

    Empty off Windows, and empty when there is nothing to name: an absent
    variable leaves the rig exactly as it was.
    """
    if sys.platform != "win32":
        return ()
    exe = windows_python(console=True)
    return ("PAD_WINPYTHON=" + _wsl_path(exe),) if exe else ()


def rig_dir():
    """Where the emulator rig lives.  Overridable so this is not welded to one
    machine's scratch directory."""
    return os.environ.get("PAD_EMU_DIR", DEFAULT_RIG_DIR)


def rig_available():
    """Whether the rig is present.  The tab stays visible when it is not and
    explains what is missing, rather than disappearing without a word."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, f))
               for f in ("watch.sh", "killgame.sh", "status.sh"))


#: Where Docker Desktop comes from when there is no Homebrew to ask.
DOCKER_URL = "https://www.docker.com/products/docker-desktop/"

#: How long to give the Docker CLI.  ``docker info`` with no daemon behind it
#: answers in about a second; the timeout is only so a wedged socket cannot
#: hang a background probe forever.
_DOCKER_PROBE_S = 12

#: Where a `docker` command lives on a Mac when this app's own PATH cannot see
#: it.  A GUI app launched from Finder inherits launchd's PATH -
#: /usr/bin:/bin:/usr/sbin:/sbin - and NOT ONE of these is on it, so a bare
#: ``["docker", "info"]`` is a PATH lookup that fails on machines where docker
#: is installed and working.  The same fact is already encoded elsewhere in
#: this codebase (MacExecutor._EXTRA_PATH, homebrew() below, the gpg candidate
#: list in plugins/bof/pipeline.py); the Docker probe was the one place that
#: still assumed a login shell's PATH.
DOCKER_DIRS = (
    "/usr/local/bin",                                  # Docker Desktop's own
                                                       # symlink; Intel Homebrew
    "/opt/homebrew/bin",                               # Apple Silicon Homebrew
    "/opt/local/bin",                                  # MacPorts
    "~/.docker/bin",                                   # Docker Desktop when it
                                                       # is told to keep out of
                                                       # /usr/local/bin
    "~/.rd/bin",                                       # Rancher Desktop
    "~/.orbstack/bin",                                 # OrbStack
    "/Applications/Docker.app/Contents/Resources/bin",  # Desktop's own copy,
                                                        # there even when the
                                                        # symlink was declined
)

#: The Mac apps that ship a Linux VM for the `docker` command to talk to.
#: Directories, not files: these are .app bundles.
DOCKER_ENGINE_APPS = (
    ("Docker Desktop", "/Applications/Docker.app"),
    ("OrbStack", "/Applications/OrbStack.app"),
    ("Rancher Desktop", "/Applications/Rancher Desktop.app"),
)


def which_tool(name, dirs=DOCKER_DIRS):
    """*name* as an absolute path, looking where a Mac actually keeps it.

    PATH FIRST, ALWAYS: someone who launched the app from a terminal, or who
    set PATH deliberately, has already answered this question and their answer
    wins.  ``dirs`` is only consulted when the inherited PATH has no answer at
    all, which for a Finder-launched .app is the normal case rather than the
    exception.

    ``isfile`` and not ``os.access(X_OK)``, matching :func:`homebrew` and the
    rest of this codebase's tool lookups: a file sitting in one of these
    directories under this name is the tool, and a permission problem is
    better reported by running it than by pretending it is not installed.
    """
    found = shutil.which(name)
    if found:
        return found
    for d in dirs:
        p = os.path.join(os.path.expanduser(d), name)
        if os.path.isfile(p):
            return p
    return None


def docker_cli():
    """The `docker` command on this machine, or None.

    ``PAD_DOCKER`` overrides, for the Mac that keeps it somewhere none of
    :data:`DOCKER_DIRS` names - and a wrong override answers None rather than
    silently falling back, because a support instruction that is quietly
    ignored is worse than one that fails.
    """
    override = (os.environ.get("PAD_DOCKER") or "").strip()
    if override:
        return override if os.path.isfile(override) else None
    return which_tool("docker")


def docker_engine():
    """What on THIS Mac can provide the daemon, as ``(label, kind, path)``,
    or None.

    macOS cannot run a Linux container itself.  ``docker`` is a client; the
    daemon lives in a Linux VM, and something has to ship that VM - Docker
    Desktop does, and so do OrbStack, Rancher Desktop and Colima.  A client
    with no engine behind it is therefore NOT "Docker is stopped", and it is
    the case a Mac reaches by installing a package manager's `docker`: MacPorts
    says of its own port that it "contains command line utilities for
    interacting with Docker, but not the core daemon".

    ``kind`` is how it starts: ``"app"`` is ``open -a``, ``"cli"`` is a command
    that has to be run and watched.
    """
    for label, app in DOCKER_ENGINE_APPS:
        if os.path.isdir(app):
            return (label, "app", app)
    colima = which_tool("colima")
    if colima:
        return ("Colima", "cli", colima)
    return None


def docker_state():
    """``ok`` / ``stopped`` / ``engineless`` / ``absent`` - macOS's answer to
    "can we emulate?".

    THE EMULATOR NEEDS LINUX, and macOS reaches it through a container (see
    ``rig_cmd``), so Docker is as much a prerequisite there as WSL is on
    Windows.  It was not treated like one: nothing on this tab checked for it,
    the manufacturer's prerequisite list does not carry it, and the only place
    it was ever named was the "rig not found" hint - which a Mac user never
    sees, because the rig SHIPS WITH THE APP and is therefore always found.  So
    the whole of "you need Docker" arrived as one line of padbox.sh's stderr,
    part way down the log pane, after Start appeared to work.

    Four answers rather than two, because the remedies are four different
    things: nothing installed is a download, installed-but-down is one click,
    and a CLIENT WITH NO ENGINE - the answer this app used to be unable to give
    - is a second install that is not Docker Desktop at all.  A Mac in that
    state was told "Docker Desktop is required" while `docker` sat on its disk,
    and clicking Start Docker on it opens an app that is not there.

    ``engineless`` is macOS-only by construction: everywhere else the daemon is
    local and "installed but not running" is the whole of the question.
    """
    cli = docker_cli()
    if not cli:
        return "absent"
    try:
        out = subprocess.run([cli, "info"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             timeout=_DOCKER_PROBE_S,
                             creationflags=_CREATE_FLAGS)
        if out.returncode == 0:
            return "ok"
    except FileNotFoundError:
        return "absent"
    except Exception:                                   # noqa: BLE001
        # A timeout is Docker Desktop still waking up, not an absent one - and
        # something has to be there to be slow, so it is not engineless either.
        return "stopped"
    if sys.platform != "darwin":
        return "stopped"
    return "stopped" if docker_engine() else "engineless"


def homebrew():
    """The `brew` binary, or None.  Homebrew installs itself in two places and
    is famously not on a GUI app's inherited PATH, so both are named."""
    for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.isfile(p):
            return p
    return None


def engine_setup_plan(cli=None):
    """What “Set up emulator…” will DO on this Mac, or None when it cannot.

    NOBODY IS SENT TO A TERMINAL.  The Windows half of this tab installs what
    the emulator needs at the press of a button, and a Mac that was handed a
    command to type instead was being asked to do the app's job - David,
    2026-08-19, on the first version of this fix.  So this returns the work
    itself, not advice: argv to run, and the sentences that describe it.

    Like :func:`setup_fix_steps`, the consent list and the work are ONE object,
    so what the dialog promises and what the button runs cannot drift apart.

    CHOSEN BY WHERE THE CLIENT CAME FROM, because that is the package manager
    already working on this Mac: a `docker` in /opt/local/bin came from
    MacPorts, whose own docker port points at colima for exactly this ("this
    port contains command line utilities for interacting with Docker, but not
    the core daemon"), and driving Homebrew on that machine would be a second
    package manager for a problem the first one already solves.

    Colima rather than Docker Desktop, and not as a preference: it installs
    without a browser, without a drag-to-Applications, and it still works on
    the macOS versions Docker Desktop has stopped supporting - which is the
    machine that reported this.  Docker Desktop stays one click away for
    anyone who wants the GUI (see ``_docker_download``).

    ``cli`` is the client this Mac already has; without one the plan installs
    that too, because colima ships the Linux machine and not the `docker`
    command.
    """
    port = which_tool("port", ("/opt/local/bin",))
    brew = homebrew()
    if cli and cli.startswith("/opt/local/") and port:
        mgr, tool, admin = "MacPorts", port, True
    elif brew:
        mgr, tool, admin = "Homebrew", brew, False
    elif port:
        mgr, tool, admin = "MacPorts", port, True
    else:
        return None
    packages = ["colima"] if cli else ["docker", "colima"]
    # THE PACKAGE NAMES ARE ARGV, NOT PROSE.  "install docker colima" is what
    # the machine needs; a person reads "the docker command" and "Colima", and
    # this is the one place the two spellings are tied to each other.
    label = " and ".join({"docker": "the docker command",
                          "colima": "Colima"}.get(p, p) for p in packages)
    # -N for MacPorts: no question this app cannot see gets asked half way
    # through an install it is driving.  Homebrew is NEVER run as root - it
    # refuses outright - which is also why `admin` is per-plan and not a
    # constant.
    install = ([tool, "-N", "install"] + packages if admin
               else [tool, "install"] + packages)
    steps = ["Install %s with %s. Nothing already on this Mac is changed or "
             "removed." % (label, mgr),
             "Start Colima, the Linux machine the docker command talks to. It "
             "runs in the background and takes a couple of minutes the first "
             "time, while it downloads its disk image."]
    if admin:
        steps.append("macOS will ask for your password once, in its own "
                     "dialog, because %s installs system-wide." % mgr)
    return {"manager": mgr, "packages": packages, "label": label,
            "admin": admin, "install": install, "steps": steps}


def parse_status(text):
    """Parse ``status.sh``'s ``key=value`` output into a dict.

    Split out of the panel so it can be tested without a Tk root — the state
    wording is the part most likely to be got wrong, and it is the part a user
    reads first.  The parsing itself now lives in :mod:`.._rig`, shared with
    the JJP panel; both rigs speak key=value for the same reason.
    """
    return _rig.parse_status(text)


def state_text(info):
    """(label, hint) for the rig's ``state=`` word.

    ``auto=`` is the number of auto-advance helpers still running, so a
    non-zero value at Tech Alerts means the rig is already dealing with it and
    the user should be told to wait rather than to press something.

    ``auto_result=gaveup`` is the case this used to hide.  The helper presses a
    fixed number of times and then exits either way; with only ``auto=`` to go
    on, "finished the job" and "gave up" both showed as the same unchanging
    "Waiting at Tech Alerts", and the two want opposite things from the human.
    """
    label, hint = _STATE_TEXT.get(info.get("state", "off"),
                                  (info.get("state", ""), ""))
    if info.get("state") == "techalerts":
        if info.get("auto", "0") != "0":
            # The helper is on the job - name the WORK (the node bus
            # bring-up, matching the footer's "Node boards" chip), not the
            # readout screen it ends on (David, 2026-08-24: with the chip
            # renamed, "Passing Tech Alerts" beside it was misleading).
            return "Bringing up node boards…", _ADVANCING_HINT
        if info.get("auto_result") == "gaveup":
            return "Stuck at Tech Alerts", _GAVEUP_HINT
        if info.get("auto_result") == "mainslock":
            # PAD-173: the refusal runs no light show, so the rig reads it as
            # Tech Alerts - and "press a switch to carry on" is the advice
            # that walks the game past the lock the user asked to see.
            return "Locked: US machine on 50 Hz", _MAINSLOCK_HINT
    return label, hint


def _wsl_path(win_path):
    """``c:\\repo\\tools\\spike2_emu`` -> ``/mnt/c/repo/tools/spike2_emu``.

    Delegates to :func:`.._rig.wsl_path`, which the JJP panel uses too.  Kept
    as a name here because three test files and several call sites import it,
    but there is now exactly ONE definition of how a Windows path is spelled
    for WSL - two panels each with their own copy is how ``alive.sh`` and
    ``killgame.sh`` came to disagree about what a running rig is.
    """
    return _rig.wsl_path(win_path)


#: WHICH LINUX THIS RIG TALKS TO.  The app can install a Linux of its own
#: (core/runtime.py) - pinned, built by us, and carrying this rig's whole
#: toolchain: the ARM cross compiler, qemu-user-static, ffmpeg, e2fsprogs,
#: fuse3, a static busybox and a criu that no Ubuntu packages.  When it is
#: installed every call below runs in THAT distro; when it is not, everything
#: behaves exactly as it did before, in the machine's default.
#:
#: EVERY wsl.exe HEAD IN THIS MODULE GOES THROUGH HERE.  There are six of them
#: and they answer questions about each other - which user the rig runs as,
#: where its home is, whether its binaries are built - so one of them asking a
#: different machine than the rest would produce answers that are individually
#: true and collectively nonsense.
def _wsl_head(root=False):
    return runtime.wsl_head(root=root) + ["-e"]


#: WHERE THIS RIG'S WORK GOES.  padpath.sh says "explicit PAD_HOME always
#: wins", so one entry moves the guest rootfs, the card cache and the
#: save-state slots onto the app's own data disk - which survives the runtime
#: being replaced, and which the user can delete in one action.
#:
#: EMPTY unless the rig is actually running in our runtime.  A machine using
#: its own distro keeps the paths it has always used: moving those would
#: strand work the user already has, for no benefit they asked for.
def _rig_env():
    d = runtime.distro_for("spike2")
    return rigdata.rig_env("spike2", bool(d) and rigdata.exists())


def rig_cmd(script, *args, env=()):
    """The command that runs one of the rig's scripts, on THIS platform.

    ONE PLACE THAT KNOWS, because there are six call sites and they were six
    copies of ``["wsl.exe", "-e", "bash", ...]``.  The rig is a Linux program,
    and the three platforms differ only in how Linux is reached:

    ============  ======================================================
    Linux         run it.  Nothing in between.
    Windows       through WSL, which is Linux.
    macOS         in a container, because ``qemu-user`` translates LINUX
                  syscalls and the chroot needs Linux namespaces - so
                  this is not a port that could be written, it is Linux
                  that has to be running somewhere.  ``docker/padbox.sh``
                  owns every detail of that and this only calls it.
    ============  ======================================================

    `env` is a list of ``NAME=value`` strings, applied with ``env`` so the
    values survive the hop without a shell re-parsing them - `wsl.exe` re-parses
    its arguments, and `$var` expands to nothing on that second pass.
    """
    if sys.platform == "darwin":
        # padbox.sh forwards the interesting variables into the container
        # itself, so they are set for IT rather than wrapped around it: `docker
        # run` takes its environment through -e, and an `env` prefix out here
        # would set them on the docker client and nowhere useful.
        box = os.path.join(rig_dir(), "docker", "padbox.sh")
        return ["/usr/bin/env"] + list(env) + ["bash", box, script] + \
               [str(a) for a in args]
    if sys.platform == "win32":
        head = _wsl_head()
        path = "%s/%s" % (_wsl_path(rig_dir()), script)
        # PAD'S OWN PYTHON RIDES ALONG ON EVERY CALL, because two different
        # scripts need it and neither can find it: setupcheck.sh reports
        # whether this PC has a Windows sound player, playaudio.sh uses one.
        # Cheap (two path lookups) and additive - the caller's own entries
        # follow it and win any argument.
        env = list(rig_win_python_env()) + _rig_env() + list(env)
    else:
        head = []
        path = os.path.join(rig_dir(), script)
    if env:
        head = head + ["env"] + list(env)
    return head + ["bash", path] + [str(a) for a in args]


#: How long the multi-boot probe gets.  It is a handful of debugfs reads on
#: the card's rootfs — measured at 0.03–0.35 s on this machine, including the
#: 16 GB images on the D: drive — so this bound is only so that a card on a
#: sleeping NAS cannot leave a worker thread parked for ever.
_MULTIBOOT_PROBE_S = 30


def multiboot_cmd(path):
    """The argv that asks the rig whether *path* boots into a MENU, or None
    when this machine cannot be asked.

    ``parts.py --multiboot`` is the ONE definition (see its docstring): the
    card's rootfs holds ``/usr/local/codeselect/codeselect`` and its
    ``images.conf`` names two or more images.  The tab does not re-implement
    any part of that test — it shells the same tool the rig itself asks, so
    the tickbox and the run can never disagree about a card.

    NOT ``rig_cmd``, which runs the rig's shell scripts: this is a python3
    program and the only thing the two would share is the ``wsl.exe -e``
    prefix.  macOS answers None deliberately — there the rig lives in a
    container whose filesystem is not this one, so the card's host path is
    not a path the probe could open, and the rig's own decision (watch.sh,
    inside the container) is left to speak for itself.
    """
    if sys.platform == "darwin":
        return None
    if sys.platform == "win32":
        return _wsl_head() + ["python3",
                "%s/parts.py" % _wsl_path(rig_dir()), "--multiboot",
                _wsl_path(path)]
    return ["python3", os.path.join(rig_dir(), "parts.py"), "--multiboot",
            path]


def parse_multiboot(text):
    """``('yes'|'no'|'unknown', why)`` out of ``parts.py --multiboot``'s line.

    Scanned line by line rather than parsed as a whole, for the reason
    :func:`parse_status` is: ``wsl.exe`` is entitled to prepend its own
    warnings ("your 131072x1 screen size is bogus") to the output, and one of
    those turning a yes into an unknown would silently switch the menu off.
    Anything else at all is 'unknown', which the caller treats as "leave the
    tickbox alone" — never as "no".
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("multiboot:"):
            continue
        state, _sep, why = line[len("multiboot:"):].strip().partition(" - ")
        state = state.strip().lower()
        if state in ("yes", "no", "unknown"):
            return state, why.strip()
    return "unknown", ""


def rig_cmd_root(script, *args):
    """The same script, as root.  WINDOWS ONLY, and that is not a limitation
    that was settled for - it is the only platform where it is honest.

    ``wsl -u root`` is uid 0 with NO PASSWORD, because the Windows side is what
    launches the distro; ``install_prerequisites.ps1`` has installed the WSL
    packages that way for several releases.  On a Linux desktop the equivalent
    is sudo, which wants a password that a GUI app has nowhere to ask for
    without becoming an invisible hang - so there the rig keeps printing the
    command instead, which is what ``ensurebuild.sh`` has always done.

    NOT ``rig_cmd(..., env=...)`` with a root flag bolted on: the normal path
    deliberately runs as the ordinary user (WSLg and the audio session belong
    to them), and the two must not be one call that a wrong argument could
    flip.
    """
    if sys.platform != "win32":
        raise RuntimeError("rig_cmd_root is WSL-only")
    root_env = _rig_env()
    return _wsl_head(root=True) + (["env"] + root_env if root_env else []) +         ["bash", "%s/%s" % (_wsl_path(rig_dir()), script)] +         [str(a) for a in args]


#: wsl_account()'s cache: [(user, home), probed].  One probe per app run is
#: plenty - the answer changes when the user reinstalls their distro, not
#: between clicks.
#: [(user, home), the distro it was probed in].  False means "never probed";
#: any other value is the distro name (or "" for the machine's default).
_WSL_ACCOUNT = [("", ""), False]

#: wsl_home()'s cache: [value, probed].  Its own, and not just a slice of the
#: one above, because it answers a NARROWER question (see wsl_home) - and
#: because pinning it is how the tests hand this module a home without a live
#: WSL.
#: [home, the distro it was probed in] - see wsl_account above.
_WSL_HOME = [None, False]


def wsl_account():
    """``(user, home)`` for the account ``wsl.exe`` logs into with no ``-u``:
    ``('david', '/home/david')`` on an ordinary distro, ``('root', '/root')``
    on one that never got a user of its own.

    THAT SECOND SHAPE IS A REAL MACHINE, not a broken one: a distro installed
    without its first-run setup logs everybody in as root, several of PAD's
    users have run on one for months, and the only sign of it in a log is
    that every ``~`` came out under /root.

    NO shell variables anywhere in the probe: ``wsl.exe`` re-parses its
    argument line and ``$HOME`` expands to empty on that second pass (the JJP
    executor learned that the hard way), so it is ``whoami`` + ``getent``,
    which carry no ``$`` at all.  ``('', '')`` when WSL does not answer at
    all; an account whose passwd row cannot be read keeps its name and loses
    only the home, because the name alone already tells the callers which
    machine they are on.

    NEVER ON THE UI THREAD - see :func:`wsl_home` for why.
    """
    # THE ANSWER BELONGS TO A DISTRO, NOT TO THE PROCESS.  This used to be
    # cached for the life of the app, which was true while there was only ever
    # one Linux to ask.  Now the app can install its own mid-session: probe the
    # Spike 2 tab once (caching the default distro's account), press Fix setup,
    # and every later run would be `wsl -d PAD-Runtime` carrying the OTHER
    # distro's user and home - a rig looking for its work in a directory that
    # belongs to nobody there.
    _here = runtime.distro_for("spike2") or ""
    if _WSL_ACCOUNT[1] == _here:
        return _WSL_ACCOUNT[0]
    _WSL_ACCOUNT[1] = _here
    user = home = ""
    try:
        u = subprocess.run(_wsl_head() + ["whoami"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=30, creationflags=_CREATE_FLAGS)
        user = u.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
    except Exception:                                   # noqa: BLE001
        user = ""
    if user:
        try:
            p = subprocess.run(_wsl_head() + ["getent", "passwd", user],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,
                               timeout=30, creationflags=_CREATE_FLAGS)
            row = p.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
            parts = row.split(":")
            if len(parts) >= 6 and parts[5].startswith("/"):
                home = parts[5]
        except Exception:                               # noqa: BLE001
            home = ""
    _WSL_ACCOUNT[0] = (user, home)
    return _WSL_ACCOUNT[0]


def wsl_home():
    """The DESKTOP user's home ('/home/david'), or None when there is no such
    user - a distro whose default account is root has none.

    The checkpointable launch below runs ``wsl -u root``, whose own HOME is
    /root - the wrong rootfs, the wrong logs, the wrong everything - so the
    desktop user's home is passed in explicitly, and this is where it comes
    from.  None therefore means "nothing to hand that launch", and every
    caller here reads it that way: the ordinary user launch instead.

    A step that MUST be root asks :func:`wsl_account` rather than this one -
    on a root-default distro root's own home is not a fallback, it is the
    right answer, and reading None as "WSL would not answer" is what stopped
    the Multi-boot tab's build dead on those machines (PAD-114).

    NEVER ON THE UI THREAD.  The first wsl.exe after a Windows reboot boots
    the whole WSL VM, so this probe's real worst case is not its 30 s
    timeouts, it is that boot - call it (and watch_cmd/kill_cmd, which call
    it) from a worker.  shutdown_sync is the one deliberate exception: app
    quit blocks by design, and it only runs while a run is up - so WSL is
    warm and the probe answers fast even when it is not already cached.
    """
    _here = runtime.distro_for("spike2") or ""
    if _WSL_HOME[1] == _here:
        return _WSL_HOME[0]
    _WSL_HOME[1] = _here
    user, home = wsl_account()
    if user and user != "root" and home:
        _WSL_HOME[0] = home
    return _WSL_HOME[0]


def watch_cmd(minutes, env, savestates=True):
    """The Start Emulator launch - and on Windows, when save states are
    enabled, it is the CHECKPOINTABLE one (item 13): ``wsl -u root`` with
    ``PAD_PIVOT=1`` and the desktop user's HOME.

    ``savestates=False`` is the tab's opt-out (the default in the UI): the
    plain user launch, the shape this tab always had before item 13.  It
    cannot be checkpointed, and watch.sh therefore starts the playfield
    without its Save/Load state controls - a run with no save states shows
    no buttons that could only ever refuse.

    This module's old rule was "never root - it breaks WSLg and audio", and
    that stopped being true when watch.sh learned the drop dance: a root
    launch boots the GUEST as root (which is what lets criu checkpoint it -
    an unprivileged userns forces setgroups off and restore dies there) and
    drops every helper back to the desktop user, whose WSLg and audio
    session they need.  Verified live across save -> load -> repeat load.
    Without the pivot boot, the playfield's Save state button can only ever
    answer "this run is not checkpointable", which is exactly what David's
    first real press got.

    Falls back to the ordinary user launch when the home probe fails, so a
    broken probe degrades to what this tab always did - no save states,
    everything else identical - rather than to a root run pointed at
    /root/spike2root.
    """
    if savestates and sys.platform == "win32":
        home = wsl_home()
        if home:
            # PAD_WINPYTHON too, and this branch has to say it itself: the
            # checkpointable launch is built here rather than by rig_cmd, and
            # a run started without it is a run whose sound quietly takes the
            # WSLg path (PAD-95).
            return (_wsl_head(root=True) + ["env",
                     "HOME=" + home, "PAD_PIVOT=1"] + _rig_env()
                    + list(rig_win_python_env()) + list(env)
                    + ["bash", "%s/watch.sh" % _wsl_path(rig_dir()),
                       str(minutes)])
    return rig_cmd("watch.sh", minutes, env=env)


def kill_cmd():
    """killgame.sh, as ROOT on Windows, because the guest may be root's.

    A PAD_PIVOT guest is a root process; the ordinary user's pkill reports
    success and kills nothing (the same lie the restored-guest teardown told
    once already), while root's kill reaches both kinds.  The desktop HOME
    rides along so padpath resolves the right rootfs.  Everywhere else, and
    when the home probe fails, the ordinary call - which is right for the
    runs it can see.
    """
    if sys.platform == "win32":
        home = wsl_home()
        if home:
            return _wsl_head(root=True) + ["env", "HOME=" + home] + _rig_env() + [
                    "bash", "%s/killgame.sh" % _wsl_path(rig_dir())]
    return rig_cmd("killgame.sh")


def load_cmd(slot):
    """loadgame.sh as ROOT with the desktop HOME — the same shape as
    kill_cmd, for the same reasons: a save-state load is a criu restore of
    a root guest, and padpath must resolve the desktop user's rootfs.
    PAD_RESTORE_KILL clears whatever guest is running (the restored one
    takes its place)."""
    if sys.platform == "win32":
        home = wsl_home()
        if home:
            return _wsl_head(root=True) + ["env", "HOME=" + home] + _rig_env() + [
                    "PAD_RESTORE_KILL=1", "bash",
                    "%s/loadgame.sh" % _wsl_path(rig_dir()), str(slot)]
    return rig_cmd("loadgame.sh", slot, env=("PAD_RESTORE_KILL=1",))


#: What the emulator needs BEYOND the rig itself, in the order a run meets
#: them: probe key (from setupcheck.sh) -> package, and what it is for.
#:
#: The tool is what is probed, because that is the fact; the package name is
#: only how Debian spells it.  Same six as the Stern section of
#: install_prerequisites.ps1 - that installer is where a user who never opens
#: this tab still gets them.
#:
#: THE NATIVE COMPILER WAS MISSING FROM THIS LIST FOR FIVE RELEASES, and a
#: machine can pass every other line here without it: the rig builds TWO
#: things, the hardware shim (ARM, cross compiled) and the renderer (native),
#: and only the cross compiler was ever asked about.  A user on 2026-08-08 had
#: the ARM one, watched the shim build, and then met
#:
#:     [build] the GL renderer is not built, and there is no gcc here
#:
#: half a minute into a run that this tab had said nothing about.  It is two
#: apt names for one capability because gcc only RECOMMENDS its headers.
#:
#: AND THEN THE DECODER, which is the same omission with a worse symptom.  Every
#: other line here builds or mounts something, so missing one ENDS the run and
#: says why; missing ffmpeg lets the run succeed completely - guest up, window
#: open, renderer at 59 fps - and simply shows black, because the picture and
#: the sound are both decoded by it out here (the game's gstreamer-0.10 has no
#: software H.264 element).  A user on 2026-08-08 sat in front of that window
#: with a log repeating `No such file or directory: 'ffmpeg'` a hundred times a
#: second while this tab said nothing and the prerequisite strip said OK - that
#: strip's ffmpeg is the WINDOWS one, which the app bundles, and this is Linux's.
_SETUP_TOOLS = (
    ("qemu", "qemu-user-static",
     "runs the machine's own 32-bit ARM game binary"),
    ("armgcc", "gcc-arm-linux-gnueabihf",
     "builds the hardware shim the game runs against"),
    ("nativecc", "gcc libc6-dev",
     "builds the renderer that draws the game's picture on this PC"),
    ("debugfs", "e2fsprogs",
     "builds the guest filesystem out of a card image, without root"),
    ("fuse", "fuse3",
     "mounts a card read only, so a title runs without extracting 6 GB"),
    ("ffmpeg", "ffmpeg",
     "decodes the game's video and sound, which it cannot decode itself"),
)

#: WHAT A FEATURE NEEDS, WHICH IS NOT WHAT THE EMULATOR NEEDS.  Same shape as
#: _SETUP_TOOLS and probed by the same setupcheck.sh loop, but kept apart
#: because missing one of these does not stop a run - and a notice that says
#: "this PC cannot run the emulator" over a machine that runs it perfectly is
#: the same wrong-accusation fault this file guards against everywhere else.
#:
#: THE FAULT THAT PUT IT HERE.  v0.126.0 made every Start a checkpointable
#: (PAD_PIVOT) boot so the save-state controls could simply be on.  That boot
#: needs a native static busybox, no machine has one by default, it was on no
#: prerequisite list at all - and run_game.sh's answer to a pivot it cannot do
#: was to stop.  So the release that added save states took the WHOLE emulator
#: away from anyone without busybox-static, which is how a user reported it on
#: 2026-08-11: two titles that had run before, no window, and
#:
#:     [run] PAD_PIVOT needs a STATIC busybox at /bin/busybox
#:     [watch] the game never started.
#:
#: watch.sh now withdraws the request and runs the ordinary boot instead, so
#: the cost is the feature.  This list is how the user gets told that BEFORE
#: the save slots turn out to do nothing, and how “Set up emulator…” is given
#: something to install.
#: THE FOURTH FIELD IS HOW IT IS GOT, and it exists because the second of
#: these cannot be got the way the first is.  ``apt`` means what it says;
#: ``build`` means no Ubuntu publishes the thing at all and getcriu.sh
#: compiles it from source.  Without the distinction the consent dialog says
#: "Install in WSL: criu", which is a promise apt cannot keep: ``apt-cache
#: policy criu`` on 24.04 prints an EMPTY version table, and naming it on an
#: install line would fail the packages beside it too.
#:
#: THE FAULT THAT PUT CRIU HERE is the busybox one, one layer down. PAD-53
#: made a missing busybox-static cost only the feature - but a machine that
#: then installed busybox-static STILL had no save states, because criu was a
#: hard-coded ``/var/tmp/criubuild/criu/criu/criu`` in eight rig scripts: one
#: developer's hand-built binary, on one machine. Everyone else got the
#: checkpointable boot, the Save and Load buttons, and a failure naming a
#: directory they had never heard of. Both halves are probed now, and both
#: are obtainable.
#: THE FIFTH FIELD IS WHICH FEATURE, and it is new because there are now two
#: of them.  Everything here used to cost save states, so the notice could
#: name that feature in its own text; the boot menu program's `make` costs
#: something else entirely, and "Save states need: make" over a machine whose
#: save states are fine would be a false sentence of exactly the kind this
#: file is built to avoid.  The rows are GROUPED by this and each group says
#: its own name (see :func:`setup_extra_groups`).
_SETUP_OPTIONAL = (
    ("busybox", "busybox-static",
     "save states: the guest is booted in the one shape that can be frozen "
     "and reloaded, and that shape needs a static busybox", "apt",
     "Save states"),
    ("criu", "criu",
     "save states: this is the program that freezes the running game and "
     "thaws it again, and no Ubuntu publishes it — PAD builds it", "build",
     "Save states"),
    # ★ PAD-126.  The menu program a multi-boot card boots into is compiled
    # by codeselect/Makefile (buildselect.sh calls `make`, because the
    # hand-built-sysroot recipe belongs in one file), and `make` is not a
    # compiler - so no list here, in setupcheck.sh or in either installer had
    # ever named it, while every machine that has built anything else happens
    # to have one.  A user's WSL did not, and pressing Build on the Multi-boot
    # tab answered him with the shell's own words from inside a script he had
    # never run: `buildselect.sh: line 78: make: command not found`.  His
    # emulator was and is perfect, which is why this is here and not above.
    ("make", "make",
     "multi-boot cards: the boot menu the card starts up into is a program, "
     "and this is what builds it", "apt",
     "Multi-boot cards"),
)

#: OF THOSE FEATURES, THE ONES ONLY A WSL RUN EVER WANTS.  ``watch_cmd`` asks
#: for the checkpointable boot on Windows and nowhere else, so a Linux
#: desktop's Start never wants a static busybox or a criu - and naming a
#: package that machine's runs would never use is a wrong accusation.  Card
#: building is not like that: the Multi-boot tab builds its menu program the
#: same way on every desktop, so the feature added by PAD-126 is deliberately
#: NOT here.
_WSL_ONLY_FEATURES = ("Save states",)

#: How long to give the setup probe.  It is five `command -v`s, one small
#: compile and a read of /proc, so it answers in well under a second on a warm
#: WSL - the timeout is entirely for a COLD one, where `wsl.exe` has to boot
#: the distro first.
_SETUP_PROBE_S = 90

#: How many drain passes (250 ms each) the setup probe gets before the tab
#: says WSL itself is booting.  A warm WSL answers inside one pass, so the
#: message never flashes on an ordinary start; a cold one - the first wsl.exe
#: after a Windows reboot boots the whole VM - takes tens of seconds, and a
#: tab that says nothing for that long reads as a broken app.  David read it
#: exactly that way on 2026-08-09.
_WSL_BOOT_TICKS = 4

#: What the tab says while that boot runs.  It names the wait AND its bound,
#: because "Starting WSL…" alone invites force-quitting at the 30 s mark.
_WSL_BOOT_TEXT = ("Starting WSL — the first start after a Windows reboot can "
                  "take a minute. The app stays usable, and this finishes on "
                  "its own.")


def setup_state():
    """What this machine still needs before it can emulate, as setupcheck.sh's
    facts - or None when the question could not be asked at all.

    None IS NOT "everything is fine", and no caller may read it that way: a
    machine with no WSL installed answers that way too, and so does one where
    the probe timed out.  Claiming a fault on no evidence is how a prerequisite
    notice ends up in front of someone whose machine is perfect.

    macOS is excluded because it emulates in a container that already carries
    every one of these (docker/Dockerfile installs them at build time); there
    the prerequisite is Docker itself, which ``docker_state`` owns.
    """
    if sys.platform == "darwin" or not rig_available():
        return None
    try:
        out = subprocess.run(rig_cmd("setupcheck.sh"), stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,
                             timeout=_SETUP_PROBE_S,
                             creationflags=_CREATE_FLAGS)
    except Exception:                                       # noqa: BLE001
        return None                 # no WSL, no bash, or it never came back
    if out.returncode != 0:
        return None
    # parse_status, not a second parser: setupcheck.sh emits the same key=value
    # shape as status.sh, and that function already survives the warnings
    # wsl.exe is entitled to prepend to stdout.
    facts = parse_status(out.stdout.decode("utf-8", "replace"))
    return facts or None


def setup_summary(facts):
    """``(missing, binfmt)`` - the two things the notice is built from.

    Pure, so the wording tests do not need a WSL or a Tk root.
    """
    if not facts:
        return [], "1"
    missing = [(_apt_name(facts, key, pkg), why)
               for key, pkg, why in _SETUP_TOOLS if facts.get(key) == "0"]
    return missing, facts.get("binfmt", "1")


def _apt_name(facts, key, pkg):
    """The package as THIS machine's apt names it.

    ★ PAD-139.  The tables here spell qemu-user-static, and on Ubuntu 26.04
    that is a virtual name apt refuses: qemu-user-binfmt carries the static
    interpreter there.  setupcheck.sh asks apt and says so as ``pkg_<key>``,
    and every list, consent line and command in this module is built from the
    answer - so the name on the tab is the one the button, and a user typing
    the printed command, will actually get.  Absent on every other machine
    and on an older rig, where the table's spelling stands.
    """
    return (facts or {}).get("pkg_" + key) or pkg


def setup_extras(facts):
    """The missing packages that cost a FEATURE rather than the emulator.

    Absent facts accuse nobody, the same as everywhere else here: an older rig
    emits no ``busybox`` line, and silence is not a missing package.

    ASKED ONLY WHERE THE FEATURE IS.  ``watch_cmd`` requests the checkpointable
    boot on Windows and nowhere else, so a Linux desktop's Start never wants a
    static busybox at all - and a notice about a package that machine's runs
    would never use is the same wrong accusation as any other.  Decided from
    the rig's own ``iswsl`` fact rather than from sys.platform, so the answer
    is about the machine the run happens on.

    PER FEATURE, THOUGH, not for the whole list: that gate belongs to the
    checkpointable boot, and a Linux desktop builds a multi-boot card's menu
    program exactly as Windows does (_WSL_ONLY_FEATURES).
    """
    return [(pkg, why) for _feat, pkg, why in _setup_optional_rows(facts)]


def _setup_optional_rows(facts):
    """``(feature, package, why)`` for every extra this machine is missing.

    The one place the ``iswsl`` gate and the "absent keys accuse nobody" rule
    are applied to this list; everything else here is a view of it.
    """
    if not facts:
        return []
    wsl = facts.get("iswsl") != "0"
    return [(feat, _apt_name(facts, key, pkg), why)
            for key, pkg, why, _how, feat in _SETUP_OPTIONAL
            if facts.get(key) == "0"
            and (wsl or feat not in _WSL_ONLY_FEATURES)]


def _and_list(names):
    """The feature names in one sentence: "Save states", "Save states and
    multi-boot cards".  Only the first keeps its capital, because the rest are
    mid-sentence by then."""
    names = [n if i == 0 else n[:1].lower() + n[1:]
             for i, n in enumerate(names)]
    if len(names) < 3:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def setup_extra_groups(facts):
    """The same rows as :func:`setup_extras`, gathered under their feature:
    ``[("Save states", [(pkg, why), …]), …]``, in _SETUP_OPTIONAL's order.

    The notice is written from this rather than from the flat list because
    what a missing package COSTS is the whole point of listing it apart from
    the six that stop a run - and with two features on the list, one heading
    would have to be wrong about one of them.
    """
    groups = []
    for feat, pkg, why in _setup_optional_rows(facts):
        for name, rows in groups:
            if name == feat:
                rows.append((pkg, why))
                break
        else:
            groups.append((feat, [(pkg, why)]))
    return groups


def setup_built(facts):
    """Of those, the ones apt cannot supply at all — PAD compiles them.

    Split out because the two are different acts and the consent dialog has to
    say which is which: ``apt-get install busybox-static`` is seconds and a
    package, ``getcriu.sh`` is a source download and a three-minute build.
    Folding the second into "Install in WSL: …" would make that dialog a
    consent to something it did not describe — and would name a package
    ``apt-get install`` cannot resolve, which fails the packages beside it.
    """
    built = {pkg for _key, pkg, _why, how, _feat in _SETUP_OPTIONAL
             if how == "build"}
    return [(pkg, why) for pkg, why in setup_extras(facts) if pkg in built]


def setup_unavailable(facts):
    """The missing packages apt cannot install on this machine at all.

    ``setupcheck.sh``'s ``nocand``, which is a fact about the machine's
    package SOURCES rather than about the machine's tools.  Older rigs do not
    emit it, and an absent key means "nothing known against them" - never
    "all of them", which would put a wrong accusation on a working PC.
    """
    return (facts or {}).get("nocand", "").split()


#: Where to send someone whose own WSL distro cannot supply a package.  An
#: LTS, and the one the rig is developed against, so it is a recommendation
#: with evidence behind it rather than "try something newer" - which is what
#: the old wording amounted to, in front of a tester already on the newest.
#: setupfix.sh names the same one in the log; a test holds the two together.
#: Defined in core.prereqs, which hands out the same name when a distro has
#: stopped starting altogether (PAD-113) - one constant, so the two pages of
#: the app cannot send one user to two different Ubuntus.
KNOWN_GOOD_DISTRO = prereqs.KNOWN_GOOD_DISTRO

#: The same release, as a user reads it.  One constant, two spellings, so the
#: sentence and the command can never name different Ubuntus.
FALLBACK_RELEASE = KNOWN_GOOD_DISTRO.split("-", 1)[1]


def setup_fetchable(facts):
    """The unavailable packages the rig will go and GET rather than give up on.

    ``setupcheck.sh``'s ``xrel``: a package this release does not publish, but
    which depends on nothing and so installs cleanly out of another Ubuntu's
    archive.  Exactly one qualifies today (qemu-user-static, a static-pie
    interpreter with an empty Depends), and setupfix.sh re-reads the
    downloaded file's control before it installs it — this is what the tab is
    allowed to PROMISE, not what the rig is allowed to do.

    Absent on an older rig, and absent means "none", which is the safe way for
    a promise to be wrong.
    """
    return (facts or {}).get("xrel", "").split()


def setup_fixable(facts):
    """Can “Set up emulator…” actually change anything on this machine?

    A BUTTON THAT CANNOT IS WORSE THAN NO BUTTON.  A tester pressed this one
    twice against a package apt had no version of, and both times the tab had
    promised, underneath the sentence saying the package could not be
    installed, that pressing it would install the package.

    Unknown is yes, like everywhere else here: an older rig that never emitted
    ``nocand`` must not have its silence read as "nothing works".
    """
    if not facts:
        return True
    # NOTHING TO DO IS NOT SOMETHING TO PRESS, and this became reachable with
    # setup_env_faults: the notice now appears for machines whose packages are
    # all present (a root login spoils the picture on a fully installed PC),
    # and without this the button would appear under it offering to install
    # nothing.  Single-sourced against the consent list rather than re-deciding
    # it here - if setupfix.sh has no step to take, there is no button.
    if not setup_fix_steps(facts):
        return False
    if facts.get("universe") == "0":
        return True             # turning universe on IS the repair
    unavailable = set(setup_unavailable(facts)) - set(setup_fetchable(facts))
    if not unavailable:
        return True             # nothing left that cannot be got somehow
    missing, binfmt = setup_summary(facts)
    # Extras count here: the button installs them too, so a machine whose only
    # installable package is a save-state one still has something to press.
    if any(pkg not in unavailable
           for pkg, _ in missing + setup_extras(facts)):
        return True             # some of them still install
    # Nothing installable left.  Switching a handler that is merely off back
    # on is the one repair that needs no package.
    return binfmt == "disabled"


def setup_ok(facts):
    """Can this machine emulate?  Unknown counts as yes - see setup_state."""
    missing, binfmt = setup_summary(facts)
    return not missing and binfmt == "1"


def same_windows_python(a, b):
    """Are these two paths the same interpreter, twin spelling and all?

    ``python.exe`` and ``pythonw.exe`` in one folder are ONE install with two
    front doors - the second is the GUI-subsystem build, which is what the
    playfield window is opened with so no console sits beside it for the whole
    run.  So ``padpy`` names ``…\\python\\python.exe`` and ``pfpy`` names
    ``…\\python\\pythonw.exe`` for the very same bundled Python, and a plain
    string compare calls PAD's own interpreter somebody else's.

    Case-insensitive because these are Windows paths and the rig gets them from
    ``wslpath``, which spells the drive letter however the mount table does.
    """
    def norm(p):
        return (p or "").strip().lower().replace("pythonw.exe", "python.exe")

    return bool(norm(a)) and norm(a) == norm(b)


def setup_env_faults(facts):
    """What this WSL will SPOIL, even though the emulator can start on it.

    A different class from everything above, and the class that cost PAD-63.
    The package facts answer "can a 32-bit ARM binary execute here"; a machine
    can pass every one of them and still show a black window, no window, or
    play through the damaged audio hop.  Nothing asked, so the tab said nothing
    and the user found out by running it and reading a log.

    Returns ``[(what is wrong, what to do), ...]`` - pure, so the wording is
    testable without a WSL or a Tk root, like every other notice part here.

    NONE OF IT IS FIXABLE BY THE BUTTON, which is why it is a separate list:
    three of the four are WSL settings that belong to the user.  The notice
    carries the route out instead, the same shape ``setup_fixable`` already
    uses for a package apt cannot supply.

    ABSENT KEYS ACCUSE NOBODY, as everywhere else here: an older rig emits none
    of these lines, and silence is not a fault.
    """
    facts = facts or {}
    out = []
    if facts.get("user") == "root":
        out.append((
            "This WSL logs in as root, so the game window will open and stay "
            "BLACK. Everything else works — sound, switches, the playfield.",
            "Give the distro an ordinary user account, make it the default, "
            "and restart WSL."))
    if facts.get("display") in ("none", "nosocket"):
        out.append((
            "WSLg is not reachable from this distro, so there will be no game "
            "window at all.",
            "Restart WSL. If it comes back, GUI apps are switched off for this "
            "PC in %USERPROFILE%\\.wslconfig."))
    if facts.get("interop") == "0":
        out.append((
            "This WSL cannot start Windows programs, so the playfield window "
            "has to be opened from here and the sound takes its poorer route.",
            "Usually systemd dropping the interop registration at boot. In a "
            "Windows terminal:\n     wsl --update"))
    elif facts.get("winaudio") == "0":
        # ONLY WHEN INTEROP WORKS.  Every candidate interpreter is a Windows
        # .exe, so a distro that cannot start Windows programs answers "no
        # Windows Python" however many are installed - and telling that user to
        # install one more is advice addressed to the wrong fault.  It was in a
        # reply draft on 2026-08-12 before this branch existed.
        #
        # ...AND WHICH OF THE TWO FAULTS IT IS (PAD-94).  "No Windows Python
        # with sounddevice" describes two machines at once - one with no
        # Python on it at all, one with a Python that is missing a package -
        # and the user who reported this had the second.  He ran the command,
        # pip installed it, and the tab went on saying no, because the rig's
        # search had never looked in the directory his interpreter was in
        # (pad_win_pythons, which asks the `py` launcher now).  This NAMES what
        # that search found, so the tab and the machine cannot disagree in
        # silence again.
        #
        # ...AND WHOSE PYTHON IT IS (PAD-95).  The reporter ran the command
        # this said and his terminal answered that `py` is not a program on
        # his PC - it is an optional tick in the Windows installer, and he had
        # never installed a Python at all.  Meanwhile PAD ships one: every
        # packaged Windows install carries an embeddable CPython with pip
        # beside the app, which is the interpreter the rig is now handed
        # (rig_win_python_env) and the one this normally names.  When it is
        # ours the answer is a menu entry in this very app - no terminal, no
        # python.org, nothing typed - so say that instead of a command.
        where = facts.get("winpy", "").strip()
        ours = facts.get("padpy", "").strip()
        if where and where.lower() == ours.lower():
            out.append((
                "PAD's own Python has no sounddevice, so the sound goes "
                "through WSLg's audio, which is measurably damaged.",
                "Nothing to type. Open the gear menu (top right), "
                "Prerequisites, “Install / repair prerequisites…”, and "
                "tick Stern Pinball."))
        elif where:
            # A PYTHON OF THE USER'S OWN, AND ITS PATH IS NOT A COMMAND.
            # PowerShell reads a quoted path in the first word as a STRING and
            # prints it, and the paths that need quoting are exactly the
            # `C:\Program Files` ones this ticket's predecessor went looking
            # for.  cd there and run it from the folder: two lines that mean
            # the same thing in PowerShell and in cmd.  (Same class of trap as
            # PAD-94's backticks: what is on this label is what gets pasted.)
            folder, sep, exe = where.rpartition("\\")
            said = ("     cd \"%s\"\n     .\\%s" % (folder, exe) if sep
                    else "     %s" % where)
            out.append((
                "The Windows Python at %s has no sounddevice, so the sound "
                "goes through WSLg's audio, which is measurably damaged."
                % where,
                "In a Windows terminal, once:\n"
                "%s -m pip install --user sounddevice" % said))
        else:
            out.append((
                "There is no Windows Python for the sound to go through, so "
                "it takes WSLg's audio instead, which is measurably damaged.",
                "Install Python for Windows from python.org, ticking "
                "“Add python.exe to PATH”, then in a Windows "
                "terminal, once:\n"
                "     python -m pip install --user sounddevice"))
    # ★ PAD-99: AND THE PLAYFIELD WINDOW HAS ITS OWN WINDOWS PYTHON.
    #
    # A SEPARATE `if`, not another arm of the chain above: a machine can be
    # missing sounddevice AND Pillow, and they are two different repairs.
    # Suppressed when interop is off only because that branch already covers
    # the same window from one cause further up - with no way to start a
    # Windows program there is nothing for this to be about.
    #
    # THE FAULT IT NAMES.  The window is a Windows process: a web page in
    # pywebview's own window (tools/spike2_emu/pfweb.py).  Any Windows Python
    # can still show it - without pywebview it opens as an Edge app window -
    # so only NO Windows Python at all means no playfield; a Python without
    # pywebview gets a note saying where the window will be instead.  (PAD-99
    # was the Tk window's version: a python.org install with tkinter and no
    # Pillow opened nothing, silently.)
    if facts.get("interop") != "0" and facts.get("winpf") == "0":
        pf_where = facts.get("pfpy", "").strip()
        pf_ours = facts.get("padpy", "").strip()
        if same_windows_python(pf_where, pf_ours):
            out.append((
                "PAD's own Python is missing pywebview or Pillow, so the "
                "virtual playfield opens in an Edge window instead of its own.",
                "Reinstall PAD over the top of this one — its installer puts "
                "both into the Python it ships."))
        elif pf_where:
            # THE SAME TWO TRAPS AS THE SOUND ADVICE ABOVE, both of them:
            # a quoted path is a STRING in PowerShell and not a command, so cd
            # there and run it from the folder - and the interpreter NAMED here
            # is the windowed one (pythonw.exe), which has no console to print
            # pip's own output to.  Type the console twin.
            folder, sep, exe = pf_where.rpartition("\\")
            exe = exe.replace("pythonw.exe", "python.exe")
            said = ("     cd \"%s\"\n     .\\%s" % (folder, exe) if sep
                    else "     %s" % exe)
            out.append((
                "The Windows Python at %s has no pywebview or Pillow, so the "
                "virtual playfield opens in an Edge window instead of its "
                "own." % pf_where,
                "For its own window, in a Windows terminal, once:\n"
                "%s -m pip install --user pywebview Pillow" % said))
        else:
            out.append((
                "There is no Windows Python here that can draw the virtual "
                "playfield window, so no playfield will open.",
                "Install Python for Windows from python.org, ticking "
                "“Add python.exe to PATH”, then in a Windows "
                "terminal, once:\n"
                "     python -m pip install --user pywebview Pillow"))
    return out


def setup_report(facts):
    """The Check button's answer, one line per fact, for the log pane.

    THE POINT IS THAT IT ALWAYS SAYS SOMETHING.  The notice speaks only when
    something is wrong, which makes silence ambiguous between "checked, fine"
    and "never asked" - and leaves a user with a black window nothing to press
    and nothing to send.  This is the thing to ask someone for instead of a
    log: every fact the rig has about their machine, in one paste.
    """
    if not facts:
        return ["setup check: no answer from WSL — it may not be installed, "
                "or the probe timed out."]
    missing, binfmt = setup_summary(facts)
    yes_no = lambda k, y, n: y if facts.get(k) == "1" else (      # noqa: E731
        n if facts.get(k) == "0" else "unknown")
    lines = ["setup check:"]
    lines.append("  packages: " + (", ".join(p for p, _ in missing) + " MISSING"
                                   if missing else "all present"))
    extras = setup_extras(facts)
    if extras:
        lines.append("  save states: %s MISSING"
                     % ", ".join(p for p, _ in extras))
    lines.append("  32-bit ARM handler: "
                 + {"1": "registered", "0": "NOT REGISTERED",
                    "disabled": "registered but SWITCHED OFF"}.get(binfmt,
                                                                   binfmt))
    if facts.get("iswsl") == "1":
        lines.append("  survives a WSL restart: "
                     + yes_no("wslconf", "yes", "NO — systemd is off"))
        lines.append("  logs in as: %s%s"
                     % (facts.get("user", "unknown"),
                        "  <- the picture will be black"
                        if facts.get("user") == "root" else ""))
        lines.append("  can start Windows programs: "
                     + yes_no("interop", "yes", "NO"))
        # NAMED, not just "found", for the reason the Mac's report names its
        # docker: this is the paste that settles a disagreement between the
        # tab and the machine, and PAD-94's user could not tell from any line
        # of it whether the interpreter he had just installed into was the one
        # being looked at.
        winpy = facts.get("winpy", "").strip()
        # AND WHETHER IT IS OURS (PAD-95), because that is the difference
        # between an answer the user types and an answer he presses: PAD's own
        # bundled interpreter is repaired by its own prerequisite installer,
        # anyone else's by a pip command.  A paste that cannot tell the two
        # apart cannot settle which was needed.
        ours = facts.get("padpy", "").strip()
        whose = (" (PAD's own)" if winpy and winpy.lower() == ours.lower()
                 else "")
        if facts.get("winaudio") == "1":
            said = "found" + (" — %s%s" % (winpy, whose) if winpy else "")
        elif facts.get("winaudio") == "0":
            said = ("%s%s, but it has no sounddevice" % (winpy, whose) if winpy
                    else "no Windows Python that WSL can see")
        else:
            said = "unknown"
        lines.append("  Windows sound player: " + said)
        # ★ PAD-99: AND THE OTHER WINDOWS PYTHON, the one that draws the
        # playfield window.  Not the same interpreter and not the same
        # question: the sound one needs sounddevice, this one wants pywebview
        # and Pillow (and opens as an Edge window without them).
        # The reporter's did, so his runs came up with a game
        # window, sound, switches and no playfield - and this report, the thing
        # he would have been asked to paste, had no line about it at all.
        pf = facts.get("pfpy", "").strip()
        pf_whose = " (PAD's own)" if same_windows_python(pf, ours) else ""
        if facts.get("winpf") == "1":
            said = "opens with " + (("%s%s" % (pf, pf_whose)) if pf
                                    else "a Windows Python")
        elif facts.get("winpf") == "0":
            said = ("%s%s, without pywebview or Pillow, so it opens as an "
                    "Edge window" % (pf, pf_whose) if pf else
                    "no Windows Python that WSL can see")
        else:
            said = "unknown"
        lines.append("  virtual playfield window: " + said)
        if ours and not whose:
            lines.append("  PAD's own Python: %s" % ours)
    lines.append("  display: %s" % facts.get("display", "unknown"))
    if facts.get("distro"):
        lines.append("  distro: %s" % facts["distro"])
    lines.append("this PC can run the emulator."
                 if setup_ok(facts) else
                 "this PC cannot run the emulator yet.")
    return lines


def setup_report_darwin(docker, cli=None, engine=None):
    """The Check button's answer on a Mac, where the question is a different
    one.

    ``setup_state`` answers None on macOS BY DESIGN - the container carries
    every package the emulator needs (docker/Dockerfile installs them at build
    time), so Docker itself is the whole prerequisite and ``docker_state``
    owns it.  Asking WSL's question on a machine that has no WSL would report
    "no answer from WSL - it may not be installed" to a user whose Mac is
    perfect, which is the same class of lie the None-is-not-fine rule on
    ``setup_state`` exists to prevent.

    Pure, like ``setup_report``, so the wording is testable without a Tk root
    or a Docker.  ``cli`` and ``engine`` are what the probe found (see
    :func:`docker_cli` and :func:`docker_engine`) and both are optional: this
    is the paste a user is asked for when a Mac disagrees with the tab, and
    "which docker, found where" is the fact that settles it.
    """
    lines = ["setup check:",
             "  this Mac emulates in a container, so there are no packages "
             "to install here."]
    lines.append("  Docker: " + {
        "ok": "running",
        "stopped": "installed, but NOT running",
        "engineless": "the command is installed, but nothing here runs "
                      "containers",
        "absent": "NOT installed",
    }.get(docker, "unknown — the probe gave no answer"))
    # NAMED, not just counted.  The bug that added this state was a docker in
    # /opt/local/bin that the app could not see, and no line of any report said
    # where it had looked.
    lines.append("  docker command: " + (cli or "not found on PATH or in "
                                         + ", ".join(DOCKER_DIRS)))
    lines.append("  container engine: "
                 + ("%s (%s)" % (engine[0], engine[2]) if engine else
                    "none installed — Docker Desktop, OrbStack, Rancher "
                    "Desktop and Colima each provide one"))
    lines.append("this Mac can run the emulator." if docker == "ok" else
                 "this Mac cannot run the emulator yet.")
    return lines


def setup_settled(facts):
    """Is there NOTHING left to say about this machine?

    Different from setup_ok, and the difference is the whole of _SETUP_OPTIONAL:
    a PC can run the emulator (setup_ok) and still be missing what its save
    states need.  The tab shows its notice on this, so that "runs, but the save
    slots will not" is a thing it can say - and stays silent on the machine
    that has everything, which is what it did before.

    ...AND "runs, but the picture will be black" IS THE SAME KIND OF THING,
    which the tab was silent about until PAD-63.  See setup_env_faults.
    """
    return (setup_ok(facts) and not setup_extras(facts)
            and not setup_env_faults(facts))


def setup_fix_steps(facts):
    """Everything “Set up emulator…” is about to change, one line each.

    THIS LIST IS THE CONSENT.  setupfix.sh installs packages and writes to
    /etc/wsl.conf inside the user's distro, and the dialog built from this is
    the only place any of that is agreed to - so it is a pure function with
    tests on it rather than a list assembled inside a callback where nothing
    can see it.
    """
    facts = facts or {}
    missing, binfmt = setup_summary(facts)
    # THE BUTTON INSTALLS THE EXTRAS TOO, so the consent list has to name them:
    # setupfix.sh installs whatever setupcheck.sh reports as `need`, which is
    # every probe that came back 0 - this list is what the user agreed to, and
    # it may not be shorter than what is about to happen.
    missing = missing + setup_extras(facts)
    unavailable = setup_unavailable(facts)
    fetch = [p for p in unavailable if p in setup_fetchable(facts)]
    steps = []
    # Named FIRST because it happens first, and because it is the one step
    # here that changes how WSL finds packages at all rather than which
    # packages are on it.
    if facts.get("universe") == "0":
        steps.append(
            "Turn on Ubuntu's “universe” component in WSL — it is "
            "switched off, and it is where %s is published."
            % ", ".join(unavailable))
    # The ordinary install covers everything EXCEPT what has to be fetched:
    # naming a package on both lines reads as installing it twice, and one of
    # the two descriptions of how would be wrong.
    built = [pkg for pkg, _ in setup_built(facts)]
    ordinary = [pkg for pkg, _ in missing
                if pkg not in fetch and pkg not in built]
    if ordinary:
        steps.append("Install in WSL:  " + "  ".join(ordinary))
    # ...AND THE ONE APT HAS NEVER HEARD OF.  No Ubuntu publishes criu, so
    # this step is a source download and a compile, not an install — a
    # different act, a different length (minutes, not seconds), and a
    # different thing to agree to.  It is named with everything it touches
    # for the same reason the rest of this list is.
    if built:
        steps.append(
            "Build %s from source in WSL — no Ubuntu publishes it. This "
            "installs the build tools, downloads the source from GitHub, "
            "compiles it (a few minutes) and puts the result in "
            "/usr/local/bin. Save states need it; nothing else does."
            % ", ".join(built))
    # NAMED SEPARATELY because it is a different act from `apt install`: the
    # package comes out of ANOTHER Ubuntu's archive.  Folding that into the
    # line above would make this dialog a consent to something it did not say.
    if fetch:
        steps.append(
            "%s is not published for your Ubuntu at all, so fetch that one "
            "from Ubuntu %s's archive and install it (it depends on nothing, "
            "so nothing else comes with it). Your package sources are not "
            "changed." % (", ".join(fetch), FALLBACK_RELEASE))
    if binfmt == "0":
        steps.append("Register the kernel's handler for 32-bit ARM programs.")
    elif binfmt == "disabled":
        steps.append("Switch the 32-bit ARM handler back on.")
    if facts.get("iswsl") == "1" and facts.get("wslconf") == "0":
        steps.append("Add [boot] systemd=true to /etc/wsl.conf, so the "
                     "registration is still there after WSL restarts.")
    return steps


def setup_notice(facts, can_fix):
    """What the tab says about a machine that cannot emulate yet.

    THE ARM HANDLER LEADS, when it is what is wrong, because it is the fault
    that produced this: a tester's first run stopped at

        chroot: failed to run command '/bin/sh': Exec format error

    which names the shell and not the missing thing, arrives after Start has
    said "Starting…", and is the one of the rig's four guest-exec faults that
    it cannot repair by itself (the other three it fixes without asking).

    AND IT HAS A SECOND, QUIETER JOB: a machine can run the emulator and still
    be missing what SAVE STATES need (_SETUP_OPTIONAL).  That gets its own
    headline, because telling someone whose emulator works that his PC cannot
    run it is how a correct notice becomes a false one.
    """
    if setup_settled(facts):
        return ""
    missing, binfmt = setup_summary(facts)
    extras = setup_extras(facts)
    env = setup_env_faults(facts)
    if setup_ok(facts):
        # Everything the RUN needs is here; what is missing costs a feature.
        # Lead with the good news, because the alternative wording has just
        # told a working machine that it is broken.  Three headlines rather
        # than two now: a fully installed PC can still be one whose picture
        # will be black, and "Save states do not yet" would be a false
        # description of that machine.
        if extras:
            # NAMED, because there is more than one of them now: save states,
            # and building a multi-boot card's menu program.  A machine
            # missing only the second must not be told its save states are
            # off, which is what one hard-coded headline said.
            feats = [f for f, _rows in setup_extra_groups(facts)]
            parts = ["The emulator runs on this PC. %s do not yet."
                     % _and_list(feats)]
        else:
            parts = ["The emulator runs on this PC, but this WSL will spoil "
                     "it."]
    else:
        parts = ["This PC cannot run the emulator yet."]
    if binfmt == "0":
        parts.append(
            "This machine has no handler registered for 32-bit ARM programs, "
            "and the game is one — so a run would stop the moment it started.")
    elif binfmt == "disabled":
        parts.append(
            "The handler for 32-bit ARM programs is registered but switched "
            "off, and the game is a 32-bit ARM program.")
    # NAMED AS THIS MACHINE NAMES THEM.  The tables above are apt's spelling;
    # on Arch (setupcheck.sh's `pm`) that is not what the user will type or
    # search for, and the commands further down are translated the same way.
    label = (pkgnames.arch_label if (facts or {}).get("pm") == "pacman"
             else (lambda pkg: pkg))
    if missing:
        parts.append("Missing:\n" + "\n".join(
            "     •  %s — %s" % (label(pkg), why) for pkg, why in missing))
    # LISTED APART FROM THE ONES ABOVE, and it has to be: those stop a run and
    # this one does not.  A run started without it boots normally and simply
    # cannot be frozen (watch.sh says the same thing in the log), so the line
    # says what it costs rather than filing it under "missing".
    for feat, rows in setup_extra_groups(facts):
        parts.append("%s need:\n" % feat + "\n".join(
            "     •  %s — %s" % (label(pkg), why) for pkg, why in rows))
    # NOT INSTALLABLE IS NOT THE SAME AS MISSING, and saying only the first is
    # what sent a tester to press a button that could never work: the tab
    # named qemu-user-static, he pressed “Set up emulator…”, and apt answered
    # "has no installation candidate" because Ubuntu's `universe` component -
    # which is where that package lives - was switched off in his WSL.
    unavailable = setup_unavailable(facts)
    if unavailable:
        named = ", ".join(unavailable)
        if facts.get("universe") == "0":
            parts.append(
                "WSL cannot install %s as it stands: Ubuntu publishes it in "
                "the “universe” component, and this distro has that switched "
                "off." % named)
        else:
            # SAY WHAT WE KNOW, NOT WHAT IT MIGHT BE.  The line that stood
            # here ("the package sources this Linux is set up with do not
            # offer it") is true but shapeless, and the log underneath it went
            # on to blame an out-of-support distro and trimmed sources —
            # neither of which had been checked, and neither of which was true
            # of the machine that met it.  The release and its components are
            # facts setupcheck.sh now reports, so they are what gets said.
            where = facts.get("distro", "").strip()
            comps = facts.get("components", "").split()
            said = "WSL cannot install %s from its own sources." % named
            if where:
                said += "  This is %s" % where
                if "universe" in comps:
                    said += ", with “universe” switched on"
                said += ", and that release does not publish it."
            else:
                said += ("  The package sources this Linux is set up with do "
                         "not offer it.")
            parts.append(said)
    fetch = [p for p in setup_unavailable(facts) if p in setup_fetchable(facts)]
    # `unavailable and` IS NEW AND IS LOAD-BEARING.  setup_fixable now also
    # answers False for a machine with simply nothing to install - which became
    # reachable the moment setup_env_faults let the notice appear on a fully
    # installed PC - and without this gate a root-login machine with every
    # package present would be told that “Set up emulator…” cannot get `that`
    # from this distro, which is a sentence about a fault it does not have.
    if can_fix and unavailable and not setup_fixable(facts):
        # The button is hidden in this state (see _setup_apply), so this is
        # the whole of what the user has to go on.
        if setup_ok(facts):
            # ...and when the emulator itself is fine, "replace your Linux" is
            # a wildly out-of-proportion answer to a feature that is off.  Say
            # what is lost, and leave the working machine alone.
            # ...and WHICH feature, from the same grouping the list above
            # uses: this sentence used to say "save states" because that was
            # the only extra there was.
            lost = [f.lower() for f, rows in setup_extra_groups(facts)
                    if any(pkg in unavailable for pkg, _why in rows)]
            parts.append(
                "“Set up emulator…” cannot get %s from this distro, so %s "
                "stay off. Everything else about the emulator is "
                "unaffected — titles start and run exactly as they do now."
                % (", ".join(unavailable) or "that",
                   _and_list(lost) or "that feature"))
        else:
            parts.append(
                "“Set up emulator…” cannot get past this — there is nothing "
                "left for it to install. PAD uses whichever distro WSL calls "
                "the default, so a distro that does carry %s, made the "
                "default, is the way through. Any current Ubuntu will do; "
                "this is the one PAD is tested on. In a Windows terminal:\n"
                "     wsl --install -d %s\n"
                "     wsl --set-default %s"
                % (", ".join(unavailable) or "the packages",
                   KNOWN_GOOD_DISTRO, KNOWN_GOOD_DISTRO))
    elif can_fix and setup_fix_steps(facts):
        # ...and the same gate on this side: with no step to take there is no
        # button and nothing to describe, and `does[0]` on an empty list is an
        # IndexError rather than a wrong sentence.
        # ONLY THE PARTS IT IS ACTUALLY GOING TO DO.  Every earlier
        # prerequisite failed on machines whose handler was unregistered too,
        # so "installs those and registers the handler" was always true; the
        # decoder is the first that turns up on its own, on a machine whose
        # handler is fine, and promising to register it there is a promise
        # about something that is not going to happen.  setup_fix_steps is the
        # consent and is already exact - this sentence is its summary and has
        # to be exact the same way.
        does = []
        built = setup_built(facts)
        if facts.get("universe") == "0":
            does.append("turns universe back on")
        # NOT EVERYTHING LISTED ABOVE IS AN INSTALL.  criu is a source build,
        # and "installs those" over a list whose only entry is criu describes
        # something that is not going to happen - apt has no such package.
        if missing or [e for e in extras if e not in built]:
            does.append("installs those in WSL")
        if built:
            does.append("builds %s from source (a few minutes)"
                        % ", ".join(p for p, _ in built))
        if binfmt == "0":
            does.append("registers the handler for 32-bit ARM programs")
        elif binfmt == "disabled":
            # A different act from registering one, and setup_fix_steps has
            # said so since it was written.
            does.append("switches the 32-bit ARM handler back on")
        # AND THE STEP THAT CAN BE THE WHOLE OF IT.  Everything above is a
        # package or the kernel handler; this one is neither, and it is the
        # only step that can turn up ALONE - a fully installed machine, its
        # handler registered, whose distro does not boot systemd, and which
        # the notice is in front of because of an environment warning
        # (setup_env_faults).  Left out of this summary it was not merely
        # unsaid: `does[0]` ran off an empty list, so the tab answered such a
        # machine with an internal error where its notice should have been.
        # Seen on this PC while photographing PAD-126.
        if facts.get("iswsl") == "1" and facts.get("wslconf") == "0":
            does.append("turns systemd on in /etc/wsl.conf, so the handler "
                        "is still registered after a WSL restart")
        parts.append(
            "“Set up emulator…” %s. It lists exactly what it will change "
            "first, and needs no password."
            % (", ".join(does[:-1]) + " and " + does[-1]
               if len(does) > 1 else does[0]))
        if fetch:
            # The user is about to be told the button works after being told
            # the package cannot be installed, so it has to say HOW — and say
            # the thing that makes it safe, which is the empty Depends.
            parts.append(
                "%s comes from Ubuntu %s's archive instead, which does "
                "publish it. It depends on nothing, so nothing else comes "
                "with it and the rest of this Linux is left alone."
                % (", ".join(fetch), FALLBACK_RELEASE))
    else:
        cmds = []
        if facts.get("universe") == "0":
            cmds.append("sudo add-apt-repository universe")
        # A package apt has no version of must not be printed INTO the command
        # unless the line above is about to make it installable: `apt install
        # a b` is all or nothing, so one such name in the list is an apt
        # command that installs none of the others.  That is the fault PAD-41
        # fixed in the rig, and it was still here in the advice the rig prints.
        # ...and neither must a package that DOES NOT EXIST.  criu is on no
        # Ubuntu at all, so `apt install criu` cannot work anywhere; it gets
        # the command that does work, on its own line.
        built_names = [p for p, _ in setup_built(facts)]
        askable = [p for p, _ in missing + extras
                   if p not in built_names
                   and (facts.get("universe") == "0" or p not in unavailable)]
        if askable:
            if facts.get("pm") == "pacman":
                # Arch.  Every name above is apt's, which is pacman's "target
                # not found", and one of them (the cross compiler) is in no
                # repository pacman has - it is named from the AUR on a line
                # of its own rather than handed to pacman with the rest.
                # `pm` is setupcheck.sh's own answer, so it is about the
                # machine the run happens on; an older rig that never emitted
                # it reads as apt, which is every rig there was before.
                cmds.extend(pkgnames.pacman_commands(askable))
            else:
                cmds.append("sudo apt install " + " ".join(askable))
        if built_names:
            cmds.append("sudo bash %s" % os.path.join(rig_dir(), "getcriu.sh"))
        if binfmt != "1":
            cmds.append(facts.get(
                "advice", pkgnames.binfmt_advice(facts.get("pm"))))
        if cmds:
            parts.append("Run this, then start again:\n" + "\n".join(
                "     %s" % c for c in cmds))
    # LAST, AND SEPARATELY, because none of it is anything the button can do.
    # Each line says what the machine will do wrong and what to change; the
    # button above stays hidden or stays about packages, and neither sentence
    # is allowed to claim these.
    for what, cure in env:
        parts.append("%s\n     %s" % (what, cure))
    return "\n\n".join(parts)
