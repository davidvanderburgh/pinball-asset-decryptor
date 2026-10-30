"""PAD-827: which clip is which, from what the emulator SAW the game do with it.

A field report (Godzilla retheme): a battle plays a dozen clips named ``gigan_ghidorah_vs_godzilla13``
and the like, and the ask was to tell them apart - by the words the game draws over one (JACKPOT)
or by what sets it off (the right ramp; a loop).

WHY NOT THE GAME PROGRAM. The program names each clip (:mod:`.clip_modes`), but on Godzilla LE
1.16 161 of the 224 code places that name one hold no text line of the game's within the same
function: a battle's clips sit in record tables its static initialiser builds, and which record
plays on which shot is decided at run time. So the reading here is the EMULATOR's, which sees
the real thing on every Spike 2 run, modes or not:

* every clip the game opens reaches the rig's video host as a file path (``padvidhost.py``'s
  ``serving`` line in ``padvid.log``), and the same file asked for again as it ends is a loop;
* the playfield window (``tools/spike2_emu/clipwatch.py``) reads those lines, names each clip
  by this module's map (:func:`write_names`: the project's ``video/manifest.txt``, so a clip has
  the name its Video tab row has), and notes the switch made just before it started;
* it lists them live and appends what it saw to a file beside the Emulate tab's volume file
  (:func:`seen_file`), which the Emulate tab's poll folds into the project
  (:class:`Merger` -> ``video/emulator_seen.json``), where the Video tab reads it (:func:`load`).

The words the game draws over a clip are on the emulator's own screen while it plays.
"""
from __future__ import annotations

import json
import os

#: the project's record of what the emulator saw, per Video tab row
SEEN_JSON = "emulator_seen.json"
REV = 1


def names_file(ctl_dir, slot):
    """The run's clip names, beside the Emulate tab's volume file, one per rig."""
    return os.path.join(ctl_dir, "clip_names_%d.json" % int(slot or 0))


def seen_file(ctl_dir, slot):
    """What the playfield window saw, one JSON line per clip start or first loop."""
    return os.path.join(ctl_dir, "clips_seen_%d.jsonl" % int(slot or 0))


def guest_path(card_path, game=""):
    """The path the game asks the video host for (``./assets/...``) of a manifest row's card
    path (``/<game>/assets/...``), or None."""
    p = (card_path or "").strip()
    if not p.startswith("/"):
        return None
    parts = p.split("/", 2)
    if len(parts) < 3 or (game and parts[1] != game):
        return None
    return "./" + parts[2]


def names_of(project, game=""):
    """``{guest path: [Video tab rel, name]}`` of the project's clips."""
    from .clip_modes import manifest_rows
    out = {}
    for rel, card_path in manifest_rows(project).items():
        g = guest_path(card_path, game)
        if g:
            out[g] = [rel, os.path.splitext(os.path.basename(rel))[0]]
    return out


def project_game(project):
    """The title folder the project's clips came from (``godzilla_le``), or ""."""
    from .clip_modes import manifest_rows
    count = {}
    for card_path in manifest_rows(project).values():
        parts = card_path.split("/", 2)
        if len(parts) == 3 and not parts[0] and parts[1]:
            count[parts[1]] = count.get(parts[1], 0) + 1
    return max(sorted(count), key=lambda g: count[g]) if count else ""


def write_names(path, project, game=""):
    """Write the run's map for the playfield window (and drop the last run's sightings beside
    it, so they are never folded into this project). The map carries the title its clips are
    of, and the window uses it only on a run of that title. Returns how many clips it names;
    never raises."""
    try:
        os.remove(os.path.join(os.path.dirname(path),
                               os.path.basename(path).replace("clip_names_", "clips_seen_")
                               .replace(".json", ".jsonl")))
    except OSError:
        pass
    ok = bool(project and os.path.isdir(project))
    game = game or (project_game(project) if ok else "")
    names = names_of(project, game) if ok else {}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"project": project or "", "game": game or "", "names": names}, f)
        os.replace(tmp, path)
    except OSError:
        return 0
    return len(names)


def seen_path(project):
    return os.path.join(project, "video", SEEN_JSON)


def load(project):
    """``{rel: {"plays": n, "after": {switch: n}, "loops": bool}}`` the emulator saw in this
    project's runs ({} for none)."""
    try:
        with open(seen_path(project), encoding="utf-8") as f:
            data = json.load(f)
        clips = data.get("clips") or {}
        return {k: v for k, v in clips.items() if isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def fold(clips, events):
    """Fold the playfield's *events* (dicts) into *clips* (:func:`load`'s shape); True when
    anything changed."""
    changed = False
    for ev in events:
        rel = ev.get("rel")
        if not rel or not isinstance(rel, str):
            continue
        c = clips.setdefault(rel, {"plays": 0, "after": {}, "loops": False})
        if ev.get("loop"):
            if not c.get("loops"):
                c["loops"] = True
                changed = True
            continue
        c["plays"] = int(c.get("plays") or 0) + 1
        sw = ev.get("switch")
        if sw:
            after = c.setdefault("after", {})
            after[sw] = int(after.get(sw) or 0) + 1
        changed = True
    return changed


def save(project, clips):
    path = seen_path(project)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"rev": REV, "clips": clips}, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


class Merger:
    """The Emulate tab's half: what the playfield window appended to *path* since the last
    look, folded into *project*'s record. One per run (the run's map names the project)."""

    def __init__(self, path, project):
        self.path, self.project = path, project
        self.pos = 0
        self.part = b""

    def poll(self):
        """Fold the new lines in; how many clip events they held. Never raises."""
        if not self.project or not os.path.isdir(os.path.join(self.project, "video")):
            return 0
        try:
            with open(self.path, "rb") as f:
                f.seek(0, 2)
                end = f.tell()
                if end < self.pos:                 # a new run's file
                    self.pos, self.part = 0, b""
                f.seek(self.pos)
                data = f.read()
                self.pos = f.tell()
        except OSError:
            return 0
        data = self.part + data
        lines = data.split(b"\n")
        self.part = lines.pop()
        events = []
        for ln in lines:
            try:
                ev = json.loads(ln.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(ev, dict):
                events.append(ev)
        if not events:
            return 0
        clips = load(self.project)
        if fold(clips, events):
            save(self.project, clips)
        return len(events)


def _times(n):
    return "once" if n == 1 else "%d times" % n


def cell(c):
    """The Video tab's "When it plays" words for one record of :func:`load`."""
    if not c:
        return ""
    after = sorted((c.get("after") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    parts = []
    if after:
        parts.append("After " + after[0][0] + (" +%d" % (len(after) - 1) if len(after) > 1 else ""))
    if c.get("loops"):
        parts.append("loops")
    if not parts:
        parts.append("No switch just before it")
    s = " · ".join(parts)
    return s[0].upper() + s[1:]


def lines(c):
    """The cell's tooltip lines: every switch seen before the clip, and the loop."""
    if not c:
        return []
    plays = int(c.get("plays") or 0)
    out = ["Played %s in the emulator." % _times(plays)] if plays else []
    after = sorted((c.get("after") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    for sw, n in after:
        out.append("After %s: %s" % (sw, _times(n)))
    alone = plays - sum(n for _sw, n in after)
    if alone > 0 and after:
        out.append("With no switch just before it: %s" % _times(alone))
    if c.get("loops"):
        out.append("Plays as a loop: the game starts it again each time it ends.")
    return out
