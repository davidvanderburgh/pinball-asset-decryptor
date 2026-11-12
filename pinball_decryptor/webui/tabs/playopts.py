"""Play options: what changes how the game plays or reports and keeps Insider Connected (PAD-1204).

David: the Modes tab's banner says a card with modes sends nothing to Insider Connected, so people reading it took
every tick on that tab to cost them Insider Connected, and the ticks had grown too crammed beside the mode list.
Handicap per player (PAD-1033), Prolonged Competition (PAD-1041), the score feed (PAD-1204) and inactivity pausing
the timers (PAD-1022) change no score, so a card carrying only those stays on Insider Connected: they have a tab of
their own that says so.

The options' state and actions stay the Modes service's (``modes.set_handicap``, ``modes.set_prolonged_comp``,
``modes.set_score_feed``, ``modes.set_idle_pause``, the handicap levels dialog): this tab asks it to publish them for
the project and its page draws them from the ``modes`` namespace."""

from .base import TabService

#: the page's lead and the line that says Insider Connected stays (mode_project.KEEPS_IC_NOTE)
#: (no word of the mode maker: the tab shows on a Spike 2 card whatever the Modes tab's switch says)
INTRO = "Options for how the game itself plays and what it reports. Tick what you want, then Write the card."


class PlayOptionsTab(TabService):
    ns = "playopts"
    key = "Play Options"
    label = "Play options"
    group = "Make"
    icon = "gear"

    def __init__(self, window):
        super().__init__(window)
        from ...plugins.stern import mode_project as MP
        self._visible = False
        self.set(intro=INTRO, keeps_ic=MP.KEEPS_IC_NOTE, keeps_ic_head=MP.KEEPS_IC_HEAD, project="",
                 none_why="Open or extract a Stern Spike 2 card project first (Extract tab): the options are the "
                          "project's.")

    def _modes(self):
        return self.window.service("modes")

    def publish(self):
        """The four options for the project now, from the Modes service (its state, its actions)."""
        modes = self._modes()
        project = modes.project() if modes is not None else ""
        if modes is not None:
            for name in ("_publish_handicap", "_publish_comp", "_publish_feed", "_publish_idle"):
                try:
                    getattr(modes, name)(project)
                except Exception:                           # noqa: BLE001 - that option just stays as it was
                    pass
        self.set(project=project)

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


TAB = PlayOptionsTab
