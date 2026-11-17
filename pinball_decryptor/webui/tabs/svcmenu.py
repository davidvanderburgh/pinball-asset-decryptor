"""Service menu: the game's operator menu as the machine will show it, with the app's own rows in it (PAD-1382).

David: "how does the user edit the service menu? I feel like we should have a visual render of the service menu in
our app so that it can be easily updated for the users." Each setting of ours (MUSIC MODE, EDITION, CO-OP PLAY,
HANDICAP, the picture settings) is switched on its own tab and the Write places it on a spare row of the game's; the
only word of where it went was a line of the build log, and since PAD-1382 several can share MORE SETTINGS and the
row under it. This page draws each page of the menu that carries one of ours, as the machine draws it
(:func:`.service_menu.pages`, planned exactly as a Write plans), lets the user step through MORE SETTINGS as the
operator will, and switches the rows on and off through the same actions the other tabs use."""

import threading

from .base import TabService, rpc

INTRO = ("The game's service menu as this card will show it at the machine: the rows the app adds, where the Write "
         "puts them, and what the operator sees. Click a row for its help.")

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
    from ...plugins.stern import mode_project as MP
    from ...plugins.stern import service_menu as SM
    from ...plugins.stern import title_reader as TR
    got = MP.project_card(project) if project else None
    card = getattr(got, "image", "") if got is not None else ""
    if not card:
        return ("This project's card image is not where it was extracted from, so its game's menu cannot be read.",
                None)
    rows = SM.wanted(project)
    elf = _ELF.get(card)
    if elf is None:
        elf = TR.game_program(card)[2]
        _ELF.clear()
        _ELF[card] = elf
    try:
        return "", SM.pages(elf, rows)
    except Exception as e:                              # noqa: BLE001 - said on the page
        return "This game's service menu could not be read (%s)." % e, None


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
        self.set(intro=INTRO, project="", reading=False, why="", menu=None, settings=[],
                 none_why="Open or extract a Stern Spike 2 card project first (Extract tab): the menu is its game's.")

    def _modes(self):
        return self.window.service("modes")

    def _project(self):
        modes = self._modes()
        return modes.project() if modes is not None else ""

    def _settings(self, project):
        from ...plugins.stern import coop_play as CP, handicap as HC, picture_settings as PS
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
        return out

    def publish(self):
        project = self._project()
        self._read_id += 1
        rid = self._read_id
        if not project:
            self.set(project="", menu=None, why="", reading=False, settings=[])
            return
        self.set(project=project, reading=True, settings=self._settings(project))

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
