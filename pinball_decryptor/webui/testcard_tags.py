"""The TEST tick on a row of the Images, Video, Audio and Scenes tabs (PAD-1279).

A ticked row goes on the Test card tab's list (testcard_core): that project's file, or
for a scene its resting frame, with the project's colour profile in it.  Each tab says
what kind its rows are, which project is open, and which file a row is; the tick itself,
the published set of ticked rows (``test_tags``) and keeping the Test card tab in step are
here, once.
"""
import logging
import os

from .rpc import rpc, RpcError
from . import testcard_core as tc

log = logging.getLogger(__name__)


class TestTagMixin(object):
    """For a tab whose rows can go on the test card.  The tab sets ``_tc_kind`` and
    gives ``_tc_project()`` (the open project's folder, or '') and ``_tc_file(rel)`` (the
    file a row stands for, or None); ``_tc_label(rel)`` and ``_tc_made(rel, item)`` (a
    scene's picture) are optional."""

    _tc_kind = None

    def _tc_project(self):
        return ""

    def _tc_file(self, rel):
        return None

    def _tc_label(self, rel):
        return os.path.splitext(os.path.basename(str(rel).rstrip("/\\")))[0]

    def _tc_made(self, rel, item):
        """Called once a row is ticked (a scene renders its resting frame here)."""
        return None

    def _tc_game(self):
        """The project's name, for the Test card tab's list."""
        p = (self._tc_project() or "").rstrip("/\\")
        base = os.path.basename(p)
        if base.lower() in ("assets", "extracted", "files", "extract"):
            base = os.path.basename(os.path.dirname(p))
        return base

    def _tc_publish(self):
        """The ticked rows of the open project, for the TEST column."""
        try:
            on = tc.available(getattr(self.window, "current_mfr", None))
            project = self._tc_project() if on else ""
            tags = sorted(tc.shared().tagged(self._tc_kind, project)) if project else []
            self.set(test_on=on, test_tags=tags, test_full=len(tc.shared().items) >= tc.MAX_ITEMS)
        except Exception:                                       # noqa: BLE001
            log.exception("test card ticks")

    @rpc
    def set_test(self, rel, on=True):
        """Tick or untick a row for the test card."""
        project = self._tc_project()
        if not project:
            raise RpcError("Open a project first")
        path = ""
        if self._tc_kind != "scene":
            path = self._tc_file(rel)
            if not path or not os.path.isfile(path):
                raise RpcError("That file is not in the project folder")
        lst = tc.shared()
        changed, why = lst.set_tag(self._tc_kind, project, rel, bool(on), self._tc_label(rel), path,
                                   self._tc_game())
        if why:
            raise RpcError(why[:1].upper() + why[1:])
        if changed and on:
            i = lst.find(self._tc_kind, project, rel)
            try:
                self._tc_made(rel, lst.items[i])
            except Exception as exc:                            # noqa: BLE001
                log.exception("test card item")
                lst.set_tag(self._tc_kind, project, rel, False)
                self._tc_publish()
                raise RpcError("Could not put it on the test card: %s" % exc)
        self._tc_publish()
        tc.changed(self.window)
        return True
