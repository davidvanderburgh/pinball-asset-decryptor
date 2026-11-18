"""padmodes_proc.py - PAD's custom-mode runtime for Spooky's P-ROC titles (Rick and Morty,
Alice Cooper's Nightmare Castle).  PAD-1387 proof of concept.  Python 2.7, as the games are.

HOW IT GETS INTO THE GAME, WITH NO GAME FILE CHANGED BUT config.yaml.  Both titles' procgame
builds the board object in GameController.create_pinproc() from the config key
`pinproc_class` (default "pinproc.PinPROC"), through procgame.util.get_class(), which
__import__s the module part.  The game's folder is sys.path[0] (`python RMGame.pyc`,
`python2 ACGame.py`, both run from it), so one line in the folder's config.yaml

    pinproc_class: padmodes_proc.PinPROC

imports this file (shipped beside RMGame.pyc / ACGame.py) before the game has built anything,
and PinPROC() below hands back the machine's own pinproc.PinPROC - the game drives the same
board object it always did.  The caller's frame holds the game; once its __init__ is over
(run_proc_game calls game.run_loop), the modes are made: procgame AdvancedModes of
mode_type Game, which SkeletonGame adds itself at every game start and removes at game end.

WHAT IT NEVER DOES: raise into the game.  Every step is guarded; a failure is logged to
padmodes.log beside this file and the game runs stock.
"""
import json
import os
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(_HERE, "padmodes.log")
MODES = os.path.join(_HERE, "padmodes.json")
_state = {"game": None, "made": False}


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def PinPROC(machine_type, *a, **k):
    """procgame's pinproc_class: the machine's own board object, and our hooks set."""
    import pinproc
    proc = pinproc.PinPROC(machine_type, *a, **k)
    try:
        game = sys._getframe(1).f_locals.get("self")    # GameController.create_pinproc
        _state["game"] = game
        log("loaded: pinproc_class hook in %s (%s), pinproc from %s"
            % (type(game).__name__, sys.argv[0], getattr(pinproc, "__file__", "?")))
        _hook_run_loop(game)
    except Exception:
        log("hook failed: %s" % traceback.format_exc())
    return proc


def _hook_run_loop(game):
    orig = game.run_loop

    def run_loop(*a, **k):
        try:
            _make_modes(game)
        except Exception:
            log("modes failed: %s" % traceback.format_exc())
        return orig(*a, **k)

    game.run_loop = run_loop      # run_proc_game: game = game_class(); game.run_loop(...)


def active_modes(game):
    return [type(m).__name__ for m in game.modes.modes]


def _make_modes(game):
    if _state["made"]:
        return
    _state["made"] = True
    with open(MODES) as f:
        spec = json.load(f)
    title = type(game).__name__
    modes = [m for m in spec.get("modes", []) if m.get("title") in (title, "*")]
    log("game %s up; active modes at run_loop: %s" % (title, active_modes(game)))
    for m in modes:
        _new_mode(game, m)


def _new_mode(game, m):
    from procgame.game.advancedmode import AdvancedMode

    class PadMode(AdvancedMode):
        """one mode of padmodes.json: on <switch> active, score <points>, play <sound>, show
        <text> for 2 s"""

        def __init__(self, game):
            super(PadMode, self).__init__(game=game, priority=m.get("priority", 200),
                                          mode_type=AdvancedMode.Game)
            self.hits = 0
            self.add_switch_handler(name=m["switch"], event_type="active", delay=None,
                                    handler=self.hit)

        def mode_started(self):
            log("mode started: %s; active modes: %s" % (m["name"], active_modes(self.game)))

        def mode_stopped(self):
            log("mode stopped: %s" % m["name"])

        def evt_ball_starting(self):
            log("evt_ball_starting: ball %s; active modes: %s"
                % (self.game.ball, active_modes(self.game)))
            return 0

        def hit(self, sw):
            try:
                self.hits += 1
                p = self.game.current_player()
                before = p.score if p else None
                got = self.game.score(m["points"])
                after = p.score if p else None
                log("switch %s active (hit %d): game.score(%d) -> %r, player score %r -> %r"
                    % (sw.name, self.hits, m["points"], got, before, after))
                if m.get("sound"):
                    snd = self.game.sound
                    ch = snd.play(m["sound"])
                    log("sound.play(%r): known=%s enabled=%s -> %r"
                        % (m["sound"], m["sound"] in snd.sounds, snd.enabled, ch))
                if m.get("text"):
                    self.show(m["text"] % {"hits": self.hits})
                self.delay(name="pad_timer", delay=1.0, handler=self.timer)
            except Exception:
                log("hit failed: %s" % traceback.format_exc())
            # None = SwitchContinue: the game's own handlers still see the switch

        def show(self, text):
            tcp = getattr(self.game, "tcpclient", None)
            if tcp is not None:                     # Alice Cooper: its Unity player
                tcp.append_text("pad_text", 0, 0, -10, text, 40, 1.0, 1.0, 0.0, layer="quick_layer")
                log("text via tcpclient.append_text: %r" % text)
                self.delay(name="pad_clear", delay=2.0, handler=lambda: tcp.remove_text("pad_text"))
                return
            import procgame.dmd
            font = self.game.fonts[m.get("font", "neo_128")]
            t = procgame.dmd.HDTextLayer(self.game.display_width / 2, 300, font, "center",
                                         line_width=0, interior_color=(255, 255, 0))
            t.set_text(text)
            self.layer = t
            log("text layer shown: %r" % text)
            self.delay(name="pad_clear", delay=2.0, handler=self.clear)

        def clear(self):
            self.layer = None

        def timer(self):
            log("delay() timer fired 1.0 s after hit %d" % self.hits)

    PadMode.__name__ = str("Pad_" + m["name"])
    mode = PadMode(game)
    log("made mode %s (AdvancedMode.Game, priority %d) on switch %s"
        % (type(mode).__name__, mode.priority, m["switch"]))
    return mode
