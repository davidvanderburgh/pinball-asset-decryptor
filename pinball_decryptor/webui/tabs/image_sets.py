"""The image sets picker (Simon, 2026-11-18): one choice, shared by the Images, Video and Scenes tabs, of which set
of the project's pictures the user is looking at and changing.

Simon: "add a drop down ... which would let the user switch between video (etc.) sets. The first option would be the
main set, then SET 2 and so on ... When the user selects set 2 - there will be an empty list of chosen images. The
user can then choose the variants". Set 1 is the project as it is; set 2 and up start empty (the same as set 1) and
hold only what differs. The operator picks one in the game's own service menu (IMAGE SET, :mod:`.scene_variants`).

Not a tab: its key is empty, so the rail never shows it. Its state (namespace ``imgsets``) is read by the picker on
each tab (``static/js/core/image_sets.js``). The sets' names are the project's (``.staged_changes.json``
``scene_variants``); which set is picked is this session's, back to set 1 for each project opened.
"""

from .base import TabService, rpc


class ImageSetsService(TabService):
    ns = "imgsets"
    key = ""

    def __init__(self, window):
        super().__init__(window)
        self._project_seen = ""
        self._hooked = None
        self.set(on=False, project="", names=[], current=1, most=0, why="")

    # -- the project ---------------------------------------------------------
    def _project(self):
        modes = self.window.service("modes")
        try:
            return modes.project() if modes is not None else ""
        except Exception:                               # noqa: BLE001
            return ""

    def _stern(self):
        mfr = self.mfr
        return mfr is not None and getattr(mfr, "key", "") == "stern"

    def _hook(self):
        """Follow the project folder (the Write/Extract tabs' variable), as the Modes tab does: nothing else says
        when it changes."""
        modes = self.window.service("modes")
        var = modes._project_var() if modes is not None and hasattr(modes, "_project_var") else None
        if var is not None and var is not self._hooked:
            self._hooked = var
            try:
                var.trace_add("write", lambda *_a: self.ctx.loop.post(self.publish))
            except Exception:                           # noqa: BLE001
                pass

    def publish(self, why=""):
        from ...plugins.stern import scene_variants as SV
        self._hook()
        project = self._project() if self._stern() else ""
        if project != self._project_seen:
            self._project_seen = project
            current = 1                                 # a project opened shows set 1, the project as it is
        else:
            current = int(self.get("current", 1) or 1)
        names = SV.set_names(project) if project else []
        current = max(1, min(current, len(names) or 1))
        self.set(on=bool(project), project=project, names=names, current=current, most=SV.MAX_SETS, why=why)

    def current(self):
        """The set picked now (1 = the project as it is)."""
        return int(self.get("current", 1) or 1)

    def _do(self, fn, *args):
        from ...plugins.stern import scene_variants as SV
        project = self._project()
        if not project:
            self.publish()
            return {"ok": False, "why": "Open a Stern Spike 2 project first."}
        try:
            got = fn(project, *args)
        except SV.SceneVariantError as e:
            why = str(e)
            self.publish(why=why[:1].upper() + why[1:] + ".")
            return {"ok": False, "why": self.get("why")}
        self.publish()
        return {"ok": True, "n": got}

    # -- the page's calls ----------------------------------------------------
    @rpc
    def pick(self, n):
        names = self.get("names") or []
        n = int(n)
        if 1 <= n <= max(1, len(names)):
            self.set(current=n, why="")
        return self.current()

    @rpc
    def add(self, name=""):
        from ...plugins.stern import scene_variants as SV
        got = self._do(SV.add_set, name)
        if got["ok"]:
            self.set(current=got["n"])                  # a new set is the one shown, ready to fill
        return got

    @rpc
    def rename(self, n, name):
        from ...plugins.stern import scene_variants as SV
        return self._do(SV.rename_set, int(n), name)

    @rpc
    def remove(self, n):
        from ...plugins.stern import scene_variants as SV
        from .. import compat
        names = self.get("names") or []
        name = names[int(n) - 1] if 1 <= int(n) <= len(names) else ""
        if not compat.messagebox.askyesno(
                "Remove image set",
                "Remove set %s (%s) and everything made for it? The sets after it move up one." % (n, name)):
            return {"ok": False, "cancelled": True}
        cur = self.current()
        got = self._do(SV.remove_set, int(n))
        if got["ok"]:
            n = int(n)
            self.set(current=1 if cur == n else (cur - 1 if cur > n else cur))
        return got

    @rpc
    def move(self, n, to):
        from ...plugins.stern import scene_variants as SV
        cur, n, to = self.current(), int(n), int(to)
        got = self._do(SV.move_set, n, to)
        if got["ok"]:
            if cur == n:
                cur = to
            elif n < cur <= to:
                cur -= 1
            elif to <= cur < n:
                cur += 1
            self.set(current=cur)
        return got

    @rpc
    def refresh(self):
        self.publish()
        return True

    # -- the shell's events --------------------------------------------------
    def on_project(self, folder):
        self.publish()

    def on_manufacturer(self, mfr):
        self.publish()

    def on_show(self):
        self.publish()


TAB = ImageSetsService
