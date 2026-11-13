"""Project > Team... (PAD-1236): several PCs working on one project.

The page dialog ``project_team`` and its state ``shellx.team``; the top bar's
"Team: N new" chip reads ``shellx.team_news``, which a check of the team folder
every :data:`CHECK_SECS` keeps current (the members' cards only: cheap).  The
work is :mod:`core.team_sync`'s; this is its window.
"""

import logging
import os
import threading

from . import compat
from .rpc import rpc
from .shellx_common import human_size, same_path

log = logging.getLogger(__name__)

CHECK_SECS = 30

INTRO = ("Work on this project with other people, each on their own PC. Everyone extracts "
         "the same card and picks the same team folder: a folder OneDrive, Dropbox, Google "
         "Drive or a network drive keeps the same on every PC. Each part of the project "
         "belongs to one person, who shares it; the others get it. Nobody's work is mixed "
         "into anybody else's.")


def _mb():
    return compat.messagebox


def _fd():
    return compat.filedialog


class TeamMixin:
    """Mixed into the ``shellx`` service (needs the Projects mixin's helpers)."""

    def _team_init(self):
        self._team_open = False
        self._team_token = 0
        self._team_told = {}                 # (project, part) -> stamp already logged
        self.set(team=None, team_news=0)
        try:
            self.ctx.loop.after(5000, self._team_tick)
        except Exception:                               # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # the check every CHECK_SECS
    # ------------------------------------------------------------------
    def _team_tick(self):
        try:
            self.ctx.loop.after(CHECK_SECS * 1000, self._team_tick)
        except Exception:                               # noqa: BLE001
            pass
        self.team_check()

    def team_check(self):
        """Look at the team folder on a worker; the chip and the log hear of new shares."""
        folder = self._active_folder()
        if not folder:
            if self.get("team_news"):
                self.set(team_news=0)
            return

        def work():
            from ..core import team_sync as TS
            try:
                got = TS.news(folder)
            except Exception:                           # noqa: BLE001
                log.exception("team: news")
                got = []
            self.ctx.loop.post(self._team_checked, folder, got)

        threading.Thread(target=work, name="pad-shellx-team-check", daemon=True).start()

    def _team_checked(self, folder, got):
        from ..core import team_sync as TS
        if not same_path(folder, self._active_folder()):
            return
        self.set(team_news=len(got))
        fresh = {}
        for part, who, stamp in got:
            if self._team_told.get((folder, part)) != stamp:
                self._team_told[(folder, part)] = stamp
                fresh.setdefault(who, []).append(TS.LABELS[part])
        for who, labels in fresh.items():
            self.window.append_log(
                "%s shared new %s. Project > Team... gets them." % (who, ", ".join(labels)),
                "info")
        if self._team_open and fresh:
            self._team_refresh()

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    @rpc
    def team_open(self):
        folder = self._active_folder()
        if not folder or not os.path.isdir(folder):
            return None
        self._team_open = True
        self._team_refresh(first=True)
        return True

    def _team_refresh(self, first=False, busy_note=""):
        from ..core import team_sync as TS
        folder = self._active_folder()
        self._team_token += 1
        token = self._team_token
        st = TS.load_state(folder)
        base = {"folder": folder, "intro": INTRO, "busy": True, "note": busy_note,
                "default_name": st.get("me") or TS.default_name(),
                "default_team": st.get("team") or ""}
        cur = self.get("team") or {}
        self.set(team=dict(cur, **base) if not first else dict(base, joined=bool(st.get("team")),
                                                                 parts=[], members=[]))

        def work():
            try:
                got = TS.status(folder)
            except Exception as e:                      # noqa: BLE001
                log.exception("team: status")
                got = {"joined": True, "ok": False, "parts": [], "members": [],
                       "warnings": ["Couldn't read the team folder: %s" % e]}
            self.ctx.loop.post(self._team_shown, token, folder, got)

        threading.Thread(target=work, name="pad-shellx-team", daemon=True).start()

    def _team_shown(self, token, folder, got):
        if token != self._team_token or not self._team_open:
            return
        cur = dict(self.get("team") or {})
        cur.update(got, busy=False, folder=folder)
        cur["running"] = self._running()
        self.set(team=cur)
        self.set(team_news=got.get("news") or 0)

    @rpc(loop=False)
    def team_close(self):
        self._team_open = False
        self._team_token += 1
        self.ctx.loop.post(lambda: self.set(team=None))
        return True

    @rpc
    def team_browse(self):
        p = _fd().askdirectory(title="The team folder (one your sync service keeps the same "
                                     "on every PC)")
        return os.path.normpath(p) if p else ""

    @rpc
    def team_join(self, team, name):
        from ..core import team_sync as TS
        folder = self._active_folder()
        if not folder or not (team or "").strip():
            return False
        try:
            warn = TS.join(folder, team.strip(), name)
        except TS.TeamError as e:
            _mb().showerror("Team", str(e))
            return False
        self.window.append_log("This project is in the team at %s now, as %s."
                               % (team.strip(), TS.folder_name(name)), "success")
        if warn:
            _mb().showwarning("Team", "\n\n".join(warn))
        self._team_refresh()
        self.team_check()
        return True

    @rpc
    def team_leave(self):
        from ..core import team_sync as TS
        folder = self._active_folder()
        if not folder:
            return False
        if not _mb().askyesno("Team", "Take this project out of its team?\n\nIt keeps "
                              "everything it has now. Your folder in the team folder stays "
                              "for the others until you delete it."):
            return False
        TS.leave(folder)
        self.set(team_news=0)
        self._team_refresh(first=True)
        return True

    @rpc
    def team_take(self, part):
        from ..core import team_sync as TS
        folder = self._active_folder()
        row = next((r for r in (self.get("team") or {}).get("parts") or ()
                    if r.get("key") == part), None)
        if row is None:
            return False
        if row.get("owner") and not row.get("mine"):
            if not _mb().askyesno(
                    "Team", "%s are %s's now. Take them over?\n\nFrom then on yours are the "
                    "ones the others get; %s gets yours too." % (
                        TS.LABELS[part], row["owner"], row["owner"])):
                return False
        try:
            TS.claim(folder, [part])
        except TS.TeamError as e:
            _mb().showerror("Team", str(e))
            return False
        self._team_refresh()
        return True

    @rpc
    def team_let_go(self, part):
        from ..core import team_sync as TS
        try:
            TS.release(self._active_folder(), [part])
        except TS.TeamError as e:
            _mb().showerror("Team", str(e))
            return False
        self._team_refresh()
        return True

    # ------------------------------------------------------------------
    # Share / Get
    # ------------------------------------------------------------------
    @rpc
    def team_share(self):
        from ..core import team_sync as TS
        title = "Share my parts"
        folder = self._active_folder()
        if self._running():
            _mb().showwarning(title, "Wait for the running job to finish first.")
            return False
        game = getattr(self.app, "_detected_caption", None) or ""
        self._flush_tabs()

        def done(out, error):
            from ..core import history_log
            if error is not None:
                _mb().showerror(title, "Sharing failed:\n%s" % error)
                self._team_refresh()
                return
            if out.get("cancelled"):
                self.window.append_log("Sharing stopped; the others still have what you "
                                       "shared before.", "info")
                self._team_refresh()
                return
            line = ("Shared %s with the team (%d file(s), %d copied, %s)."
                    % (", ".join(TS.LABELS[p] for p in out["parts"]), out["files"],
                       out["copied"], human_size(out["bytes"])))
            history_log.record(folder, [line])
            self.window.append_log(line, "success")
            if out.get("gone"):
                self.window.append_log(
                    "  %d file(s) the project names are not on this PC and were left out: "
                    "Project > Relink moved files finds them." % len(out["gone"]), "warning")
            self._team_refresh()

        def work(progress, cancel):
            return TS.share(folder, game=game, progress=progress, cancel=cancel)

        try:
            # the refusals (owns nothing, no team folder) before a progress window opens
            st, _team, me = TS._team_of(folder)
            if not any(o == me for o in TS.owners(_team).values()):
                raise TS.TeamError("You own no part of the project yet. Take the parts you "
                                   "work on first, so the others know whose they are.")
        except TS.TeamError as e:
            _mb().showwarning(title, str(e))
            return False
        self._start_job(title, "Copying your parts to the team folder...", work, done)
        return True

    @rpc
    def team_get(self, parts=None):
        """Get from the team: the parts with news (or *parts*), each put back as extracted
        and then given its owner's; asks first when this PC changed one of them."""
        from ..core import team_sync as TS
        title = "Get from the team"
        folder = self._active_folder()
        if self._running():
            _mb().showwarning(title, "Wait for the running job to finish first.")
            return False
        rows = {r["key"]: r for r in (self.get("team") or {}).get("parts") or ()}
        if parts is None:
            parts = [k for k, r in rows.items() if r.get("news")]
        if not parts:
            _mb().showinfo(title, "Nothing new from the team.")
            return False
        clash = [rows[p] for p in parts if rows.get(p, {}).get("changed_here")]
        if clash and not _mb().askyesno(
                title, "You changed these on this PC, but they are other people's:\n\n%s\n\n"
                "Getting them replaces your changes with theirs. Go ahead?" % "\n".join(
                    "  •  %s (%s's)" % (r["label"], r["owner"]) for r in clash)):
            return False
        self._flush_tabs()

        def work(progress, cancel):
            return TS.receive(folder, parts, progress=progress)

        def done(out, error):
            from ..core import history_log
            if error is not None:
                _mb().showerror(title, "Getting the team's parts failed:\n%s" % error)
                self._team_refresh()
                return
            lines = list(out.get("lines") or [])
            for who, n in out.get("waiting") or ():
                lines.append("%s's last share is still arriving on this PC (%s); try again "
                             "in a moment." % (who, "%d file(s) to go" % n if n > 0
                                               else "its record is not here yet"))
            if out.get("lines"):
                history_log.record(folder, out["lines"] + list(out.get("notes") or []))
            for ln in lines:
                self.window.append_log(ln, "success" if ln in out["lines"] else "warning")
            for n in out.get("notes") or ():
                self.window.append_log("  " + n, "info")
            if out.get("got"):
                if same_path(folder, self._active_folder()):
                    self.window.reload_assets_tabs()
                    self._scenes_reload(folder)
                    svc = self.window.service("modes")
                    if svc is not None and getattr(svc, "refresh", None):
                        try:
                            svc.refresh()
                        except Exception:               # noqa: BLE001
                            log.exception("modes refresh after team get")
            self._team_refresh()
            self.team_check()

        self._start_job(title, "Taking the team's parts into this project...", work, done)
        return True
