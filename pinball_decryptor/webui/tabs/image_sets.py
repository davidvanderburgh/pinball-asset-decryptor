"""The themes picker (Simon, 2026-11-18; "image sets" in the code): one choice, on the Images tab, of which theme
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
        # Simon: themes stay behind an Advanced switch (the Images tab's); off, the project is theme 1 alone
        enabled = bool(project) and SV.themes_on(project)
        current = max(1, min(current, len(names) or 1)) if enabled else 1
        self.set(on=bool(project), enabled=enabled, can_off=len(names) <= 1, project=project, names=names,
                 most=SV.MAX_SETS, why=why)
        self._use(current)
        self.publish_unlocks()

    # -- the Advanced box's three unlocks (Simon, 2026-11-19: "images and video AND text are separate unlocks", the
    #    same box on Scenes, Images and Video - static/js/core/unlock_box.js) ---------------------------------------
    def publish_unlocks(self):
        from ...core import colour_profile as cp, staged_changes
        project = self._project() if self._stern() else ""
        images = self.window.service("images")
        video = self.window.service("video")
        try:
            offered_img = bool(images is not None and images._per_file_colour())
        except Exception:                               # noqa: BLE001
            offered_img = False
        data = staged_changes.peek(project) if project else {}
        self.set(unlock={
            "offered": bool(project) and offered_img,
            "images": bool(data.get(cp.STOCK_IMAGES_KEY)),
            "videos": bool(video is not None and video.get("color_stock")),
            "videos_offered": bool(video is not None and video.get("color_offered")),
            "text": cp.text_unlocked(data),
        })

    @rpc
    def set_unlock(self, kind, on):
        """One of the Advanced box's ticks: "images" (the Images tab's own unlock), "videos" (the Video tab's
        Advanced) or "text" (the game's own lines of text, a box of their own now)."""
        from ...core import colour_profile as cp, staged_changes
        project = self._project()
        if not project:
            return False
        on = bool(on)
        if kind in ("images", "text"):
            # the first use of the box: the lines get a box of their own, as they are now, so images no longer
            # move them
            data = staged_changes.load(project)
            if not cp.text_unlock_separate(data):
                data[cp.STOCK_TEXT_KEY] = cp.text_unlocked(data)
                staged_changes.save(project, data)
        try:
            if kind == "images":
                svc = self.window.service("images")
                if svc is not None:
                    svc.set_color_unlocked(on)
                # the Images tab keeps it only for a folder it has scanned: else the Scenes editor's way, else here
                if bool(staged_changes.peek(project).get(cp.STOCK_IMAGES_KEY)) != on:
                    text = self.window.service("text")
                    scenes = getattr(text, "scenes", None)
                    if scenes is not None and getattr(scenes, "assets_dir", "") and scenes.is_open():
                        scenes.tree_color_unlocked(on)
                if bool(staged_changes.peek(project).get(cp.STOCK_IMAGES_KEY)) != on:
                    data = staged_changes.load(project)
                    if on:
                        data[cp.STOCK_IMAGES_KEY] = True
                        cp.unlock_switches(data)
                    else:
                        data.pop(cp.STOCK_IMAGES_KEY, None)
                        cp.lock_switches(data, {})
                    staged_changes.save(project, data)
            elif kind == "videos":
                svc = self.window.service("video")
                if svc is not None:
                    svc.set_color_stock(on)
            elif kind == "text":
                data = staged_changes.load(project)
                if cp.text_unlocked(data) != on:
                    cp.set_text_unlocked(data, on)
                    staged_changes.save(project, data)
                    self.log("Scenes: the game's own lines of text are %s." % (
                        "unlocked: each can have the individual files color profile baked in when you build"
                        if on else "locked again (their color switches come back when the box is ticked)"), "info")
            else:
                return False
        finally:
            for ns, name in (("text", "scenes_pictures_changed"), ("text", "scenes_lines_changed"),
                             ("color", "asset_switches_changed")):
                fn = getattr(self.window.service(ns), name, None)
                if fn is not None:
                    try:
                        fn()
                    except Exception:                   # noqa: BLE001
                        pass
            self.publish_unlocks()
        return True

    @rpc
    def set_enabled(self, on):
        """The Images tab's Advanced "Themes" switch."""
        from ...plugins.stern import scene_variants as SV
        return self._do(SV.set_themes_on, bool(on))

    #: the services told when the set picked changes (each has ``on_image_set(n)``)
    LISTENERS = ("images",)

    def _use(self, n, **more):
        """Pick set *n* and tell the tabs that show it; told once per real change."""
        self.set(current=n, **more)
        if n == getattr(self, "_told", None):
            return
        self._told = n
        for ns in self.LISTENERS:
            svc = self.window.service(ns)
            hook = getattr(svc, "on_image_set", None)
            if hook is None:
                continue
            try:
                hook(n)
            except Exception:                           # noqa: BLE001 - one tab's trouble never stops the picker
                import logging
                logging.getLogger(__name__).exception("on_image_set %s", ns)

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
            self._use(n, why="")
        return self.current()

    @rpc
    def add(self, name=""):
        from ...plugins.stern import scene_variants as SV
        got = self._do(SV.add_set, name)
        if got["ok"]:
            self._use(got["n"])                         # a new set is the one shown, ready to fill
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
            self._use(1 if cur == n else (cur - 1 if cur > n else cur))
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
            self._use(cur)
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
