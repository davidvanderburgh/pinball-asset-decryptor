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
from ...plugins.stern import boot_flip as BF

INTRO = ("The game's service menu as this card will show it at the machine: the rows the app adds, where the Write "
         "puts them, and what the operator sees. Click a row for its help.")
#: the real menu: what ticking it does, and costs
REAL_NOTE = ("Boots the game in the emulator, hidden and muted, with this project's edits, and shows the page as the "
             "game itself draws it. A minute or more (longer the first time a card is used); the emulator must be "
             "stopped.")

#: each setting of ours, its name, and where it is switched when not here
SETTINGS = (
    ("music_mode", "Music Mode", "Set on the Audio tab: give a sound more than one music choice."),
    ("edition", "Edition", "Only for a card that holds several editions of the game (Write tab, Editions...): a "
                           "card of one edition has none to pick."),
    ("handicap", "Handicap", ""),
    ("colour_blind", "Color Blind", "Play options tab: color-blind insert colors."),
    ("spoken_scores", "Spoken Scores", "Play options tab: the machine says each player's score."),
    ("image_set", "Image Set", "Made on the Images tab (Themes, under Advanced): the operator picks which theme "
                               "the screens show."),
    ("brightness", "Picture settings", "Brightness, Contrast and Saturation (Write tab)."),
    ("saved_progress", "Saved Progress", "On the card when the project keeps progress between games (a variable "
                                         "saved between games). Clear clears it; so does a factory reset."),
    ("boot_show", "Boot Menu", BF.SHOW_WHERE),                      # Simon (2026-11-27)
    ("boot_timer", "Boot Menu Timer", BF.TIMER_WHERE),
    ("boot_flip", "Boot Menu Flipper", "For a multi-boot card (Multi-boot tab): the operator's switch for the right "
                                       "flipper hold back to the boot menu. The hold is always 5 s; the value is "
                                       "how many seconds no game must have been running before that hold works, "
                                       "so it never fires during play (0 Off, 15 to start with and the "
                                       "recommended minimum, up to 120). It wins over the Multi-boot tab's own "
                                       "setting."),
)

#: a ticked row with nothing behind it yet goes on the card with placeholder values (PR #40 review: shown after the
#: row's place, "On Custom Code. A placeholder ...", so the owner sees it is one)
PLACEHOLDER_NOTE = "A placeholder (values %s): nothing uses it yet. %s"

#: PAD-1393 round 2: what an unticked row of :data:`.service_menu.OFF_KEYS` means for the card
OFF_NOTES = {
    "music_mode": "Off the card: every sound plays its own music. Tick to add its row.",
    "edition": "Off the card: the card cannot be picked by edition. Tick to add its row.",
    "image_set": "Off the card: the screens show the scenes as the project has them. Tick to add its row.",
}


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
        from ...plugins.stern import handicap as HC, picture_settings as PS
        from ...plugins.stern import service_menu as SM
        out = []
        try:                                            # PAD-1393: the settings the project has, ticked or not
            has = {w[0] for w in SM.wanted(project, honour_off=False)}
        except Exception:                               # noqa: BLE001 - shown as off then
            has = set()
        ticked = SM.on_keys(project)
        for key, name, where in SETTINGS:
            if key == "brightness" and not PS.OFFERED:
                continue
            row = {"key": key, "name": name, "where": where, "can": False, "on": False, "note": ""}
            if key in SM.OFF_KEYS:                      # PAD-1393 round 2: ticked/unticked here
                on = key in ticked                      # round 3: unticked until the owner ticks it
                if on and key not in has:               # Simon: a row can go on before there is anything behind it
                    note = PLACEHOLDER_NOTE % (", ".join(SM.PLACEHOLDER_NAMES), where)
                elif on:
                    note = ""
                else:
                    note = OFF_NOTES[key] + ("" if key in has else " " + where)
                row.update(can=True, on=on, note=note)
            elif key in SM.BOOT_KEYS:                   # Simon: needs nothing in the project; unticked to start with
                on = key in ticked
                row.update(can=True, on=on, note="" if on else "Not on the card: tick to add its row. " + where)
            elif key == "handicap":
                on = HC.load(project)
                row.update(can=True, on=on, note="" if on else "Not on the card: tick to add its row.")
            elif key in ("colour_blind", "spoken_scores"):     # PAD-1589: the Play options tab's ticks
                from ...plugins.stern import accessibility as AC
                on = bool(AC.load_cvd(project) if key == "colour_blind" else AC.load_spoken(project))
                row.update(can=True, on=on, note="" if on else "Not on the card: tick to add its row.")
            elif key == "saved_progress":               # PAD-1402: follows the modes, not switched here
                on = key in has
                row.update(on=on, note="" if on else "Not on the card: nothing in the project is saved between "
                                                     "games.")
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
        from ...plugins.stern import service_menu as SM
        modes = self._modes()
        if modes is None:
            return False
        if key == "handicap":
            ok = modes.set_handicap(bool(on))
        elif key == "colour_blind":                     # PAD-1589
            ok = modes.set_colour_blind(bool(on))
        elif key == "spoken_scores":
            ok = modes.set_spoken_scores(bool(on))
        elif key in SM.TICK_KEYS:                        # PAD-1393 round 2: the row on or off the card, the setting kept
            project = self._project()
            if not project:
                return False
            data = SM.load(project)
            ticked = set(data["on"])
            if on:
                ticked.add(key)
            else:
                ticked.discard(key)
            data["on"] = sorted(ticked)
            name = dict((k, n) for k, n, _w in SETTINGS)[key]
            self._save(project, data, "%s %s" % (name, "on the card" if on else "left off the card"))
            return True
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
        self.publish()

    # PAD-1546: behind another tab nothing is read, on_show reads it
    def on_project(self, folder):
        if self.shown():
            self.publish()

    def on_manufacturer(self, mfr):
        if self.shown():
            self.publish()


TAB = ServiceMenuTab
