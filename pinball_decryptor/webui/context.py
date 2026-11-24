"""One object holding the web UI's moving parts, passed everywhere."""

import secrets
import threading

from .dialogs import Dialogs
from .drops import DropBox
from .loop import UiLoop
from .rpc import Registry
from .state import EventBus, Store


class Context:
    def __init__(self):
        self.loop = UiLoop()
        self.bus = EventBus()
        self.store = Store(self.bus)
        self.dialogs = Dialogs(self.loop, self.store)
        self.registry = Registry(self.loop)
        self.token = secrets.token_urlsafe(24)
        self.host = None         # the desktop host (window chrome, pickers)
        self.app = None          # the App (run logic, app.py)
        self.window = None       # the WebWindow (what the run logic drives)
        self.start_geometry = None   # the window's saved place (host.build)
        self._clients = 0
        self._clients_lock = threading.Lock()
        self.on_clients_changed = None
        # set once a page has asked for its state: the native window's page
        # reached the app (the host's blank-window watch, PAD-748)
        self.page_seen = threading.Event()
        # PAD-1545: the desktop host opens its window while the App is still
        # being made.  Set by the host to an Event that fires once the App is
        # there; the page's first ask for its state waits on it.  None when
        # nothing is being made (tests, a Context used on its own).
        self.building = None
        # ...and the host asking the App to open the last project as its
        # first job on the loop, not inside its constructor
        self.defer_session = False
        # files dropped on the window, by full path (drops.py, PAD-838)
        self.drops = DropBox()

    # -- read by the HTTP server ----------------------------------------
    def state_snapshot(self):
        """The page's starting point: the event number and the state as of
        that number (events after it are replayed on top)."""
        first = not self.page_seen.is_set()
        # the page reached the app, whether or not the App is made yet: the
        # host's blank-window watch is satisfied from here
        self.page_seen.set()
        building = self.building
        if building is not None:
            building.wait()
        if first:
            # the first page of this run is up: a Restart to update's
            # splash, if this is the version it waited for, is done
            # (core/update_splash, PAD-1036); a FindWindow when there is none
            try:
                from ..core import update_splash
                update_splash.dismiss()
            except Exception:                           # noqa: BLE001
                pass
        window = self.window
        seq = self.bus.last_seq
        state = self.store.snapshot()
        log = window.log_history() if window is not None else []
        return {"seq": seq, "state": state, "log": log,
                "token": None}

    def client_connected(self):
        with self._clients_lock:
            self._clients += 1
            n = self._clients
        if self.on_clients_changed:
            self.on_clients_changed(n)

    def client_disconnected(self):
        with self._clients_lock:
            self._clients = max(0, self._clients - 1)
            n = self._clients
        if self.on_clients_changed:
            self.on_clients_changed(n)

    @property
    def clients(self):
        return self._clients
