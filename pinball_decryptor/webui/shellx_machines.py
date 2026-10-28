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

ADD_TITLE = "Pick the card image or update file your machine runs"


def card_types():
    """The picker's file types: every manufacturer's that lists machines
    (PAD-787), then all of them, then any file."""
    from ..core import machines
    types = [t for k in machines.kinds().values() for t in k["types"]]
    every = " ".join(sorted({p for _l, pats in types for p in pats.split()}))
    return ([("Machine files", every)] if every else []) + types + \
        [("All files", "*.*")]


def not_a_card():
    """The message for a file no manufacturer's printer can read."""
    from ..core import machines
    whats = [k["what"] for k in machines.kinds().values()]
    if len(whats) > 1:
        whats = ", ".join(whats[:-1]) + " or " + whats[-1]
    else:
        whats = "".join(whats) or "a card image"
    return ("This file isn't one PAD can read the game and build of.\n\n"
            "Pick the file your machine runs: %s." % whats)


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
            text = ("%s has %s %s out; %s runs %s. My machines (manufacturer "
                    "menu) links to %s."
                    % (r["maker"], r["title"], r["newer"], r["name"],
                       r["build"], r["page_words"]))
            self.window.append_log(text, "info")
            self.window.toast(text, "info", ms=12000)
            told.append("%s:%s" % (r["id"], r["newer"]))
        settings[machines.TOLD_KEY] = told[-200:]
        self._mach_save()

    def _machine_row(self, m, folders):
        from ..core import code_watch, machines
        info = self._release_info(m)
        mfr = m.get("manufacturer") or ""
        found = machines.projects_for(m, folders)
        place = found[0][1] if found else None
        card = m.get("card") or ""
        row = {"id": m["id"], "name": m.get("name") or "",
               "mfr": mfr, "maker": machines.maker(mfr),
               "noun": machines.noun(mfr),
               "page_words": code_watch.page_words(mfr),
               "transfer": self._can_transfer(mfr),
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
        if info and code_watch.has_source(mfr):
            newest = code_watch.newest(mfr, info["key"])
            if newest and newest > tuple(info["version"]):
                row["newer"] = machines.version_words(mfr, newest)
                row["newer_url"] = code_watch.page_url(mfr, info["key"])
        return row

    @staticmethod
    def _release_info(m):
        from ..core import machines
        try:
            return machines.release_info(m)
        except Exception:                               # noqa: BLE001
            log.exception("release info")
            return None

    def _can_transfer(self, mfr_key):
        """Whether the maker's Mod Pack tab carries mods onto new code
        (Stern's); the others' Mod Pack only exports and imports."""
        mfr = next((x for x in getattr(self.window, "manufacturers", ())
                    if x.key == mfr_key), None)
        caps = getattr(mfr, "capabilities", None)
        return bool(getattr(caps, "mod_transfer", False))

    def _watch_text(self, rows, on):
        """One line under the list: when each maker's page was read, and
        any that couldn't be."""
        from ..core import code_watch
        if not on:
            return "The daily check for new game code is off."
        mfrs = sorted({r["mfr"] for r in rows if code_watch.has_source(r["mfr"])})
        if not mfrs:
            return ""
        pages = _and([code_watch.page_words(k) for k in mfrs])
        if self._mach_checking:
            return "Checking %s…" % pages
        states = {k: code_watch.state(k) for k in mfrs}
        if not any(st.get("checked") for st in states.values()):
            return "%s: checked once a day." % _cap(pages)
        good, bad = [], []
        for k in mfrs:
            st = states[k]
            if not st.get("checked"):
                continue
            if st.get("ok"):
                good.append((k, float(st["checked"])))
            else:
                bad.append("Couldn't read %s at %s (%s); it is tried again "
                           "later." % (code_watch.page_words(k),
                                       _stamp(st["checked"]),
                                       st.get("error") or "no answer"))
        out = []
        if good:
            out.append("%s checked at %s; once a day." % (
                _cap(_and([code_watch.page_words(k) for k, _t in good])),
                _stamp(max(t for _k, t in good))))
        return " ".join(out + bad)

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
        owned = {}
        for m in machines.entries(settings):
            k = m.get("manufacturer")
            if not code_watch.has_source(k):
                continue
            rel = self._release_info(m)
            owned.setdefault(k, set())
            if rel:
                owned[k].add(rel["key"])
        mfrs = [k for k in sorted(owned)
                if force or code_watch.due(k, keys=owned[k])]
        if not mfrs:
            return False
        self._mach_checking = True
        self._machines_refresh()

        def work():
            try:
                for k in mfrs:
                    st = code_watch.check(k, keys=owned[k])
                    log.info("game-code check %s: %s", k,
                             "ok" if st.get("ok") else st.get("error"))
            except Exception:                           # noqa: BLE001
                log.exception("game-code check")
            finally:
                self.ctx.loop.post(self._machines_checked)

        threading.Thread(target=work, name="pad-codewatch", daemon=True).start()
        return True

    def _machines_checked(self):
        self._mach_checking = False
        # a machine added while this check ran (another maker, another
        # title) was turned away as busy: its page is read now
        if not self._machines_check(force=False):
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
                                                 filetypes=card_types())

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
            compat.messagebox.showerror("Add machine", not_a_card())
            return None
        mfr = info.get("manufacturer") or "stern"
        if name is None:
            rel = self._release_info({"manufacturer": mfr,
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
                             name.strip(), mfr,
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
        path = path or self._pick_card("Pick the %s %s runs now" % (
            machines.noun(m.get("manufacturer")), m.get("name")))
        if not path:
            return False
        info = self._measure_card(path)
        if not info or not info.get("sidx"):
            compat.messagebox.showerror("Change card", not_a_card())
            return False
        if (info.get("manufacturer") or "stern") != m.get("manufacturer"):
            compat.messagebox.showerror(
                "Change card", "%s is a %s machine: pick the %s it runs now."
                % (m.get("name") or "This machine",
                   machines.maker(m.get("manufacturer")),
                   machines.noun(m.get("manufacturer"))))
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
                "Take %s off My machines?\n\nThe %s and any project stay "
                "where they are." % (m.get("name") or "this machine",
                                     machines.noun(m.get("manufacturer")))):
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
        rel = self._release_info(m or {}) or {}
        url = code_watch.page_url((m or {}).get("manufacturer"), rel.get("key"))
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
        if not r.get("transfer"):
            # JJP, BoF: their Mod Pack exports and imports a pack; there is
            # no transfer whose field 1 to fill
            return True
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


def _and(words):
    words = list(words)
    return words[0] if len(words) == 1 else \
        ", ".join(words[:-1]) + " and " + words[-1]


def _cap(text):
    return text[:1].upper() + text[1:]


def _stamp(ts):
    when = datetime.datetime.fromtimestamp(float(ts))
    return when.strftime("%H:%M") if when.date() == datetime.date.today() \
        else when.strftime("%b %d")


def _same(a, b):
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))
