"""PAD-664: a blocks mode played on the desk, to word its rules for the printable rules sheet.

The rules sheet (:mod:`.rules_sheet`) says how a mode starts (which shot, how many hits for the 1st, 2nd and 3rd
start) and what its stages ask for. A program says that only in its blocks, and the same rule is built many ways
(a hits count, a counter of its own, a light at a shot, a level that climbs), so instead of reading the blocks for
patterns the sheet PLAYS them: this module runs a program's hats and blocks the way its C does (variables and their
resets, timers in ms, the clock, a light at a shot, the shots it lights), and the sheet's player makes shots and
watches what happens - the hit that starts the mode, the stage it moves to, the shots it lights, the clock it sets.

Only what the rules depend on is modelled: no screens, sounds, lights shows or mechanisms (their blocks do nothing
here). One player, one ball at a time unless a Multiball block serves more. Everything is integer arithmetic, as the
C's is (a division by 0 is 0).
"""
from __future__ import annotations

from . import block_modes as BM


#: blocks run for one event at most (a program that loops through its timers is cut off, never hangs the app)
STEP_LIMIT = 20000


class Sim:
    """One game of one blocks program. ``stock``: one of the game's own modes runs (the "stock" condition)."""

    def __init__(self, program):
        self.p = program
        self.scripts = [s for s in program.get("scripts") or [] if isinstance(s, dict)]
        self.var_reset = {}
        for v in program.get("vars") or []:
            if isinstance(v, dict) and v.get("name"):
                self.var_reset[v["name"]] = v.get("reset") or "mode"
        self.vars = {}
        self.hits = {}
        self.timers = {}                # name -> due ms
        self.now = 0
        self.running = False
        self.lit = None                 # the shot the mode is lit at
        self.lit_shots = {}             # shot -> pattern, while the mode runs
        self.clock = 0                  # ms left on the mode's clock
        self.has_clock = int(program.get("seconds") or 0) > 0   # 0 seconds: no clock, it runs until a block ends it
        self.balls = 1
        self.stock = False
        self.points = 0
        self.scored = 0
        self.starts = 0
        self.ends = 0
        self.ended_how = ""             # "time", "block" (an End the mode block), "drain"
        self.hud = {"title": "", "line": ""}
        self.events = []                # (kind, detail) of everything the sheet's player looks at
        self._every = {}                # hat index -> next due ms
        self._steps = 0
        self.combo_ring = []            # PAD-708: the last shots, newest first: (name, the shots lit then, ms)
        self.chain = 0                  # PAD-708: the combos in a row
        self.chain_at = None            # ... when the last was made, and its window
        self.chain_ms = 0
        self.new_game()

    # ---------------------------------------------------------------- the game around the mode
    def copy(self):
        """The game as it stands, to try a shot on (the program itself is shared, never copied)."""
        out = Sim.__new__(Sim)
        out.__dict__.update(self.__dict__)
        for key in ("vars", "hits", "timers", "lit_shots", "hud", "_every"):
            setattr(out, key, dict(getattr(self, key)))
        out.events = list(self.events)
        out.combo_ring = list(self.combo_ring)
        return out

    def new_game(self):
        for name in self.var_reset:
            self.vars[name] = 0
        self.new_ball()

    def new_ball(self):
        if self.running and self.p.get("ends_on_drain", True):    # PAD-708: as the C (a mode may run on)
            self.end("drain")
        for name, reset in self.var_reset.items():
            if reset == "ball":
                self.vars[name] = 0
        self.hits = {}
        self.timers = {}
        self.balls = 1
        self.combo_clear()

    # ---------------------------------------------------------------- PAD-708: combos, as the C judges them
    def combo_clear(self):
        self.combo_ring = []
        self.chain, self.chain_at = 0, None

    def _combo_made(self, hat, j):
        steps = BM.combo_steps(hat)[:BM.COMBO_STEPS_MAX]
        if j < 1 or j > len(self.combo_ring) or j > len(steps):
            return False
        ms = BM.combo_ms(hat)
        for s in range(j):
            e = j - 1 - s
            name, lit, at = self.combo_ring[e]
            step = steps[s]
            if not (step == BM.COMBO_ANY or step == BM.COMBO_LIT and name in lit or step == name):
                return False
            if s and at - self.combo_ring[e + 1][2] > ms:
                return False
        return True

    def combo_steps(self, hat):
        """A combo's shots made so far (combo_made_so_far in the C)."""
        n = len(BM.combo_steps(hat))
        if not self.combo_ring or n < 2 or self.now - self.combo_ring[0][2] > BM.combo_ms(hat):
            return 0
        for j in range(n - 1, 0, -1):
            if self._combo_made(hat, j):
                return j
        return 0

    def in_row(self):
        if self.chain_at is None or self.now - self.chain_at > self.chain_ms:
            return 0
        return self.chain

    def _combo_shot(self, name, was):
        """The shot into the ring; the scripts of the combos it makes (their When holding), as the C's combo_shot."""
        self.combo_ring.insert(0, (name, set(self.lit_shots), self.now))
        del self.combo_ring[BM.COMBO_STEPS_MAX:]
        fired, win = set(), 0
        for i, s in enumerate(self.scripts[:]):
            h = s.get("hat") or {}
            if h.get("kind") != "combo" or not self._when(h, was) or len(BM.combo_steps(h)) < 2:
                continue
            if self._combo_made(h, len(BM.combo_steps(h))):
                fired.add(i)
                win = max(win, BM.combo_ms(h))
        if fired:
            self.chain = self.in_row() + 1
            self.chain_at, self.chain_ms = self.now, win
            self.events.append(("combo", self.chain))
        return fired

    def shot(self, name):
        """The player makes ``name``. Returns True when the mode started on it."""
        before = self.starts
        was_lit = self.lit                      # a light this shot puts on waits for the next
        self._steps = 0
        self.hits[name] = self.hits.get(name, 0) + 1
        was = self.running                      # PAD-708: judged by the mode's state before the shot, as the C
        fired = self._combo_shot(name, was)     # ... and its combos before any script runs
        for i, s in enumerate(self.scripts):
            h = s.get("hat") or {}
            if h.get("kind") == "shot" and h.get("shot") == name and self._when(h, was) \
                    or h.get("kind") in ("any_shot", "switch") and self._when(h, was):   # PAD-675: a shot's switch too
                self.run(s.get("do"))
            elif h.get("kind") == "combo" and i in fired:
                self.events.append(("combo_made", i))
                self.run(s.get("do"))
        if not self.running and was_lit == name and self.lit == name:
            self.start()
        return self.starts > before

    def switches(self, n=1):
        """PAD-675: ``n`` playfield switch hits that are no shot (a slingshot, a pop)."""
        for _ in range(int(n)):
            self._steps = 0
            for s in self.scripts:
                h = s.get("hat") or {}
                if h.get("kind") == "switch" and self._when(h):
                    self.run(s.get("do"))

    def advance(self, ms):
        """``ms`` of the game go by: timers run out, Every hats tick, the clock runs down."""
        end = self.now + ms
        while True:
            due = []
            for name, at in self.timers.items():
                due.append((at, 0, name))
            if self.running:
                for i, at in self._every.items():
                    due.append((at, 1, i))
                if self.has_clock:
                    due.append((self.now + self.clock, 2, None))
            due = [d for d in due if d[0] <= end]
            if not due:
                break
            at, kind, what = min(due, key=lambda d: (d[0], d[1]))
            self._tick_clock(at)
            self._steps = 0
            if kind == 0:
                del self.timers[what]
                for s in self.scripts:
                    h = s.get("hat") or {}
                    if h.get("kind") == "timer_done" and h.get("timer") == what:
                        self.run(s.get("do"))
            elif kind == 1:
                h = self.scripts[what].get("hat") or {}
                self._every[what] = at + max(1, int(_num(h.get("seconds"), 1) * 1000))
                self.run(self.scripts[what].get("do"))
            else:
                self.end("time")
        self._tick_clock(end)

    def _tick_clock(self, at):
        if at <= self.now:
            return
        if self.running and self.has_clock:
            before = self.clock
            self.clock = max(0, self.clock - (at - self.now))
            for s in self.scripts:
                h = s.get("hat") or {}
                if h.get("kind") == "seconds_left":
                    mark = int(_num(h.get("seconds"), 0) * 1000)
                    if before > mark >= self.clock:
                        self.run(s.get("do"))
        self.now = at

    def _when(self, hat, running=None):
        w = hat.get("when") or "any"
        return w == "any" or (w == "running") == (self.running if running is None else running)

    # ---------------------------------------------------------------- the mode
    def can_start(self):
        if self.running:
            return False
        if self.p.get("wait_multiball") and (self.stock or self.balls > 1):
            return False
        if self.p.get("game_modes") in ("block", "give_way") and self.stock:
            return False
        return True

    def start(self):
        if not self.can_start():
            return
        self.running = True
        self.lit = None
        self.starts += 1
        self.clock = int(self.p.get("seconds") or 0) * 1000
        self.lit_shots = {}
        self.scored = 0
        self.points = 0
        self.hud = {"title": "", "line": ""}
        self.combo_clear()                      # PAD-708
        for name, reset in self.var_reset.items():
            if reset == "mode":
                self.vars[name] = 0
        self._every = {i: self.now + max(1, int(_num((s.get("hat") or {}).get("seconds"), 1) * 1000))
                       for i, s in enumerate(self.scripts) if (s.get("hat") or {}).get("kind") == "every"}
        self.events.append(("start", self.starts))
        for s in self.scripts:
            if (s.get("hat") or {}).get("kind") == "mode_start":
                self.run(s.get("do"))

    def end(self, how):
        if not self.running:
            return
        self.running = False
        self.ends += 1
        self.ended_how = how
        self.events.append(("end", how))
        for s in self.scripts:
            if (s.get("hat") or {}).get("kind") == "mode_end":
                self.run(s.get("do"))
        self.combo_clear()                      # PAD-708
        self.lit_shots = {}
        self.balls = 1

    # ---------------------------------------------------------------- the blocks
    def run(self, stack):
        for b in stack or []:
            if not isinstance(b, dict):
                continue
            self._steps += 1
            if self._steps > STEP_LIMIT:
                return
            op = b.get("op")
            if op == "if":
                if self.cond(b.get("cond")):
                    self.run(b.get("then"))
                elif b.get("else") is not None:
                    self.run(b.get("else"))
            elif op == "start_mode":
                self.start()
            elif op == "end_mode":
                self.end("block")
            elif op == "score":
                if self.running:
                    self.points += self.val(b.get("points"))
                    self.scored += 1
                self.events.append(("score", self.val(b.get("points"))))
            elif op == "set":
                self.vars[b.get("var")] = self.val(b.get("value"))
            elif op == "change":
                self.vars[b.get("var")] = self.vars.get(b.get("var"), 0) + self.val(b.get("by"))
            elif op == "set_hits":
                self.hits[b.get("shot")] = max(0, self.val(b.get("value")))
            elif op == "light_shot":
                shot = b.get("shot")
                if shot:
                    if b.get("pattern") == "off":
                        self.lit_shots.pop(shot, None)
                    else:
                        self.lit_shots[shot] = b.get("pattern") or "solid"
            elif op == "lights_off":
                if b.get("shot") == "*":
                    self.lit_shots = {}
                elif b.get("shot"):
                    self.lit_shots.pop(b.get("shot"), None)
            elif op == "add_time":
                if self.running and self.has_clock:
                    self.clock += self.val(b.get("seconds")) * 1000
            elif op == "set_time":
                if self.running and self.has_clock:
                    ms = self.val(b.get("seconds")) * 1000
                    self.clock = max(self.clock, ms) if b.get("at_least") else ms
                    self.events.append(("clock", ms // 1000, bool(b.get("at_least"))))
            elif op == "ball_save":
                self.events.append(("ball_save", b.get("seconds")))
            elif op == "multiball":
                try:
                    self.balls = max(self.balls, int(b.get("balls") or 1))
                except (TypeError, ValueError):
                    pass
                self.events.append(("multiball", self.balls))
            elif op == "timer_start":
                ms = max(0, self.val(b.get("ms")))
                self.timers[b.get("timer")] = self.now + max(1, ms)
                self.events.append(("timer", b.get("timer"), ms))
            elif op == "timer_stop":
                self.timers.pop(b.get("timer"), None)
            elif op == "hud_text":
                which = "title" if b.get("which") == "title" else "line"
                self.hud[which] = str(b.get("text") or "")
                self.events.append(("hud_" + which, self.hud[which]))
            elif op == "hud_award":
                self.events.append(("award", str(b.get("text") or "")))
            elif op == "light_mode":
                if not self.running and b.get("shot"):
                    self.lit = b.get("shot")
                    self.events.append(("lit", self.lit))
            elif op == "unlight_mode":
                if not b.get("mode"):
                    self.lit = None

    def val(self, e):
        if not isinstance(e, dict):
            return _num(e, 0)
        k = e.get("k")
        if k == "num":
            return _num(e.get("v"), 0)
        if k == "var":
            return self.vars.get(e.get("name"), 0)
        if k == "hits":
            return self.hits.get(e.get("shot"), 0)
        if k == "scored":
            return self.scored
        if k == "total":
            return self.points
        if k == "secs_left":
            return self.clock // 1000 if self.running and self.has_clock else 0
        if k == "balls":
            return self.balls
        if k == "player":
            return 1
        if k == "timer_left":
            at = self.timers.get(e.get("timer"))
            return max(0, at - self.now) if at is not None else 0
        if k == "combo_chain":                  # PAD-708
            return self.in_row()
        if k == "combo_steps":
            name = str(e.get("combo") or "").strip().lower()
            for s in self.scripts:
                h = s.get("hat") or {}
                if h.get("kind") == "combo" and str(h.get("name") or "").strip().lower() == name:
                    return self.combo_steps(h)
            return 0
        if k == "op":
            a, b = self.val(e.get("a")), self.val(e.get("b"))
            op = e.get("op")
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                return 0 if b == 0 else int(a / b)
            return 0
        return 1 if self.cond(e) else 0

    def cond(self, e):
        if not isinstance(e, dict):
            return False
        k = e.get("k")
        if k == "cmp":
            a, b = self.val(e.get("a")), self.val(e.get("b"))
            return {"<": a < b, "<=": a <= b, "=": a == b, "!=": a != b, ">=": a >= b,
                    ">": a > b}.get(e.get("op"), False)
        if k == "and":
            return self.cond(e.get("a")) and self.cond(e.get("b"))
        if k == "or":
            return self.cond(e.get("a")) or self.cond(e.get("b"))
        if k == "not":
            return not self.cond(e.get("a"))
        if k == "running":
            return self.running
        if k == "stock":
            return self.stock
        if k == "can_start":
            return self.can_start()
        if k == "lit":
            return self.lit is not None
        if k == "shields_away":
            return bool(getattr(self, "shields_away", False))
        return bool(self.val(e))


def _num(v, default):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def walk(stack):
    """Every block of a stack, the ones inside an If's branches too."""
    for b in stack or []:
        if not isinstance(b, dict):
            continue
        yield b
        if b.get("op") == "if":
            yield from walk(b.get("then"))
            yield from walk(b.get("else"))


def walk_value(e):
    """Every value and condition inside ``e``."""
    if not isinstance(e, dict):
        return
    yield e
    for key in ("a", "b", "cond"):
        yield from walk_value(e.get(key))
