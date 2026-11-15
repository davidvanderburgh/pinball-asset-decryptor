"""padmenu_proc.py - back to the boot menu without switching the machine off, for the P-ROC
titles of a Spooky multi-boot update (Rick and Morty, Alice Cooper's Nightmare Castle; PAD-1309).

On the machine it is .pad/padmenu_py/sitecustomize.py, and the multi-boot launcher
(padselect_proc.sh) puts that folder first on the game's PYTHONPATH, so Python loads it before
the game.  Python 2.7, as the games are.

    hold the coin door's EXIT for 3 s during a game (the card's back_hold=)
        -> sync; reboot (as root) or sudo -n reboot
        -> the machine starts again, and the boot menu comes up as at power-up

HOW IT SEES THE BUTTON.  These games are procgame games: the game builds pinproc.PinPROC and
calls its get_events() once per pass of its run loop, and keeps its switches by the machine
yaml's names, the coin door's EXIT as `exit` on both titles.  When the game first imports
pinproc, PinPROC is replaced by a thin stand-in that hands every call to the real board object
and, on each get_events(), asks the game's own `exit` switch whether it is active - the game's
own answer, with its own wiring (NC/NO) applied, so nothing is decoded here.  The switch is
found through whatever holds the board object and a `switches` collection (the game
controller), once the game has loaded its yaml.  The real pinproc (the C module on the
machine) and the emulator's (tools/proc_emu/pystub) are wrapped the same way.

WHAT IT NEVER DOES: raise into the game (every step is guarded; a failure leaves the game as it
is), fire twice, or restart a machine in PAD's emulator unless the rig hands it a stand-in
(CODESELECT_REBOOT), as padmenu.so does.

PADMENU_HOLD_MS / PADMENU_SWITCH (default "exit") / CODESELECT_REBOOT are for the tests and rig.
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
#: 3 s, or the card's back_hold= (padselect_proc.sh hands it in as PADMENU_HOLD_MS; 0 = off)
_HOLD = float(os.environ.get("PADMENU_HOLD_MS") or 3000) / 1000.0
_NAME = os.environ.get("PADMENU_SWITCH") or "exit"
_REBOOT_SH = ('sync; if [ "$(id -u)" = 0 ]; then exec ${CODESELECT_REBOOT:-reboot}; '
              'else exec ${CODESELECT_REBOOT:-sudo -n reboot}; fi')
_RIG_VARS = ("PROC_EMU_CTL", "PROC_EMU_FPGA", "SPP_LOG")
#: a file `debug` beside this one: say what it finds (a rig's run cannot pass variables in)
_DEBUG = os.path.exists(os.path.join(_HERE, "debug"))


def _say(msg):
    try:
        sys.stderr.write("padmenu: %s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def _restart():
    rb = os.environ.get("CODESELECT_REBOOT", "")
    if not rb and any(os.environ.get(v) for v in _RIG_VARS):
        _say("in the emulator with no CODESELECT_REBOOT - not restarting")
        return
    _say("EXIT held - restarting the machine into the boot menu")
    env = {"PATH": "/sbin:/usr/sbin:/bin:/usr/bin"}
    if rb:
        env["CODESELECT_REBOOT"] = rb
    try:
        import subprocess
        subprocess.Popen(["/bin/sh", "-c", _REBOOT_SH], env=env, close_fds=True,
                         preexec_fn=getattr(os, "setsid", None))
    except Exception as e:
        _say("could not start the restart: %s" % e)


class _Watch(object):
    def __init__(self):
        self.switch = None
        self.next_look = 0.0
        self.looks = 0
        self.since = None
        self.fired = False

    def find(self, board):
        """the game's own `exit` switch object: procgame's Switch (a name, a number and
        is_active()), found among the live objects once the game has loaded its yaml"""
        import gc
        for o in gc.get_objects():
            try:
                if (type(o).__name__ == "Switch" and getattr(o, "name", None) == _NAME
                        and callable(getattr(o, "is_active", None))):
                    return o
            except Exception:
                continue
        return None

    def tick(self, board):
        if self.fired or _HOLD <= 0:
            return
        if _DEBUG and not self.looks and self.switch is None:
            _say("debug: first get_events")
        now = time.time()
        if self.switch is None:
            if now < self.next_look or self.looks > 300:
                return
            self.looks += 1
            self.next_look = now + 2.0
            self.switch = self.find(board)
            if self.switch is None:
                if _DEBUG:
                    _say("debug: no switch named %s yet" % _NAME)
                return
            _say("watching %s (switch %s)" % (_NAME, getattr(self.switch, "number", "?")))
        try:
            active = bool(self.switch.is_active())
        except Exception:
            return
        if not active:
            self.since = None
            return
        if self.since is None:
            self.since = now
        elif now - self.since >= _HOLD:
            self.fired = True
            _restart()


def _wrap(mod):
    real = getattr(mod, "PinPROC", None)
    if real is None or getattr(real, "_padmenu", False):
        return

    class PinPROC(object):
        _padmenu = True

        def __init__(self, *a, **k):
            object.__setattr__(self, "_real", real(*a, **k))
            object.__setattr__(self, "_watch", _Watch())

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_real"), name)

        def __setattr__(self, name, value):
            setattr(object.__getattribute__(self, "_real"), name, value)

        def get_events(self, *a, **k):
            events = object.__getattribute__(self, "_real").get_events(*a, **k)
            try:
                object.__getattribute__(self, "_watch").tick(self)
            except Exception:
                pass
            return events

    mod.PinPROC = PinPROC


class _Finder(object):
    """the first `import pinproc` loads the real module, then wraps its PinPROC"""

    def find_module(self, name, path=None):
        return self if name == "pinproc" else None

    def load_module(self, name):
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        mod = __import__(name)
        if _DEBUG:
            _say("debug: pinproc from %s" % getattr(mod, "__file__", "?"))
        try:
            _wrap(mod)
        except Exception as e:
            _say("not watching EXIT: %s" % e)
        return mod

    # Python 3's import system asks for find_spec; these games are 2.7, so stay out of its way
    def find_spec(self, *a, **k):
        return None


if "pinproc" in sys.modules:
    try:
        _wrap(sys.modules["pinproc"])
    except Exception:
        pass
elif sys.version_info[0] == 2:
    sys.meta_path.insert(0, _Finder())


def _chain():
    """the machine's own sitecustomize, if it has one, still runs"""
    try:
        import imp
        paths = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
        f, pth, desc = imp.find_module("sitecustomize", paths)
        try:
            imp.load_module("_pad_next_sitecustomize", f, pth, desc)
        finally:
            if f:
                f.close()
    except Exception:
        pass


_chain()
