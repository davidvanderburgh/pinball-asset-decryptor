"""Try it for the web Modes tab: the project's modes in the emulator (item 127).

Ported from ``gui/modes_tab.py`` (``ModesPanel``'s Try it section on feature/emulate-prepare:
the state machine with preflight, the rig check first, root install, progress and cancel).
Every sentence the person reads is the Tk tab's. What changed is only the plumbing:

* Tk may only be touched from its main thread, so the Tk panel QUEUED worker notes and a
  150 ms ``after`` watch flushed them. The web UI's state lives in the store, which the UI
  loop owns; a worker hands its note to the loop with ``loop.post`` (FIFO, so notes, log
  lines and state changes keep their order) and it is shown at once.
* The Emulate tab is the web ``emulate`` service (``window.service("emulate")``), asked
  through the SAME launch API the Tk panel used on the Tk ``EmulatePanel``:
  ``launch_with(prepare)`` + ``last_refusal``, ``launch_state()``, ``set_preparing(text,
  pct)``, ``prepare_cancelled()``, ``prepare_refuse(reason)``, ``launch_as_root()``,
  ``_last_up`` and ``_launch_serial``; it tells this tab a launch is over through
  :meth:`TryItMixin.run_ended` (Tk's ``run_ended_cb``). Each is looked up at call time, so a
  window with no Emulate service (or a test) answers None/False rather than raising.

ONE LAUNCHER. Try it hands a preparation to the Emulate service's own Start: the card is the
one in that tab's box (``emulate_card_var``, which this tab's "Try it on" field edits), the
run is that tab's run, and its Stop stops it. The preparation runs on that tab's start
worker: it builds the modes set with WRITE'S OWN CODE (mode_tryit.build_set), puts the
object, the port and the mode files where the rig reads them (modes/tryit.sh), and returns
the run's extra environment.
"""

import os
import shutil
import subprocess
import sys
import threading
import time

from ..plugins.stern import mode_assets as MA
from ..plugins.stern import mode_project as MP
from ..plugins.stern import mode_runtime as MR
from ..plugins.stern import mode_tryit as MT
from . import emulate_rig
from .tabs import emulate as _emulate_tab

#: what a refused rig command says in a session with the rig switched off (the Emulate
#: service's own sentence, so both tabs read the same)
NO_RIG_TEXT = _emulate_tab.NO_RIG_TEXT


def no_rig():
    """``PAD_UI_NO_RIG`` (captures, tests): this tab builds its rig commands without asking
    WSL anything and runs none of them, as the Emulate service does. Its own name, so a test
    can switch this tab's guard off while the Emulate service keeps its own."""
    return _emulate_tab.no_rig()


class _TryItPrepare:
    """The callable Try it hands the Emulate service (``launch_with``): the tab's
    preparation, run on that tab's start worker with the card it is booting.

    AN OBJECT, NOT A BOUND METHOD, because the Emulate tab reads the refusal off the
    callable itself (``getattr(prepare, "last_reason", "")`` after a None) to pin it beside
    its own box, and a bound method takes no attributes."""

    def __init__(self, panel):
        self._panel = panel
        #: why the last preparation returned None, or "" (the Emulate tab shows it)
        self.last_reason = ""

    def __call__(self, card):
        return self._panel._tryit_prepare_call(card)

    def __repr__(self):
        return "<Try it preparation of the web Modes tab>"


class TryItMixin:
    """Try it, Start mode now, End mode, the live push after an autosave, code modes and
    the SDK. Mixed into :class:`.tabs.modes.ModesTab`."""

    TRYIT_TIP = (
        "Try it builds this project's modes as Write puts them on a card (their screens, "
        "clips and own sounds, from the card itself) and starts the card in the Emulate tab "
        "with them. Then start a game: a "
        "mode starts on its shots, or at once with Start mode now. Edits you make while the "
        "game runs reach it within a second. A mode's own sound costs about three minutes "
        "the first time it changes and is reused after that.")

    #: The states of one Try it, in order (the Tk tab's). ``idle`` before the first press;
    #: ``preflight`` from the press until the Emulate tab's worker picks the preparation up;
    #: ``building`` while Write's engine builds the set; ``installing`` while the rig script
    #: copies the stage in; ``starting`` once the env is handed back and the emulator boots;
    #: ``live`` while the run is up; ``ended`` when that run went down; ``failed`` when any
    #: step refused (the note says which). The button reads "Cancel" through the working four.
    TRYIT_STATES = ("idle", "preflight", "building", "installing", "starting", "live",
                    "ended", "failed")
    TRYIT_WORKING = ("preflight", "building", "installing", "starting")

    TRYIT_UNSUPPORTED = {
        "darwin": ("Try it runs on Windows and Linux for now: on a Mac the emulator's "
                   "container cannot see the modes yet. Your modes are saved in the "
                   "project."),
    }
    TRYIT_CANCELLED = "Try it was cancelled; nothing was started."
    TRYIT_NOT_UP = "the emulator did not come up; the Emulate tab's log says why."

    START_TIP = ("Start the mode open on the left in the running game, without its starting "
                 "shots. A game must be in play.")
    END_TIP = "End whichever of this project's modes is running."
    CODE_TIP = ("A mode written in C, for what the form cannot do: a copy of the Mode SDK's "
                "template in this project's modes folder. Try it builds it in with the others.")
    CUT_TIP = ("Cut the code-mode examples' clip, picture, music and calls from your own copy "
               "of the Godzilla films, with the film cutter. Pick the folder that holds the "
               "films.")
    LEAVE_OUT_TIP = ("Build this Try it without the modes' own sounds: the game's own calls "
                     "play, and the sound bank is not grown (the slow part of a build). A card "
                     "Written from the project still carries them.")

    def _init_tryit(self):
        #: stand-ins the tests set: subprocess.run, the opener, ffmpeg, the platform
        self._run_fn = None
        self._opener = None
        self._ffmpeg_fn = None
        self._platform = sys.platform
        self._tryit_base = MT.tryit_dir()
        #: what the last successful install put in the rig: project, slug -> slot, and
        #: each mode's asset signature then (screen and clip fields).
        self._tryit_live = None
        self._tryit_project = ""
        #: the one Try it state (TRYIT_STATES), changed only through _tryit_set
        self._tryit = {"state": "idle", "reason": "", "progress": None, "run": None}
        self._tryit_working = False
        #: this tab's own Cancel (the button pressed while a preparation runs)
        self._tryit_cancel = False
        self._tryit_last_progress = None
        self._tryit_started = None
        #: the callable handed to the Emulate service
        self.tryit_prepare = _TryItPrepare(self)
        self._down_ticks = 0
        self.set(tryit={"state": "idle", "reason": "", "progress": None, "working": False,
                        "started": None},
                 tryit_line="", leave_out=False,
                 emu={"have": False, "up": False, "busy": False, "card": "",
                      "verdict": "", "verdict_kind": "", "verdict_tip": ""})

    # ---- the Emulate service (the Tk EmulatePanel's launch API) ------------------------
    def _emu(self):
        svc = self.window.service("emulate")
        if svc is None or getattr(svc, "placeholder", None):
            return None
        return svc

    def _emu_call(self, name, *args, default=None):
        fn = getattr(self._emu(), name, None)
        if not callable(fn):
            return default
        try:
            return fn(*args)
        except Exception:                                   # noqa: BLE001
            return default

    def _running_fn(self):
        """Is the emulator up (the Emulate panel's own answer)."""
        emu = self._emu()
        if emu is None:
            return False
        up = getattr(emu, "_last_up", None)
        if up is None:
            fn = getattr(emu, "is_up", None)
            try:
                up = fn() if callable(fn) else False
            except Exception:                               # noqa: BLE001
                up = False
        return bool(up)

    def _run_id_fn(self):
        """The Emulate service's launch number (``_launch_serial``), or None."""
        return getattr(self._emu(), "_launch_serial", None)

    def _try_fn(self, prepare):
        """Tk's ``main_window._modes_try``: the Emulate tab's own launch with this tab's
        preparation, ``(accepted, reason)``. The Emulate service's ``try_it`` is that seam
        (launch_with, then the Emulate tab comes forward once the launch is accepted, so
        the person watches the run they asked for, as on Tk); a service without it gets
        launch_with alone. Back on this tab, the footer shows the same state."""
        emu = self._emu()
        seam = getattr(emu, "try_it", None) if emu is not None else None
        if callable(seam):
            res = seam(prepare)
            return res if isinstance(res, tuple) else (bool(res), "")
        launch = getattr(emu, "launch_with", None) if emu is not None else None
        if not callable(launch):
            return False, "there is no Emulate tab to run it in"
        if not launch(prepare):
            return False, str(getattr(emu, "last_refusal", "") or
                              "the Emulate tab did not start the run")
        return True, ""

    def _emulate_state(self):
        """The Emulate tab's launch_state(), or None when there is none to ask (or it
        cannot answer): the preflight then leaves those checks to launch_with."""
        emu = self._emu()
        fn = getattr(emu, "launch_state", None) if emu is not None else None
        if not callable(fn):
            return None
        try:
            return fn() or None
        except Exception:                                   # noqa: BLE001
            return None

    def _as_root(self):
        return bool(self._emu_call("launch_as_root", default=False))

    def _progress_fn(self, text, pct=None):
        fn = getattr(self._emu(), "set_preparing", None)
        if callable(fn):
            fn(text, pct)

    def _refuse_fn(self, reason):
        fn = getattr(self._emu(), "prepare_refuse", None)
        if callable(fn):
            fn(reason)

    def _cancel_fn(self):
        return bool(self._emu_call("prepare_cancelled", default=False))

    # ---- the commands (pure) ----------------------------------------------------------
    def _rig_module(self):
        """The rig command builders: the Emulate service's own when it has them (a test's
        stand-in), else the web Emulate tab's one seam onto them (``webui/emulate_rig``,
        which re-exports ``rig_cmd`` and ``rig_cmd_root`` from where they are defined
        today; imported at the top of this module, so a wrong path fails at import)."""
        emu = self._emu()
        if emu is not None and callable(getattr(emu, "rig_cmd", None)):
            return emu
        return emulate_rig

    def _inert_cmd(self, script, *args, root=False):
        """Under PAD_UI_NO_RIG: the Emulate service's own inert command (``_cmd`` /
        ``_cmd_root``: a plain argv that consults nothing), or the same argv built here.
        ``rig_cmd`` would ask core.runtime which distro to use, and off the UI loop that
        question can run ``wsl.exe -l``."""
        emu = self._emu()
        fn = getattr(emu, "_cmd_root" if root else "_cmd", None) if emu is not None else None
        if callable(fn):
            try:
                return fn(script, *args)
            except Exception:                               # noqa: BLE001
                pass
        return ["bash", "%s/%s" % (emulate_rig.rig_dir(), script)] + [str(a) for a in args]

    def _rig_cmd(self, script, *args):
        mod = self._rig_module()
        if mod is emulate_rig and no_rig():
            return self._inert_cmd(script, *args)
        return mod.rig_cmd(script, *args)

    def _rig_cmd_root(self, script, *args):
        mod = self._rig_module()
        if mod is emulate_rig and no_rig():
            return self._inert_cmd(script, *args, root=True)
        return mod.rig_cmd_root(script, *args)

    @staticmethod
    def _linux_path(path):
        return MT._wsl_path(path) if sys.platform == "win32" else path

    def tryit_env(self):
        return MT.try_env(MT.set_dir(self._tryit_base))

    def check_cmd(self, as_root=False):
        if as_root:
            return self._rig_cmd_root("modes/tryit.sh", "check")
        return self._rig_cmd("modes/tryit.sh", "check")

    def install_cmd(self, stage, as_root=False):
        if as_root:
            return self._rig_cmd_root("modes/tryit.sh", "install", self._linux_path(stage))
        return self._rig_cmd("modes/tryit.sh", "install", self._linux_path(stage))

    def trigger_cmd(self, slot):
        return self._rig_cmd("modes/tryit.sh", "start", str(int(slot)))

    def stop_cmd(self, codes=()):
        return self._rig_cmd("modes/tryit.sh", "stop", *codes)

    def push_cmd(self, path, slot):
        return self._rig_cmd("modes/tryit.sh", "push", self._linux_path(path), str(int(slot)))

    def compile_cmd(self, out, sources):
        interp = os.path.join(MR.sdk_dir(), "mode_file.c")
        return self._rig_cmd("modes/sdk/build_mode.sh", "-o", self._linux_path(out),
                             *[self._linux_path(s) for s in sources],
                             self._linux_path(interp))

    def _run(self, cmd, timeout=600, cancel=None):
        """``(ok, output)``. Never on the UI loop: a wsl.exe can take seconds. Polled every
        0.2 s so ``cancel()`` can kill it mid-way: then ``(False, "cancelled")``."""
        if not cmd:
            return False, "no command"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if self._run_fn is None and no_rig():
            return False, NO_RIG_TEXT          # the Emulate service's _run refuses the same
        if self._run_fn is not None:
            try:
                r = self._run_fn(cmd, capture_output=True, text=True, timeout=timeout,
                                 creationflags=flags)
            except (OSError, subprocess.SubprocessError) as e:
                return False, str(e)
            return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, creationflags=flags)
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
        chunks = []

        def drain():
            try:
                chunks.append(proc.stdout.read() or "")
            except (OSError, ValueError):
                pass
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        why = None
        while proc.poll() is None:
            if cancel is not None and cancel():
                why = "cancelled"
            elif time.monotonic() > deadline:
                why = "timed out after %d s" % timeout
            if why is not None:
                try:
                    proc.kill()
                    proc.wait(5)
                except (OSError, subprocess.SubprocessError):
                    pass
                reader.join(1)
                return False, why
            time.sleep(0.2)
        reader.join(5)
        return proc.returncode == 0, "".join(chunks).strip()

    # ---- the state, notes and the loop -------------------------------------------------
    def _on_loop(self):
        try:
            return self.ctx.loop.in_loop()
        except Exception:                                   # noqa: BLE001
            return True

    def _tryit_note(self, text):
        """Say ``text`` in the log and on the Try it line. Safe from a worker thread."""
        self._say("Try it: " + text)
        self._tryit_post(text)

    def _tryit_set(self, state, reason="", progress=None):
        assert state in self.TRYIT_STATES, state
        self._tryit_post((state, reason, progress))

    def _tryit_post(self, item):
        if self._on_loop():
            self._tryit_show(item)
        else:
            self.ctx.loop.post(self._tryit_show, item)

    def _tryit_flush(self):
        """Tk's flush point; on the web every note is shown as it lands."""
        return None

    def _tryit_show(self, item):
        if isinstance(item, tuple):
            self._tryit_apply(*item)
        else:
            self.set(tryit_line=str(item))

    def _tryit_apply(self, state, reason, progress):
        was = self._tryit["state"]
        self._tryit["state"] = state
        self._tryit["reason"] = reason or ""
        self._tryit["progress"] = progress
        if state in ("idle", "preflight"):
            self._tryit["run"] = None
        if progress is not None:
            text, pct = progress
            line = "Preparing: %s" % text
            if pct is not None:
                line += " %d%%" % pct
            self.set(tryit_line=line)
        if state in self.TRYIT_WORKING and was not in self.TRYIT_WORKING:
            self._tryit_started = time.time()
        elif state not in self.TRYIT_WORKING:
            self._tryit_started = None
        self._tryit_render()

    def _tryit_render(self):
        self._tryit_working = self._tryit["state"] in self.TRYIT_WORKING
        prog = self._tryit["progress"]
        self.set(tryit={"state": self._tryit["state"], "reason": self._tryit["reason"],
                        "progress": list(prog) if prog else None,
                        "working": self._tryit_working, "started": self._tryit_started})
        if self._tryit_working:
            self._kick_ticker()

    def _tryit_tick(self):
        """Each tick: the preparation handed its env back (starting) and the Emulate
        service says the run is up - it is live, and the record names the launch it belongs
        to. While live, a run that went down (and the Emulate service has not said so)
        lands ended after three seconds."""
        up = self._running_fn()
        st = self._tryit["state"]
        if st == "starting" and up:
            self._tryit_set("live")
            self._tryit["run"] = self._run_id_fn()
            self._down_ticks = 0
        elif st == "live" and not up:
            self._down_ticks += 1
            if self._down_ticks >= 3:
                self._down_ticks = 0
                self.run_ended(self._tryit.get("run"))
        else:
            self._down_ticks = 0

    # ---- Try it -----------------------------------------------------------------------
    @staticmethod
    def _tryit_code_triggers(codes):
        return [s for s, _p in codes if MT.code_trigger_name(s)]

    @staticmethod
    def _tryit_code_unreached(codes):
        return MT.unreachable_code_modes(codes)

    def on_try(self):
        """The Try it button (the same button is Cancel while a preparation runs)."""
        if self._tryit_working:
            if self._tryit["state"] == "starting":
                self._tryit_note("the modes are in the emulator and the run is the Emulate "
                                 "tab's now: stop it there if you do not want it.")
            else:
                self._tryit_cancel = True
                self._tryit_note("cancelling…")
            return False
        self._save_if_edited()
        project = self.project()
        if self._platform in self.TRYIT_UNSUPPORTED:
            self._tryit_note(self.TRYIT_UNSUPPORTED[self._platform])
            return False
        if not project:
            self._tryit_note(MP.NO_PROJECT_HELP)
            return False
        if self._emu() is None or not callable(getattr(self._emu(), "launch_with", None)):
            self._tryit_note("there is no Emulate tab to run it in.")
            return False
        if not MP.list_modes(project)[0] and not MT.code_mode_sources(project):
            self._tryit_note("there are no modes in this project yet.")
            return False
        state = self._emulate_state()
        if state:
            if state.get("busy"):
                self._tryit_note("the emulator is starting or stopping; wait for it.")
                return False
            if state.get("up"):
                self._tryit_note("the emulator is already running: stop it on the Emulate "
                                 "tab first, then press Try it.")
                return False
            if state.get("overrides"):
                self._tryit_note("\"apply my edits\" is ticked on the Emulate tab; untick it "
                                 "to try the modes (Try it already carries your edits).")
                return False
        self._tryit_project = project
        self._tryit_cancel = False
        self._tryit_last_progress = None
        self._tryit_set("preflight")
        self._tryit_note("building the modes and starting the card in the Emulate tab…")
        res = self._try_fn(self.tryit_prepare)
        handed, reason = res if isinstance(res, tuple) else (bool(res), "")
        if not handed:
            self._tryit_set("failed", reason or "the Emulate tab did not start the run")
            self._tryit_note(reason or "the Emulate tab did not start the run; it says why "
                             "there (pick a card, stop a run that is up, or untick \"apply "
                             "my edits\").")
        return handed

    def _tryit_cancelled(self):
        if self._tryit_cancel:
            return True
        return self._cancel_fn()

    def _tryit_progress(self, done, total, text):
        pct = int(done * 100 / total) if total else None
        if (text, pct) == self._tryit_last_progress:
            return
        self._tryit_last_progress = (text, pct)
        self._tryit_set("building", progress=(text, pct))
        try:
            self._progress_fn(text, pct)
        except Exception:                                   # noqa: BLE001
            pass

    def _tryit_refuse(self, text, reason=None):
        self.tryit_prepare.last_reason = text
        self._tryit_note(text)
        try:
            self._refuse_fn(text)
        except Exception:                                   # noqa: BLE001
            pass
        self._tryit_set("failed", reason if reason is not None else text)
        return None

    def _tryit_cancelled_refuse(self):
        return self._tryit_refuse(self.TRYIT_CANCELLED, reason="cancelled")

    @staticmethod
    def _rig_sentence(out):
        said = [ln.strip() for ln in (out or "").splitlines() if "[tryit]" in ln]
        if said:
            line = said[-1]
            return line[line.index("[tryit]") + len("[tryit]"):].strip()
        return (out or "").strip()[-400:]

    def _tryit_prepare_call(self, card):
        self.tryit_prepare.last_reason = ""
        try:
            env = self._tryit_prepare(card)
        except Exception as e:                              # noqa: BLE001
            text = "the run could not be prepared: %s" % e
            self.tryit_prepare.last_reason = text
            self._tryit_post(text)
            self._tryit_set("failed", str(e))
            raise
        if env is None and not self.tryit_prepare.last_reason:
            self._tryit_refuse("the run was not prepared; the log says why.")
        return env

    def _ffmpeg_path(self):
        try:
            if self._ffmpeg_fn is not None:
                return self._ffmpeg_fn()
            from ..core.audio import find_ffmpeg
            return find_ffmpeg()
        except Exception:                                   # noqa: BLE001
            return None

    def _tryit_prepare(self, card):
        project = self._tryit_project or self.project()
        ffmpeg = self._ffmpeg_path()
        if not card or not os.path.isfile(card):
            return self._tryit_refuse("pick a card image in the Emulate tab first (a %s card)."
                                      % MT.project_title(project).label)
        as_root = self._as_root()
        ok, out = self._run(self.check_cmd(as_root=as_root), timeout=120,
                            cancel=self._tryit_cancelled)
        if not ok:
            if out == "cancelled" or self._tryit_cancelled():
                return self._tryit_cancelled_refuse()
            return self._tryit_refuse(self._rig_sentence(out)
                                      or "the emulator's rig did not answer the modes' check.")
        found_modes, broken = MP.list_modes(project) if project else ([], [])
        try:
            with_assets = MT.code_modes_with_assets(project) if project else []
        except MT.TryItError as e:
            return self._tryit_refuse(str(e))
        if not found_modes and not broken and MT.code_mode_sources(project) and not with_assets:
            return self._tryit_prepare_code_only(project, card, as_root)
        self._tryit_set("building")
        # the design's "leave out own sounds": build_set's own sound_ok=False (None = the
        # environment gate, as a Write reads it - the Tk tab's only choice)
        sound_ok = False if self.get("leave_out") else None
        try:
            ts = MT.build_set(project, card, base=self._tryit_base, ffmpeg=ffmpeg,
                              log=lambda m: self._say("Try it: " + m),
                              progress=self._tryit_progress, cancel=self._tryit_cancelled,
                              sound_ok=sound_ok)
        except (MT.TryItError, MP.ModeProjectError, OSError, ValueError) as e:
            if self._tryit_cancelled():
                return self._tryit_cancelled_refuse()
            return self._tryit_refuse(str(e))
        if ts is None or self._tryit_cancelled():
            return self._tryit_cancelled_refuse()
        codes = MT.code_mode_sources(project)
        if codes and not getattr(ts, "code_object", False):
            ok, out = self._run(self.compile_cmd(os.path.join(ts.stage_dir, MT.OBJECT_NAME),
                                                 [p for _s, p in codes]),
                                cancel=self._tryit_cancelled)
            if not ok:
                if out == "cancelled":
                    return self._tryit_cancelled_refuse()
                return self._tryit_refuse("the code modes did not build: %s" % out[-400:])
            self._say("Try it: built %d code mode(s) with the mode files: %s"
                      % (len(codes), ", ".join(s for s, _p in codes)))
        self._tryit_set("installing")
        ok, out = self._run(self.install_cmd(ts.stage_dir, as_root=as_root),
                            cancel=self._tryit_cancelled)
        if not ok:
            if out == "cancelled":
                return self._tryit_cancelled_refuse()
            return self._tryit_refuse("could not put the modes in the emulator: %s"
                                      % self._rig_sentence(out)[-400:])
        found = dict(ts.specs) or dict(MP.list_modes(project)[0])
        self._tryit_live = {
            "project": project,
            "slots": {slug: slot for slot, slug, _name in ts.slots},
            "signatures": {slug: MT.asset_signature(found[slug]) for _s, slug, _n in ts.slots
                           if slug in found},
            "sounds": {slug: MT.sound_signature(found[slug]) for _s, slug, _n in ts.slots
                       if slug in found},
            "stage": ts.stage_dir,
            "run": self._run_id_fn(),
            "codes": self._tryit_code_triggers(codes),
            "codes_unreached": self._tryit_code_unreached(codes),
            "own": dict(getattr(ts, "own_sounds", None) or {}),
        }
        if ts.slots:
            ready = ("%d mode(s) ready (%s). Start a game, then play the starting shots or press "
                     "Start mode now." % (len(ts.slots), ", ".join(n for _s, _g, n in ts.slots)))
        else:
            ready = "Ready. Start a game, then play each mode's starting shots."
        if getattr(ts, "reused", False):
            ready += " (the set from the last Try it, used as it is)"
        self._tryit_note(ready
                         + self._tryit_code_note(codes)
                         + self._tryit_sound_note(MT.sounds_left_out(ts)))
        if not MT.title_files(ts):
            self._say("Try it: nothing of the game's own files to change, so the run takes "
                      "no override set, only the mode object")
        if self._tryit_cancelled():
            return self._tryit_cancelled_refuse()
        self._tryit_set("starting")
        return MT.run_env(ts)

    @staticmethod
    def _tryit_sound_note(names):
        if not names:
            return ""
        return (" Own sounds of %s are not in this run, nor on a card Written from this "
                "project (the log says why): the game's own calls play." % ", ".join(names))

    @staticmethod
    def _tryit_code_note(codes):
        if not codes:
            return ""
        return (" Code mode(s) built in: %s (each starts on its own starting shots, or on "
                "its test trigger /dump/<folder>.start). A card Written from this project "
                "carries them the same way, with their own clip, screen, music and calls."
                % ", ".join(s for s, _p in codes))

    def _tryit_prepare_code_only(self, project, card, as_root=False):
        codes = MT.code_mode_sources(project)
        try:
            game_dir, version, _part = MT.card_title(card)
        except MT.TryItError as e:
            return self._tryit_refuse(str(e))
        port = MR.port_file(game_dir, version)
        if not port:
            return self._tryit_refuse("The Mode SDK has no port for %s %s, so no mode can run "
                                      "on it." % (game_dir or "this card", version))
        self._tryit_set("building")
        stage = MT.stage_dir(self._tryit_base)
        try:
            if os.path.isdir(stage):
                shutil.rmtree(stage)
            os.makedirs(stage)
            shutil.copyfile(port, os.path.join(stage, MT.PORT_NAME))
        except OSError as e:
            return self._tryit_refuse("could not make the Try it folder %s: %s" % (stage, e))
        ok, out = self._run(self.compile_cmd(os.path.join(stage, MT.OBJECT_NAME),
                                             [p for _s, p in codes]),
                            cancel=self._tryit_cancelled)
        if not ok:
            if out == "cancelled":
                return self._tryit_cancelled_refuse()
            return self._tryit_refuse("the code modes did not build: %s" % out[-400:])
        self._tryit_set("installing")
        ok, out = self._run(self.install_cmd(stage, as_root=as_root),
                            cancel=self._tryit_cancelled)
        if not ok:
            if out == "cancelled":
                return self._tryit_cancelled_refuse()
            return self._tryit_refuse("could not put the modes in the emulator: %s"
                                      % self._rig_sentence(out)[-400:])
        self._tryit_live = {"project": project, "slots": {}, "signatures": {},
                            "stage": stage, "run": self._run_id_fn(),
                            "codes": self._tryit_code_triggers(codes),
                            "codes_unreached": self._tryit_code_unreached(codes)}
        self._tryit_note("no modes made in the form, so no screens or clips to build. Start "
                         "a game on %s %s." % (game_dir, version)
                         + self._tryit_code_note(codes))
        if self._tryit_cancelled():
            return self._tryit_cancelled_refuse()
        self._tryit_set("starting")
        return ["PAD_MODE_SO=%s" % MT.GUEST_OBJECT]

    # ---- in the running game ------------------------------------------------------------
    def _tryit_live_now(self):
        live = self._tryit_live
        if not live:
            return None
        run = live.get("run")
        if run is not None and self._run_id_fn() != run:
            self._tryit_live = None
            return None
        return live if self._running_fn() else None

    def run_ended(self, serial):
        """From the Emulate service (Tk's ``run_ended_cb``) when a launch is over: ``serial``
        is the launch that ended. On the UI loop (posted there when called off it)."""
        if not self._on_loop():
            self.ctx.loop.post(self.run_ended, serial)
            return
        st = self._tryit["state"]
        run = self._tryit["run"]
        live = self._tryit_live
        if live is not None and (serial is None or live.get("run") in (None, serial)):
            self._tryit_live = None
        if st == "live" and (run is None or serial == run):
            self._tryit_set("ended")
            self._tryit_note("The run ended. Press Try it to run the modes again.")
        elif st in ("preflight", "starting") and run is None:
            self._tryit_set("failed", "not up")
            self._tryit_note(self.TRYIT_NOT_UP)

    def _selected_slot(self):
        project = self._open_project or self.project()
        live = self._tryit_live_now()
        if live and live.get("project") == project and self._slug in live["slots"]:
            return live["slots"][self._slug]
        return None

    def _not_in_game_reason(self, name):
        project = self._open_project or self.project()
        live = self._tryit_live_now()
        if not live:
            return ("the run that is up was not started by Try it, so none of these modes "
                    "is in it: stop it, then press Try it.")
        if live.get("project") != project:
            return ("the running game has another project's modes: stop the run, then press "
                    "Try it.")
        return ("%s is not in the running game yet: stop the run and press Try it again."
                % name)

    def _in_background(self, cmd, done):
        def work():
            ok, out = self._run(cmd, timeout=60)
            done(ok, out)
        t = threading.Thread(target=work, daemon=True, name="modes-rig")
        t.start()
        return t

    def on_start_now(self):
        if not self._slug:
            self._tryit_note("open a mode first.")
            return None
        if not self._running_fn():
            self._tryit_note("the emulator is not running: press Try it first.")
            return None
        name = self._spec.name if self._spec else self._slug
        slot = self._selected_slot()
        if slot is None:
            self._tryit_note(self._not_in_game_reason(name))
            return None
        cmd = self.trigger_cmd(slot)
        self._in_background(cmd, lambda ok, out: self._tryit_note(
            ("asked the game to start %s. A game must be in play." % name)
            if ok else "could not reach the emulator: %s" % out[-300:]))
        return cmd

    def on_end_now(self):
        if not self._running_fn():
            self._tryit_note("the emulator is not running.")
            return None
        live = self._tryit_live_now()
        if live is None:
            self._tryit_note("the run that is up was not started by Try it, so it has no "
                             "modes of this tab's to end.")
            return None
        codes = list(live.get("codes") or [])
        unreached = list(live.get("codes_unreached") or [])
        cmd = self.stop_cmd(codes)
        self._in_background(cmd, lambda ok, out: self._tryit_note(
            self._end_note(bool(live.get("slots")), codes, unreached) if ok
            else "could not reach the emulator: %s" % out[-300:]))
        return cmd

    @staticmethod
    def _end_note(form_modes, codes, unreached=()):
        if not codes:
            note = "asked the game to end the running mode."
        else:
            names = ", ".join(codes)
            if form_modes:
                note = "asked the game to end the running mode, and the code mode(s) %s." % names
            else:
                note = "asked the game to end the code mode(s) %s." % names
        if unreached:
            one = len(unreached) == 1
            note = ("%s; not ended: %s (%s; use letters, digits and _)."
                    % (note.rstrip("."), ", ".join(unreached),
                       "its folder name is not a trigger name" if one
                       else "their folder names are not trigger names"))
        return note

    def _tryit_saved(self, project, slug, spec):
        """After an autosave: while a Try it run is up, push this mode's regenerated file."""
        live = self._tryit_live_now()
        if not live or live.get("project") != project or slug not in live["slots"]:
            return None
        slot = live["slots"][slug]
        waits = MT.asset_signature(spec) != live["signatures"].get(slug)
        sounds = live.setdefault("sounds", {})
        if MT.sound_signature(spec) != sounds.get(slug, MT.sound_signature(spec)):
            sounds[slug] = MT.sound_signature(spec)
            self._tryit_note("%s: a change to its own sounds reaches the game at the next "
                             "Try it." % spec.name)
        own = (live.get("own") or {}).get(slug) or {}
        try:
            text = MP.runtime_cfg(spec, slug, own_sounds=own.get("requests") or None,
                                  own_sound_ms=own.get("ms") or None)
        except MP.ModeProjectError:
            return None
        if text == self._tryit_game_has(live, slug, slot):
            return None
        folder = os.path.join(live["stage"], "push")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, MA.mode_file_name(slot))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        cmd = self.push_cmd(path, slot)
        note = ("%s updated in the running game." % spec.name
                + (" Its screen or clip changes at the next Try it." if waits else ""))

        def pushed(ok, out):
            if ok:
                live.setdefault("texts", {})[slug] = text
            self._tryit_note(note if ok else "could not update the running game: %s" % out[-300:])
        self._in_background(cmd, pushed)
        return cmd

    @staticmethod
    def _tryit_game_has(live, slug, slot):
        text = live.get("texts", {}).get(slug)
        if text is not None:
            return text
        try:
            with open(os.path.join(live["stage"], MA.mode_file_name(slot)),
                      encoding="utf-8", newline="") as f:
                return f.read()
        except OSError:
            return None

    # ---- code modes and the SDK ---------------------------------------------------------
    def make_code_mode(self, name):
        """Copy the SDK's template into ``modes/<slug>/<slug>.c``. Returns the path."""
        slug, path = MT.new_code_mode(self.project(), name)
        self._tryit_note("made modes/%s/%s.c from the Mode SDK's template. Edit it, then "
                         "Try it builds it in; its test trigger is /dump/%s.start."
                         % (slug, slug, slug))
        return slug, path

    def sdk_doc(self):
        return os.path.join(MR.sdk_dir(), "MODE_SDK.md")

    def open_path(self, path):
        opener = self._opener
        try:
            if opener is not None:
                opener(path)
            elif self._platform == "win32":
                os.startfile(path)                          # noqa: S606
            else:
                subprocess.Popen(["open" if self._platform == "darwin" else "xdg-open", path])
        except (OSError, AttributeError) as e:
            how = self._open_as_text(path)
            if how:
                self._tryit_note("opened %s %s (nothing on this computer opens a %s file by "
                                 "itself)." % (os.path.basename(path), how,
                                               os.path.splitext(path)[1] or "plain"))
                return
            self._tryit_note("could not open %s: %s" % (path, e))

    def _open_as_text(self, path):
        import pathlib
        import webbrowser
        try:
            if self._platform == "win32":
                subprocess.Popen(["notepad.exe", path])             # noqa: S603,S607
                return "in Notepad"
            if webbrowser.open(pathlib.Path(os.path.abspath(path)).as_uri()):
                return "in the web browser"
        except (OSError, ValueError, RuntimeError, webbrowser.Error):
            pass
        return ""
