"""Service menu: the game's operator menu as the machine will show it, with the app's own rows in it (PAD-1382).

David: "how does the user edit the service menu? I feel like we should have a visual render of the service menu in
our app so that it can be easily updated for the users." Each setting of ours (MUSIC MODE, EDITION, CO-OP PLAY,
HANDICAP, the picture settings) is switched on its own tab and the Write places it on a spare row of the game's; the
only word of where it went was a line of the build log, and since PAD-1382 several can share MORE SETTINGS and the
row under it. This page draws each page of the menu that carries one of ours, as the machine draws it
(:func:`.service_menu.pages`, planned exactly as a Write plans), lets the user step through MORE SETTINGS as the
operator will, and switches the rows on and off through the same actions the other tabs use."""

import hashlib
import os
import tempfile
import threading

from .base import TabService, rpc

INTRO = ("The game's service menu as this card will show it at the machine: the rows the app adds, where the Write "
         "puts them, and what the operator sees. Click a row for its help.")
#: the real menu: what ticking it does, and costs
REAL_NOTE = ("Boots the game in the emulator, hidden and muted, with this project's edits, and shows the page as the "
             "game itself draws it. A minute or more (longer the first time a card is used); the emulator must be "
             "stopped.")

#: each setting of ours, its name, and where it is switched when not here
SETTINGS = (
    ("music_mode", "Music Mode", "Set on the Audio tab: give a sound more than one music choice."),
    ("edition", "Edition", "Set on the Write tab (Editions...) for a card that is one of several editions."),
    ("coop_play", "Co-op Play", ""),
    ("handicap", "Handicap", ""),
    ("brightness", "Picture settings", "Brightness, Contrast and Saturation (Write tab)."),
)


def project_menu(project):
    """``(why, menu)`` for *project*: :func:`.service_menu.pages` of its card's game program, or the reason none."""
    from ...plugins.stern import service_menu as SM
    if not project or not os.path.isdir(project):
        return "Open a project first.", None
    got = _ELF.get(project)
    if got is None:
        try:
            got = SM.find_program(project)
        except ValueError as e:
            return str(e), None
        _ELF.clear()
        _ELF[project] = got
    elf, source = got
    from ...plugins.stern.adjustments import is_wide
    wide = is_wide(elf)
    try:
        if wide:                                        # Spike 3: the rows its own Write puts on a card
            from ...plugins.stern import spike3_menu as S3
            rows = S3.rows_wanted(project)
        else:
            rows = SM.wanted(project)
        menu = SM.pages(elf, rows)
    except Exception as e:                              # noqa: BLE001 - said on the page
        return "This game's service menu could not be read (%s)." % e, None
    menu["source"] = source
    return "", menu


_ELF = {}


class ServiceMenuTab(TabService):
    ns = "svcmenu"
    key = "Service Menu"
    label = "Service menu"
    group = "Make"
    icon = "list"

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self._read_id = 0
        self._shots = {}                # (project, category, row) -> png: the real menu read this session
        self.set(intro=INTRO, project="", reading=False, why="", menu=None, settings=[],
                 real_on=False, real_busy=False, real_png="", real_why="", real_for="",
                 real_note=REAL_NOTE,
                 none_why="Open or extract a Stern Spike 2 card project first (Extract tab): the menu is its game's.")

    def _modes(self):
        return self.window.service("modes")

    def _project(self):
        modes = self._modes()
        return modes.project() if modes is not None else ""

    def _settings(self, project):
        """The app's settings that can have a row, in the owner's order (:func:`.service_menu.arrange`'s)."""
        from ...plugins.stern import coop_play as CP, handicap as HC, picture_settings as PS
        from ...plugins.stern import service_menu as SM
        out = []
        for key, name, where in SETTINGS:
            if key == "brightness" and not PS.OFFERED:
                continue
            row = {"key": key, "name": name, "where": where, "can": False, "on": False, "note": ""}
            if key == "coop_play":
                on = CP.load(project)
                row.update(can=on, on=CP.menu_asked(project),
                           note="" if on else "Turn co-op play on first, for its row.")
            elif key == "handicap":
                row.update(can=True, on=HC.load(project))
            out.append(row)
        mine = SM.load(project)
        rank = {k: n for n, k in enumerate(mine["order"])}
        return [r for _n, r in sorted(enumerate(out), key=lambda x: (rank.get(x[1]["key"], len(rank)), x[0]))]

    def publish(self):
        project = self._project()
        self._read_id += 1
        rid = self._read_id
        if not project:
            self.set(project="", menu=None, why="", reading=False, settings=[], real_png="", real_why="")
            return
        self.set(project=project, reading=True, settings=self._settings(project), real_png="", real_why="")

        def work():
            try:
                why, menu = project_menu(project)
            except Exception as e:                      # noqa: BLE001 - said on the page
                why, menu = "This game's service menu could not be read (%s)." % e, None
            self.ctx.loop.post(lambda: self._done(rid, why, menu))
        threading.Thread(target=work, daemon=True, name="svcmenu-read").start()

    def _done(self, rid, why, menu):
        if rid != self._read_id:
            return
        self.set(reading=False, why=why, menu=menu)

    @rpc
    def set_row(self, key, on):
        """Switch one of our rows on or off, through the action its own tab uses."""
        modes = self._modes()
        if modes is None:
            return False
        if key == "coop_play":
            ok = modes.set_coop_menu(bool(on))
        elif key == "handicap":
            ok = modes.set_handicap(bool(on))
        else:
            return False
        self.publish()
        return ok

    # -- the owner's order of the app's rows (round 3) ----------------------------------------------------------------
    def _save(self, project, data, what):
        from ...core import history_log
        from ...plugins.stern import service_menu as SM
        before = SM.load(project)
        SM.save(project, data)
        hist = history_log.diff_scalar("service menu  " + what, "", "changed")
        history_log.record(project, [hist] if hist else [])
        if before != data:
            self.log("[service menu] %s - the card gets it at the next Write" % what)
        self.publish()

    @rpc
    def move(self, key, step):
        """Move one row up (-1) or down (+1) in the owner's order of the app's rows and their own."""
        from ...plugins.stern import service_menu as SM
        project = self._project()
        if not project:
            return False
        keys = [r["key"] for r in self._settings(project)]
        if key not in keys:
            return False
        i = keys.index(key)
        j = max(0, min(len(keys) - 1, i + int(step)))
        keys[i], keys[j] = keys[j], keys[i]
        data = SM.load(project)
        data["order"] = keys
        self._save(project, data, "order of the rows")
        return True

    # -- the real menu, from the emulator (round 3; off unless ticked) ----------------------------------------------
    @rpc
    def set_real(self, on):
        self.set(real_on=bool(on), real_why="")
        return True

    @rpc
    def render(self, page_index, row):
        """Read page *page_index*'s real look, row *row* picked, from the game itself in the emulator (minutes the first
        time: the project's edits are prepared as Emulate prepares them, then a hidden, muted run walks the menu)."""
        from ...plugins.stern import mode_project as MP
        from ...plugins.stern import service_menu as SM
        project = self._project()
        menu = self.get("menu") if hasattr(self, "get") else None
        menu = menu or {}
        pages = menu.get("pages") or []
        if not project or not (0 <= int(page_index) < len(pages)) or self.get("real_busy"):
            return False
        page = pages[int(page_index)]
        if menu.get("wide"):
            self.set(real_why="The real menu is read on Spike 2 games only for now: the Spike 3 emulator does not open "
                              "the settings pages yet.")
            return False
        if page.get("rank") is None:
            self.set(real_why="The real menu can be read for the Machine Settings pages only.")
            return False
        key = (project, page["category"], int(row))
        if key in self._shots and os.path.isfile(self._shots[key]):
            self.set(real_png=self._shots[key], real_why="", real_for=page["name"])
            return True
        got = MP.project_card(project)
        card = getattr(got, "image", "") if got is not None else ""
        emulate = self.window.service("emulate")
        if not card or emulate is None or not hasattr(emulate, "menu_shot"):
            self.set(real_why="The emulator is not available for this card.")
            return False
        folder = os.path.join(tempfile.gettempdir(), "spike2_svcmenu")
        os.makedirs(folder, exist_ok=True)
        png = os.path.join(folder, "%s.png" % hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16])
        steps = SM.walk(page["rank"], int(row), page.get("style", "list"), len(page["rows"]))
        self.set(real_busy=True, real_why="", real_png="")

        def work():
            try:
                why = emulate.menu_shot(card, project, steps, png, game=getattr(got, "game_dir", "") or "")
            except Exception as e:                      # noqa: BLE001 - said on the page
                why = "The emulator could not show the menu: %s" % e
            self.ctx.loop.post(lambda: self._real_done(key, png, why, page["name"]))
        threading.Thread(target=work, daemon=True, name="svcmenu-real").start()
        return True

    def _real_done(self, key, png, why, name):
        if not why:
            self._shots[key] = png
        self.set(real_busy=False, real_why=why, real_png="" if why else png, real_for=name)

    @rpc
    def refresh(self):
        self.publish()
        return True

    def on_show(self):
        self._visible = True
        self.publish()

    def on_hide(self):
        self._visible = False

    def on_project(self, folder):
        if self._visible:
            self.publish()

    def on_manufacturer(self, mfr):
        if self._visible:
            self.publish()


TAB = ServiceMenuTab
