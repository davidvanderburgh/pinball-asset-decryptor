"""One object holding the web UI's moving parts, passed everywhere."""

import secrets
import threading

from .dialogs import Dialogs
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
        self._clients = 0
        self._clients_lock = threading.Lock()
        self.on_clients_changed = None

    # -- read by the HTTP server ----------------------------------------
    def state_snapshot(self):
        """The page's starting point: the event number and the state as of
        that number (events after it are replayed on top)."""
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
