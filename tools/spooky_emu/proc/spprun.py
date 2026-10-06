"""spprun.py - run a Spooky P-ROC title's launcher, telling the rig when it
reaches attract.

usage (netns.sh does this):  python2 spprun.py <launcher.py|.pyc>   in its folder

Python 2.7.  The game runs unchanged on proc_emu's pinproc (first on
PYTHONPATH); this only watches it:

* `attract` is written beside $SPP_LOG the first time a mode whose class
  name says Attract is added to the game's mode queue (Rick and Morty's
  CustomAttract, Alice Cooper's myAttractMode) - run_game.sh's "up".
* the board's ball model (tools/proc_emu/prochw.py `balls`) is turned on
  then too, from $SPP_BALLS = "eject=<coil> shooter=<switch> launch=<coil>"
  named as in the machine yaml: the game's own coil objects give the driver
  numbers (a PDB coil's number depends on the order the game set up its
  driver groups, which only the game knows).  It goes to the board's control
  socket, $PROC_EMU_CTL.
* every mode added and removed is logged to $SPP_LOG, the rig's record of
  what the game is doing (it ships bytecode, and its own log is mostly off).
* files of the machine's OS the game READS are answered from the rig:
  $SPP_OSFILES = "<machine path>=<rig path>;...".  Alice Cooper's launcher
  opens /sbin/codeupdate (wants SYNC_FIX and LOG_FIX in it) and
  /etc/X11/xinit/xinitrc (wants `uptest` and `delete`), and when either is
  missing or old it copies its own over them and reboots the cabinet; its
  package carries both files, so run_game.sh points the two paths at them.
"""
import marshal
import os
import socket
import sys
import time

LOG = os.environ.get("SPP_LOG")
RIG = os.path.dirname(LOG) if LOG else None


def log(msg):
    if LOG:
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))


# The machine's OS files the game reads, answered from the rig.
import __builtin__
_osfiles = dict(kv.split("=", 1) for kv in os.environ.get("SPP_OSFILES", "").split(";") if "=" in kv)
if _osfiles:
    _orig_open = __builtin__.open

    def _open(name, *a, **k):
        if isinstance(name, basestring) and name in _osfiles:
            log("os file %s -> %s" % (name, _osfiles[name]))
            name = _osfiles[name]
        return _orig_open(name, *a, **k)

    __builtin__.open = _open

sys.path.insert(0, os.getcwd())
launcher = sys.argv[1]
sys.argv = sys.argv[1:]

from procgame.game import mode as pgmode       # the title's own procgame
import procgame.config as pgconfig

# The machine's config.yaml draws the screen full screen and borderless
# (Rick and Morty: dmd_fullscreen True) - on a PC that covered the whole
# desktop, over the virtual playfield (PAD-405).  This procgame reads only
# ./config.yaml and ~/.pyprocgame/config.yaml (no ../local_config, unlike
# the AP titles'), so the rig sets the window over whatever it loaded: a
# window at 0,0, framed when it is on somebody's desktop so it can be moved.
# Its developers' key map goes too (1 = Start but A = the house, R = a
# flipper...): the rig's key listener gives the game window the playfield
# window's keys (run_game.sh), and with both a key pressed two switches.
CONFIG = {"dmd_fullscreen": False,
          "dmd_window_border": os.environ.get("SPP_VISIBLE") == "1",
          "screen_position_x": 0, "screen_position_y": 0,
          "keyboard_switch_map": {}}


def _config():
    values = getattr(pgconfig, "values", None)
    if isinstance(values, dict):
        values.update(CONFIG)


_orig_load = pgconfig.load


def _load(*a, **k):
    r = _orig_load(*a, **k)
    _config()
    return r


pgconfig.load = _load
_config()

_orig_add = pgmode.ModeQueue.add
_orig_remove = pgmode.ModeQueue.remove
_seen = {"attract": False}


def _ball_model(game):
    spec = dict(kv.split("=", 1) for kv in os.environ.get("SPP_BALLS", "").split() if "=" in kv)
    ctl = os.environ.get("PROC_EMU_CTL")
    if not spec or not ctl:
        return
    try:
        words = ["balls", "eject=%d" % game.coils[spec["eject"]].number,
                 "shooter=%d" % game.switches[spec["shooter"]].number]
        if "launch" in spec:
            words.append("launch=%d" % game.coils[spec["launch"]].number)
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        s.connect(ctl)
        s.sendall((" ".join(words) + "\n").encode())
        log("ball model: %s -> %s" % (" ".join(words), s.recv(4096).strip()))
        s.close()
    except Exception as e:                      # a rig nicety, never the game's end
        log("ball model failed: %r" % (e,))


def _add(self, m):
    name = type(m).__name__
    log("mode + %s" % name)
    if not _seen["attract"] and "attract" in name.lower():
        _seen["attract"] = True
        log("attract: %s" % name)
        _ball_model(m.game)
        if RIG:
            open(os.path.join(RIG, "attract"), "w").close()
    return _orig_add(self, m)


def _remove(self, m):
    log("mode - %s" % type(m).__name__)
    return _orig_remove(self, m)


pgmode.ModeQueue.add = _add
pgmode.ModeQueue.remove = _remove

main_file = launcher[:-1] if launcher.endswith(".pyc") else launcher
g = {"__name__": "__main__", "__file__": os.path.abspath(main_file), "__builtins__": __builtins__}
log("run %s" % launcher)
if launcher.endswith(".pyc"):
    with open(launcher, "rb") as f:
        code = marshal.loads(f.read()[8:])     # 2.7: magic + mtime, then the code
else:
    with open(launcher) as f:
        code = compile(f.read(), main_file, "exec")
exec(code, g)
