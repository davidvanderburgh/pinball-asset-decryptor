"""Server-side UI state and the event stream that mirrors it to the page.

:class:`EventBus` numbers every event and keeps the recent ones, so a page
that reconnects (or loads late) asks for "everything after N" and misses
nothing.  :class:`Store` is the UI state as plain JSON-able values, one
namespace per tab (``"extract"``, ``"audio"``, ``"shell"`` ...); a change is
published as a ``state`` event carrying only the keys that changed, and the
page keeps an identical copy.

Everything here is thread-safe: pipeline workers, HTTP handlers and the UI
loop all publish.
"""

import copy
import itertools
import json
import threading
import time
from collections import deque


def _jsonable(value):
    """Normalise a value to what json.dumps round-trips (tuples -> lists,
    sets -> sorted lists, non-str dict keys -> str)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


class EventBus:
    """Numbered, buffered publish/subscribe for the page."""

    def __init__(self, keep=4000):
        self._lock = threading.Condition()
        self._events = deque(maxlen=keep)    # (seq, json_text)
        self._seq = itertools.count(1)
        self._last = 0
        self._closed = False

    @property
    def last_seq(self):
        return self._last

    def publish(self, etype, **data):
        data["t"] = etype
        text = json.dumps(_jsonable(data), separators=(",", ":"))
        with self._lock:
            seq = next(self._seq)
            self._last = seq
            self._events.append((seq, text))
            self._lock.notify_all()
        return seq

    def since(self, seq):
        """Events after ``seq`` as [(seq, text)], plus whether some were
        dropped (the page then reloads its whole state)."""
        with self._lock:
            if not self._events:
                return [], False
            first = self._events[0][0]
            gap = seq + 1 < first and seq < self._last
            return [(s, t) for s, t in self._events if s > seq], gap

    def wait(self, seq, timeout):
        """Block until an event after ``seq`` exists (or timeout)."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._last <= seq and not self._closed:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._lock.wait(left)
            return self._last > seq

    def close(self):
        with self._lock:
            self._closed = True
            self._lock.notify_all()

    @property
    def closed(self):
        return self._closed


_MISSING = object()


class Store:
    """The UI state, one dict per namespace, mirrored to the page."""

    def __init__(self, bus):
        self._bus = bus
        self._lock = threading.RLock()
        self._ns = {}

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._ns)

    def namespace(self, ns):
        with self._lock:
            return copy.deepcopy(self._ns.get(ns, {}))

    def get(self, ns, key, default=None):
        with self._lock:
            value = self._ns.get(ns, {}).get(key, _MISSING)
            if value is _MISSING:
                return default
            return copy.deepcopy(value)

    def set(self, ns, **values):
        """Merge ``values`` into ``ns``; publish only the keys that changed."""
        changed = {}
        with self._lock:
            space = self._ns.setdefault(ns, {})
            for key, value in values.items():
                value = _jsonable(value)
                if space.get(key, _MISSING) != value:
                    space[key] = value
                    changed[key] = value
        if changed:
            self._bus.publish("state", ns=ns, patch=changed)
        return changed

    def replace(self, ns, values):
        """Replace the whole namespace (keys not in ``values`` are dropped)."""
        values = _jsonable(dict(values))
        with self._lock:
            self._ns[ns] = values
        self._bus.publish("state", ns=ns, patch=values, replace=True)

    def set_item(self, ns, key, index, value):
        """Replace one element of a list held at ``ns.key`` (a table row)
        without resending the whole list."""
        value = _jsonable(value)
        with self._lock:
            seq = self._ns.setdefault(ns, {}).get(key)
            if not isinstance(seq, list) or not 0 <= index < len(seq):
                return False
            if seq[index] == value:
                return False
            seq[index] = value
        self._bus.publish("item", ns=ns, key=key, index=index, value=value)
        return True

    def patch_item(self, ns, key, index, **fields):
        """Merge ``fields`` into the dict at ``ns.key[index]``."""
        with self._lock:
            seq = self._ns.setdefault(ns, {}).get(key)
            if not isinstance(seq, list) or not 0 <= index < len(seq):
                return False
            row = seq[index]
            if not isinstance(row, dict):
                return False
            new = dict(row)
            new.update(_jsonable(fields))
        return self.set_item(ns, key, index, new)
