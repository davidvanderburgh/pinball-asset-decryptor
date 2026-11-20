"""padmodes_proc.py - PAD's custom mode runtime for Spooky's P-ROC titles (SkeletonGame on
pyprocgame, Python 2.7): Rick and Morty (PAD-1420; the PAD-1387 probe made into the runtime) and
Alice Cooper's Nightmare Castle (PAD-1421: its screen is a Unity player, see "Alice Cooper's screen").
Written so Python 3 reads it too (the app's tests drive its mode logic with a stand-in game).

HOW IT GETS INTO THE GAME.  The update carries this file as ``pad/padmodes_proc.py`` (with an
empty ``pad/__init__.py`` and the mode folder ``pad/modes``) in the game's folder, and ONE line
added to the folder's ``config.yaml``:

    pinproc_class: pad.padmodes_proc.PinPROC

procgame's GameController.create_pinproc() builds the board object from that key through
procgame.util.get_class(), which ``__import__``s ``pad.padmodes_proc`` from the game's folder
(sys.path[0]: the machine runs ``python RMGame.pyc`` from it) before the game has built anything.
PinPROC() hands back the machine's own ``pinproc.PinPROC``: the game drives the same board it
always did.  The caller's frame holds the game; once its __init__ is over (run_proc_game calls
game.run_loop) the runtime adds ONE mode of ours, PadRuntime: an AdvancedMode of type Game,
which SkeletonGame adds itself at every game start and takes out at the game's end.  No game
file changes but config.yaml; a stock update brings the stock config.yaml back, and the modes
are out.

WHAT IT RUNS: every ``pad/modes/*.mode`` (title.cfg + *.mode, the JJP keys tools/jjp_emu/MODES.md
describes; the ones taken here are mkspkmodes.py's KEYS):

  start / start_count   the game's switches that start it, and how many hits it takes
  shots / points        the switches that score while it runs, and what each scores
  seconds               how long it runs (0: until the ball ends)
  complete / complete_points   shots that complete it, and the bonus for that
  sound_start/_shot/_complete/_end   the game's own sounds (game.sound: a voice goes to the
                                     voice channel, queued behind what it is saying)
  title, panel, fonts, colors        a panel over the game's screen, in the game's HD fonts (Alice
                                     Cooper: the game's own text on its Unity player, no fonts)

Switches: the game's own switch handlers (add_switch_handler, active), only while a ball is in
play (not tilted, no service mode); ours never stop a switch for the game's modes.  Points go
through the game's own RMGame.score, which applies the playfield multiplier and rounds up to
100, as for the game's own awards.  A mode ends on time, on completion, at the end of the ball
(evt_ball_ending), on tilt (evt_tilt) and when the game ends; start counts reset at every new
game.  ``pad/modes/off`` turns them all off.

WHAT IT NEVER DOES: raise into the game.  Every step is guarded; a failure is logged and the
game runs stock.  SkeletonGame keeps only a weakref to a mode (notifyOfNewMode), so this module
holds PadRuntime itself (an unheld one was collected and Start crashed the game).

PADMODES_PORT=<file>: also write the title's port report there (switches with their labels,
lights, the sounds of config/asset_list.yaml, the game's modes, the HD fonts) and, at the first
ball of a game, measure the points scale (one 1,000-point game.score) into it.
Log: PAD_MODES_LOG, else pad/padmodes.log (else /tmp/pad_modes.log).
"""
import json
import os
import sys
import time
import traceback

VERSION = "1"
_HERE = os.path.dirname(os.path.abspath(__file__))
MODE_DIR = os.path.join(_HERE, "modes")
PLACES = {"top": 0.04, "middle": 0.36, "bottom": 0.68}
#: the priority of our mode: above every game mode that may stop a switch (the game's own go
#: up to 9000, service mode; its tilt mode is 99998 and must stay above us)
PRIORITY = 9500
_state = {"game": None, "made": False, "runtime": None, "log": None}


# ============================================================================ log
def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    for p in _log_paths():
        try:
            with open(p, "a") as f:
                f.write(line)
            _state["log"] = p
            return
        except (IOError, OSError):
            continue


def _log_paths():
    if _state["log"]:
        return [_state["log"]]
    env = os.environ.get("PAD_MODES_LOG")
    return [env] if env else [os.path.join(_HERE, "padmodes.log"), "/tmp/pad_modes.log"]


# ============================================================================ the way in
def PinPROC(machine_type, *a, **k):
    """procgame's pinproc_class: the machine's own board object, with our hook set."""
    import pinproc
    proc = pinproc.PinPROC(machine_type, *a, **k)
    try:
        game = sys._getframe(1).f_locals.get("self")    # GameController.create_pinproc
        _state["game"] = game
        log("loaded: PadModes runtime %s from %s into %s (%s)"
            % (VERSION, __file__, type(game).__name__, sys.argv[0]))
        _hook_run_loop(game)
    except Exception:
        log("hook failed, the game runs stock: %s" % traceback.format_exc())
    return proc


def _hook_run_loop(game):
    orig = game.run_loop

    def run_loop(*a, **k):
        try:
            join(game)
        except Exception:
            log("the modes failed, the game runs stock: %s" % traceback.format_exc())
        return orig(*a, **k)

    game.run_loop = run_loop      # run_proc_game: game = game_class(); game.run_loop(...)


def join(game, mode_dir=None):
    """Read the mode files and add PadRuntime to the game (once)."""
    if _state["made"]:
        return _state["runtime"]
    _state["made"] = True
    modes, title = load_modes(game, mode_dir or MODE_DIR)
    port = os.environ.get("PADMODES_PORT", "")
    if not modes and not port:
        return None
    rt = make_runtime(game, modes, title, port)
    _state["runtime"] = rt                    # SkeletonGame holds only a weakref
    known = sum(len(v) for v in getattr(game, "known_modes", {}).values())
    log("PadModes joined the game: %d custom mode(s); PadRuntime (AdvancedMode.Game, priority %d) "
        "beside %d game modes" % (len(modes), PRIORITY, known))
    if port:
        rt.write_port()
    return rt


# ============================================================================ the mode files
def parse(text):
    d = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s[0] in "#;" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if " #" in v:
            v = v[:v.index(" #")].strip()
        d[k.strip()] = v
    return d


def to_int(s, default=0):
    s = (s or "").replace(",", "").replace("_", "").strip()
    try:
        return int(s)
    except ValueError:
        return default


def _read(path):
    with open(path) as f:
        return f.read()


def load_modes(game, d):
    """[mode dict] from the folder, as the check (mkspkmodes.py) reads it; ([], {}) when off."""
    if not os.path.isdir(d):
        log("no mode folder %s: no custom modes" % d)
        return [], {}
    if os.path.exists(os.path.join(d, "off")):
        log("%s/off is there: custom modes are off" % d)
        return [], {}
    title = parse(_read(os.path.join(d, "title.cfg"))) if os.path.isfile(os.path.join(d, "title.cfg")) else {}
    out = []
    for fn in sorted(f for f in os.listdir(d) if f.endswith(".mode")):
        cfg = dict(title)
        cfg.update(parse(_read(os.path.join(d, fn))))
        m = {
            "file": fn, "cfg": cfg, "name": cfg.get("name") or fn[:-5],
            "start": switches(game, fn, "start", cfg.get("start", "")),
            "shots": switches(game, fn, "shots", cfg.get("shots", "")),
            "start_count": max(1, to_int(cfg.get("start_count"), 1)),
            "points": to_int(cfg.get("points"), 1000000),
            "seconds": to_int(cfg.get("seconds"), 20),
            "complete": to_int(cfg.get("complete"), 0),
            "complete_points": to_int(cfg.get("complete_points"), 0),
            "hits": 0, "running": False, "made": 0, "total": 0, "left": 0.0,
        }
        m["title"] = cfg.get("title") or m["name"]
        start_rules(game, fn, m, cfg)
        out.append(m)
        log('mode %s "%s": start %s x%d, shots %s, %d points, %s, complete %d (+%d)' % (
            fn, m["name"], " ".join(m["start"]) or "-", m["start_count"], " ".join(m["shots"]) or "-",
            m["points"], ("%d s" % m["seconds"]) if m["seconds"] > 0 else "until the ball ends",
            m["complete"], m["complete_points"]))
    log("%d custom mode(s) from %s" % (len(out), d))
    return out, title


def start_rules(game, fn, m, cfg):
    """PAD-1424: JJP's start rules (MODES.md "Start rules from the game's hook lists")."""
    m["combo"] = switches(game, fn, "start_combo", cfg.get("start_combo", ""))
    m["combo_seconds"] = max(1, to_int(cfg.get("combo_seconds"), 5))
    m["start_score"] = to_int(cfg.get("start_score"), 0)
    m["start_on"] = set(w.lower() for w in cfg.get("start_on", "").replace(",", " ").split())
    m["start_after"] = set(w.lower() for w in cfg.get("start_after", "").replace(",", " ").split())
    m["once"] = cfg.get("start_once") or "no"
    m["reset_ball"] = (cfg.get("start_count_reset") or "game") == "ball"
    m.update(combo_at=0, combo_time=0.0, ran_ball=False, ran_game=False, score_fired=set())
    if m["combo"] or m["start_on"] or m["start_after"] or m["start_score"] > 0:
        log("mode %s start rules: on %s; after %s; score %d; combo %s within %d s; once %s; count reset %s" % (
            fn, " ".join(sorted(m["start_on"])) or "-", " ".join(sorted(m["start_after"])) or "-",
            m["start_score"], " ".join(m["combo"]) or "-", m["combo_seconds"], m["once"],
            "ball" if m["reset_ball"] else "game"))


#: switches that are not the playfield (valid_playfield is the ball's first playfield switch)
NOT_PLAYFIELD = ("trough", "shooter", "plunge", "launch", "flipper", "start", "coin", "door", "tilt",
                 "slam", "outhole", "drain", "button", "service", "volume", "menu", "eject", "enter",
                 "exit", "up", "down")


def is_playfield(name):
    """By the switch's name: the trough, the shooter lane, the buttons and the coin door are not."""
    import re
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", name or "")   # leftInlane, slingRight, sw_1
    for w in words:
        w = w.lower()
        if any(w == x or (len(x) > 3 and w.startswith(x)) for x in NOT_PLAYFIELD):
            return False
    return bool(words)


def switches(game, fn, key, v):
    names = _switch_names(game)
    out = []
    for w in v.replace(",", " ").split():
        n = w if w in names else names.get(w.lower()) if not w.isdigit() else _by_number(game, w)
        if not n:
            log("%s: %s %s is not one of this game's switches (ignored)" % (fn, key, w))
        elif n not in out:
            out.append(n)
    return out


def _switch_names(game):
    d = {}
    for sw in _items(game.switches):
        d[sw.name] = sw.name
        d.setdefault(sw.name.lower(), sw.name)
    return d


def _by_number(game, w):
    for sw in _items(game.switches):
        if str(getattr(sw, "number", "")) == w:
            return sw.name
    return None


def _items(group):
    """The items of one of the game's collections (procgame's AttrCollection iterates them)."""
    try:
        return list(group or ())
    except TypeError:
        return []


# ============================================================================ the runtime mode
def make_runtime(game, modes, title, port=""):
    from procgame.game.advancedmode import AdvancedMode
    return _runtime_class(AdvancedMode)(game, modes, title, port)


def _runtime_class(base):
    class PadRuntime(base):
        """Every custom mode of the folder, inside one mode of the game's."""

        def __init__(self, game, modes, title, port=""):
            self.pad_modes = modes
            self.pad_title = title
            self.port_path = port
            self.ball_live = False
            self.shown = None
            self.measured = False
            self.voices = []            # [[key, sounds, asked at]] voices of ours not yet heard
            self.last_tick = None
            self.panel_key = None
            self.unity_sent = 0.0
            super(PadRuntime, self).__init__(game=game, priority=PRIORITY, mode_type=base.Game)
            self.valid_seen = False
            self.mb_since, self.mb_was = 0.0, False
            self.last_running = None
            self.extra_seen = -1
            self.rules_at = 0.0
            seen = []
            want_all = any("valid_playfield" in m.get("start_on", ()) for m in modes)
            names = list(_switch_names(game).values()) if want_all else []
            for m in modes:
                for n in m["start"] + m["shots"] + m.get("combo", []) + names:
                    if n not in seen:
                        seen.append(n)
                        self.add_switch_handler(name=n, event_type="active", delay=None, handler=self.pad_switch)
            self.layer = None
            log("switch handlers on %s" % (" ".join(seen) or "-"))

        # ------------------------------------------------------------ the game's events
        def mode_started(self):
            log("PadRuntime started with the game (mode queue)")

        def mode_stopped(self):
            self.pad_stop_all("the game ended")

        def evt_game_starting(self):
            self.ball_live = False
            for m in self.pad_modes:
                self.pad_stop(m, "")
                m["hits"] = 0
                m.update(combo_at=0, ran_game=False, score_fired=set())
            log("game starting: start counts reset")

        def evt_ball_starting(self):
            self.ball_live = True
            g = self.game
            ball, of = to_int(str(getattr(g, "ball", 0)), 0), to_int(str(getattr(g, "balls_per_game", 0)), 0)
            log("ball starting (ball %s of %s, player %d)" % (ball, of, _player_index(g) + 1))
            self.valid_seen = False
            self.mb_since, self.mb_was = 0.0, False
            self.last_running = None
            self.extra_seen = -1
            for m in self.pad_modes:
                m["ran_ball"], m["combo_at"] = False, 0
                if m.get("reset_ball"):
                    m["hits"] = 0
            self.pad_event("ball_start")
            if ball == 1:
                self.pad_event("first_ball")
            if ball > 0 and of > 0 and ball >= of and _extra_balls(g) <= 0:
                self.pad_event("last_ball")
            if self.port_path and not self.measured:
                self.measured = True
                before = pad_score(self.game)
                got = pad_award(self.game, 1000)    # the score's change: a title's score() may return None
                log("points scale: game.score(1000) scored %r (score %r -> %r, multiplier %r)" % (
                    got, before, pad_score(self.game), getattr(self.game, "multiplier", 1)))
                self.write_port(got)

        def evt_ball_saved(self):
            self.pad_event("ball_saved")

        def evt_ball_ending(self, args=None):
            self.pad_stop_all("the ball ended")

        def evt_tilt_ball_ending(self):
            self.pad_stop_all("the ball ended (tilt)")

        def evt_tilt(self, slam=None):
            self.pad_stop_all("slam tilt" if slam else "tilt")

        def evt_game_ending(self):
            self.pad_stop_all("the game ended")

        # ------------------------------------------------------------ switches
        def pad_playing(self):
            g = self.game
            if not self.ball_live or getattr(g, "game_tilted", False) or g.current_player() is None:
                return False
            sm = getattr(g, "service_mode", None)
            return not (sm is not None and sm in g.modes)

        def pad_switch(self, sw):
            try:
                if self.pad_playing():
                    now = time.time()
                    if not self.valid_seen and is_playfield(sw.name):
                        self.valid_seen = True
                        self.pad_event("valid_playfield")
                    for m in self.pad_modes:
                        if m["running"]:
                            if sw.name in m["shots"]:
                                self.pad_shot(m, sw.name)
                            continue
                        self.pad_combo(m, sw.name, now)
                        if not m["running"] and sw.name in m["start"]:
                            self.pad_fire(m, "start switch %s hit" % sw.name)
            except Exception:
                log("switch %s failed: %s" % (getattr(sw, "name", sw), traceback.format_exc()))
            return None             # SwitchContinue: the game's own modes still see the switch

        # ------------------------------------------------------------ start rules (PAD-1424)
        def pad_fire(self, m, why):
            """A start rule fired for m: one more toward its start_count."""
            if m["running"] or not self.pad_playing():
                return
            if (m.get("once") == "ball" and m.get("ran_ball")) or (m.get("once") == "game" and m.get("ran_game")):
                return
            m["hits"] += 1
            log("%s: %s (%d of %d)" % (m["name"], why, m["hits"], m["start_count"]))
            if m["hits"] >= m["start_count"]:
                self.pad_start(m)

        def pad_event(self, ev):
            """start_on: ball_start, first_ball, last_ball, valid_playfield, ball_saved, extra_ball,
            multiball_end."""
            log("game event %s" % ev)
            for m in self.pad_modes:
                if ev in m.get("start_on", ()):
                    self.pad_fire(m, "start_on %s" % ev)

        def pad_combo(self, m, name, now):
            combo = m.get("combo") or []
            if len(combo) < 2 or m["running"]:
                return
            if m["combo_at"] > 0 and now - m["combo_time"] > m["combo_seconds"]:
                m["combo_at"] = 0
            if combo[m["combo_at"]] == name:
                m["combo_at"] += 1
                m["combo_time"] = now
            elif combo[0] == name:
                m["combo_at"], m["combo_time"] = 1, now
            if m["combo_at"] >= len(combo):
                m["combo_at"] = 0
                self.pad_fire(m, "start_combo made")

        def pad_rules(self, now):
            """Ten times a second in a ball: the score, extra balls, the balls in play (a
            multiball's end) and the game's running modes (start_after)."""
            if not self.pad_playing() or now - self.rules_at < 0.1:
                return
            self.rules_at = now
            g = self.game
            player, score = _player_index(g), pad_score(g)
            for m in self.pad_modes:
                if m.get("start_score", 0) > 0 and score >= m["start_score"] and player not in m["score_fired"]:
                    m["score_fired"].add(player)
                    self.pad_fire(m, "start_score %d reached (%d)" % (m["start_score"], score))
            extra = _extra_balls(g)
            if extra >= 0:
                if self.extra_seen >= 0 and extra > self.extra_seen:
                    self.pad_event("extra_ball")
                self.extra_seen = extra
            in_play = _balls_in_play(g)
            if in_play > 1:
                if not self.mb_since:
                    self.mb_since = now
                if now - self.mb_since >= 0.5:
                    self.mb_was = True
            else:
                self.mb_since = 0.0
                if self.mb_was and in_play >= 0:
                    self.mb_was = False
                    self.pad_event("multiball_end")
            if not any(m.get("start_after") for m in self.pad_modes):
                return
            running = set(n.lower() for n in _running_modes(g, self))
            if self.last_running is not None:
                for ended in sorted(self.last_running - running):
                    for m in self.pad_modes:
                        if ended in m["start_after"] or "any" in m["start_after"]:
                            self.pad_fire(m, "start_after %s ended" % ended)
            self.last_running = running

        def pad_start(self, m):
            m["hits"], m["running"], m["made"], m["total"] = 0, True, 0, 0
            m["combo_at"], m["ran_ball"], m["ran_game"] = 0, True, True
            m["left"] = float(m["seconds"])
            log("%s: STARTED (%s)" % (m["name"], ("%d s" % m["seconds"]) if m["seconds"] > 0 else "until the ball ends"))
            self.pad_sound(m, "sound_start")
            self.shown = m
            self.pad_draw()

        def pad_shot(self, m, name):
            got = pad_award(self.game, m["points"])
            m["made"] += 1
            m["total"] += got
            log("%s: shot %d%s on %s: %d points (player score %s)" % (
                m["name"], m["made"], (" of %d" % m["complete"]) if m["complete"] > 0 else "", name, got,
                pad_score(self.game)))
            self.pad_sound(m, "sound_shot")
            self.shown = m
            if m["complete"] > 0 and m["made"] >= m["complete"]:
                bonus = pad_award(self.game, m["complete_points"]) if m["complete_points"] > 0 else 0
                m["total"] += bonus
                log("%s: COMPLETED, bonus %d, mode total %d" % (m["name"], bonus, m["total"]))
                self.pad_sound(m, "sound_complete")
                self.pad_stop(m, "")
                return
            self.pad_draw()

        def pad_stop(self, m, why):
            if not m["running"]:
                return
            m["running"] = False
            if why:
                log("%s: ended (%s), %d shot(s), total %d" % (m["name"], why, m["made"], m["total"]))
                self.pad_sound(m, "sound_end")
            if self.shown is m:
                self.shown = next((x for x in self.pad_modes if x["running"]), None)
            self.pad_draw()

        def pad_stop_all(self, why):
            self.ball_live = False
            for m in self.pad_modes:
                self.pad_stop(m, why)

        # ------------------------------------------------------------ time
        def mode_tick(self):
            try:
                now = time.time()
                dt = 0.0 if self.last_tick is None else min(1.0, now - self.last_tick)
                self.last_tick = now
                if self.voices:
                    self.pad_watch_voices()
                self.pad_rules(now)
                for m in self.pad_modes:
                    if m["running"] and m["seconds"] > 0:
                        m["left"] -= dt
                        if m["left"] <= 0:
                            self.pad_stop(m, "time ran out")
                if self.shown is not None and self.shown["running"] and (
                        self.shown["seconds"] > 0 or unity_client(self.game) is not None):
                    self.pad_draw(timer_only=True)
            except Exception:
                log("tick failed: %s" % traceback.format_exc())
            return super(PadRuntime, self).mode_tick()

        # ------------------------------------------------------------ sounds
        def pad_sound(self, m, key):
            name = m["cfg"].get(key, "")
            if not name:
                return
            try:
                snd = self.game.sound
                entry = snd.sounds.get(name)
                if entry is None:
                    log("%s: %s %s: no such sound in this game" % (m["name"], key, name))
                    return
                if entry.get("is_voice"):
                    busy = _voice_busy()
                    snd.play_voice(name)
                    log("%s: %s %s to the game's voice channel%s" % (m["name"], key, name,
                                                                   ", queued" if busy else ""))
                    self.voices.append([name, list(entry.get("sound_list") or ()), time.time()])
                else:
                    snd.play(name)
                    log("%s: %s %s played as a sound effect (game.sound.play)" % (m["name"], key, name))
            except Exception:
                log("%s: %s %s failed: %s" % (m["name"], key, name, traceback.format_exc()))

        def pad_watch_voices(self):
            playing = _voice_now()
            while self.voices:
                key, sounds, at = self.voices[0]
                if playing is not None and any(playing is s for s in sounds):
                    log("callout %s played on the game's voice channel" % key)
                elif time.time() - at > 30:
                    log("callout %s never played: the game dropped its voice queue" % key)
                else:
                    return
                self.voices.pop(0)

        # ------------------------------------------------------------ the panel
        def pad_draw(self, timer_only=False):
            try:
                self._pad_draw(timer_only)
            except Exception:
                log("panel failed: %s" % traceback.format_exc())
                self.layer = None

        def _pad_draw(self, timer_only):
            m = self.shown
            if m is None or not m["running"] or m["cfg"].get("panel", "middle") == "none":
                self.layer, self.panel_key = None, None
                tcp = unity_client(self.game)
                if tcp is not None and self.unity_sent:
                    unity_clear(tcp)
                    self.unity_sent = 0.0
                return
            secs = int(max(0.0, m["left"]) + 0.999) if m["seconds"] > 0 else -1
            key = (m["file"], m["title"], m["total"], secs)
            tcp = unity_client(self.game)
            if tcp is not None:
                now = time.time()
                if key == self.panel_key and now - self.unity_sent < UNITY_REFRESH:
                    return
                self.panel_key, self.unity_sent = key, now
                unity_panel(tcp, m, secs)
                return
            if key == self.panel_key:
                return
            self.panel_key = key
            self.layer = panel_layer(self.game, m, secs)

        # ------------------------------------------------------------ the port report
        def write_port(self, scored=None):
            try:
                p = port_report(self.game)
                if scored is not None:
                    p["points_scale_measured"] = {"asked": 1000, "scored": scored,
                                                  "multiplier": getattr(self.game, "multiplier", 1)}
                with open(self.port_path, "w") as f:
                    json.dump(p, f, indent=1, sort_keys=True)
                log("port report written to %s: %d switches, %d lamps, %d sounds (%d voice), %d game "
                    "modes, %d fonts" % (self.port_path, len(p["switches"]), len(p["lamps"]), len(p["sounds"]),
                                         p["voice_lines"], len(p["game_modes"]), len(p["fonts"])))
            except Exception:
                log("port report failed: %s" % traceback.format_exc())

    return PadRuntime


# ============================================================================ the game's scoring
def _player_index(game):
    try:
        return int(getattr(game, "current_player_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _extra_balls(game):
    """The player up's extra balls (awarded, not yet played); -1 when there is no player."""
    try:
        p = game.current_player()
        return -1 if p is None else int(getattr(p, "extra_balls", 0) or 0)
    except Exception:
        return -1


def _balls_in_play(game):
    try:
        return int(game.trough.num_balls_in_play)
    except Exception:
        return -1


def _running_modes(game, ours=None):
    """The game's modes running now, by class name (the port report's game_modes).  Alice Cooper
    keeps some modes queued with modeStarted 0: those are not running."""
    out = []
    try:
        for md in list(game.modes):
            if md is ours or getattr(md, "modeStarted", 1) in (0, False):
                continue
            out.append(type(md).__name__)
    except Exception:
        pass
    return out


def pad_score(game):
    p = game.current_player()
    return p.score if p is not None else 0


def pad_award(game, points):
    before = pad_score(game)
    game.score(points)
    return pad_score(game) - before


# ============================================================================ the game's sounds
def _voice_channel():
    from procgame import sound as S
    from pygame import mixer
    return mixer.Channel(S.CH_VOICE)


def _voice_busy():
    try:
        return bool(_voice_channel().get_busy())
    except Exception:
        return False


def _voice_now():
    try:
        ch = _voice_channel()
        return ch.get_sound() if ch.get_busy() else None
    except Exception:
        return None


# ============================================================================ the panel
def colour(hexs, default=(255, 255, 255, 255)):
    h = (hexs or "").strip().lstrip("#")
    if len(h) not in (6, 8):
        return default
    try:
        v = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
    except ValueError:
        return default
    return tuple(v + [255] * (4 - len(v)))


def commas(n):
    return "{:,}".format(int(n))


def _font(game, name):
    fonts = getattr(game, "fonts", {}) or {}
    return fonts.get(name) or fonts.get("default") or (list(fonts.values())[0] if fonts else None)


def _fit(font, text, width, size):
    """The biggest size up to *size* at which *text* fits *width* in *font*."""
    from procgame.dmd.sdl2_displaymanager import sdl2_DisplayManager
    dm = sdl2_DisplayManager.inst()
    while size > 10 and dm.font_get_size(text, font.name, size)[0] > width:
        size -= 2
    return size, dm.font_get_size(text, font.name, size)


def panel_layer(game, m, secs):
    """The mode's panel: a box over the game's screen with its title, its total and its time
    left, each row in the game's own HD fonts, shrunk to its row."""
    from procgame import dmd
    cfg = m["cfg"]
    W, H = int(game.display_width), int(game.display_height)
    w, h = int(W * 0.56), int(H * 0.27)
    frame = dmd.Frame(w, h)
    frame.fill_rect(0, 0, w, h, colour(cfg.get("panel_color"), (0, 0, 0, 176)))
    rows = (("title", m["title"], 0.0, 0.45, "ffffff"), ("value", commas(m["total"]), 0.42, 0.36, "ffdc00"),
            ("timer", "" if secs < 0 else str(secs), 0.76, 0.24, "ffffff"))
    for k, text, y0, frac, col in rows:
        if not text:
            continue
        f = _font(game, cfg.get("font_" + k, ""))
        if f is None:
            continue
        size, (tw, th) = _fit(f, text, int(w * 0.92), int(h * frac * 0.78))
        c = colour(cfg.get(k + "_color"), colour(col))
        f.draw(frame, text, int((w - tw) / 2), int(h * y0 + (h * frac - th) / 2), c[:3], None, font_size=size)
    layer = dmd.FrameLayer(opaque=False, frame=frame)
    layer.set_target_position(int(W * 0.22), int(H * PLACES.get(cfg.get("panel", "middle"), 0.36)))
    return layer


# ============================================================================ the port report
def _asset_list(game):
    """config/asset_list.yaml (the game's own list of its sounds and fonts), or {}."""
    try:
        import yaml
        base = os.path.dirname(_HERE)
        with open(os.path.join(base, "config", "asset_list.yaml")) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        log("asset_list.yaml not read: %s" % traceback.format_exc().splitlines()[-1])
        return {}


def _machine_switches(game):
    """{name: label} from the machine yaml the game loaded (PRSwitches)."""
    cfg = getattr(game, "config", None) or {}
    out = {}
    try:
        for name, v in (cfg.get("PRSwitches") or {}).items():
            out[name] = (v or {}).get("label") or name
    except Exception:
        pass
    return out


def _switch_order(sw):
    n = getattr(sw, "number", None)
    return (0, n, sw.name) if isinstance(n, int) else (1, 0, sw.name)


def port_report(game):
    labels = _machine_switches(game)
    sws = sorted(_items(game.switches), key=_switch_order)
    sw = [s.name for s in sws]
    lamps = []
    for group in ("leds", "lamps"):
        for it in _items(getattr(game, group, None) or []):
            if it.name not in lamps:
                lamps.append(it.name)
    assets = _asset_list(game)
    audio = assets.get("Audio") or {}
    paths = {}
    for kind in ("Voice", "Effects", "Music"):
        for e in audio.get(kind) or ():
            if isinstance(e, dict) and e.get("key") and e.get("file"):
                paths.setdefault(e["key"], "%s/%s" % (kind.lower(), e["file"]))
    snd = getattr(game, "sound", None)
    sounds = getattr(snd, "sounds", {}) or {}
    voice = sorted(k for k, v in sounds.items() if v.get("is_voice"))
    effects = sorted(k for k, v in sounds.items() if not v.get("is_voice"))
    fonts = sorted((getattr(game, "fonts", {}) or {}).keys())
    font_files = {}
    hd = (assets.get("Fonts") or {}).get("HDFonts") or ()
    for e in hd:
        if isinstance(e, dict) and e.get("key") in fonts:
            font_files[e["key"]] = [e.get("file"), e.get("size")]
    modes, types = [], {}
    for t, lst in sorted((getattr(game, "known_modes", {}) or {}).items()):
        for ref in lst:
            m = ref()
            if m is not None and type(m).__name__ != "PadRuntime":
                modes.append(type(m).__name__)
                types[type(m).__name__] = [int(t), int(m.priority)]
    return {
        "engine": "proc", "runtime": VERSION, "game_class": type(game).__name__,
        "display": ([UNITY_W, UNITY_H] if unity_client(game) is not None else
                    [int(getattr(game, "display_width", 0)), int(getattr(game, "display_height", 0))]),
        "screen": "unity_player" if unity_client(game) is not None else "skeletongame",
        "switches": sw, "switch_ids": dict((s.name, getattr(s, "number", "")) for s in sws),
        "switch_labels": dict((s.name, labels.get(s.name, s.name)) for s in sws),
        "lamps": lamps, "sounds": voice + effects, "voice_lines": len(voice), "sound_paths": paths,
        "music": sorted(getattr(snd, "music", {}).keys()) if hasattr(snd, "music") else [],
        "game_modes": modes, "game_mode_types": types, "fonts": fonts, "font_files": font_files,
    }


# ============================================================================ Alice Cooper's screen
# Alice Cooper's Nightmare Castle (PAD-1421) draws nothing with SkeletonGame layers: its screen is a
# Unity player the game drives over TCP (game.tcpclient: ``||{'cmd':'APPEND_TEXT',...}`` messages to
# 127.0.0.1:9999).  Its panel is the game's own kind of text: rows on the player's 684x384 virtual
# screen (x 342 is the middle), each with a black copy 3 dots down-right one step behind it, as the
# game's hurry-up timer and high scores are drawn.  The player has one font and no boxes, so a mode
# on Alice Cooper takes no font_* and no panel_color (the check refuses them by name).
#
# The game clears what is on its screen as its own modes come and go (tcpclient.unload_assets at
# every mode start), so the rows are sent again once a second while a mode is shown.
UNITY_W, UNITY_H = 684, 384
UNITY_LAYER = "quick_layer"      # above base_layer (the room) and vid_layer (the game's mode videos)
UNITY_DEPTH = -300               # in front of the game's own quick_layer texts (-110 .. -290)
#: (row, size, dy from the place's y) - sizes in the player's text units (the hurry-up timer is 20)
UNITY_ROWS = (("title", 10, 0), ("value", 8, 34), ("timer", 7, 62))
UNITY_PLACES = {"top": 92, "middle": 160, "bottom": 262}
UNITY_REFRESH = 1.0


def unity_client(game):
    """The game's Unity player client (Alice Cooper), or None for a game drawing its own layers."""
    tcp = getattr(game, "tcpclient", None)
    return tcp if tcp is not None and hasattr(tcp, "append_text") else None


def unity_names():
    out = []
    for k, _s, _y in UNITY_ROWS:
        out += ["pad_" + k, "pad_" + k + "_b"]
    return out


def unity_clear(tcp):
    for n in unity_names():
        tcp.remove_text(n)


def unity_panel(tcp, m, secs):
    """Send the mode's panel to the Unity player: its rows, each with its shadow."""
    cfg = m["cfg"]
    y0 = UNITY_PLACES.get(cfg.get("panel", "middle"), UNITY_PLACES["middle"])
    rows = {"title": (m["title"], "ffffff"), "value": (commas(m["total"]), "ffdc00"),
            "timer": ("" if secs < 0 else str(secs), "ffffff")}
    unity_clear(tcp)
    for k, size, dy in UNITY_ROWS:
        text, col = rows[k]
        if not text:
            continue
        text = text.replace("'", "").replace("\\", "")       # the message is a quoted dict
        r, g, b = [c / 255.0 for c in colour(cfg.get(k + "_color"), colour(col))[:3]]
        y = y0 + dy
        tcp.append_text("pad_" + k + "_b", UNITY_W // 2 + 3, y + 3, UNITY_DEPTH + 1, text, size,
                        0, 0, 0, justify="center", layer=UNITY_LAYER)
        tcp.append_text("pad_" + k, UNITY_W // 2, y, UNITY_DEPTH, text, size, r, g, b,
                        justify="center", layer=UNITY_LAYER)
