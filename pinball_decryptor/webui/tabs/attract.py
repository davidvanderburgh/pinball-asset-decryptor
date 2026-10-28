"""Attract tab (PAD-782): the attract mode editor of a Stern Spike 2 game.

The page lists the screens the game shows in attract (read off its program: the last scores, PRESS START, the high
scores and champions, the tutorial clips, the logos) and lets the owner put items of their own between them - photos
(several at once: a slideshow), a clip, a text card - each with its time on the glass, moved up and down past the
game's screens. The modes' challenge champions (PAD-660) are switched on or off here, and the attract flipper sounds
(PAD-641, kept by the Audio tab with the project's other sounds) are set here too, so attract has one home. Run in
emulator starts the Emulate tab with the project's changes.

Everything is the project's (``attract_items`` in ``.staged_changes.json``,
:mod:`...plugins.stern.attract_items`); the build makes the items clips of the game's video bank and the mode runtime
plays them between the game's screens.
"""

import os
import threading

from .. import compat
from .base import TabService, rpc

INTRO = ("Put your own photos, clips and text cards between the game's own attract screens, each for as long as "
         "you like.")
PHOTO_TYPES = [("Pictures", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"), ("All files", "*.*")]
CLIP_TYPES = [("Videos", "*.mp4 *.mov *.m4v *.mkv *.avi *.webm *.wmv *.mpg *.mpeg"), ("All files", "*.*")]
NEW_TEXT = "Your words here"


class AttractTab(TabService):
    ns = "attract"
    key = "Attract"
    label = "Attract"
    group = "Make"
    icon = "film"

    def __init__(self, window):
        super().__init__(window)
        self._project = ""
        self._prof = None
        self._pages = []
        self._rec = None
        self._read_id = 0
        self.set(project="", available=False, why="", reading=False, pages=[], seq=[], champions=True,
                 champions_tip="", champions_shown=False, insider="", running=False, intro=INTRO, count=0, max=0)

    # -- the project ---------------------------------------------------------------------------------------------
    def _folder(self):
        var = getattr(self.window, "write_assets_var", None)
        return ((var.get() if var is not None else "") or "").strip()

    def on_project(self, folder):
        if getattr(self, "_visible", False) or self.window.current_tab_key() == self.key:
            self._read()

    def on_show(self):
        self._visible = True
        if self._folder() != self._project or self._rec is None:
            self._read()
        self._audio_ready()

    def on_running(self, running, mode):
        self.set(running=bool(running))

    def _audio_ready(self):
        """The attract flipper sounds are the Audio tab's (saved with the project's other sounds): its scan of this
        project is what reads them, so start one when it has not read this project."""
        audio = self.window.service("audio")
        folder = self._folder()
        if audio is None or not folder:
            return
        if getattr(audio, "_scan_dir", "") != folder and not getattr(audio, "_scanning", False):
            try:
                audio.scan()
            except Exception:                           # noqa: BLE001 - the section just stays empty
                pass

    def _read(self):
        """The project's record now, and the game's screens off its card (a worker: it may open the card)."""
        from ...plugins.stern import attract_items as AI
        folder = self._folder()
        self._project = folder
        self._rec = AI.load(folder) if folder else AI.Record()
        self._read_id += 1
        rid = self._read_id
        if not folder:
            self._pages, self._prof = [], None
            self.set(project="", available=False, reading=False,
                     why="Set the project folder on the Extract tab first: the items are the project's.")
            self._paint()
            return
        self.set(project=folder, reading=True)

        def work():
            from ...plugins.stern import clip_variants as CV
            why, pages, prof = "", [], None
            try:
                prof = CV.project_title(folder, probe=True)
                why = AI.title_refusal(prof)
                if not why:
                    pages = AI.project_pages(folder, prof)
                    why = AI.project_refusal(folder, prof) if pages else ""
                    if not pages:
                        why = ("The card this project was extracted from is not on this PC, so the app cannot read "
                               "which screens the game shows. Point the project at its card on the Extract tab.")
            except Exception as e:                      # noqa: BLE001 - said on the page
                why = "The game's attract screens could not be read: %s" % e
            self.ctx.loop.post(lambda: self._read_done(rid, prof, pages, why))
        threading.Thread(target=work, daemon=True, name="attract-read").start()

    def _read_done(self, rid, prof, pages, why):
        if rid != self._read_id:
            return
        self._prof, self._pages = prof, pages
        self.set(reading=False, available=not why, why=why)
        self._paint()

    # -- the sequence ----------------------------------------------------------------------------------------------
    def _sequence(self):
        """The game's screens and the items in play order: ``[("game", page index) | ("item", item index)]``."""
        rec = self._rec
        out = []
        for k, p in enumerate(self._pages):
            out += [("item", i) for i, it in enumerate(rec.items) if it.entry == p.entry and it.where == "before"]
            out.append(("game", k))
            out += [("item", i) for i, it in enumerate(rec.items) if it.entry == p.entry and it.where == "after"]
        n = len(self._pages)
        out += [("item", i) for i, it in enumerate(rec.items) if it.entry >= n]       # past the game's: kept, said
        return out

    def _paint(self):
        from ...plugins.stern import attract_items as AI
        rec = self._rec or AI.Record()
        seq, run = [], None
        for kind, k in self._sequence():
            if kind == "game":
                p = self._pages[k]
                if run is not None and run["name"] == p.name and run["sometimes"] == p.sometimes:
                    run["last"] = p.entry
                    run["n"] += 1
                    continue
                run = {"t": "game", "name": p.name, "first": p.entry, "last": p.entry, "n": 1,
                       "sometimes": p.sometimes, "seconds": round(p.seconds, 1)}
                seq.append(run)
            else:
                run = None
                it = rec.items[k]
                seq.append({"t": "item", "i": k, "kind": it.kind, "label": it.label(), "text": it.text,
                            "file": os.path.basename(it.file) if it.file else "", "seconds": it.seconds,
                            "missing": bool(it.file) and not os.path.isfile(it.file),
                            "past": it.entry >= len(self._pages)})
        # the modes' challenge champions (PAD-660): a part of the mode maker, so only with its preview on
        from ...core import preview
        shown = bool(preview.enabled("modes"))
        self.set(pages=len(self._pages), seq=seq, champions=bool(rec.champions), count=len(rec.items),
                 max=AI.MAX_ITEMS, insider=AI.INSIDER_WORDS, champions_shown=shown,
                 champions_tip=("The champion of each mode's challenge game, shown in attract after the game's own "
                                "champions. Off: only the game's own.") if shown else "")

    def _save(self, what):
        from ...plugins.stern import attract_items as AI
        if not self._project:
            return False
        AI.save(self._project, self._rec)
        if what:
            self.log("Attract: %s." % what, "info")
        self._paint()
        return True

    # -- the buttons -----------------------------------------------------------------------------------------------
    @rpc
    def refresh(self):
        self._read()
        return True

    @rpc
    def add(self, kind, first, last, where):
        """Add items: ``photo`` (several files: a slideshow), ``clip`` or ``text``, after the game screen run
        ``first..last`` (``where`` after: after its last screen; before: before its first)."""
        from ...plugins.stern import attract_items as AI
        if not self.get("available") or self.get("running"):
            return False
        rec = self._rec
        room = AI.MAX_ITEMS - len(rec.items)
        if room <= 0:
            compat.messagebox.showinfo("Attract", "A card can carry at most %d attract items." % AI.MAX_ITEMS)
            return False
        entry = int(last) if where == "after" else int(first)
        where = "after" if where == "after" else "before"
        at = self._insert_at(entry, where)
        if kind == "text":
            rec.items.insert(at, AI.Item("text", entry, where, text=NEW_TEXT, seconds=AI.DEFAULT_SECONDS["text"]))
            return self._save("a text card %s the game's screen %d" % (where, entry + 1))
        start = self.window.last_browse_dir("attract")
        start = start if start and os.path.isdir(start) else ""
        fd = compat.filedialog
        if kind == "photo":
            got = fd.askopenfilenames(title="Choose photos for the attract mode (several: a slideshow)",
                                      initialdir=start, filetypes=PHOTO_TYPES)
            files = list(got) if isinstance(got, (list, tuple)) else ([got] if got else [])
        elif kind == "clip":
            got = fd.askopenfilename(title="Choose a clip for the attract mode", initialdir=start,
                                     filetypes=CLIP_TYPES)
            files = [got[0] if isinstance(got, (list, tuple)) else got] if got else []
        else:
            return False
        files = [os.path.normpath(f) for f in files if f][:room]
        if not files:
            return False
        self.window.remember_browse_dir("attract", os.path.dirname(files[0]))
        for n, f in enumerate(files):
            rec.items.insert(at + n, AI.Item(kind, entry, where, file=f, seconds=AI.DEFAULT_SECONDS[kind]))
        return self._save("%s %s the game's screen %d" % (
            "%d photo(s)" % len(files) if kind == "photo" else "the clip %s" % os.path.basename(files[0]),
            where, entry + 1))

    def _insert_at(self, entry, where):
        """Where in the record an item put ``where`` the game's screen ``entry`` goes: after the others there."""
        at = len(self._rec.items)
        for i, it in enumerate(self._rec.items):
            if it.entry == entry and it.where == where:
                at = i + 1
        return at

    @rpc
    def move(self, i, delta):
        """Move item ``i`` one step up (-1) or down (+1) in the sequence: past another item, or past a game screen
        (a run of them in one step), when it then plays on the other side of it."""
        rec = self._rec
        i, delta = int(i), (1 if int(delta) > 0 else -1)
        if self.get("running") or not 0 <= i < len(rec.items):
            return False
        seq = self._sequence()
        pos = seq.index(("item", i))
        j = pos + delta
        if not 0 <= j < len(seq):
            return False
        it = rec.items[i]
        kind, k = seq[j]
        if kind == "item":                              # past its neighbour: its place, then just before / after it
            other = rec.items[k]
            rec.items.pop(i)
            kk = rec.items.index(other)
            it.entry, it.where = other.entry, other.where
            rec.items.insert(kk if delta < 0 else kk + 1, it)
            return self._save("")
        # past a game screen (and the rest of its run of the same name)
        name = self._pages[k].name
        while 0 <= j + delta < len(seq) and seq[j + delta][0] == "game" and self._pages[seq[j + delta][1]].name == name:
            j += delta
            k = seq[j][1]
        p = self._pages[k]
        it.entry, it.where = p.entry, ("after" if delta > 0 else "before")
        # in the record: after the items now before it at that place, before those after it
        rec.items.pop(i)
        same = [n for n, o in enumerate(rec.items) if o.entry == it.entry and o.where == it.where]
        rec.items.insert((same[-1] + 1) if (same and delta < 0) else (same[0] if same else len(rec.items)), it)
        return self._save("")

    @rpc
    def move_by(self, i, steps):
        """A drag: item ``i`` moved ``steps`` rows of the painted sequence (one at a time, as the arrows do)."""
        i, steps = int(i), int(steps)
        item = self._rec.items[i] if 0 <= i < len(self._rec.items) else None
        moved = False
        for _ in range(min(abs(steps), 400)):
            if item is None or not self.move(self._rec.items.index(item), 1 if steps > 0 else -1):
                break
            moved = True
        return moved

    @rpc
    def remove(self, i):
        rec = self._rec
        i = int(i)
        if self.get("running") or not 0 <= i < len(rec.items):
            return False
        it = rec.items.pop(i)
        return self._save("%s taken off" % it.label())

    @rpc
    def set_seconds(self, i, seconds):
        from ...plugins.stern import attract_items as AI
        rec = self._rec
        i = int(i)
        if not 0 <= i < len(rec.items):
            return False
        it = rec.items[i]
        s = AI.clean_seconds(seconds, it.kind)
        if s == it.seconds:
            return False
        it.seconds = s
        return self._save("")

    @rpc
    def set_text(self, i, text):
        from ...plugins.stern import attract_items as AI
        rec = self._rec
        i = int(i)
        if not 0 <= i < len(rec.items) or rec.items[i].kind != "text":
            return False
        t = AI.clean_text(text)
        if not t or t == rec.items[i].text:
            return False
        rec.items[i].text = t
        return self._save("")

    @rpc
    def set_champions(self, on):
        if self._rec is None or self.get("running"):
            return False
        self._rec.champions = bool(on)
        return self._save("the modes' challenge champions are %s in attract mode"
                          % ("shown" if on else "not shown"))

    @rpc
    def try_it(self):
        """Run in emulator: the Emulate tab, started with the project's changes (the attract items among them)."""
        emu = self.window.service("emulate")
        if emu is None:
            return False
        var = getattr(emu, "emulate_overrides_var", None)
        if var is not None and not var.get():
            var.set(True)
        self.window.select_tab("emulate")
        try:
            return bool(emu.toggle()) if not (getattr(emu, "_last_up", False) or emu._launched()) else True
        except Exception:                               # noqa: BLE001 - the Emulate tab says why
            return False


TAB = AttractTab
