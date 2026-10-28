"""My machines on the picker's home (PAD-783): the owner's machines, the
card and project of each, and whether the manufacturer has newer code.

Mixed into the ``shellx`` service; the page half is ``MyMachines`` in
``static/js/shell.js``.  The records are :mod:`..core.machines` (settings),
the card's words come from its fingerprint (:mod:`..core.lineage`), and the
"1.17 is out" line from :mod:`..core.code_watch`, which reads the
manufacturer's public game-code page at most once a day while the owner has
a machine of that make and the check is on.  Nothing is ever downloaded:
the row links to the page.

``shellx.machines``::

    {"rows": [...], "watch": bool, "watch_text": str, "checking": bool}
"""

import datetime
import logging
import os
import threading

from . import compat
from .rpc import rpc
from .shellx_common import human_size, off_loop, reveal_in_file_manager

log = logging.getLogger(__name__)

#: How often the loop looks whether a daily check is due (ms).
WATCH_TICK_MS = 3600 * 1000
#: The first look, after the app has settled (ms).
WATCH_FIRST_MS = 20 * 1000

ADD_TITLE = "Pick the card image your machine runs"
CARD_TYPES = [("Card images", "*.raw *.img *.bin"), ("All files", "*.*")]
NOT_A_CARD = ("This file isn't a Stern Spike 2 card image PAD can read: it "
              "has no Stern update index.\n\nPick the .raw or .img of the SD "
              "card the machine boots from.")


class MachinesMixin:
    """Needs ``self.app``, ``self.window``, ``self.ctx``, ``self.set``,
    ``self.get`` and ``self.open_link``."""

    def _machines_init(self):
        self._mach_token = 0
        self._mach_checking = False
        self.set(machines={"rows": [], "watch": True, "watch_text": "",
                           "checking": False})
        self.ctx.loop.after(0, self._machines_refresh)
        self.ctx.loop.after(WATCH_FIRST_MS, self._machines_tick)

    # -- state ---------------------------------------------------------------
    def _mach_settings(self):
        return getattr(self.app, "_settings", None)

    def _mach_save(self):
        try:
            self.app._save_settings()
        except Exception:                               # noqa: BLE001
            log.exception("save settings (machines)")

    def _machines_refresh(self):
        """Rebuild the rows off the loop (each row reads its projects'
        lineage files, which can sit on a slow or missing drive)."""
        from ..core import machines, project_registry
        settings = self._mach_settings()
        if settings is None:
            return
        rows = machines.entries(settings)
        folders = [e["folder"] for e in project_registry.entries(settings)]
        on = machines.watch_on(settings)
        self._mach_token += 1
        token = self._mach_token

        def work():
            try:
                built = [self._machine_row(m, folders) for m in rows]
            except Exception:                           # noqa: BLE001
                log.exception("My machines rows")
                built = []
            self.ctx.loop.post(self._machines_publish, token, built, on)

        threading.Thread(target=work, name="pad-machines", daemon=True).start()

    def _machines_publish(self, token, rows, on):
        if token != self._mach_token:
            return
        if on:
            self._tell_newer(rows)
        self.set(machines={"rows": rows, "watch": on,
                           "watch_text": self._watch_text(rows, on),
                           "checking": self._mach_checking})

    def _tell_newer(self, rows):
        """Newer code for a machine is said once, wherever the owner is (the
        app opens into their last manufacturer, not the picker): a toast and
        a log line, then only the row's "is out" shows it."""
        from ..core import machines
        settings = self._mach_settings()
        if settings is None:
            return
        told = list(settings.get(machines.TOLD_KEY) or [])
        fresh = [r for r in rows if r["newer"]
                 and "%s:%s" % (r["id"], r["newer"]) not in told]
        if not fresh:
            return
        for r in fresh:
            text = ("Stern has %s %s out; %s runs %s. My machines (manufacturer "
                    "menu) links to Stern's game-code page."
                    % (r["title"], r["newer"], r["name"], r["build"]))
            self.window.append_log(text, "info")
            self.window.toast(text, "info", ms=12000)
            told.append("%s:%s" % (r["id"], r["newer"]))
        settings[machines.TOLD_KEY] = told[-200:]
        self._mach_save()

    def _machine_row(self, m, folders):
        from ..core import code_watch, machines
        info = self._release_info(m)
        found = machines.projects_for(m, folders)
        place = found[0][1] if found else None
        card = m.get("card") or ""
        row = {"id": m["id"], "name": m.get("name") or "",
               "mfr": m.get("manufacturer") or "",
               "title": (info or {}).get("title") or m.get("label") or "",
               "edition": (info or {}).get("edition") or "",
               "build": (info or {}).get("build") or "",
               "card": card, "card_name": os.path.basename(card),
               "card_missing": not os.path.isfile(card),
               "size": human_size(m["size"]) if m.get("size") else "",
               "lineage": machines.card_words(m, place),
               "project": found[0][0] if found else "",
               "project_name": os.path.basename(found[0][0]) if found else "",
               "project_missing": bool(found) and not os.path.isdir(found[0][0]),
               "more_projects": [f for f, _w, _l in found[1:]],
               "newer": "", "newer_url": ""}
        if info and code_watch.has_source(row["mfr"]):
            newest = code_watch.newest(row["mfr"], info["key"])
            if newest and newest > tuple(info["version"]):
                from ..plugins.stern.machine_info import short_version
                row["newer"] = short_version(newest)
                row["newer_url"] = code_watch.page_url(row["mfr"])
        return row

    @staticmethod
    def _release_info(m):
        if m.get("manufacturer") != "stern":
            return None
        try:
            from ..plugins.stern import machine_info
            return machine_info.release_info(
                m.get("sidx"), machine_info.known_release_keys())
        except Exception:                               # noqa: BLE001
            log.exception("release info")
            return None

    def _watch_text(self, rows, on):
        from ..core import code_watch
        if not on:
            return "The daily check for new game code is off."
        mfrs = sorted({r["mfr"] for r in rows if code_watch.has_source(r["mfr"])})
        if not mfrs:
            return ""
        st = code_watch.state(mfrs[0])
        if self._mach_checking:
            return "Checking Stern's game-code page…"
        if not st.get("checked"):
            return "Stern's game-code page is checked once a day."
        when = datetime.datetime.fromtimestamp(float(st["checked"]))
        stamp = when.strftime("%H:%M") if when.date() == datetime.date.today() \
            else when.strftime("%b %d")
        if not st.get("ok"):
            return ("Couldn't read Stern's game-code page at %s (%s); it is "
                    "tried again later." % (stamp, st.get("error") or "no answer"))
        return "Stern's game-code page checked at %s; once a day." % stamp

    # -- the daily check -------------------------------------------------------
    def _machines_tick(self):
        try:
            self._machines_check(force=False)
        finally:
            self.ctx.loop.after(WATCH_TICK_MS, self._machines_tick)

    def _machines_check(self, force=False):
        """Read each due manufacturer's page off the loop.  Only makes the
        owner has a machine of, never with the check off."""
        from ..core import code_watch, machines
        settings = self._mach_settings()
        if settings is None or self._mach_checking:
            return False
        if not machines.watch_on(settings) or not code_watch.allowed():
            return False
        mfrs = sorted({m.get("manufacturer") for m in machines.entries(settings)
                       if code_watch.has_source(m.get("manufacturer"))})
        mfrs = [k for k in mfrs if force or code_watch.due(k)]
        if not mfrs:
            return False
        self._mach_checking = True
        self._machines_refresh()

        def work():
            for k in mfrs:
                st = code_watch.check(k)
                log.info("game-code check %s: %s", k,
                         "ok" if st.get("ok") else st.get("error"))
            self.ctx.loop.post(self._machines_checked)

        threading.Thread(target=work, name="pad-codewatch", daemon=True).start()
        return True

    def _machines_checked(self):
        self._mach_checking = False
        self._machines_refresh()

    # -- page calls ---------------------------------------------------------------
    def _mach(self, mid):
        from ..core import machines
        settings = self._mach_settings()
        return machines.get(settings, mid) if settings is not None else None

    def _measure_card(self, path):
        from ..core import lineage
        try:
            return off_loop(self.ctx, lineage.card_print, path, True)
        except Exception:                               # noqa: BLE001
            log.exception("card print %s", path)
            return None

    def _pick_card(self, title=ADD_TITLE):
        return compat.filedialog.askopenfilename(title=title,
                                                 filetypes=CARD_TYPES)

    @rpc
    def machines_add(self, path=None, name=None):
        """Add a machine from its card image (a picker when no *path*).
        Returns its id, or ``None`` when nothing was added."""
        from ..core import machines
        path = path or self._pick_card()
        if not path:
            return None
        info = self._measure_card(path)
        if not info or not info.get("sidx"):
            compat.messagebox.showerror("Add machine", NOT_A_CARD)
            return None
        if name is None:
            rel = self._release_info({"manufacturer": "stern",
                                      "sidx": info["sidx"]}) or {}
            guess = " ".join(x for x in (rel.get("title"),
                                         (rel.get("edition") or "").split(" /")[0])
                             if x) or info.get("label") or "My machine"
            name = compat.simpledialog.askstring(
                "Add machine", "A name for this machine (yours to choose):",
                initialvalue=guess)
            if name is None:
                return None
        entry = machines.add(self.app._settings, os.path.abspath(path), info,
                             name.strip(), "stern",
                             stamp=datetime.datetime.now().isoformat(
                                 timespec="seconds"))
        self._mach_save()
        self._machines_refresh()
        self._machines_check(force=False)
        return entry["id"]

    @rpc
    def machines_rebind(self, mid, path=None):
        """The machine runs another card now (new code, a new build)."""
        from ..core import machines
        m = self._mach(mid)
        if m is None:
            return False
        path = path or self._pick_card("Pick the card image %s runs now"
                                       % m.get("name"))
        if not path:
            return False
        info = self._measure_card(path)
        if not info or not info.get("sidx"):
            compat.messagebox.showerror("Change card", NOT_A_CARD)
            return False
        machines.rebind(self.app._settings, mid, os.path.abspath(path), info)
        self._mach_save()
        self._machines_refresh()
        return True

    @rpc
    def machines_rename(self, mid, name=None):
        from ..core import machines
        m = self._mach(mid)
        if m is None:
            return False
        if name is None:
            name = compat.simpledialog.askstring(
                "Rename machine", "A name for this machine:",
                initialvalue=m.get("name") or "")
        if not name or not machines.rename(self.app._settings, mid, name):
            return False
        self._mach_save()
        self._machines_refresh()
        return True

    @rpc
    def machines_remove(self, mid):
        from ..core import machines
        m = self._mach(mid)
        if m is None:
            return False
        if not compat.messagebox.askyesno(
                "Remove machine",
                "Take %s off My machines?\n\nThe card image and any project "
                "stay where they are." % (m.get("name") or "this machine")):
            return False
        machines.remove(self.app._settings, mid)
        self._mach_save()
        self._machines_refresh()
        return True

    @rpc
    def machines_set_watch(self, on):
        from ..core import machines
        settings = self._mach_settings()
        if settings is None:
            return False
        machines.set_watch(settings, bool(on))
        self._mach_save()
        self._machines_refresh()
        if on:
            self._machines_check(force=False)
        return True

    @rpc
    def machines_refresh(self):
        """The picker came up: a project extracted or built since joins its
        machine's row."""
        self._machines_refresh()
        return True

    @rpc
    def machines_check_now(self):
        return self._machines_check(force=True)

    @rpc
    def machines_open_page(self, mid):
        """The manufacturer's game-code page, in the browser."""
        from ..core import code_watch
        m = self._mach(mid)
        url = code_watch.page_url((m or {}).get("manufacturer"))
        if url:
            self.open_link(url)
        return bool(url)

    @rpc
    def machines_show_card(self, mid):
        m = self._mach(mid)
        card = (m or {}).get("card") or ""
        if not os.path.isfile(card):
            return False
        reveal_in_file_manager(card)
        return True

    # -- the working view, for one machine --------------------------------------
    def _row(self, mid):
        for r in (self.get("machines") or {}).get("rows") or []:
            if r["id"] == mid:
                return r
        return None

    def _enter(self, mfr_key):
        """Switch to the machine's manufacturer (Spike 2 era) as a click on
        its picker card does.  False when it is not loaded or a run is on."""
        if self.window._is_running():
            return False
        mfr = next((m for m in self.window.manufacturers
                    if m.key == mfr_key), None)
        if mfr is None:
            return False
        if getattr(self.app, "_current_mfr", None) is not mfr:
            self.window.pick_manufacturer(mfr_key)
        else:
            self.window.show_mfr_view()
        if mfr_key == "stern" and getattr(mfr, "current_era", "spike2") != "spike2":
            self.window.set_era("spike2")
        return True

    def _open_machine_project(self, mid):
        r = self._row(mid)
        if not r or not r["project"] or r["project_missing"]:
            return None
        if not self._enter(r["mfr"]):
            return None
        from ..core import project_file
        if project_file.has_anchor(r["project"]):
            self.app._open_project_folder_checked(r["project"])
        else:
            self.window.extract_output_var.set(r["project"])
        return r

    @rpc
    def machines_open_project(self, mid):
        return self._open_machine_project(mid) is not None

    @rpc
    def machines_extract(self, mid):
        """No project yet: the Extract tab with the machine's card picked."""
        r = self._row(mid)
        if not r or r["card_missing"] or not self._enter(r["mfr"]):
            return False
        self.window.extract_input_var.set(r["card"])
        self.window.select_tab("extract")
        return True

    @rpc
    def machines_transfer(self, mid):
        """Transfer Mods: the machine's project opened and preselected as the
        one whose mods move (field 1), on the Mod Pack tab."""
        r = self._open_machine_project(mid)
        if r is None:
            return False
        self.window.select_tab("modpack")
        src = getattr(self.window, "transfer_src_var", None)
        dst = getattr(self.window, "transfer_dst_var", None)
        if src is not None:
            src.set(r["project"])
            # the tab fills field 2 with the open project (the usual flow:
            # the NEW extract is open); here the open one is the OLD one
            if dst is not None and _same(dst.get(), r["project"]):
                dst.set("")
        return True

    @rpc
    def machines_write(self, mid):
        r = self._open_machine_project(mid)
        if r is None:
            return False
        self.window.select_tab("write")
        return True


def _same(a, b):
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))
