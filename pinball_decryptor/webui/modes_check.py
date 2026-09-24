"""Check this game, for the web Modes tab: prove what the app knows of a card's build.

A port the app drafted (or worked out on this PC) has never run a mode, so the tab says it is
unproven. This plays ONE scripted game of the card in the emulator and reads what the game
sent, with no mode made and nothing to build:

1. the preparation (run on the Emulate service's start worker, as Try it's is) stages the
   pinned mode object, the build's port and ``gamecheck.on`` (:mod:`..plugins.stern.game_check`)
   and installs them with ``modes/tryit.sh install``;
2. once the run is up, ``modes/gamecheck.sh play <game>`` starts a game, presses each playfield
   switch once and drains until a ball ends (about two minutes);
3. ``gamecheck.sh log`` hands back the object's ``check`` lines, :func:`.game_check.read` says
   which shots, events and end of ball were seen, the result is kept beside the port
   (:func:`.game_check.record`), and a port worked out on this PC is recorded as run live, so
   Write carries modes on it;
4. the run is stopped, and the title's note says what the check found.

It uses Try it's plumbing (the rig commands, ``_run``, the Emulate service) but not its state:
the two never run at once, and the person stays on this tab (``launch_with``, not the Emulate
tab's ``try_it`` seam, which brings that tab forward).
"""

import os
import shutil
import threading
import time

from ..plugins.stern import game_check as GC
from ..plugins.stern import mode_project as MP
from ..plugins.stern import mode_runtime as MR
from ..plugins.stern import mode_tryit as MT


class _CheckPrepare:
    """The callable handed to the Emulate service's ``launch_with`` (an object, so the Emulate
    tab can read ``last_reason`` off it after a refusal, as it does Try it's)."""

    def __init__(self, panel):
        self._panel = panel
        self.last_reason = ""

    def __call__(self, card):
        return self._panel._check_prepare_call(card)

    def __repr__(self):
        return "<Check this game preparation of the web Modes tab>"


class GameCheckMixin:
    """Check this game. Mixed into :class:`.tabs.modes.ModesTab` beside TryItMixin."""

    CHECK_TIP = ("Check this game plays one game of this card in the emulator by itself (about "
                 "two minutes): it starts a game, hits each playfield switch once and drains the "
                 "ball, then says which of the game's shots, events and end of ball the app got "
                 "right. No mode is needed and nothing is built.")
    #: idle; preparing (the press until the run is handed its env); starting (booting);
    #: playing (gamecheck.sh play); passed / failed (the note says what it found)
    CHECK_STATES = ("idle", "preparing", "starting", "playing", "passed", "failed")
    CHECK_WORKING = ("preparing", "starting", "playing")
    #: how long gamecheck.sh play may take: its own waits add up to under seven minutes
    CHECK_PLAY_TIMEOUT = 600

    def _init_check(self):
        self._check = {"state": "idle", "line": "", "started": None, "game": "", "port": "",
                       "label": "", "run": None, "down": 0}
        self._check_cancel = False
        self.check_prepare = _CheckPrepare(self)
        self.set(check={"state": "idle", "line": "", "working": False, "started": None})

    # ---- state ----------------------------------------------------------------------------
    def _check_working(self):
        return self._check["state"] in self.CHECK_WORKING

    def _check_set(self, state, line=None):
        """Change the check's state (and its line). Safe from a worker thread."""
        assert state in self.CHECK_STATES, state
        if not self._on_loop():
            self.ctx.loop.post(self._check_set, state, line)
            return
        was = self._check["state"]
        self._check["state"] = state
        if line is not None:
            self._check["line"] = line
        if state in self.CHECK_WORKING and was not in self.CHECK_WORKING:
            self._check["started"] = time.time()
        elif state not in self.CHECK_WORKING:
            self._check["started"] = None
        self.set(check={"state": state, "line": self._check["line"],
                        "working": state in self.CHECK_WORKING,
                        "started": self._check["started"]})
        if state in self.CHECK_WORKING:
            self._kick_ticker()

    def _check_line(self, text):
        self._say("Check this game: " + text)
        if not self._on_loop():
            self.ctx.loop.post(self._check_line_show, text)
        else:
            self._check_line_show(text)

    def _check_line_show(self, text):
        self._check["line"] = text
        self._check_set(self._check["state"], text)

    # ---- rig commands ---------------------------------------------------------------------
    def check_play_cmd(self, game):
        return self._rig_cmd("modes/gamecheck.sh", "play", game)

    def check_log_cmd(self):
        return self._rig_cmd("modes/gamecheck.sh", "log")

    # ---- the button -----------------------------------------------------------------------
    def on_check(self):
        """Check this game (the same button is Cancel while one runs)."""
        if self._check_working():
            if self._check["state"] == "preparing":
                self._check_cancel = True
                self._check_line("cancelling…")
            else:
                self._check_line("the check is playing its game in the emulator; stop the run "
                                 "on the Emulate tab to end it.")
            return False
        if self._tryit_working or self._tryit["state"] == "live":
            self._check_line("Try it is using the emulator; stop its run first.")
            return False
        if self._platform in self.TRYIT_UNSUPPORTED:
            self._check_line(self.TRYIT_UNSUPPORTED[self._platform])
            return False
        if not self.project():
            self._check_line(MP.NO_PROJECT_HELP)
            return False
        emu = self._emu()
        launch = getattr(emu, "launch_with", None) if emu is not None else None
        if not callable(launch):
            self._check_line("there is no Emulate tab to run it in.")
            return False
        why = self._refusal()
        if why:
            self._check_set("failed", why)
            return False
        state = self._emulate_state()
        if state:
            if state.get("busy"):
                self._check_line("the emulator is starting or stopping; wait for it.")
                return False
            if state.get("up"):
                self._check_line("the emulator is already running: stop it on the Emulate tab "
                                 "first, then press Check this game.")
                return False
            if state.get("overrides"):
                self._check_line("\"apply my edits\" is ticked on the Emulate tab; untick it to "
                                 "check the game as it shipped.")
                return False
        self._check_cancel = False
        self._check["run"] = None
        self._check["down"] = 0
        self._check_set("preparing", "putting the check in the emulator and starting the card…")
        if not launch(self.check_prepare):
            reason = str(getattr(emu, "last_refusal", "") or "the Emulate tab did not start the run")
            self._check_set("failed", reason)
            return False
        return True

    # ---- the preparation (the Emulate service's start worker) -------------------------------
    def _check_prepare_call(self, card):
        self.check_prepare.last_reason = ""
        try:
            env = self._check_prepare(card)
        except Exception as e:                              # noqa: BLE001
            self._check_refuse("the check could not be prepared: %s" % e)
            raise
        return env

    def _check_refuse(self, text):
        self.check_prepare.last_reason = text
        try:
            self._refuse_fn(text)
        except Exception:                                   # noqa: BLE001
            pass
        self._check_set("failed", text)
        return None

    def _check_cancelled(self):
        return self._check_cancel or self._cancel_fn()

    def _check_prepare(self, card):
        if not card or not os.path.isfile(card):
            return self._check_refuse("pick a card image in the Emulate tab first.")
        try:
            game_dir, version, _part = MT.card_title(card)
        except MT.TryItError as e:
            return self._check_refuse(str(e))
        port = MR.port_file(game_dir, version)
        label = MP.title_label(game_dir or "this card", version)
        if not port:
            return self._check_refuse(MP.no_port_words(label))
        as_root = self._as_root()
        ok, out = self._run(self.check_cmd(as_root=as_root), timeout=120,
                            cancel=self._check_cancelled)
        if not ok:
            if out == "cancelled" or self._check_cancelled():
                return self._check_refuse("the check was cancelled; nothing was started.")
            return self._check_refuse(self._rig_sentence(out)
                                      or "the emulator's rig did not answer.")
        stage = os.path.join(self._tryit_base, "check-stage")
        try:
            if os.path.isdir(stage):
                shutil.rmtree(stage)
            os.makedirs(stage)
            shutil.copyfile(MR.prebuilt_object(), os.path.join(stage, MT.OBJECT_NAME))
            shutil.copyfile(port, os.path.join(stage, MT.PORT_NAME))
            with open(os.path.join(stage, GC.FLAG_NAME), "w", encoding="utf-8") as f:
                f.write(GC.FLAG_TEXT)
        except OSError as e:
            return self._check_refuse("could not make the check's folder %s: %s" % (stage, e))
        ok, out = self._run(self.install_cmd(stage, as_root=as_root),
                            cancel=self._check_cancelled)
        if not ok:
            if out == "cancelled":
                return self._check_refuse("the check was cancelled; nothing was started.")
            return self._check_refuse("could not put the check in the emulator: %s"
                                      % self._rig_sentence(out)[-400:])
        if self._check_cancelled():
            return self._check_refuse("the check was cancelled; nothing was started.")
        self._check.update(game=game_dir, port=port, label=label, run=self._run_id_fn())
        self._check_set("starting", "starting %s in the emulator…" % label)
        return ["PAD_MODE_SO=%s" % MT.GUEST_OBJECT]

    # ---- while it runs ------------------------------------------------------------------------
    def _check_tick(self):
        """Each tick: a run that came up starts the play; one that went down fails the check."""
        st = self._check["state"]
        if st not in ("starting", "playing"):
            return
        up = self._running_fn()
        if st == "starting" and up:
            self._check["run"] = self._run_id_fn()
            self._check_set("playing", "playing a game in the emulator: a game starts, each "
                                       "playfield switch is hit once, then the ball drains…")
            self._check_play()
        elif st == "playing" and not up:
            self._check["down"] += 1
            if self._check["down"] >= 3:
                self._check_set("failed", "the emulator stopped before the check finished.")
        else:
            self._check["down"] = 0

    def _check_run_ended(self, serial):
        """The Emulate service says a launch is over (TryItMixin.run_ended calls this)."""
        if self._check["state"] in ("preparing", "starting", "playing"):
            if self._check["state"] == "preparing" and self._check.get("run") is None:
                return          # the preparation itself refused: it said why already
            self._check_set("failed", "the emulator stopped before the check finished.")

    def _check_play(self):
        game, port, label = self._check["game"], self._check["port"], self._check["label"]

        def work():
            ok, out = self._run(self.check_play_cmd(game), timeout=self.CHECK_PLAY_TIMEOUT)
            _lok, log = self._run(self.check_log_cmd(), timeout=60)
            self.ctx.loop.post(self._check_done, port, label, ok, out, log)
        threading.Thread(target=work, daemon=True, name="modes-check").start()

    def _check_done(self, port, label, ok, out, log):
        if self._check["state"] != "playing":
            return                    # the run went down meanwhile; that was said
        try:
            prof = MP.profile_from_port(port)
        except MP.ModeProjectError as e:
            self._check_set("failed", "the port could not be read back: %s" % e)
            return
        res = GC.read(log, out, prof.shots, prof.events)
        said = [ln for ln in (out or "").splitlines() if ln.startswith("[check]")
                and not ln.startswith("[check] switch ")]
        for ln in said:
            self._say("Check this game: " + ln[len("[check] "):])
        if not res.armed and not res.refused and said:
            # it never got as far as the game: say where it stopped
            self._check_set("failed", "the check stopped: %s" % said[-1][len("[check] "):])
        else:
            GC.record(port, res)
            if res.ok:
                from ..plugins.stern import port_derive as PD
                if PD.is_derived(port):
                    PD.record_live_run(port, res.armed)
            self._check_set("passed" if res.ok else "failed", res.summary(label))
        if self._running_fn() and self._check.get("run") in (None, self._run_id_fn()):
            self._emu_call("stop")
            self._check_line_show(self._check["line"] + " The check stopped the emulator when it "
                                  "was done.")
        self._say("Check this game: " + self._check["line"])
        fn = getattr(self, "refresh", None)
        if callable(fn):
            try:
                fn()
            except Exception:                               # noqa: BLE001
                pass

    # ---- what the tab shows ----------------------------------------------------------------
    def _check_record(self, profile):
        """The check kept for ``profile``'s port as it is now, or None."""
        if profile is None:
            return None
        return GC.load(MP.port_path(profile))
