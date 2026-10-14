"""The project menu's Reset... (PAD-569, DragonRR; PAD-576 moved it off the top bar): the page dialog ``reset``, its state
``shellx.reset``.

The dialog lists the kinds of change (:data:`core.project_reset.KINDS`) with how many each
has in the open project, ticked by the user; Reset asks once more (it cannot be undone) and
hands the kinds to the run logic (``App._start_reset``), which puts them back the way the
project was extracted.  The Write tab's "Revert all changes..." opens it with every kind
ticked.
"""

import logging
import os
import threading

from . import compat
from .rpc import rpc

log = logging.getLogger(__name__)

INTRO = ("Put parts of this project back the way they were extracted from the card, to "
         "start over. It works on the whole project at once: to put back one scene, use "
         "Revert on the Scenes tab instead.")
WARNING = ("This cannot be undone: your changes to what you tick are gone for good. Files of "
           "your own that you picked from elsewhere stay where they are, and nothing on a card "
           "changes until the next Write.")


class ResetMixin:
    """Mixed into the ``shellx`` service."""

    def _reset_init(self):
        self._reset_token = 0
        self.set(reset=None)

    def _reset_folder(self):
        var = self._var_or_none("write_assets_var")
        return ((var.get() if var is not None else "") or "").strip()

    @rpc
    def reset_open(self):
        """The dialog opened: count what each kind has (the changed files on a worker)."""
        from ..core import project_reset as PR
        folder = self._reset_folder()
        self._reset_token += 1
        token = self._reset_token
        ok = bool(folder and os.path.isdir(folder))
        rows = PR.counts(folder) if ok else dict.fromkeys(PR.KEYS, 0)
        self._reset_publish(folder, rows, busy=ok, ok=ok)
        if not ok:
            return False

        def _work():
            changed = []
            try:
                from ..core.checksums import all_changed
                changed = all_changed(folder, quick=True)
            except Exception:                        # noqa: BLE001
                log.exception("reset: changed files")
            try:
                got = PR.counts(folder, changed)
            except Exception:                        # noqa: BLE001
                log.exception("reset: counts")
                got = rows
            self.ctx.loop.post(self._reset_counted, token, folder, got)

        threading.Thread(target=_work, name="pad-shellx-reset-count", daemon=True).start()
        return True

    def _reset_counted(self, token, folder, rows):
        if token != self._reset_token:
            return
        self._reset_publish(folder, rows, busy=False, ok=True)

    def _reset_publish(self, folder, counts, busy, ok):
        from ..core import lineage
        from ..core import project_reset as PR
        try:
            # PAD-539 (DragonRR): extracted from a card a Write changed, "as extracted" is that
            # card, not the game as it shipped
            base = lineage.extracted_from_note(lineage.extracted_from(folder), scenes=False)                 if ok else None
        except Exception:                            # noqa: BLE001
            base = None
        self.set(reset={
            "folder": folder, "name": os.path.basename(os.path.normpath(folder)) if folder else "",
            "ok": ok, "busy": busy, "intro": INTRO, "warning": WARNING, "base_note": base,
            "running": bool(getattr(self.window, "_running", False)),
            "rows": [{"key": k, "label": label, "detail": detail, "n": int(counts.get(k) or 0)}
                     for k, label, detail in PR.KINDS]})

    @rpc
    def reset_close(self):
        self._reset_token += 1
        self.set(reset=None)
        return True

    @rpc
    def reset_run(self, kinds):
        """Reset… pressed: ask once more, then hand the kinds to the run logic.  True when
        it started (the dialog closes)."""
        from ..core import project_reset as PR
        kinds = PR.normalise(kinds)
        folder = self._reset_folder()
        if not kinds or not folder or not os.path.isdir(folder):
            return False
        if getattr(self.window, "_running", False):
            compat.messagebox.showinfo(
                "Reset", "Wait for the job that is running to finish (or cancel it) first.")
            return False
        fn = self.window.cb.get("on_reset")
        if fn is None:
            return False
        every = len(kinds) == len(PR.KEYS)
        what = ("EVERYTHING in this project" if every else
                "\n".join("  •  " + PR.LABELS[k] for k in kinds))
        if not compat.messagebox.askyesno(
                "Reset",
                "Put back the way they were extracted:\n\n%s\n\nin %s?\n\nThis cannot be "
                "undone." % (what, folder)):
            return False
        self._reset_token += 1
        self.set(reset=None)
        return bool(fn(folder, kinds))
