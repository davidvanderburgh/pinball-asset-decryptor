"""CHECK THIS GAME: what one scripted game in the emulator says about a build's port.

The Modes tab's Check this game boots the card with the pinned mode object and a staged
``gamecheck.on`` (``modes/tryit.sh install``), and ``modes/gamecheck.sh play`` starts a game,
presses each playfield switch once with a mark before it, and drains until a ball ends. The
object (``mode_file.c``) logs ``check`` lines: the marks, every shot mask the game dispatches,
every event the port names, the end of ball. :func:`read` turns those lines, and the switch
names ``play`` printed, into a :class:`CheckResult`; :func:`record` keeps it beside the ports
derived on this machine, tied to the port's exact text, and :func:`load` finds it again.

A check PASSES when the runtime hooked the game with the port, a game started, at least one of
the port's shots came from a switch and a drain ended a ball through the port's end of ball:
the core a mode needs. Which shots and events it saw, and which it did not, are said too; a
shot a check did not see is not wrong (a switch the check leaves alone may make it), only
unseen.
"""

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field

#: the file tryit.sh install copies into the guest's /dump to switch the object's logging on
FLAG_NAME = "gamecheck.on"
#: what the flag file holds (the object reads only that it is there)
FLAG_TEXT = "the Modes tab's Check this game\n"
#: the events a scripted game with one drain fires on every build that names them
EXPECTED_EVENTS = ("game_start", "ball_start", "ball_end", "bonus_start", "bonus_end")

_MARK = re.compile(r"\bcheck mark (\S+)")
_SHOT = re.compile(r"\bcheck shot (0x[0-9a-fA-F]+) in_game (-?\d+)")
_EVENT = re.compile(r"\bcheck event (\S+) \((0x[0-9a-fA-F]+)\)")
_SWITCH = re.compile(r"\[check\] switch (\d+) (.+)$")


@dataclass
class CheckResult:
    armed: str = ""                  # the runtime's "armed:" line, "" when it never hooked the game
    refused: str = ""                # its "NOT THIS GAME'S PORT" line, when it refused the port
    started: bool = False            # a game was in play (a shot in game, or game_start)
    pressed: int = 0                 # switches the check pressed
    shots_seen: dict = field(default_factory=dict)    # port shot name -> the switch that made it
    shots_unseen: list = field(default_factory=list)  # port shot names no press made
    ball_end: bool = False           # the port's end of ball ran after a drain
    events_seen: list = field(default_factory=list)   # port event names that fired
    events_unseen: list = field(default_factory=list)  # EXPECTED_EVENTS the port names that did not
    when: str = ""
    port_sha1: str = ""

    @property
    def ok(self):
        return bool(self.armed and not self.refused and self.started and self.shots_seen
                    and self.ball_end)

    def summary(self, label="the game"):
        """One or two sentences for the person."""
        if self.refused:
            return ("%s did not take what the app knows of it: the runtime refused the port (%s), "
                    "so a mode cannot run on this build." % (label, self.refused))
        if not self.armed:
            return ("The check never saw the mode runtime hook %s, so nothing about it is proven."
                    % label)
        if not self.started:
            return "The check could not start a game on %s, so nothing about it is proven." % label
        n, total = len(self.shots_seen), len(self.shots_seen) + len(self.shots_unseen)
        words = ["%d of the %d shots came from their switches" % (n, total)]
        words.append("a drain ended the ball" if self.ball_end else "NO drain ended a ball")
        if self.events_seen:
            words.append("%d event%s fired (%s)" % (len(self.events_seen),
                         "" if len(self.events_seen) == 1 else "s", ", ".join(self.events_seen)))
        head = ("Checked in the emulator: modes run on %s. " % label if self.ok
                else "Checked in the emulator, NOT proven: ")
        text = head + "; ".join(words) + "."
        if self.shots_unseen:
            text += " Not seen: %s." % ", ".join(self.shots_unseen[:8])
            if len(self.shots_unseen) > 8:
                text = text[:-1] + " and %d more." % (len(self.shots_unseen) - 8)
        if self.events_unseen:
            text += " Events that did not fire: %s." % ", ".join(self.events_unseen)
        return text


def read(log_text, play_text, shots, events=()):
    """The check of one run: ``log_text`` = ``gamecheck.sh log`` (mode.log's lines),
    ``play_text`` = what ``gamecheck.sh play`` printed (the switch names), ``shots`` = the
    port's ``[(name, mask)]``, ``events`` = the port's event names."""
    names = {}
    for line in (play_text or "").splitlines():
        m = _SWITCH.search(line.strip())
        if m:
            names[m.group(1)] = m.group(2).strip()
    res = CheckResult()
    mark, masks_by_mark, fired = None, {}, []
    for line in (log_text or "").splitlines():
        if "NOT THIS GAME'S PORT" in line:
            res.refused = line.split("]", 1)[-1].strip()
        elif "armed: " in line:
            res.armed = line[line.index("armed: "):].strip()
        m = _MARK.search(line)
        if m:
            mark = m.group(1)
            if mark.isdigit():
                res.pressed += 1
            continue
        m = _SHOT.search(line)
        if m:
            mask, in_game = int(m.group(1), 16), int(m.group(2))
            if in_game:
                res.started = True
            if mark is not None:
                masks_by_mark.setdefault(mark, []).append(mask)
            continue
        m = _EVENT.search(line)
        if m:
            fired.append(m.group(1))
            if m.group(1) == "game_start":
                res.started = True
            continue
        if re.search(r"\bcheck ball end\b", line):
            res.ball_end = True
    for name, mask in shots:
        who = next((sw for sw, ms in masks_by_mark.items() if sw.isdigit()
                    and any(m & mask for m in ms)), None)
        if who is None:
            res.shots_unseen.append(name)
        else:
            res.shots_seen[name] = names.get(who, "switch %s" % who)
    res.events_seen = [e for e in dict.fromkeys(fired) if e in set(events) or not events]
    res.events_unseen = [e for e in EXPECTED_EVENTS if e in set(events) and e not in fired]
    res.when = time.strftime("%Y-%m-%d %H:%M")
    return res


# ---- where a check is kept ------------------------------------------------------------------
def checks_dir():
    from .title_reader import cache_dir
    return cache_dir("checks")


def _sha1(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _record_path(port_path):
    return os.path.join(checks_dir(), os.path.basename(port_path) + ".check.json")


def record(port_path, res):
    """Keep ``res`` for the port at ``port_path``, tied to its text: a port that changes needs
    another check. True when kept."""
    try:
        res.port_sha1 = _sha1(port_path)
        path = _record_path(port_path)
        tmp = path + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(res.__dict__), f, indent=1)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def load(port_path):
    """The check kept for the port at ``port_path`` as it is now, or None."""
    if not port_path:
        return None
    try:
        with open(_record_path(port_path), "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or d.get("port_sha1") != _sha1(port_path):
            return None
        known = CheckResult.__dataclass_fields__
        return CheckResult(**{k: v for k, v in d.items() if k in known})
    except (OSError, TypeError, ValueError):
        return None


def passed(port_path):
    """Has a check passed on this PC with the port as it is now?"""
    res = load(port_path)
    return bool(res is not None and res.ok)
