"""The Getting started page (PAD-813): short videos and steps for the jobs a
new user comes for.  It opens by itself the first time the app starts (and
at every start while "Show this when the app opens" is ticked), and the top
bar's Getting started button brings it back.

State ``shellx.getting_started``: ``open``, ``at_launch``, ``flow``, ``tasks``
(each with its video and poster path, for the page's ``mediaUrl``) and
``note``.  The content is :mod:`.getting_started`; the page is
``GettingStarted`` in ``static/js/shell.js``.
"""

import logging
import os

from . import getting_started as GS
from .rpc import rpc

log = logging.getLogger(__name__)

SETTING = "getting_started_at_launch"


class GettingStartedMixin:
    """Mixed into the ``shellx`` service."""

    def _gs_init(self):
        settings = getattr(self.app, "_settings", None)
        if not isinstance(settings, dict):
            settings = {}
        self._gs_open = GS.opens_at_launch(settings)
        if self._gs_open and SETTING not in settings:
            # a new user sees it once; the tick brings it back every start
            self._gs_store(False)
        self._gs_publish()

    def _gs_store(self, value):
        settings = getattr(self.app, "_settings", None)
        if not isinstance(settings, dict):
            return
        settings[SETTING] = bool(value)
        try:
            self.app._save_settings()
        except Exception:                               # noqa: BLE001
            log.exception("save settings (getting started)")

    def _gs_tabs(self):
        """The rail tabs the open manufacturer has."""
        rail = self.ctx.store.get("shell", "tabs") or []
        return {t.get("ns") for t in rail if t.get("visible")}

    def _gs_publish(self):
        settings = getattr(self.app, "_settings", None) or {}
        tasks = []
        for t in GS.TASKS:
            video = GS.video_path(t["id"])
            poster = GS.video_path(t["id"], "jpg")
            tasks.append({
                "id": t["id"], "title": t["title"], "tab": t["tab"], "go": t["go"],
                "steps": list(t["steps"]),
                "video": video if os.path.isfile(video) else "",
                "poster": poster if os.path.isfile(poster) else ""})
        self.set(getting_started={
            "open": bool(self._gs_open),
            "at_launch": bool(settings.get(SETTING, False)),
            "flow": [{"tab": a, "what": b} for a, b in GS.FLOW],
            "tasks": tasks, "note": GS.NOTE,
            "problems": [{"title": a, "text": b} for a, b in GS.PROBLEMS]})

    @rpc
    def getting_started_open(self):
        self._gs_open = True
        self._gs_publish()
        return True

    @rpc
    def getting_started_close(self):
        self._gs_open = False
        self._gs_publish()
        return True

    @rpc
    def getting_started_at_launch(self, value):
        self._gs_store(bool(value))
        self._gs_publish()
        return True

    @rpc
    def getting_started_guide(self, key):
        """A written guide on GitHub: the first-mod walkthrough or Common
        problems."""
        url = GS.guide_url(key)
        if not url:
            return False
        self.open_link_checked(url, what="the user guide")
        return True

    @rpc
    def getting_started_go(self, task_id):
        """A task's button: close the page and open its tab when the open
        manufacturer has it, else the picker to choose one."""
        task = next((t for t in GS.TASKS if t["id"] == task_id), None)
        self._gs_open = False
        self._gs_publish()
        shell = self.ctx.store.get("shell", "view")
        if (task is not None and task["tab"] and shell == "mfr"
                and task["tab"] in self._gs_tabs()):
            self.window.select_tab(task["tab"])
            return task["tab"]
        return ""
