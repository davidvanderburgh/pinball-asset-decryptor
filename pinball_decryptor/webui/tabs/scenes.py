"""The Scenes tab (PAD-251): every scene of the card, drawn as the machine draws it, and the
scene editor.  It used to be a floating window over the other tabs; it is a page of its own
now, like Modes.

The scenes' state and calls stay where they always were, in the Text tab's
:class:`~..text_scenes.TextScenesService` (namespace ``text_scenes``): the Images, Text, Video
and Fonts jumps ("Show in Scenes…", "Scenes…") open it there and it brings this tab forward.
This service only says which project the page shows and keeps it in step with the project
folder.  The page is ``static/js/tabs/scenes.js``.
"""

import os

from .base import TabService


class ScenesTab(TabService):
    ns = "scenes"
    key = "Scenes"

    def __init__(self, window):
        super().__init__(window)
        self._folder_var = None
        self.set(folder="", empty="")

    def _scenes(self):
        text = self.window.service("text")
        return getattr(text, "scenes", None)

    def _assets(self):
        text = self.window.service("text")
        try:
            return (text._assets_path() or "").strip() if text is not None else ""
        except Exception:                                # noqa: BLE001
            return ""

    def _showing(self):
        return self.ctx.store.get("shell", "tab") == self.ns

    def _hook_folder(self):
        """The project folder is the Extract tab's (``write_assets_var``); a new one while this
        page shows (the Project menu) opens its scenes."""
        var = getattr(self.window, "write_assets_var", None)
        if var is None or var is self._folder_var:
            return
        self._folder_var = var
        try:
            var.trace_add("write", lambda *_a: self.ctx.loop.post(self._folder_changed))
        except Exception:                                # noqa: BLE001
            pass

    def _folder_changed(self):
        if self._showing():
            self.show_project()

    def show_project(self):
        """Open the scenes of the current project folder (nothing is re-read when it is the one
        already showing)."""
        self._hook_folder()
        svc = self._scenes()
        assets = self._assets()
        if svc is None:
            self.set(empty="unavailable", folder="")
            return False
        if not assets or not os.path.isdir(assets):
            self.set(empty="no_project", folder="")
            return False
        self.set(empty="", folder=assets)
        if svc.is_open() and os.path.normcase(os.path.abspath(svc.assets_dir)) == \
                os.path.normcase(os.path.abspath(assets)):
            # the same project: redraw the scene, since another tab may have changed a
            # picture or a font since it was drawn (DragonRR: "auto update")
            svc.refresh_view()
            return True
        opened = bool(svc.open(assets))
        # PAD-513: the Text tab's scan reads the card again for a project read by an older
        # build (the boxes the game fills in); opening Scenes first starts it too
        text = self.window.service("text")
        if opened and text is not None and not _same(getattr(text, "_text_scan_dir", ""), assets):
            try:
                text._maybe_rescan()
            except Exception:                            # noqa: BLE001
                pass
        return opened

    # -- hooks -------------------------------------------------------------
    def refresh_after_revert(self):
        """PAD-569: Reset… closed the scenes (their undo could put back what it reset); the
        page shows them again, as they are now."""
        if self._showing():
            self.show_project()

    def on_show(self):
        self.show_project()

    def on_manufacturer(self, mfr):
        # the Text tab closed the scenes of the previous manufacturer; if this page stays
        # the selected one it opens the scenes again
        self.set(folder="", empty="")
        if getattr(self, "_visible", False):
            self.ctx.loop.post(self._folder_changed)


def _same(a, b):
    return bool(a) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


TAB = ScenesTab
