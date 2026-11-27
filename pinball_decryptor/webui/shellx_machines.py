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

    {"rows": [...], "watch": bool, "watch_text": str, "checking": bool,
     "open": bool (PAD-1585: its own page, from the top bar), "network": [...] (machines remote access found
     that no row runs), "newer_count": int,
     "remote": address whose Remote panel is open ("" none; PAD-1632), "buttons": [[key, label], ...]}

PAD-1632 (David: "I should be able to see the remote access controls here easily (to see the screen, data, etc.
like on the remote access screen) without having to make or load a project"): a machine's row opens a Remote panel
- its screen, its status, its logs, its settings and a restart - right on the page.  The panel is the Network
tab's own service (``network.*``, tabs/network.py) pointed at that machine; nothing is done twice.
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
#: PAD-1588: how often the machines on the network are looked at for a settings backup (ms), and the first look
BACKUP_TICK_MS = 30 * 60 * 1000
BACKUP_FIRST_MS = 90 * 1000

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
        self._mach_open = False
        self._mach_last = ([], False, [])
        self._mach_online = {}          # PAD-1585: address -> True (answers now) / False; absent = not checked yet
        self._mach_probing = False
        self._mach_finding = False      # PAD-1627: the page's own look over the network
        self._mach_find = {"pct": 0, "note": "", "kind": ""}
        self._mach_found_once = False
        self._mach_remote = None        # PAD-1632: the address whose Remote panel is open; None = never chosen
        self.set(machines={"rows": [], "watch": False, "watch_text": "",
                           "checking": False, "open": False, "network": [], "newer_count": 0,
                           "online": {}, "finding": False, "find_pct": 0, "find_note": "",
                           "find_kind": "", "remote": "", "buttons": []})
        self.ctx.loop.after(0, self._machines_refresh)
        self.ctx.loop.after(WATCH_FIRST_MS, self._machines_tick)
        self._backing_up = False
        self.ctx.loop.after(BACKUP_FIRST_MS, self._backup_tick)

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
            network = _network_machines()
            self.ctx.loop.post(self._machines_publish, token, built, on, network)

        threading.Thread(target=work, name="pad-machines", daemon=True).start()

    def _machines_publish(self, token, rows, on, network=()):
        if token != self._mach_token:
            return
        if on:
            self._tell_newer(rows)
        rows, unlinked = link_network(rows, network)
        # PAD-1627: which of a row's machines says where it is (the row offers to turn that on for one that
        # doesn't)
        says = {n["address"]: n["announces"] for n in network}
        for r in rows:
            r["announces"] = says.get(r.get("address"))
        self._mach_last = (rows, on, unlinked)
        self._machines_set()
        if self._mach_open:
            self._machines_probe()

    def _machines_set(self):
        from ..core import machine_backups, remote_buttons
        rows, on, unlinked = self._mach_last
        settings = self._mach_settings() or {}
        self.set(machines={"rows": rows, "watch": on,
                           "watch_text": self._watch_text(rows, on),
                           "checking": self._mach_checking,
                           "open": bool(self._mach_open), "network": unlinked,
                           "newer_count": sum(1 for r in rows if r.get("newer")),
                           "online": dict(self._mach_online),
                           "finding": bool(self._mach_finding), "find_pct": self._mach_find["pct"],
                           "find_note": self._mach_find["note"], "find_kind": self._mach_find["kind"],
                           # PAD-1632: the Remote panel open on the page, and the service buttons it offers
                           "remote": self._mach_remote if self._mach_remote in self._mach_addresses() else "",
                           "buttons": [list(pair) for pair in remote_buttons.LABELS],
                           # PAD-1588: settings and score backups by themselves
                           "backup": {"auto": machine_backups.auto_on(settings),
                                      "keep": machine_backups.keep_of(settings),
                                      "busy": bool(getattr(self, "_backing_up", False)),
                                      "any": any(r.get("backup_machines") for r in rows)}})

    # -- the green light (PAD-1585): which machines answer on the network right now ------------------------
    def _mach_addresses(self):
        rows, _on, unlinked = self._mach_last
        return sorted({r["address"] for r in rows if r.get("address")} | {n["address"] for n in unlinked})

    def _machines_probe(self):
        """Ask every address the page shows whether its SSH server answers (the banner only, all at once, off
        the loop); the page shows a green light for those that do."""
        addresses = self._mach_addresses()
        if self._mach_probing:
            return
        self._mach_probing = True

        def work():
            from ..core import machine_scan
            got = {}
            # a screen capture (PAD_UI_CAPTURE) names its "online" machines: it has no machine to ask
            shot = (os.environ.get("PAD_SHOT_ONLINE") or "").split(",") \
                if os.environ.get("PAD_UI_CAPTURE") else None

            def one(a):
                if shot is not None:
                    got[a] = a in shot
                    return
                try:
                    got[a] = bool(machine_scan.online(a))
                except Exception:                       # noqa: BLE001
                    got[a] = False
            threads = [threading.Thread(target=one, args=(a,), daemon=True) for a in addresses]
            for t in threads:
                t.start()
            # PAD-1627: meanwhile the network is asked which PAD machines are on; one at an address (or with an
            # identity) this computer doesn't have it at is logged in to and remembered there, so the page
            # follows a machine the router moved within one check, with no sweep
            recs = []
            if shot is None and not self._mach_finding:
                try:
                    recs = machine_scan.news()
                except Exception:                       # noqa: BLE001
                    log.exception("machines that announce themselves")
            for t in threads:
                t.join(5)
            if any(r.get("lets_in") for r in recs):
                self.ctx.loop.post(self._machines_probed_news, recs)
            else:
                self.ctx.loop.post(self._machines_probed, got)

        threading.Thread(target=work, name="pad-machines-online", daemon=True).start()

    def _machines_probed_news(self, recs):
        self._mach_probing = False
        if not self._mach_finding:
            self._machines_found(recs, "")

    def _machines_probed(self, got):
        self._mach_probing = False
        self._mach_online = got
        # PAD-1632: the one machine that is on has its Remote panel open when the page comes up (until the owner
        # opens or closes one, which is then kept)
        if self._mach_open and self._mach_remote is None and not os.environ.get("PAD_UI_CAPTURE"):
            on = [a for a in self._mach_addresses() if got.get(a) is True]
            if len(on) == 1:
                self._remote_open(on[0])
        self._machines_set()
        # PAD-1627 (David: "I don't see my godzilla that is turned on right now"): a machine this computer knows
        # that doesn't answer at its address has most likely been given another by the router, so the network is
        # looked over for it, once per run by itself (Find my machines on the page does it whenever asked)
        if self._mach_open and not self._mach_found_once and not os.environ.get("PAD_UI_CAPTURE"):
            known = {n["address"] for n in _network_machines() if n["known"]}
            if any(got.get(a) is False for a in known):
                self._machines_find()

    # -- PAD-1627: Find my machines, from the page ------------------------------------------------------------
    def _machines_find(self):
        if self._mach_finding:
            return False
        self._mach_finding = True
        self._mach_found_once = True
        self._mach_find = {"pct": 0, "note": "Looking over your network for your machines…", "kind": ""}
        self._machines_set()
        loop = self.ctx.loop

        def progress(done, total):
            loop.post(self._machines_find_pct, int(done * 100 / total) if total else 0)

        def work():
            from ..core import machine_scan
            try:
                found, err = machine_scan.scan(progress=progress, careful=_find_careful), ""
            except Exception as e:                      # noqa: BLE001 - said on the page, never raised
                found, err = [], str(e) or e.__class__.__name__
            loop.post(self._machines_found, found, err)
        threading.Thread(target=work, name="pad-machines-find", daemon=True).start()
        return True

    def _machines_find_pct(self, pct):
        if self._mach_finding and pct != self._mach_find["pct"]:
            self._mach_find["pct"] = pct
            self._machines_set()

    def _machines_found(self, found, err):
        from ..core import machine_scan, machines
        before = {n["address"] for n in _network_machines()}
        try:
            ours, moved = machine_scan.remember(found)
        except Exception as e:                          # noqa: BLE001
            log.exception("remember found machines")
            ours, moved, err = [], {}, err or str(e)
        settings = self._mach_settings()
        if settings is not None and moved:
            # a row linked to the old address follows its machine to the new one
            for m in machines.entries(settings):
                if m.get("address") in moved:
                    machines.set_address(settings, m["id"], moved[m["address"]])
            self._mach_save()
        self._mach_finding = False
        self._mach_find = {"pct": 100, "kind": "err" if err else ("ok" if ours else ""),
                           "note": ("Couldn't look over the network: %s" % err) if err
                           else find_words(ours, moved, before, _network_machines())}
        self._mach_online = {}
        self._machines_refresh()

    @rpc
    def machines_find(self):
        """Find my machines: look over the home network for the machines that let this computer in, remember
        each (one at a new address is followed there) and light the ones that are on."""
        return self._machines_find()

    @rpc
    def machines_announce_on(self, address):
        """A machine whose card was set up before PAD-1627: put today's remote access start script on its card
        and start its announce, so it is found wherever the router puts it (core/network_apply
        .announce_to_machine).  The game goes on; the machine is not restarted."""
        from ..core import network_apply, remote_send
        found = next((n for n in _network_machines() if n["address"] == address), None)
        if found is None or getattr(self, "_mach_announcing", False):
            return False
        name = found["name"] or found["title"] or "the machine"
        if not compat.messagebox.askyesno(
                "Find this machine by itself",
                "Have %s (at %s) say where it is on your network?\n\nYour router gives the machine a new address "
                "whenever it likes. With this on, the machine tells PAD where it is each time it starts, so PAD "
                "finds it in a second without looking over the whole network.\n\nOne small file on the "
                "machine's card is replaced (PAD's own remote access start script). The game is not stopped and "
                "the machine is not restarted." % (name, address)):
            return False
        self._mach_announcing = True

        def work():
            try:
                machine = remote_send.connect(address)
                try:
                    res = network_apply.announce_to_machine(machine)
                finally:
                    machine.close()
                if res == "none":
                    text, kind = ("%s's system has no announce service, so nothing was changed: PAD keeps finding "
                                  "it by looking over the network." % name, "info")
                else:
                    text, kind = ("%s now says where it is: PAD finds it by itself, whatever address your router "
                                  "gives it." % name, "success")
            except Exception as e:                      # noqa: BLE001 - said, never raised into the page
                text, kind = "Couldn't turn that on for %s: %s" % (name, e), "error"
            self.ctx.loop.post(self._machines_announced, text, kind)
        threading.Thread(target=work, name="pad-machine-announce", daemon=True).start()
        return True

    def _machines_announced(self, text, kind):
        self._mach_announcing = False
        self.window.append_log(text, kind)
        self.window.toast(text, kind, ms=9000)
        self._mach_online = {}
        self._machines_refresh()

    @rpc
    def machines_name_network(self, address, name=None):
        """The owner's name for a machine found on the network ("" puts the game's name back)."""
        from ..core import pad_ssh_key
        found = next((n for n in _network_machines() if n["address"] == address), None)
        if found is None:
            return False
        if name is None:
            name = compat.simpledialog.askstring(
                "Name this machine", "A name for the machine at %s (yours to choose):" % address,
                initialvalue=found["name"] or found["title"])
            if name is None:
                return False
        if name.strip() == found["title"]:
            name = ""
        pad_ssh_key.name_machine(address, name)
        self._machines_refresh()
        return True

    @rpc
    def machines_forget_network(self, address):
        """Take a machine found on the network off this computer's list (Find my machines finds it again when
        it is on and lets this computer in)."""
        from ..core import pad_ssh_key, remote_send
        if not any(n["address"] == address for n in _network_machines()):
            return False
        if not compat.messagebox.askyesno(
                "Forget machine", "Forget the machine at %s?\n\nNothing on the machine changes. Find my machines "
                "finds it again when it is on and lets this computer in." % address):
            return False
        try:
            host, port = remote_send.parse_address(address)
            pad_ssh_key.forget_host(host, port)
        except Exception:                               # noqa: BLE001 - the list entry still goes
            pass
        pad_ssh_key.forget_machine(address)
        self._machines_refresh()
        return True

    # -- PAD-1632: the Remote panel of one machine, on the page -------------------------------------------------
    def _net(self):
        try:
            return self.window.service("network")
        except Exception:                               # noqa: BLE001 - no Network tab in this build
            return None

    def _remote_quiet(self):
        """Nothing keeps reading a machine nobody is looking at: the live view and the followed log stop."""
        net = self._net()
        if net is None:
            return
        try:
            net.stop_live()
            net.follow_log(False)
        except Exception:                               # noqa: BLE001
            log.exception("stop the remote panel's readers")

    def _remote_open(self, address, read=True):
        """Point the Network tab's service at *address* (it is also the machine Send to machine uses from now)
        and read its status once, when it is on."""
        from ..core import pad_ssh_key
        if not pad_ssh_key.select_machine(address):
            return False
        net = self._net()
        if net is not None:
            if net.get("address") != address:
                # another machine's screen, status and notes are not this one's
                self._remote_quiet()
                net.set(check="", check_kind="", care_status=[], care_note="", care_kind="", care_log="",
                        screen_path="", screen_note="", screen_kind="", buttons_note="", buttons_kind="")
            net._show_machine()
            if read and self._mach_online.get(address) is True and not os.environ.get("PAD_UI_CAPTURE"):
                net.machine_status()
        self._mach_remote = address
        return True

    @rpc
    def machines_remote(self, address, on=True):
        """Open (or close) the Remote panel of the machine at *address*: one at a time."""
        address = (address or "").strip()
        if not on or not address:
            self._remote_quiet()
            self._mach_remote = ""
            self._machines_set()
            return True
        if address not in self._mach_addresses() or not self._remote_open(address):
            return False
        self._machines_set()
        return True

    def _machines_online_tick(self):
        """While the page is open, the lights are checked again every :data:`ONLINE_EVERY_MS`."""
        if not self._mach_open:
            self._mach_online_ticking = False
            return
        self._machines_probe()
        self.ctx.loop.after(ONLINE_EVERY_MS, self._machines_online_tick)

    # -- the page (PAD-1585: its own place, from the top bar) ----------------------
    @rpc
    def machines_open(self):
        """My machines' own page; Getting started closes (one page over the app at a time)."""
        self._mach_open = True
        if getattr(self, "_gs_open", False):
            self.getting_started_close()
        self._machines_set()
        self._machines_refresh()
        if not getattr(self, "_mach_online_ticking", False):
            self._mach_online_ticking = True
            self.ctx.loop.after(ONLINE_EVERY_MS, self._machines_online_tick)
        return True

    @rpc
    def machines_close(self):
        self._mach_open = False
        self._remote_quiet()
        self._machines_set()
        return True

    @rpc
    def machines_go_network(self, address=None):
        """The Network tab (remote access set up, Find my machine, Send an image): the maker's of the row at
        *address*, with that machine the one it acts on (PAD-1632); Stern's with no address (the empty page)."""
        mfr = "stern"
        if address:
            from ..core import pad_ssh_key
            pad_ssh_key.select_machine(address)
            row = next((r for r in self._mach_last[0] if r.get("address") == address), None)
            mfr = (row or {}).get("mfr") or "stern"
        if not self._enter(mfr):
            return False
        try:
            self.window.select_tab("network")
        except Exception:                               # noqa: BLE001
            return False
        return True

    @rpc
    def machines_add_network(self, address):
        """A machine remote access found: the card image it runs is picked (My machines knows a machine by its
        card), and the machine is linked to *address*, so Update's Send to machine goes to it."""
        from ..core import machines
        found = next((n for n in _network_machines() if n["address"] == address), None)
        what = found["title"] if found and found.get("title") else "the machine"
        path = self._pick_card("Pick the card image %s at %s runs" % (what, address))
        if not path:
            return None
        # PAD-1627: a machine already named on the page keeps that name as its row's
        mid = self.machines_add(path, name=(found or {}).get("name") or None)
        if mid:
            machines.set_address(self.app._settings, mid, address)
            self._mach_save()
            self._machines_refresh()
        return mid

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
            text = ("%s has %s %s out; %s runs %s. My machines (top bar) "
                    "updates it, and links to %s."
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
        # PAD-1632: no project joined by itself: the known projects of its game are offered to pick from
        same = [] if found else [f for f in machines.game_projects(m, folders) if os.path.isdir(f)]
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
               # PAD-1632: how the project joined ("linked" by hand, "holds" the card file, else by fingerprint)
               "project_how": found[0][1][0] if found else "",
               "game_projects": [{"folder": f, "name": os.path.basename(f)} for f in same],
               "newer": "", "newer_url": "",
               # PAD-1585: the game it runs (to find it on the network) and the address remote access reaches it at
               "game": (info or {}).get("key") or "", "address": m.get("address") or "",
               # PAD-1585: Update on a multi-boot card updates every image of the game on it
               "multi": mfr == "stern" and os.path.isfile(card) and _multi(card)}
        row.update(self._backup_fields(m))
        if info and code_watch.has_source(mfr):
            newest = code_watch.newest(mfr, info["key"])
            if newest and newest > tuple(info["version"]):
                row["newer"] = machines.version_words(mfr, newest)
                row["newer_url"] = code_watch.page_url(mfr, info["key"])
        return row

    @staticmethod
    def _backup_fields(m):
        """PAD-1588: the machines on the network running this row's game that this computer can log in to, and
        their kept settings backups, newest first."""
        from ..core import machine_backups
        game = machine_backups.game_key(m)
        ms = machine_backups.for_game(game) if game else []
        kept = []
        for net in ms:
            for b in machine_backups.kept(net["id"]):
                kept.append({"path": b["path"], "taken": b["taken"][:16], "files": b["files"],
                             "why": b["why"], "address": net["address"], "stamp": b["stamp"]})
        kept.sort(key=lambda b: b["stamp"], reverse=True)
        return {"backup_machines": [n["address"] for n in ms], "backups": kept,
                "backup_last": kept[0]["taken"] if kept else ""}

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
        mfrs = sorted({r["mfr"] for r in rows if code_watch.has_source(r["mfr"])})
        if not mfrs:
            return ""
        pages = _and([code_watch.page_words(k) for k in mfrs])
        if not on:
            return ("The check for new game code is off: PAD reads no "
                    "maker's site. Tick it to have %s read once a day."
                    % pages)
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

    # -- PAD-1588: settings and score backups -------------------------------------
    def _backup_tick(self):
        try:
            self._backup_pass()
        finally:
            self.ctx.loop.after(BACKUP_TICK_MS, self._backup_tick)

    def _backup_pass(self):
        """Every machine of My machines that answers on the network and is due is backed up off the loop (only
        reads: the game goes on).  Never beside a Send, which takes its own first."""
        from ..core import machine_backups
        settings = self._mach_settings()
        if settings is None or self._backing_up or not machine_backups.auto_on(settings):
            return False
        if getattr(self.app, "_send_active", False):
            return False
        games = machine_backups.my_games(settings)
        if not games or not any(m["game"] in games for m in machine_backups.known()):
            return False
        keep = machine_backups.keep_of(settings)
        self._backing_up = True

        def say(text, level="info"):
            self.ctx.loop.post(self.window.append_log, text, level)

        def work():
            try:
                for m, res, err in machine_backups.auto_pass(games, keep, log=say):
                    log.info("settings backup %s: %s", m["address"], res["status"] if res else err)
            except Exception:                           # noqa: BLE001
                log.exception("settings backup pass")
            finally:
                self.ctx.loop.post(self._backup_passed)
        threading.Thread(target=work, name="pad-machine-backup", daemon=True).start()
        return True

    def _backup_passed(self):
        self._backing_up = False
        self._machines_refresh()

    @rpc
    def machines_set_backup(self, auto=None, keep=None):
        """The switch (backups by themselves, and before a Send or a whole-card write) and how many each keeps."""
        from ..core import machine_backups
        settings = self._mach_settings()
        if settings is None:
            return False
        if auto is not None:
            settings[machine_backups.AUTO_KEY] = bool(auto)
        if keep is not None:
            settings[machine_backups.KEEP_KEY] = machine_backups.keep_of({machine_backups.KEEP_KEY: keep})
            for net in machine_backups.known():
                machine_backups.prune(net["id"], machine_backups.keep_of(settings))
        self._mach_save()
        self._machines_refresh()
        if auto:
            self._backup_pass()
        return True

    def _backup_target(self, mid, path=""):
        """``(row's entry, network machine)`` for a row's backup call: the machine *path* was taken from, else the
        first that runs the row's game."""
        from ..core import machine_backups
        m = self._mach(mid)
        if m is None:
            return None, None
        ms = machine_backups.for_game(machine_backups.game_key(m))
        if path:
            where = os.path.normcase(os.path.dirname(os.path.abspath(path)))
            ms = [n for n in ms if os.path.normcase(os.path.abspath(machine_backups.folder(n["id"]))) == where]
        return m, (ms[0] if ms else None)

    @rpc
    def machines_backup_now(self, mid):
        """Back the row's machine up now, whatever the last one's age (none kept when nothing changed)."""
        from ..core import machine_backups
        m, net = self._backup_target(mid)
        if net is None:
            return False
        keep = machine_backups.keep_of(self._mach_settings() or {})
        name = m.get("name") or "the machine"

        def work():
            try:
                machine = machine_backups._connect(net["address"])
                try:
                    res = machine_backups.take(machine, net["id"], keep, force=True, why="by hand",
                                               address=net["address"])
                finally:
                    machine.close()
                if res["status"] == "taken":
                    text, kind = ("Backed up %s's settings, audits and high scores (%d files)."
                                  % (name, res["files"]), "success")
                else:
                    text, kind = ("%s's settings are the same as its backup of %s, so no new one is kept."
                                  % (name, res["last"]["taken"][:16]), "info")
            except Exception as e:                      # noqa: BLE001 - said, never raised into the page
                text, kind = "Couldn't back up %s: %s" % (name, e), "error"
            self.ctx.loop.post(self._backup_said, text, kind)
        threading.Thread(target=work, name="pad-machine-backup-now", daemon=True).start()
        return True

    def _backup_said(self, text, kind):
        self.window.append_log(text, kind)
        self.window.toast(text, kind, ms=9000)
        self._machines_refresh()

    @rpc
    def machines_restore(self, mid, path):
        """Put a kept backup back on the row's machine: the game is held while its settings are swapped, every file
        checked, then the game starts again (core/machine_care.restore_settings)."""
        from ..core import machine_care, remote_send
        m, net = self._backup_target(mid, path)
        if net is None or not os.path.isfile(path or ""):
            return False
        try:
            manifest, _raw = machine_care.read_backup(path)
        except machine_care.CareError as e:
            compat.messagebox.showerror("Restore settings", str(e))
            return False
        name = m.get("name") or "the machine"
        when = (manifest.get("taken") or "")[:16]
        if not compat.messagebox.askyesno(
                "Restore settings",
                "Put the backup of %s back on %s (at %s)?\n\nIts adjustments, audits and high scores become those "
                "of that backup. A game being played ends while they are put back, then the game starts again. The "
                "settings it has now are kept on the machine beside them." % (when, name, net["address"]),
                icon="warning"):
            return False

        def work():
            try:
                machine = remote_send.connect(net["address"])
                try:
                    res = machine_care.restore_settings(machine, path)
                finally:
                    machine.close()
                text, kind = ("Put %s's settings, audits and high scores of %s back (%d files); its game started "
                              "again." % (name, when, res["files"]), "success")
            except Exception as e:                      # noqa: BLE001 - said, never raised into the page
                text, kind = "Couldn't restore %s's settings: %s" % (name, e), "error"
            self.ctx.loop.post(self._backup_said, text, kind)
        threading.Thread(target=work, name="pad-machine-restore", daemon=True).start()
        return True

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
        if getattr(self, "_mach_open", False):          # PAD-1585: the working view, not the page over it
            self._mach_open = False
            self._machines_set()
        self._remote_quiet()                            # PAD-1632: the page's live view ends with the page
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
        self._open_folder(r["project"])
        return r

    def _open_folder(self, folder):
        from ..core import project_file
        if project_file.has_anchor(folder):
            self.app._open_project_folder_checked(folder)
        else:
            self.window.extract_output_var.set(folder)

    # -- PAD-1632: the owner says which project is a machine's ---------------------------------------------------
    @rpc
    def machines_link_project(self, mid, folder=None, open_it=False):
        """This machine's project is *folder* (a folder picker when none): the row names it from now on, whatever
        card it was extracted from.  *open_it* also opens it in the working view."""
        from ..core import machines
        m = self._mach(mid)
        if m is None:
            return False
        if folder is None:
            folder = compat.filedialog.askdirectory(
                title="Pick the project folder of %s" % (m.get("name") or "this machine"))
        if not folder:
            return False
        if not os.path.isdir(folder):
            compat.messagebox.showerror("Choose project", "That folder isn't there:\n    %s" % folder)
            return False
        folder = os.path.abspath(folder)
        machines.set_project(self.app._settings, mid, folder)
        touch = getattr(self.app, "_registry_touch", None)
        if touch is not None:
            try:
                touch(folder)
            except Exception:                           # noqa: BLE001 - the link itself is stored
                log.exception("registry touch %s", folder)
        self._mach_save()
        self._machines_refresh()
        if open_it and self._enter(m.get("manufacturer") or "stern"):
            self._open_folder(folder)
        return True

    @rpc
    def machines_unlink_project(self, mid):
        """Take the by-hand project link back: the row finds its project by itself again."""
        from ..core import machines
        if self._mach(mid) is None or not machines.set_project(self.app._settings, mid, ""):
            return False
        self._mach_save()
        self._machines_refresh()
        return True

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
    def machines_update(self, mid):
        """PAD-1585: Update to <newer build> - this machine's project carried onto Stern's new card image by the
        app (app._start_machine_update), told first what can't be carried.  Built, the machine is shown on the
        update and the Write tab is set to put it on the machine: Send to machine (over the network, its
        settings, audits and high scores stay) or Build / flash SD card."""
        r = self._row(mid)
        if not r or not r.get("transfer") or r["card_missing"]:
            return False
        if r.get("multi"):
            # every image of the game on the card, each with its own project: none is opened
            if not self._enter(r["mfr"]):
                return False
        else:
            r = self._open_machine_project(mid)
            if r is None:
                return False

        def updated(card, replaced, plan):
            if os.path.isfile(card):
                self.machines_rebind(mid, card)
            n = "%d image%s of the game" % (len(replaced), "" if len(replaced) == 1 else "s")
            if _same(card, r["card"]):
                how = ("%s's card is updated in place: %s replaced, every other image and the menu as they "
                       "were." % (r["name"] or "The machine", n))
            else:
                how = ("%s's card is built again beside the old one, because its first image is now a new "
                       "release, whose system an in-place update cannot carry: %s replaced, every other image "
                       "and the menu as they were." % (r["name"] or "The machine", n))
            compat.messagebox.showinfo(
                "Card updated",
                "%s\n    %s\n\nPut it on the machine: Send to machine sends only what changed and keeps the "
                "machine's settings, audits and high scores; a card write keeps them with Keep the card's own "
                "settings." % (how, card))

        def built(build, workspace, raw):
            if r.get("address"):
                # PAD-1585: the machine remote access reaches this one at is the one Send to machine uses
                try:
                    from ..core import pad_ssh_key
                    pad_ssh_key.select_machine(r["address"])
                except Exception:                       # noqa: BLE001
                    log.exception("select the machine for Send")
            w = self.window
            w.write_upd_var.set(raw)
            w.write_assets_var.set(workspace)
            w.write_output_var.set(os.path.dirname(build))
            w.write_filename_var.set(os.path.basename(build))
            # the update's extract is the machine's project from now on: known to the app, so the
            # row (which finds a machine's project among the known ones) still names one
            touch = getattr(self.app, "_registry_touch", None)
            if touch is not None:
                touch(workspace)
                self.app._save_settings()
            if os.path.isfile(build):
                self.machines_rebind(mid, build)
            w.select_tab("write")
            compat.messagebox.showinfo(
                "Update built",
                "%s is built:\n    %s\n\nPut it on the machine from the Write tab: Send to machine sends only "
                "what changed over your network and keeps the machine's settings, audits and high scores. Or "
                "Build / flash SD card writes a card; tick Keep the card's own settings there to keep them "
                "when you write over the machine's card." % (r["name"] or "The update", build))

        return bool(self.app._start_machine_update(mid, r["project"], r["card"], on_built=built,
                                                   on_multi=updated))

    @rpc
    def machines_write(self, mid):
        r = self._open_machine_project(mid)
        if r is None:
            return False
        self.window.select_tab("write")
        return True


#: how often the open page checks again which machines answer
ONLINE_EVERY_MS = 30000


def _network_machines():
    """PAD-1585: the machines remote access found (Network tab, remote_access/machines.json), each
    ``{"address", "game", "title"}``; [] when it has none or the file cannot be read."""
    try:
        from ..core import pad_ssh_key
        found = pad_ssh_key.machines()
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for m in found:
        game = m.get("game") or ""
        title = ""
        if game:
            try:
                from ..core import machines
                rel = machines.release_info({"manufacturer": "stern", "sidx": game + "-0_00_0.sidx"}) or {}
                # PAD-1627: the whole edition ("LE / Premium": one build runs both, so the machine cannot say
                # which it is; David's Premium read "Godzilla LE")
                title = " ".join(x for x in (rel.get("title"), rel.get("edition")) if x)
            except Exception:                           # noqa: BLE001
                title = ""
        out.append({"address": m["address"], "game": game, "title": title or game.replace("_", " ").title(),
                    # the owner's own name for it, and whether anything ever answered there (False: an address
                    # only typed in on the Network tab)
                    "name": m.get("name") or "", "known": bool(game or m.get("host_key")),
                    # True once the machine has said where it is by itself (core/machine_announce.py)
                    "announces": bool(m.get("announces"))})
    return out


def _find_careful(recs):
    """Whether the page's look over the network goes on to the slow pass: while a machine this computer knows
    is not accounted for (a machine just switched on is missed by the quick sweep, PAD-1456), or when it knows
    none and none let it in.  A known machine is accounted for by its identity, or by a machine of its game that
    let this computer in (its card written again has a new identity)."""
    from ..core import pad_ssh_key
    # a machine that says where it is (PAD-1627) is asked, not swept for: when it is on it has answered
    known = [m for m in pad_ssh_key.machines() if (m["host_key"] or m["game"]) and not m.get("announces")]
    if not known and any(m.get("announces") for m in pad_ssh_key.machines()):
        return False
    seen = {tuple(r["host_key"]) for r in recs if r.get("host_key")}
    games = {r.get("game") for r in recs if r.get("lets_in") and r.get("game")}
    if known:
        return not all(m["host_key"] in seen or m["game"] in games for m in known)
    return not any(r.get("lets_in") for r in recs)


def find_words(ours, moved, before, network):
    """What Find my machines found, in a line for the page."""
    by = {n["address"]: n for n in network}

    def said(a):
        n = by.get(a) or {}
        return n.get("name") or n.get("title") or "A machine"
    if not ours:
        return ("No machine that lets this computer in answered. Is it switched on, on this network, and its card "
                "set up for remote access (Network tab)?")
    new_at = {v: k for k, v in moved.items()}
    parts = []
    for r in ours:
        a = r["address"]
        if a in new_at:
            parts.append("%s is on at %s (it was at %s)" % (said(a), a, new_at[a]))
        elif a not in before:
            parts.append("found %s at %s" % (said(a), a))
        else:
            parts.append("%s is on at %s" % (said(a), a))
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


def link_network(rows, network):
    """*rows* with each one's network address - the one it was linked to, else the one machine remote access found
    running its game (several of the same game: none is guessed) - and the found machines no row runs.
    -> ``(rows, unlinked)``."""
    rows = [dict(r) for r in rows]
    taken = {r["address"] for r in rows if r.get("address")}
    for r in rows:
        if r.get("address") or not r.get("game"):
            continue
        same = [n for n in network if n["game"] == r["game"] and n["address"] not in taken]
        if len(same) == 1:
            r["address"] = same[0]["address"]
            taken.add(r["address"])
    return rows, [n for n in network if n["address"] not in taken]


def _multi(card):
    """True when the card image *card* carries more than one game image (cached on the file's identity)."""
    try:
        from ..plugins.stern import multiimage
        return len(multiimage.images_for_path(card)) > 1
    except Exception:                                   # noqa: BLE001
        return False


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
