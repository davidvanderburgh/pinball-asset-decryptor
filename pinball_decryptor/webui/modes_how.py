"""PAD-1064: How it works, on the page of each of the game's own modes - read-only, from the game program.

A tester asked to see "the code or logic behind the game's built-in modes": its rules, what starts it, and "which
sound effects and callouts are associated with specific modes". A stock mode is compiled C++ in the game program,
so there is no source to show; what the app reads off the program is shown instead, in words:

* what starts it - the rule (or the other mode) whose code calls its start, from the card's stock-mode table
  (``start`` lines: :mod:`..plugins.stern.stock_modes`; a generated table names the class too since
  :data:`..plugins.stern.stock_reader.READER_REV` 6), and a screen it is picked on;
* the clips its own code plays (:mod:`..plugins.stern.clip_modes`, the Video tab's reading);
* the sounds and callouts its own code asks for by a fixed number, each with its Sound Test name and the file the
  extract made of it (:attr:`..plugins.stern.clip_sounds.SoundReading.modes`). EMULATOR-CHECKED against PAD-455's
  census on Godzilla LE 1.16: of the 40 listed calls the census heard, 40 played the listed request and 39 while
  their own mode was forced (the 40th, Planet X Hurry Up, while Planet X Multiball ran - the multiball starts it).

Its timers and awards are the page's other section, as before. The card's clips and sounds are read on a worker,
once per card (``clip_modes.read_card`` keeps the reading by the card file, so after the Video tab's first look it
is instant).
"""

import os
import re
import threading

#: the most clips and sounds a page lists before "and N more"
CLIPS_MAX = 40
SOUNDS_MAX = 60

HOW_NOTE = ("Read from the game program: the game's modes are compiled into it, so there is no code to show, "
            "only what the app can read off it.")
SOUNDS_NOTE = ("The sounds this mode's own code asks for by a fixed number. A sound the game works out while it "
               "plays (a random pick, one of a list) or asks for from code several modes share is not listed.")

_START = re.compile(r"^(start|select):\s*(.*)$")
_IN = re.compile(r",\s*in ([A-Za-z_][\w:]*?)::v\[\d+\]\s*$")


def _camel_words(name):
    """``RuleBuildingLocks`` -> ``Building Locks``, ``Rule_Danger_Room`` -> ``Danger Room``."""
    s = re.sub(r"^(Rule|crule|Mode|cmode)_?", "", name) or name
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s.replace("_", " "))
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in s.split())


def start_words(build, mode):
    """``[sentence]``: what starts *mode* (a :class:`.stock_modes.Mode` of *build*), one line per way the table
    names, in its order; ``[]`` when the table names none in words a person can use."""
    from ..plugins.stern import clip_modes as CM
    by_cls = {m.cls: m for m in build.modes.values()}
    out = []
    for line in getattr(mode, "starts", None) or ():
        m = _START.match(line.strip())
        if not m:
            continue                                        # a stop line
        kind, rest = m.groups()
        if kind == "select" or "select screen" in rest:
            words = "Picked by the player on one of the game's selection screens."
        else:
            got = _IN.search(rest)
            if not got:
                continue
            cls = got.group(1)
            if cls in by_cls:
                words = "Started by the game's own %s mode, while it runs." % by_cls[cls].name
            elif cls.startswith("cmode_") or cls.startswith("BDL"):
                words = "Started by the game's own %s mode, while it runs." % CM.mode_label(cls)
            else:
                words = "Started by the game's %s rule (the code that counts its shots)." % _camel_words(cls)
        if words not in out:
            out.append(words)
    return out


class HowItWorksMixin:
    """Mixed into the Modes tab: ``self._how`` is the card's :class:`.clip_modes.CardClips` once read."""

    def _init_how(self):
        self._how = None
        self._how_key = None
        self._how_run = 0
        self._how_names = None              # (sound_requests.tsv rows, {idx: audio file}) of the project

    def _how_card(self, project):
        from ..plugins.stern import mode_project as MP
        try:
            card = MP.project_card(project)
        except Exception:                                   # noqa: BLE001 - no card, nothing to read
            card = None
        return getattr(card, "image", "") or ""

    def _how_kick(self):
        """Read the project's card's clips and sounds on a worker, once per card; the open game mode's page
        follows when it is done."""
        project = self.project()
        card = self._how_card(project) if project else ""
        try:
            st = os.stat(card) if card else None
        except OSError:
            st = None
        key = (os.path.normcase(project or ""), card, st.st_size if st else 0, int(st.st_mtime) if st else 0)
        if key == self._how_key:
            return
        self._how_run += 1
        run = self._how_run
        self._how_key, self._how, self._how_names = key, None, None
        if not card:
            return

        def _work():
            from ..plugins.stern import clip_modes as CM
            try:
                got = CM.read_card(card, CM.manifest_rows(project), cancel=lambda: self._how_run != run)
            except Exception as e:                          # noqa: BLE001 - never break the tab
                got = CM.CardClips(card=card, note="the card could not be read (%s)" % e)

            def _apply():
                if self._how_run != run:
                    return
                self._how = got
                if self._game_mode is not None:
                    self._publish_game_mode()
            self.ctx.loop.post(_apply)

        threading.Thread(target=_work, daemon=True, name="modes-how").start()

    def _how_class(self, clips, mode):
        """The reading's class for the table's *mode*: the same class (a C++ title), else the one whose words
        are the mode's name (a plain-C title's mode key)."""
        reading = clips.reading
        known = set(reading.labels) | set(clips.sound_reading.modes)
        if mode.cls in known:
            return mode.cls

        def flat(t):
            return re.sub(r"[^a-z0-9]", "", (t or "").lower())
        for c in sorted(known):
            if flat(reading.label(c)) == flat(mode.name):
                return c
        return ""

    def _how_sound_names(self):
        if self._how_names is None:
            from ..plugins.stern import clip_sounds as CS
            project = self.project() or ""
            self._how_names = (CS.read_requests(project), CS.audio_files(project))
        return self._how_names

    def _how_sound(self, sr, req, calls):
        """One listed sound: its file (where the extract made one), else its Sound Test name, else its number."""
        rows, audio = self._how_sound_names()
        row = rows.get(req) or {}
        name = sr.names.get(req) or row.get("name", "")
        files = [audio[i] for i in row.get("idx", ()) if i in audio]
        project = self.project() or ""
        text = os.path.splitext(os.path.basename(files[0]))[0] if files else (name or "Sound request %d" % req)
        if len(files) > 1:
            text += " (+%d)" % (len(files) - 1)
        lines = ["Sound request %d" % req]
        if name:
            lines.append("Sound Test: %s" % name)
        lines += [os.path.basename(f) for f in files]
        if calls > 1:
            lines.append("Asked for in %d places of its code" % calls)
        return {"key": str(req), "text": text, "name": name if files and name and name not in text else "",
                "path": os.path.join(project, *files[0].split("/")) if files and project else "",
                "tip": {"head": text, "lines": lines}}

    def _how_for(self, build, mid):
        """``{"starts", "clips", "sounds", ...}`` for the game's mode *mid*: what the page's How it works shows."""
        mode = build.modes.get(mid)
        out = {"note": HOW_NOTE, "starts": start_words(build, mode) if mode else [], "clips": [], "clips_more": "",
               "sounds": [], "sounds_more": "", "sounds_note": SOUNDS_NOTE, "reading": False, "unread": ""}
        clips = self._how
        if mode is None:
            return out
        if clips is None:
            out["reading"] = bool(self._how_key and self._how_key[1])
            out["unread"] = ("Reading the card's clips and sounds..." if out["reading"] else
                             "The card the project was extracted from is not on this PC, so its clips and sounds "
                             "can't be read.")
            return out
        cls = self._how_class(clips, mode)
        if not cls:
            out["unread"] = ("The app can't tell this mode's code apart in the game program, so its clips and sounds "
                             "are not listed." if not clips.note else "Clips and sounds: %s." % clips.note)
            return out
        reading = clips.reading
        by_name = {}
        for rel, name in clips.name_of.items():
            by_name.setdefault(name, rel)
        names = sorted((n for n in reading.refs if cls in reading.modes_of(n)), key=str.lower)
        out["clips"] = [{"key": n, "text": n, "rel": by_name.get(n, ""),
                         "tip": {"head": n, "lines": [by_name[n]] if n in by_name else
                                 ["Not in this project's extract"]}} for n in names[:CLIPS_MAX]]
        if len(names) > CLIPS_MAX:
            out["clips_more"] = "And %d more." % (len(names) - CLIPS_MAX)
        sr = clips.sound_reading
        rows = sr.modes.get(cls) or []
        out["sounds"] = [self._how_sound(sr, req, n) for req, _at, n in rows[:SOUNDS_MAX]]
        if len(rows) > SOUNDS_MAX:
            out["sounds_more"] = "And %d more." % (len(rows) - SOUNDS_MAX)
        if not rows and sr.note and not sr.modes:
            out["sounds_note"] = "Sounds: %s." % sr.note
        return out
