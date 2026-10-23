"""PAD-664: the printable rules sheet of a project's modes, made from the mode files.

David's Heisei card (PAD-658) went to the cabinet with a one-page "Godzilla Custom Modes" sheet written by hand from
the modes' sources, and it went stale twice (an old version, 14 modes, starts and windows that round 3 had changed).
So the Modes tab makes it (Rules sheet...): one row per mode that goes on the card - its name as the game shows it,
how it starts (the shot, and what the 1st, 2nd and 3rd start take), its stages a line each (what to shoot, the
clock), and whether it cashes out - a foot with the rules every mode shares, and the title and version from the
project. Saved as a PDF (Letter or A4, landscape, one page when it fits: :mod:`pinball_decryptor.core.pdf_sheet`)
and as HTML.

WHERE THE WORDS COME FROM.
- A mode made of BLOCKS is played on the desk (:mod:`.blocks_sim`): its start shots are made until it starts (or is
  lit, and then its lit shot), three times over, which gives the counts however the blocks build the rule; then the
  mode is played by shooting what it lights, and each stage (the variable that counts them) is worded from what
  was shot in it, its HUD title and the clock it set.
- A FORM mode words its fields (start shot and count, the shots that score, its seconds, a multiball).
- A mode in C words what its assets say (its name, its clock); the rest is the person's to write.
- Any mode may carry words of its own (``modes/<slug>/sheet.json``: ``start``, ``stages`` one per line, ``cash``,
  ``tag``), and a field written there wins over the generated words. The sheet's own title, line under it, foot,
  order and the modes left off are kept in ``modes/rules_sheet.json``.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re

from . import blocks_sim as BS
from . import block_modes as BM
from . import mode_project as MP

SHEET_FILE = "sheet.json"               # a mode's own words, in its folder
PROJECT_FILE = "rules_sheet.json"        # the sheet's settings, in the project's modes folder
PAPERS = {"letter": ("Letter", 792.0, 612.0), "a4": ("A4", 841.89, 595.28)}   # landscape, in points
STARTS = 3                               # the starts a row counts: 1st / 2nd / 3rd
SHOT_GAP_MS = 1500                       # the desk player makes a shot this often
START_TRIES = 1200                       # hits of a start shot before the player gives up on it
PLAY_MS = 15 * 60 * 1000                 # the longest the player plays one mode
STALL_SHOTS = 40                         # shots with no progress before the player lets time pass
STAGE_SHOTS = 60                         # shots in one stage before the player calls it endless (jackpots)
WINDOW_MIN_MS = 5000                     # a timer a shot starts, this long or more, is a window for the next
PROBE_MS = 3000                          # how long after a shot the player looks at what it did
SPINS, POPS = 10, 4                      # the switch hits of one spinner shot, of one ball in the pop bumpers
COUNT_MAX = 9                            # a shot made more often than this in a stage is said without its count
FIELDS = ("start", "stages", "cash", "tag")
ANY_SHOT = "(any shot)"
SWITCH = "(any switch)"                  # PAD-675: a When any playfield switch is hit rule
SWITCH_TRIES = 6 * START_TRIES           # switch hits come by the thousand (GODZILLA ANGRY's 1000, 2000, 3000)
SWITCH_GAP_MS = 100                      # ... and fast


# ------------------------------------------------------------------ words
def shot_word(name):
    """A shot's name as the sheet says it (the port's own name, as the HUD lines say them)."""
    return str(name or "").strip()


def join_shots(names, last="or"):
    """``Shield target left, center or right``: the shots' shared words said once."""
    names = [shot_word(n) for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    words = [n.split(" ") for n in names]
    common = 0
    while all(len(w) > common + 1 for w in words) and len({tuple(w[:common + 1]) for w in words}) == 1:
        common += 1
    if common:
        tails = [" ".join(w[common:]) for w in words]
        tails[0] = names[0]
    else:
        tails = names
    return ", ".join(tails[:-1]) + " %s %s" % (last, tails[-1])


def counts_words(counts):
    return " / ".join(str(c) for c in counts)


_SMALL = {"a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}


def title_words(text):
    """A HUD title (capitals) as the sheet's words: ``THE NIGHT ATTACK`` -> ``The Night Attack``."""
    text = re.sub(r"\s+", " ", str(text or "")).strip(" :-")
    if not text:
        return ""
    if text.upper() != text:
        return text
    words = text.lower().split(" ")
    for i, w in enumerate(words):
        if i and w in _SMALL:
            continue
        words[i] = w[:1].upper() + w[1:]
    return " ".join(words)


def secs(ms):
    s = int(round(ms / 1000.0))
    return "%d\u00a0s" % s


# ------------------------------------------------------------------ a blocks mode on the desk
def _idle_shots(program):
    """The shots the mode listens to while it is not running, in the order its rules name them; ANY_SHOT when an
    any-shot rule listens too."""
    out = []
    for s in program.get("scripts") or []:
        h = s.get("hat") or {}
        if (h.get("when") or "any") == "running":
            continue
        if h.get("kind") == "shot" and h.get("shot") and h["shot"] not in out:
            out.append(h["shot"])
        elif h.get("kind") == "any_shot" and ANY_SHOT not in out:
            out.append(ANY_SHOT)
        elif h.get("kind") == "switch" and SWITCH not in out:
            out.insert(0, SWITCH)               # first: a shot is its switch's hit too, so it counts there as well
    return out


def _running_shots(program):
    out = []
    for s in program.get("scripts") or []:
        h = s.get("hat") or {}
        if (h.get("when") or "any") != "idle" and h.get("kind") == "shot" and h.get("shot") and h["shot"] not in out:
            out.append(h["shot"])
    return out


def _shared_read(program):
    """The shared variables a not-running rule reads: what the other modes leave for this one."""
    shared = {v["name"] for v in program.get("vars") or [] if isinstance(v, dict) and v.get("shared")}
    out = []
    for s in program.get("scripts") or []:
        if ((s.get("hat") or {}).get("when") or "any") == "running":
            continue
        for b in BS.walk(s.get("do")):
            for e in BS.walk_value(b.get("cond")):
                if e.get("k") == "var" and e.get("name") in shared and e["name"] not in out:
                    out.append(e["name"])
    return out


def _hit_until(sim, shot, tries=START_TRIES, probe=None):
    """Make ``shot`` until the mode starts (or is lit, and then its lit shot), or ``probe`` (a test on a copy of the
    game after each hit) says it would start - and then start it that way. Returns ``(hits, how)`` - how: "start",
    "lit:<shot>", "probe" - with ``sim`` left at the start, or None."""
    if shot == SWITCH and tries == START_TRIES:
        tries = SWITCH_TRIES
    for n in range(1, tries + 1):
        if shot == SWITCH:
            sim.switches(1)
            sim.advance(SWITCH_GAP_MS)
        else:
            sim.shot(shot)
            sim.advance(SHOT_GAP_MS)
        if sim.running:
            return n, "start"
        if sim.lit is not None:
            lit = sim.lit
            sim.shot(lit)
            sim.advance(SHOT_GAP_MS)
            return (n, "lit:" + lit) if sim.running else None
        if probe is not None and probe(sim.copy()):
            probe(sim)                          # the game's own mode runs on through the run it joined
            return (n, "probe") if sim.running else None
    return None


def _join_probe(sim):
    """A mode made ready that starts with the game's next mode of its own (JET JAGUAR joins the next battle)."""
    sim.stock = True
    sim.shot(ANY_SHOT)
    return sim.running


def _round_until(sim, shots, tries=START_TRIES, shared=()):
    """Make ``shots`` in turn (or, with ``shared``, play the other modes' part - their shared variables set - and
    any shot) until the mode starts or is lit and then started. ``(made, how)`` or None."""
    for n in range(1, tries + 1):
        if shared:
            for name in shared:
                sim.vars[name] = 1
            sim.shot(ANY_SHOT)
        else:
            sim.shot(shots[(n - 1) % len(shots)])
        sim.advance(SHOT_GAP_MS)
        if sim.running:
            return n, "start"
        if sim.lit is not None:
            lit = sim.lit
            sim.shot(lit)
            sim.advance(SHOT_GAP_MS)
            return (n, "lit:" + lit) if sim.running else None
    return None


def start_rule(program, others=()):
    """How a blocks mode starts, played on the desk, and its first run: a dict with ``words`` (the Start column),
    ``counts`` (what the 1st, 2nd and 3rd start take), ``shots``, ``lit`` (the shot it is lit at, if it is) and
    ``run``: :func:`play`'s record of the first run. Between starts each run is played out (a mode may count a start
    only once it got somewhere: GODZILLA ANGRY's multiball) and the ball ends. ``others``: ``[(name, program)]`` of
    the project's other blocks modes, which name the modes a shared variable waits on."""
    idle = _idle_shots(program)
    base = BS.Sim(program)
    result = {"counts": [], "shots": [], "lit": "", "run": None, "words": ""}
    firsts = {}                                 # shot -> (hits, how, sim at the start)
    for shot in idle:
        for probe in (None, _join_probe):
            sim = base.copy()
            got = _hit_until(sim, shot, probe=probe)
            if got:
                firsts[shot] = (got[0], got[1], sim, probe)
                break
    if firsts:
        best = max(idle, key=lambda s: (s in firsts, firsts[s][0] if s in firsts else 0, -idle.index(s)))
        n, how, sim, probe = firsts[best]
        same = [s for s in idle if s in firsts and firsts[s][0] == n]
        if SWITCH in same:                      # PAD-675: any shot counts there only as its switch's hit
            same = [SWITCH]
        weights = ["%s counts %d" % (shot_word(s), round(n / float(firsts[s][0])))
                   for s in idle if s in firsts and s not in same and firsts[s][0]
                   and round(n / float(firsts[s][0])) > 1]
        counts, run = _starts(sim, n, lambda s: _hit_until(s, best, probe=probe))
        result.update(counts=counts, shots=same, run=run, lit=how[4:] if how.startswith("lit:") else "")
        result["words"] = _start_words(program, same, counts, how, weights, probe=probe)
        return result
    shots = [s for s in idle if s != ANY_SHOT]
    if len(shots) > 1:                          # no shot alone starts it: every one in turn (EBIRAH's powerlines)
        sim = base.copy()
        got = _round_until(sim, shots)
        if got:
            counts, run = _starts(sim, got[0], lambda s: _round_until(s, shots))
            result.update(counts=counts, shots=shots, run=run, lit=got[1][4:] if got[1].startswith("lit:") else "")
            result["words"] = _start_words(program, shots, counts, got[1], [], every=True)
            return result
    shared = _shared_read(program)
    if shared:                                  # the other modes' play lights it (SHIN GODZILLA)
        sim = base.copy()
        got = _round_until(sim, (), tries=50, shared=shared)
        if got:
            counts, run = _starts(sim, got[0], lambda s: _round_until(s, (), tries=50, shared=shared))
            names = _modes_setting(shared, others)
            words = "%s round%s of %s" % (counts_words(counts), "" if counts == [1] else "s",
                                          join_shots(names, "and") if names else "the other modes")
            result.update(counts=counts, run=run, lit=got[1][4:] if got[1].startswith("lit:") else "")
            result["words"] = words + _lit_tail(got[1], [])
            return result
    result["words"] = _event_words(program)
    sim = base.copy()
    sim.start()
    if sim.running:
        result["run"] = play(program, sim)
    return result


def _starts(sim, first, again):
    """The counts of STARTS starts from a game at its first (``first`` made it): each run played out, the ball
    ended, ``again(sim)`` for the next. ``(counts, the first run)``."""
    counts = [first]
    run = play(sim.p, sim)
    for _k in range(1, STARTS):
        sim.stock = False
        sim.new_ball()
        sim.advance(SHOT_GAP_MS)
        got = again(sim)
        if not got:
            break
        counts.append(got[0])
        play(sim.p, sim, quick=True)
    sim.stock = False
    return counts, run


def _lit_tail(how, shots):
    if not how.startswith("lit:"):
        return ""
    lit = how[4:]
    if shots and len(shots) == 1 and shots[0] == lit:
        return "; then once more"
    return "; then the %s" % shot_word(lit)


def _start_words(program, shots, counts, how, weights, every=False, probe=None):
    if shots == [ANY_SHOT]:
        what = "Any %s shots" % counts_words(counts)
    elif shots == [SWITCH]:
        what = "%s playfield switch hits" % counts_words(counts)
    elif every:
        what = "%s %s in all" % (join_shots(shots, "and"), counts_words(counts))
    else:
        what = "%s %s" % (join_shots(shots), counts_words(counts))
    if weights:
        what += " (%s)" % ", ".join(weights)
    if _one_ball(program, shots, counts, every, probe):
        what += ", in one ball"
    if how == "probe":
        what += "; joins the game's next mode"
    return what + _lit_tail(how, shots)


def _one_ball(program, shots, counts, every=False, probe=None):
    """True when the hits must all come in one ball: the first start's count split over two balls does not start
    it (or light it, or make it ready to join the game's next mode)."""
    if not shots or shots[0] in (ANY_SHOT, SWITCH) or not counts or counts[0] < 2:
        return False
    sim = BS.Sim(program)
    order = shots if every else shots[:1]
    for i in range(counts[0] - 1):
        sim.shot(order[i % len(order)])
        sim.advance(SHOT_GAP_MS)
    sim.new_ball()
    sim.shot(order[(counts[0] - 1) % len(order)])
    sim.advance(SHOT_GAP_MS)
    return not sim.running and sim.lit is None and not (probe is not None and probe(sim.copy()))


def _modes_setting(shared, others):
    out = []
    for name, prog in others:
        if any(b.get("op") in ("set", "change") and b.get("var") in shared
               for s in prog.get("scripts") or [] for b in BS.walk(s.get("do"))):
            out.append(name)
    return out


def _event_words(program):
    for s in program.get("scripts") or []:
        h = s.get("hat") or {}
        if h.get("kind") == "event" and any(b.get("op") in ("start_mode", "light_mode") for b in BS.walk(s.get("do"))):
            return "When the game: %s" % (h.get("event") or "?")
        if h.get("kind") == "challenge":
            return "As a challenge (%s)" % (h.get("challenge") or "?")
    return ""


def _stage_compares(program, name):
    top = n = 0
    for s in program.get("scripts") or []:
        for b in BS.walk(s.get("do")):
            for e in BS.walk_value(b.get("cond")):
                if e.get("k") == "cmp" and (e.get("a") or {}).get("k") == "var" and e["a"].get("name") == name \
                        and (e.get("b") or {}).get("k") == "num":
                    n += 1
                    top = max(top, BS._num(e["b"].get("v"), 0))
    return n, top


def stage_var(program):
    """The variable that counts the mode's stages: reset each run, stepped by 1, compared with stage numbers.
    Names with stage / phase / wave / round / part win."""
    best, best_score = None, 0
    for v in program.get("vars") or []:
        if not isinstance(v, dict) or not v.get("name") or (v.get("reset") or "mode") != "mode":
            continue
        name = v["name"]
        steps = sum(1 for s in program.get("scripts") or [] for b in BS.walk(s.get("do"))
                    if b.get("op") == "change" and b.get("var") == name and (b.get("by") or {}).get("v") == 1)
        compares, top = _stage_compares(program, name)
        if not steps or top < 2:
            continue
        score = compares + (100 if re.search(r"stage|phase|wave|round|part", name, re.I) else 0)
        if score > best_score:
            best, best_score = name, score
    return best


def play(program, sim, quick=False):
    """The mode played on the desk from its start by shooting what it lights, until it ends: ``{"stages": [...],
    "cash": shot or "", "balls": the most in play}``. A stage (the :func:`stage_var` value) is ``{"n", "titles",
    "shots": [(shot, hits)], "clock": s set as it began, "window": the longest window a shot opened, ms}``.
    ``cash``: a lit shot that ends the mode before its last stage and pays (a scoop between stages); the player
    never takes it. ``quick``: only play it out (a later start's run)."""
    var = stage_var(program)
    _n, top = _stage_compares(program, var) if var else (0, 0)
    record = {"stages": [], "cash": "", "balls": 1}
    if not sim.running:
        return record
    run_shots = _running_shots(program)
    tried = {}
    stall = 0
    end_at = sim.now + (PLAY_MS // 3 if quick else PLAY_MS)

    def stage_of(s):
        return s.vars.get(var, 0) if var else 0

    cur = {"n": stage_of(sim), "titles": [], "shots": [], "clock": 0, "balls": 0}
    record["stages"].append(cur)
    mark = _last_start(sim.events)                  # the events not yet put to a stage
    while sim.running and sim.now < end_at:
        if stage_of(sim) != cur["n"]:
            cur = {"n": stage_of(sim), "titles": [], "shots": [], "clock": 0, "balls": 0}
            record["stages"].append(cur)
        _note_events(cur, sim.events[mark:])
        mark = len(sim.events)
        for key, said in (("seen", sim.hud.get("title")), ("seen_lines", sim.hud.get("line"))):
            if said:                                # how long each title and line is up in the stage
                counts = cur.setdefault(key, {})
                counts[said] = counts.get(said, 0) + 1
        record["balls"] = max(record["balls"], sim.balls)
        lit = list(sim.lit_shots)
        pool = lit if stall < STALL_SHOTS else lit + [s for s in run_shots if s not in lit]
        pick, best = None, None
        idle = sim.copy()                               # the game without the shot, to tell what the shot did
        idle.advance(PROBE_MS)
        for shot in pool:
            cp = sim.copy()
            n0 = len(cp.events)
            _make(cp, shot)
            cp.advance(PROBE_MS)
            moved = cp.running and stage_of(cp) != stage_of(idle)
            changed = sum(1 for k in set(idle.vars) | set(cp.vars) if idle.vars.get(k, 0) != cp.vars.get(k, 0))
            paid = any(e[0] == "score" for e in cp.events[n0:])
            if not cp.running:
                last = not var or stage_of(sim) >= top
                if paid and not last and stage_of(sim) >= 1 and not record["cash"] and cp.ended_how == "block":
                    record["cash"] = shot
                # the shot that finishes the last stage, taken only when nothing else there does anything
                fin = last and (changed or paid) and shot != record["cash"]     # never the cash-out shot
                rank = (1 if fin else 0, 0.5 if fin else changed, -tried.get(shot, 0))
            else:
                rank = (2 if moved else 1, changed + (1 if paid else 0), -tried.get(shot, 0))
            if best is None or rank > best:
                pick, best = shot, rank
        if pick is None or best[0] == 0 or best[0] == 1 and best[1] == 0:
            stall += 1                                  # nothing lit does anything yet: let the game go on
            if stall > STALL_SHOTS * 4:
                break
            sim.advance(SHOT_GAP_MS)
            continue
        stall = 0
        tried[pick] = tried.get(pick, 0) + 1
        n0 = len(sim.events)
        stage0 = stage_of(sim)
        _make(sim, pick)
        n1 = len(sim.events)
        sim.advance(SHOT_GAP_MS)
        if sim.running or not var or stage0 >= top:
            _note_shot(cur, pick, sim.events[n0:n1])    # a shot that ends the mode early (a cash out) is not a stage's
        if not sim.running:
            break                                       # its end's words (won, lost) are no stage's
        cur["made"] = cur.get("made", 0) + 1
        if cur["made"] > STAGE_SHOTS and stage_of(sim) == cur["n"]:
            break                                       # a stage that never ends (a multiball's jackpots)
    if sim.running:
        sim.end("time")
    record["stages"] = [st for st in record["stages"] if st["shots"]]
    return record


def _note_shot(st, shot, events):
    for i, (s, n) in enumerate(st["shots"]):
        if s == shot:
            st["shots"][i] = (s, n + 1)
            break
    else:
        st["shots"].append((shot, 1))
    for e in events:
        if e[0] == "timer" and e[2] >= WINDOW_MIN_MS:
            st.setdefault("timers", []).append(e[2])


def burst(shot):
    """How many switch hits one shot of the player's makes: a spinner spins, a ball in the pop bumpers bounces."""
    low = (shot or "").lower()
    return SPINS if "spinner" in low else POPS if "pop" in low else 1


def _make(sim, shot):
    for _ in range(burst(shot)):
        sim.shot(shot)
        if not sim.running:
            break


def _last_start(events):
    for i in range(len(events) - 1, -1, -1):
        if events[i][0] == "start":
            return i
    return 0


def _note_events(st, events):
    for e in events:
        if e[0] == "hud_title" and e[1] and e[1] not in st["titles"]:
            st["titles"].append(e[1])
        elif e[0] == "hud_line" and e[1] and e[1] not in st.setdefault("lines", []):
            st["lines"].append(e[1])
        elif e[0] == "clock" and not e[2]:
            st["clock"] = e[1]
        elif e[0] == "multiball" and not st.get("balls"):
            st["balls"] = e[1]


def _window(st):
    """The time the player has for the next shot of a stage: shown only when its HUD line counts one down (the
    kit's "... IN" line), the timer the stage's shots start most often."""
    if not any(re.search(r"\bIN$", line.strip(), re.I) for line in st.get("lines") or []):
        return 0
    timers = st.get("timers") or []
    return max(set(timers), key=timers.count) if timers else 0


def end_titles(program):
    """HUD titles the mode shows as it ends (won, lost, cashed): set beside an End the mode block, or before a
    timer whose rule ends it. They name no stage."""
    enders = set()
    for s in program.get("scripts") or []:
        h = s.get("hat") or {}
        if h.get("kind") == "timer_done" and _ends_directly(s.get("do")):
            enders.add(h.get("timer"))
    out = set()
    for s in program.get("scripts") or []:
        if (s.get("hat") or {}).get("kind") == "mode_end":
            out |= {b.get("text") for b in BS.walk(s.get("do")) if b.get("op") == "hud_text"}
        for stack in _stacks(s.get("do")):
            ops = [b for b in stack if isinstance(b, dict)]
            if any(b.get("op") == "end_mode" or b.get("op") == "timer_start" and b.get("timer") in enders
                   for b in ops):
                out |= {b.get("text") for b in ops if b.get("op") == "hud_text" and b.get("which") == "title"}
    return {t for t in out if t}


def _ends_directly(stack):
    return any(isinstance(b, dict) and b.get("op") == "end_mode" for b in stack or [])


def _stacks(stack):
    if not isinstance(stack, list):
        return
    yield stack
    for b in stack:
        if isinstance(b, dict) and b.get("op") == "if":
            yield from _stacks(b.get("then"))
            yield from _stacks(b.get("else"))


def stage_title(st, mode_name):
    """A stage's name from the HUD titles it showed: the one up longest, without the mode's name or a "PHASE 2:"
    (an instruction, a count or the end's words name no stage)."""
    seen = st.get("seen") or {}
    order = sorted(st["titles"], key=lambda t: -seen.get(t, 0))
    for t in order:
        if t in st.get("ending", ()):
            continue
        t2 = re.sub(r"^(PHASE|STAGE|PART|ROUND|WAVE)\s*\d+\s*:\s*", "", t, flags=re.I)
        if mode_name and t2.upper().startswith(mode_name.upper() + ":"):
            t2 = t2[len(mode_name) + 1:]
        t2 = t2.strip()
        if t2 and _bare(t2) != _bare(mode_name) and not re.match(r"^(\d+\s|SHOOT\b|HIT\b)", t2, re.I):
            return title_words(t2)
    # no title of its own: the name a HUD line gives it ("THE BOULDER: NOW THE MECHA LANE"), the one up longest
    seen = st.get("seen_lines") or {}
    for line in sorted(st.get("lines") or [], key=lambda t: -seen.get(t, 0)):
        m = re.match(r"^([A-Z0-9][A-Z0-9 '.!-]{2,28}):\s", line)
        if m and seen.get(line) and not re.search(r"^(SHOOT|HIT|NOW)\b|\b(LIT|SHOT|SHOTS)\b", m.group(1)):
            return title_words(m.group(1))
    return ""


def _bare(text):
    return re.sub(r"[^A-Z0-9]+", "", str(text or "").upper())


def stage_line(st, mode_name, seconds=0):
    shots = st["shots"]
    names = [shot_word(shot) + (" %dx" % n if 1 < n <= COUNT_MAX and burst(shot) == 1 else "")
             for shot, n in shots[:6]]
    what = ", ".join(names)
    if len(shots) > 6:
        what += " and %d more" % (len(shots) - 6)
    if st.get("balls", 0) > 1:
        what = "%d balls, %s" % (st["balls"], what)
    title = stage_title(st, mode_name)
    line = ("%s: %s" % (title, what)) if title else what
    extra = []
    if st.get("clock") and st["clock"] != seconds:
        extra.append(secs(st["clock"] * 1000))
    window = _window(st)
    if window:
        extra.append("%s for each shot" % secs(window))
    if extra:
        line += " (%s)" % ", ".join(extra)
    return line


def blocks_rules(program, others=()):
    """The generated words of a blocks mode: ``{"name", "start", "stages": [...], "cash", "balls"}``."""
    start = start_rule(program, others)
    run = start.get("run") or {"stages": [], "cash": "", "balls": 1}
    name = program.get("name") or ""
    ending = end_titles(program)
    for st in run["stages"]:
        st["ending"] = ending
    lines = [stage_line(st, name, int(program.get("seconds") or 0)) for st in run["stages"]]
    return {"name": name, "start": start["words"], "stages": lines, "cash": _cash_word(run["cash"]),
            "balls": run["balls"], "seconds": int(program.get("seconds") or 0), "counts": start["counts"]}


def _cash_word(shot):
    if not shot:
        return ""
    return "Scoop" if "scoop" in shot.lower() else shot_word(shot)


# ------------------------------------------------------------------ form and C modes
def form_rules(spec):
    """The generated words of a form mode (a :class:`.mode_project.ModeSpec`)."""
    start = ""
    if getattr(spec, "starts_on", "shot") == "event" and getattr(spec, "start_event", ""):
        start = "When the game: %s" % spec.start_event
    elif getattr(spec, "start_sequence", None):
        start = "In order, in one ball: %s" % ", ".join(shot_word(s) for s in spec.start_sequence)
    else:
        shots = [spec.start_shot] + [s for s in (spec.start_or or []) if s]
        start = "%s %d" % (join_shots(shots), int(spec.start_count or 1))
        if int(spec.start_count or 1) > 1:
            start += ", in one ball"
        for item in spec.start_also or []:
            try:
                start += "; and %s %d" % (shot_word(item[0]), int(item[1]))
            except (TypeError, ValueError, IndexError):
                pass
    if getattr(spec, "after", ""):
        start += "; after %s" % spec.after
    scoring = [shot_word(s) for s in spec.scoring_shots or []]
    line = ", ".join(scoring[:6]) + (" and %d more" % (len(scoring) - 6) if len(scoring) > 6 else "")
    if spec.seconds:
        line += " (%s)" % secs(int(spec.seconds) * 1000)
    balls = int(spec.balls or 3) if getattr(spec, "multiball", False) else 1
    if balls > 1:
        line = "%d balls, %s" % (balls, line)
    return {"name": spec.name, "start": start, "stages": [line] if line else [], "cash": "", "balls": balls,
            "seconds": int(spec.seconds or 0), "counts": []}


def code_rules(assets):
    """The generated words of a mode in C: only its clock is known; the rest is written by the person."""
    secs_ = int(getattr(assets, "seconds", 0) or 0)
    hud = getattr(assets, "hud", None) or {}
    line = str(hud.get("line") or "").strip() if isinstance(hud, dict) else ""
    stage = title_words(line) if line else ""
    if secs_:
        stage = (stage + " (%s)" % secs(secs_ * 1000)) if stage else secs(secs_ * 1000)
    return {"name": assets.name, "start": "", "stages": [stage] if stage else [], "cash": "", "balls": 1,
            "seconds": secs_, "counts": []}


# ------------------------------------------------------------------ the person's own words
def mode_words_path(project, slug):
    return os.path.join(MP.mode_folder(project, slug), SHEET_FILE)


def load_mode_words(project, slug):
    try:
        with open(mode_words_path(project, slug), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return _clean_words(data)


def _clean_words(data):
    out = {}
    if not isinstance(data, dict):
        return out
    for k in ("start", "cash", "tag"):
        v = str(data.get(k) or "").strip()
        if v:
            out[k] = v[:300]
    st = data.get("stages")
    if isinstance(st, str):
        st = st.splitlines()
    if isinstance(st, list):
        lines = [str(x).strip()[:300] for x in st if str(x or "").strip()]
        if lines:
            out["stages"] = lines[:12]
    return out


def save_mode_words(project, slug, words):
    """Write a mode's own words (empty fields are dropped; nothing left removes the file)."""
    data = _clean_words(words)
    path = mode_words_path(project, slug)
    if not data:
        try:
            os.remove(path)
        except OSError:
            pass
        return data
    _write_json(path, data)
    return data


def project_path(project):
    return os.path.join(MP.modes_dir(project), PROJECT_FILE)


def load_settings(project):
    try:
        with open(project_path(project), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = {}
    for k in ("title", "intro", "foot"):
        v = str(data.get(k) or "").strip()
        if v:
            out[k] = v[:1200]
    out["paper"] = data.get("paper") if data.get("paper") in PAPERS else "letter"
    out["order"] = [str(s) for s in data.get("order") or [] if isinstance(s, str)]
    out["off"] = [str(s) for s in data.get("off") or [] if isinstance(s, str)]
    return out


def save_settings(project, settings):
    data = {k: v for k, v in (settings or {}).items() if k in ("title", "intro", "foot", "paper", "order", "off") and v}
    os.makedirs(MP.modes_dir(project), exist_ok=True)
    _write_json(project_path(project), data)
    return load_settings(project)


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ------------------------------------------------------------------ the sheet
def project_modes(project, profile=None):
    """``[(slug, kind, name, data)]`` of every mode of the project, in the Modes tab's order: data is the spec
    (form), the program (blocks) or the assets (C). ``problems``: the ones that would not go on a card, with why."""
    from . import code_modes as CM
    out, left = [], []
    found, broken = MP.list_modes(project)
    for slug, err in broken:
        left.append((slug, slug, "its mode.json does not load (%s)" % err))
    for slug, spec in found:
        try:
            spec_card = MP.retarget(spec, profile)[0] if profile is not None else spec
            problems = MP.validate(spec_card, MP.mode_folder(project, slug))
        except Exception:                       # noqa: BLE001 - never a sheet stopped by a check
            problems = []
        if problems:
            left.append((slug, spec.name, "it is not ready to build: " + " ".join(problems)))
            continue
        out.append((slug, "form", spec.name, spec))
    for slug in CM.code_slugs(project):
        if BM.is_blocks(project, slug):
            try:
                prog = BM.load(project, slug)
            except (OSError, ValueError) as e:
                left.append((slug, slug, "its blocks do not load (%s)" % e))
                continue
            out.append((slug, "blocks", prog.get("name") or slug.upper(), prog))
        else:
            try:
                assets = CM.load(project, slug)
            except (OSError, ValueError) as e:
                left.append((slug, slug, "its assets do not load (%s)" % e))
                continue
            out.append((slug, "code", assets.name, assets))
    return out, left


_CACHE = {}                              # (kind, what the words are made from) -> words; a mode played once


def _key(kind, data, others=()):
    if kind == "blocks":
        body = data
    elif kind == "form":
        body = data.to_json()
    else:
        body = {"name": getattr(data, "name", ""), "seconds": getattr(data, "seconds", 0),
                "hud": getattr(data, "hud", None)}
    text = json.dumps([kind, body, [n for n, _d in others]], sort_keys=True, default=str)
    return kind, hashlib.sha1(text.encode("utf-8")).hexdigest()


def generated(modes):
    """``{slug: words}`` for every mode in ``modes`` (:func:`project_modes`). A mode's words are kept while what
    they come from is unchanged, so a sheet made again after an edit of the person's words is quick."""
    blocks = [(name, data) for _s, kind, name, data in modes if kind == "blocks"]
    out = {}
    for slug, kind, name, data in modes:
        others = [(n, d) for n, d in blocks if d is not data] if kind == "blocks" else []
        key = _key(kind, data, [(n, d) for n, d in others if _modes_setting(_shared_read(data), [(n, d)])]
                   if kind == "blocks" else ())
        if key in _CACHE:
            out[slug] = dict(_CACHE[key])
            continue
        try:
            if kind == "blocks":
                words = blocks_rules(data, others)
            elif kind == "form":
                words = form_rules(data)
            else:
                words = code_rules(data)
        except Exception as e:                  # noqa: BLE001 - one odd mode never stops the sheet
            words = {"name": name, "start": "", "stages": [], "cash": "", "balls": 1, "seconds": 0,
                     "counts": [], "error": str(e)}
        if len(_CACHE) > 400:
            _CACHE.clear()
        _CACHE[key] = words
        out[slug] = dict(words)
    return out


def shared_foot(modes, gen):
    """The rules every mode shares, in a few sentences, from the modes themselves."""
    progs = [d for _s, k, _n, d in modes if k == "blocks"]
    words = []
    cash = {g.get("cash") for g in gen.values() if g.get("cash")}
    if cash:
        words.append("Cash out: between stages, %s ends the mode and pays what it has won so far; or push on."
                     % ("the scoop" if cash == {"Scoop"} else "the shot in Cash out"))
    secs_ = sorted({g.get("seconds") for g in gen.values() if g.get("seconds")})
    floor = sorted({BS._num((b.get("seconds") or {}).get("v"), 0) for p in progs for s in p.get("scripts") or []
                    for b in BS.walk(s.get("do")) if b.get("op") == "set_time" and b.get("at_least")})
    clock = ""
    if secs_:
        clock = ("Each mode runs %d s" % secs_[0]) if len(secs_) == 1 else ("Modes run %d s or more" % secs_[0])
    if floor and floor[-1]:
        clock += ("; " if clock else "") + "a good shot tops the clock back up to %d s" % floor[-1]
    if clock:
        words.append(clock + ".")
    one = "One mode at a time"
    if any(p.get("wait_multiball") for p in progs):
        one += "; a ready mode waits out one of the game's own modes or a multiball"
    words.append(one + ".")
    words.append("Shoot what is lit.")
    ends = [bool(getattr(d, "ends_on", "drain") == "drain") if k == "form" else bool(d.get("ends_on_drain", True))
            if k == "blocks" else True for _s, k, _n, d in modes]
    if ends and all(ends):
        words.append("A drain or tilt ends a mode.")
    return " ".join(words)


def game_name(label):
    """``Godzilla Premium 1.16`` -> ``Godzilla``: the title without its model and version."""
    words = (label or "").split()
    while words and (re.match(r"^v?\d+(\.\d+)+[a-z]?$", words[-1], re.I) or words[-1].lower() in (
            "pro", "premium", "le", "limited", "edition", "premium/le", "(premium/le)")):
        words.pop()
    return " ".join(words) or label or ""


def edition_words(label, card_name):
    """The card's own words after the title's (a custom build's name: ``Heisei Custom V1.99D Kaiju Edition``)."""
    name = re.split(r"[\\/]", str(card_name or ""))[-1]           # a Windows path read on macOS or Linux too
    stem = re.sub(r"\.(raw|img)$", "", name, flags=re.I)
    stem = re.sub(r"[-_ ]modified$", "", stem)
    if label and stem.lower().startswith(label.lower()):
        rest = stem[len(label):].strip(" -_()")
        return rest
    return ""


def build(project, profile=None, label="", card=""):
    """The sheet: ``{"title", "intro", "rows": [...], "foot", "paper", "left": [...], "modes": [...]}``.
    ``rows``: one per mode on the sheet, ``{"slug", "name", "tag", "start", "stages", "cash", "own": {...}}``
    (own: the fields the person wrote). ``modes``: every mode with its generated and own words, on or off the
    sheet, for the dialog. ``left``: ``(name, why)`` of the modes that do not go on the card."""
    settings = load_settings(project)
    modes, left = project_modes(project, profile)
    gen = generated(modes)
    order = settings["order"]
    rank = {s: i for i, s in enumerate(order)}
    first = {m[0]: i for i, m in enumerate(modes)}
    modes.sort(key=lambda m: (rank.get(m[0], len(rank)), first[m[0]]))
    edition = edition_words(label, card)
    game = game_name(label)
    title = settings.get("title") or ("%s Custom Modes" % game if game else "Custom Modes")
    rows, every = [], []
    for slug, kind, name, data in modes:
        g = gen[slug]
        own = load_mode_words(project, slug)
        row = {"slug": slug, "kind": kind, "name": name, "tag": own.get("tag", ""),
               "start": own.get("start") or g["start"],
               "stages": own.get("stages") or g["stages"],
               "cash": own.get("cash") or g["cash"],
               "balls": g.get("balls", 1),
               "gen": {k: g.get(k) for k in ("start", "stages", "cash")}, "own": own,
               "on": slug not in settings["off"]}
        every.append(row)
        if row["on"]:
            rows.append(row)
    n = len(rows)
    what = label + (" (%s)" % edition if edition else "")
    intro = settings.get("intro") or (
        "This card adds %d mode%s to %s. %sThe numbers in Start are what the 1st / 2nd / 3rd start take."
        % (n, "" if n == 1 else "s", what or "the game",
           "Each mode is played in stages. " if any(len(r["stages"]) > 1 for r in rows) else ""))
    foot = settings.get("foot") or shared_foot([m for m in modes if m[0] not in settings["off"]],
                                               {r["slug"]: gen[r["slug"]] for r in rows})
    return {"title": title, "intro": intro, "foot": foot, "paper": settings["paper"], "rows": rows,
            "modes": every, "left": [(name, why) for _s, name, why in left], "edition": edition, "label": label,
            "settings": settings}


def stage_cells(row):
    """The Stages cell's lines: ``[(number or "", words)]``, numbered when there are several."""
    lines = list(row.get("stages") or [])
    out = []
    for i, line in enumerate(lines):
        out.append((str(i + 1) if len(lines) > 1 else "", line))
    return out


# ------------------------------------------------------------------ HTML
# the PDF's look; Arial has Helvetica's widths, so the type sizes that fit the PDF on its page fit the HTML too
HTML_CSS = """
  @page { size: %(paper)s landscape; margin: 0.4in 0.45in; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: Arial, Helvetica, "Liberation Sans", sans-serif; color: #1a1a1a; background: #fff;
         -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  h1 { font-size: 22pt; margin: 0 0 2pt; font-weight: 700; }
  .sub { font-size: %(sub)spt; margin: 0 0 9pt; color: #333; }
  table { width: 100%%; border-collapse: collapse; font-size: %(size)spt; line-height: 1.22; table-layout: fixed; }
  th { background: #222; color: #fff; text-align: left; font-weight: 700; padding: 5pt 7pt; font-size: 9pt;
       white-space: nowrap; }
  td { padding: 3pt 7pt; vertical-align: top; border-bottom: 1px solid #c9c9c9; }
  tr:nth-child(even) td { background: #f0f0f0; }
  th.mode { width: 13%%; } th.start { width: 25%%; } th.cash { width: 7%%; }
  td.mode { font-weight: 700; }
  td.cash { text-align: center; }
  .tag { display: block; font-weight: 700; font-size: 0.82em; color: #666; letter-spacing: 0.04em; margin-top: 1pt; }
  .n { font-weight: 700; }
  .foot { font-size: %(foot)spt; margin: 7pt 0 0; color: #222; }
  @media screen { body { margin: 0.4in 0.45in; } }
"""
# PAD-695: printed from a browser (Print... prints the dialog's preview; a saved page prints the same) the page sets
# its rows a little taller than the PDF does, so on Letter the foot ran on to a second page. Before it prints it lays
# itself out at the paper's width and shrinks its type until it fits the page's height, as the PDF does; after, its
# own sizes come back. Print... calls padFitPage() itself too, so it holds wherever print events do not reach.
HTML_FIT = """
(function () {
  var W = %(w)s, H = %(h)s, base = null;
  function els() { return [document.querySelector("table"), document.querySelector(".sub"),
                           document.querySelector(".foot")]; }
  function fit() {
    var e = els(), b = document.body, s = b.style, keep = [s.width, s.margin];
    unfit();
    if (!base) base = e.map(function (x) { return x ? parseFloat(getComputedStyle(x).fontSize) : 0; });
    s.width = W + "px"; s.margin = "0";
    for (var f = 1; f >= 0.5; f -= 0.02) {
      e.forEach(function (x, i) { if (x) x.style.fontSize = (base[i] * f) + "px"; });
      if (b.getBoundingClientRect().height <= H) break;
    }
    s.width = keep[0]; s.margin = keep[1];
  }
  function unfit() { els().forEach(function (x) { if (x) x.style.fontSize = ""; }); }
  window.padFitPage = fit;
  addEventListener("beforeprint", fit);
  addEventListener("afterprint", unfit);
})();
"""
PAGE_MARGIN_IN = (0.4, 0.45)             # the @page margins above: top/bottom, left/right
HEAD_ROW = ('<tr><th class="mode">Mode</th><th class="start">Start</th><th>Stages</th>'
            '<th class="cash">Cash out</th></tr>')


def to_html(sheet, paper=None):
    """The sheet as a web page: the PDF's layout, at the type size that fits the PDF on its page."""
    E = html.escape
    paper = paper if paper in PAPERS else sheet.get("paper", "letter")
    rows = []
    for r in sheet["rows"]:
        tag = '<span class="tag">%s</span>' % E(r["tag"]) if r.get("tag") else ""
        stages = " &middot; ".join(('<span class="n">%s</span>&nbsp;%s' % (E(n), E(w))) if n else E(w)
                                   for n, w in stage_cells(r))
        rows.append('    <tr><td class="mode">%s%s</td><td class="start">%s</td>\n      <td>%s</td>'
                    '<td class="cash">%s</td></tr>' % (E(r["name"]), tag, E(r["start"] or ""), stages,
                                                       E(r["cash"]) if r.get("cash") else "&mdash;"))
    size, sub, foot = _fit(sheet, paper)
    css = HTML_CSS % {"paper": PAPERS[paper][0].lower(), "size": size, "sub": sub, "foot": foot}
    _label, pw, ph = PAPERS[paper]                  # the page's room in CSS px (96 a inch), a little held back
    fit = HTML_FIT % {"w": "%.1f" % ((pw / 72.0 - 2 * PAGE_MARGIN_IN[1]) * 96),
                      "h": "%.1f" % ((ph / 72.0 - 2 * PAGE_MARGIN_IN[0]) * 96 * 0.98)}
    return "\n".join([
        "<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        "<title>%s</title>" % E(sheet["title"]), "<style>%s</style>" % css, "</head>", "<body>",
        "<h1>%s</h1>" % E(sheet["title"]), '<p class="sub">%s</p>' % E(sheet["intro"]),
        "<table>", "  <thead>", "    " + HEAD_ROW, "  </thead>", "  <tbody>", "\n".join(rows), "  </tbody>", "</table>",
        '<p class="foot">%s</p>' % E(sheet["foot"]), "<script>%s</script>" % fit, "</body>", "</html>", ""])


def to_pdf(sheet, paper=None, measure=False):
    """The sheet as PDF bytes (:mod:`pinball_decryptor.core.pdf_sheet`): one page when it fits. ``measure``: only
    the type sizes that fit it (:func:`.pdf_sheet.table_pdf`)."""
    from ...core import pdf_sheet
    paper = paper if paper in PAPERS else sheet.get("paper", "letter")
    _label, w, h = PAPERS[paper]
    rows = []
    for r in sheet["rows"]:
        rows.append([[(r["name"], "bold")] + ([("\n" + r["tag"], "tag")] if r.get("tag") else []),
                     [(r["start"] or "", "")],
                     _stage_runs(r),
                     [(r["cash"] or "\u2014", "")]])
    return pdf_sheet.table_pdf(sheet["title"], sheet["intro"], ["Mode", "Start", "Stages", "Cash out"], rows,
                               sheet["foot"], page=(w, h), widths=(0.13, 0.25, 0.55, 0.07), centre=(3,),
                               measure=measure)


def _fit(sheet, paper):
    """The type sizes (the table, the line under the title, the foot) the PDF fits its page with, for the HTML."""
    return tuple("%g" % s for s in to_pdf(sheet, paper, measure=True))


def _stage_runs(r):
    runs = []
    for i, (n, w) in enumerate(stage_cells(r)):
        if i:
            runs.append((" \u00b7 ", ""))
        if n:
            runs.append((n + "\u00a0", "bold"))         # the number stays with its stage's first word
        runs.append((w, ""))
    return runs
