"""Plumbing the two web Emulate tabs of the JJP and Spike 1 rigs share.

The old Tk panels (the JJP and Spike 1 Emulate tabs) each carried the same
few pieces: log from any thread, the shared Volume / Mute control file, a
status poller that backs off while nothing runs, and a launch that streams
the rig's output line by line.  Here they are once, on the web UI's loop
instead of Tk's ``after``.

The rig facts themselves (how a rig script is invoked, how its status is
parsed, the control file's path) are NOT redefined here: they are imported
from the modules every rig shares (``webui/rig.py``,
``webui/emulate_core.py``), so no two tabs can disagree about them.

``PAD_UI_NO_RIG`` (set by the tests and the capture script) switches every
rig call off: no status poll, no launch, no WSL call of any kind.
"""

import os
import subprocess
import threading
import time

from pinball_decryptor.webui import rig as _rig
from . import emulate_core as _stern_emulate

#: The footer ladder the web window starts with (the Stern rig's); a JJP or
#: Spike 1 tab puts it back when its own manufacturer goes away, so the
#: Spike 2 tab never inherits another rig's slot names.
try:
    from .window import EMULATE_PHASES as DEFAULT_EMULATE_PHASES
except Exception:                                      # noqa: BLE001
    DEFAULT_EMULATE_PHASES = ("Copy card", "Boot", "Tech Alerts", "Attract")


def rig_off():
    """True when this session must not touch any emulator rig (tests and
    screen captures set ``PAD_UI_NO_RIG``)."""
    return os.environ.get("PAD_UI_NO_RIG", "") not in ("", "0")


def audio_ctl_file():
    return _stern_emulate.AUDIO_CTL_FILE


def load_audio_ctl():
    return _stern_emulate._load_audio_ctl()


def write_audio_ctl(gain, muted):
    return _stern_emulate._write_audio_ctl(gain, muted)


def windows_python(console=False):
    return _stern_emulate.windows_python(console=console)


class RigTabMixin:
    """The shared half of the two services.  The host class is a
    :class:`~.tabs.base.TabService` and sets ``LOG_PREFIX``, ``PHASES``,
    ``POLL_*`` and implements ``_rig_ready()``, ``_read_status()`` and
    ``_apply(info)``."""

    POLL_MS = 2000
    POLL_IDLE_MS = 10000
    POLL_FIRST_MS = 700
    LOG_PREFIX = ""
    PHASES = ()

    def _init_rig_state(self):
        self._poll_job = None
        self._poll_busy = False
        self._polled_once = False
        self._last_poll_at = 0.0
        self._stopped = False
        self._busy = False
        #: a Start or Stop is in flight (the Start button's spinner); a WSL
        #: restart only greys Start, as the Tk button was
        self._go_busy = False
        self._last_up = False
        self._info = {}
        self._vol_quiet = False
        vol0, mute0 = load_audio_ctl()
        self._volume_var = self.var("volume", "float", round(vol0 * 100, 1))
        self._mute_var = self.var("mute", "bool", bool(mute0))
        self._volume_var.trace_add("write", self._on_volume_change)
        self._mute_var.trace_add("write", self._on_volume_change)
        # Seed the control file now, so a first Start plays at what the
        # slider shows (the Tk panels did this in build()).  Not in a test
        # or capture session: those never touch the machine's files.
        if not rig_off():
            self._on_volume_change()

    # -- threads -> the loop ---------------------------------------------
    def _post(self, fn, *args):
        try:
            self.ctx.loop.post(fn, *args)
        except Exception:                              # noqa: BLE001
            pass

    def _log(self, msg):
        """Log from ANY thread: the line is appended on the UI loop, in the
        order the workers produced them."""
        self._post(self.window.append_log, msg)

    def _footer(self, kind, pct=None, text=""):
        """Move the footer's ladder for THIS tab (the window ignores it while
        another tab shows, as the Tk window did)."""
        self._post(self._footer_now, kind, pct, text)

    def _footer_now(self, kind, pct=None, text=""):
        try:
            self.window.set_emulate_progress(kind, pct, text, tab=self.key)
        except Exception:                              # noqa: BLE001
            pass

    # -- volume ------------------------------------------------------------
    def _on_volume_change(self, *_args):
        """Volume / Mute moved: write the live control file every rig's
        player follows (shared with the other Emulate tabs)."""
        if self._vol_quiet:
            return
        try:
            gain = max(0.0, min(1.0, float(self._volume_var.get()) / 100.0))
        except (TypeError, ValueError):
            gain = 1.0
        write_audio_ctl(gain, bool(self._mute_var.get()))

    def _reload_volume(self):
        """Show what the control file says now: another Emulate tab may have
        moved the shared knob since this one was built."""
        vol, mute = load_audio_ctl()
        self._vol_quiet = True
        try:
            self._volume_var.set(round(vol * 100, 1))
            self._mute_var.set(bool(mute))
        finally:
            self._vol_quiet = False

    # -- the footer ladder -------------------------------------------------
    def _show_own_phases(self):
        try:
            self.window.set_emulate_phases(self.PHASES)
        except Exception:                              # noqa: BLE001
            pass

    def _restore_default_phases(self):
        f = self.store.get("shell", "footer") or {}
        if tuple(f.get("phases") or ()) == tuple(self.PHASES) or \
                tuple(self.window._phases.get("emulate") or ()) == \
                tuple(self.PHASES):
            try:
                self.window.set_emulate_phases(DEFAULT_EMULATE_PHASES)
            except Exception:                          # noqa: BLE001
                pass

    # -- polling -----------------------------------------------------------
    def _poll_wanted(self):
        """Poll whenever this machine has the rig, from app start and for
        every manufacturer, as the Tk panels did (both were built for every
        manufacturer and polled from ``build()``): so an app quit takes down
        a game this session never showed (a terminal-started run, one left by
        an earlier session), and a JJP key plugged in is handed to WSL
        whichever manufacturer is on screen.  Idle, that is one status call
        every ``POLL_IDLE_MS``."""
        return not rig_off() and not self._stopped and self._rig_ready()

    def _start_polling(self):
        """The Tk panel's ``build()``: the first poll ``POLL_FIRST_MS`` after
        the tab is built."""
        self._schedule_poll(self.POLL_FIRST_MS)

    def _poll_now(self):
        """A status reading now (and the schedule after it)."""
        self._cancel_poll()
        self._poll()
        self._schedule_poll()

    def _poll_on_show(self):
        """The tab came up: a reading older than one busy period is taken
        again at once, so Start / Stop never acts on a state up to
        ``POLL_IDLE_MS`` old (a second launch over a running game)."""
        if not self._poll_wanted():
            return
        if not self._busy and \
                time.monotonic() - self._last_poll_at > self.POLL_MS / 1000.0:
            self._poll_now()
        else:
            self._schedule_poll()

    def _schedule_poll(self, ms=None):
        if self._poll_job is not None or not self._poll_wanted():
            return
        if ms is None:
            if not self._polled_once:
                ms = self.POLL_FIRST_MS
            else:
                ms = self.POLL_MS if self._last_up else self.POLL_IDLE_MS
        try:
            self._poll_job = self.ctx.loop.after(ms, self._poll)
        except Exception:                              # noqa: BLE001
            self._poll_job = None

    def _cancel_poll(self):
        job, self._poll_job = self._poll_job, None
        if job is not None:
            try:
                self.ctx.loop.after_cancel(job)
            except Exception:                          # noqa: BLE001
                pass

    def _poll(self):
        self._poll_job = None
        if not self._poll_wanted():
            return
        # Skipping rather than queueing: a status poll is a snapshot, and
        # the answer a stacked poll would give is the one already in flight.
        if self._poll_busy or self._busy:
            self._schedule_poll()
            return
        self._poll_busy = True

        def run():
            info = {}
            try:
                info = self._read_status()
            except Exception:                          # noqa: BLE001
                info = {}
            if self._stopped:
                self._poll_busy = False
                return

            def apply_and_release():
                self._poll_busy = False
                self._polled_once = True
                self._last_poll_at = time.monotonic()
                try:
                    self._apply(info)
                finally:
                    # one bad reading must not end the polling for good
                    self._schedule_poll()

            self._post(apply_and_release)

        threading.Thread(target=run, daemon=True,
                         name="pad-%s-poll" % self.ns).start()

    def _run_status(self, cmd, timeout=25):
        """One status.sh round trip -> the parsed key=value dict."""
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=timeout,
                                 creationflags=_rig.CREATE_FLAGS)
            text = out.stdout.decode("utf-8", "replace")
        except Exception:                              # noqa: BLE001
            text = ""
        return _rig.parse_status(text)

    # -- the launch --------------------------------------------------------
    def _run_streaming(self, cmd, timeout=1800, on_line=None):
        """Run a rig command, logging each line AS IT IS PRINTED (a launch
        captured and logged once at the end reads as a frozen app), bounded
        by ``timeout``.  ``on_line(line)`` sees every non-empty line.

        Returns the exit code, or None when the command could not start."""
        timed_out = {"v": False}
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, universal_newlines=True,
                encoding="utf-8", errors="replace",
                creationflags=_rig.CREATE_FLAGS)
        except Exception as exc:                       # noqa: BLE001
            self._log("%scould not start the rig: %s" % (self.LOG_PREFIX,
                                                          exc))
            return None

        def _kill():
            timed_out["v"] = True
            try:
                proc.kill()
            except Exception:                          # noqa: BLE001
                pass

        killer = threading.Timer(timeout, _kill)
        killer.daemon = True
        killer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._log(self.LOG_PREFIX + line)
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:                  # noqa: BLE001
                        pass
        finally:
            killer.cancel()
            try:
                proc.stdout.close()
            except Exception:                          # noqa: BLE001
                pass
            proc.wait()
        if timed_out["v"]:
            self._log("%sstart timed out — the rig was stopped."
                      % self.LOG_PREFIX)
        return proc.returncode

    def _refuse_off(self):
        """True (and a log line) when the rig is switched off for this
        session: a test or a capture must never start anything."""
        if rig_off():
            self.log("%sthe emulator rig is switched off in this session "
                     "(PAD_UI_NO_RIG)." % self.LOG_PREFIX)
            return True
        return False
