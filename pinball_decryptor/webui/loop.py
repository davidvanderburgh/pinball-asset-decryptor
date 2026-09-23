"""The web UI's event loop: one thread that plays the part Tk's mainloop did.

The run logic in :mod:`pinball_decryptor.app` was written for Tk: it is
single-threaded, it schedules work with ``root.after(ms, fn)``, and its modal
questions (``messagebox.askyesno``) return a value while the event loop keeps
turning underneath them.  This loop keeps all three promises, so that logic
runs unchanged:

* every call that touches app or window state runs on THIS thread;
* ``after`` / ``after_idle`` / ``after_cancel`` behave like Tk's;
* a modal wait on this thread (:meth:`UiLoop.pump_until`) keeps running the
  other queued work, the way Tk's nested dialog loop does, so log lines and
  progress keep arriving while a question is on screen.

Other threads (HTTP handlers, pipeline workers) hand work in with
:meth:`post` or :meth:`call`.
"""

import heapq
import itertools
import logging
import threading
import time
import traceback

log = logging.getLogger(__name__)


class LoopStopped(RuntimeError):
    """The loop was shut down while a caller waited on it."""


class _Future:
    __slots__ = ("event", "result", "error")

    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.error = None


class UiLoop:
    def __init__(self, name="pad-ui"):
        self._name = name
        self._lock = threading.Condition()
        self._ready = []                 # FIFO of (fn, args)
        self._timers = []                # heap of (due, seq, timer_id)
        self._timer_fns = {}             # timer_id -> (fn, args)
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)
        self._thread = None
        self._stopped = False
        self._depth = 0                  # nesting of pump_until
        self.error_hook = None           # fn(exc_text) for uncaught errors

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=self._name,
                                        daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock:
            self._stopped = True
            self._lock.notify_all()

    @property
    def stopped(self):
        return self._stopped

    def in_loop(self):
        return threading.current_thread() is self._thread

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    # ------------------------------------------------------------------
    # scheduling (thread-safe)
    # ------------------------------------------------------------------
    def post(self, fn, *args):
        """Run ``fn(*args)`` on the loop as soon as it is free."""
        with self._lock:
            if self._stopped:
                return
            self._ready.append((fn, args))
            self._lock.notify_all()

    def after(self, ms, fn=None, *args):
        """Tk's ``after``: run ``fn(*args)`` in ``ms`` milliseconds; returns
        an id for :meth:`after_cancel`.  With no ``fn`` it sleeps, as Tk's
        does (only sensible off the loop)."""
        if fn is None:
            time.sleep(max(0, ms) / 1000.0)
            return None
        tid = "after#%d" % next(self._ids)
        due = time.monotonic() + max(0, ms) / 1000.0
        with self._lock:
            if self._stopped:
                return tid
            self._timer_fns[tid] = (fn, args)
            heapq.heappush(self._timers, (due, next(self._seq), tid))
            self._lock.notify_all()
        return tid

    def after_idle(self, fn, *args):
        return self.after(0, fn, *args)

    def after_cancel(self, tid):
        if not tid:
            return
        with self._lock:
            self._timer_fns.pop(tid, None)

    def call(self, fn, *args, timeout=None):
        """Run ``fn(*args)`` on the loop and return its result (or raise its
        exception) in the calling thread.  On the loop itself it runs
        inline."""
        if self.in_loop():
            return fn(*args)
        fut = _Future()

        def _job():
            try:
                fut.result = fn(*args)
            except BaseException as e:           # noqa: BLE001 - re-raised
                fut.error = e
            finally:
                fut.event.set()

        self.post(_job)
        if not fut.event.wait(timeout):
            if self._stopped:
                raise LoopStopped("the UI loop stopped")
            raise TimeoutError("the UI loop did not answer in time")
        if fut.error is not None:
            raise fut.error
        return fut.result

    # ------------------------------------------------------------------
    # the loop itself
    # ------------------------------------------------------------------
    def _next_job(self, block_until=None, wake=None):
        """Pop the next runnable job, waiting for one.  Returns None when the
        loop stops, or when ``wake`` (an Event) is set while waiting."""
        with self._lock:
            while True:
                if self._stopped:
                    return None
                if wake is not None and wake.is_set():
                    return None
                now = time.monotonic()
                while self._timers and self._timers[0][0] <= now:
                    _due, _seq, tid = heapq.heappop(self._timers)
                    job = self._timer_fns.pop(tid, None)
                    if job is not None:
                        self._ready.append(job)
                if self._ready:
                    return self._ready.pop(0)
                timeout = None
                if self._timers:
                    timeout = max(0.0, self._timers[0][0] - now)
                if wake is not None:
                    timeout = 0.05 if timeout is None else min(timeout, 0.05)
                self._lock.wait(timeout)

    def _run_job(self, job):
        fn, args = job
        try:
            fn(*args)
        except Exception:                          # noqa: BLE001 - logged
            text = traceback.format_exc()
            log.error("UI loop job failed:\n%s", text)
            hook = self.error_hook
            if hook is not None:
                try:
                    hook(text)
                except Exception:                  # noqa: BLE001
                    pass

    def _run(self):
        while True:
            job = self._next_job()
            if job is None:
                return
            self._run_job(job)

    def pump_until(self, event, timeout=None):
        """Keep running loop work until ``event`` is set.  Called ON the loop
        by a modal wait so the app stays alive underneath the question, as
        Tk's nested dialog loop does.  Off the loop it simply waits."""
        if not self.in_loop():
            return event.wait(timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        self._depth += 1
        try:
            while not event.is_set():
                if self._stopped:
                    return False
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                job = self._next_job(wake=event)
                if job is not None:
                    self._run_job(job)
            return True
        finally:
            self._depth -= 1

    def notify(self):
        """Wake the loop (used when an Event a pump waits on is set)."""
        with self._lock:
            self._lock.notify_all()
