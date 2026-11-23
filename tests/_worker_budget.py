"""One machine-wide budget of xdist workers, shared by every test run.

PAD-1536 (David, 2026-11-23: "we're using nearly 100% of my cpu right
now. there are only 2 tickets working"): two tickets each ran the full
suite 13 s apart, each `-n auto` took 8 workers on his 16-thread PC, and
16 workers on 16 threads ran for 7+ minutes where one run alone takes
about one.  Every run assumed it owned the machine.

Now `-n auto` asks this module instead.  The budget is what `-n auto`
gave one run before (xdist's own count: the physical cores, 8 here, half
the threads, the half that stays free for David's own use of the PC):

  * a run alone takes the whole budget - the single-run case is unchanged;
  * a run that starts while others hold workers takes an even share of
    the budget (budget // runs, at least MIN_SHARE) once that many are
    free, and WAITS for them otherwise, saying so;
  * a run that ends, or dies, gives its workers back (dead runs are
    noticed by process id, so a killed run cannot hold workers forever).

So two full runs no longer fight: the second waits for the first's
minute, or both run on half.  It never lowers a process's priority
(David rejected Idle priority), and it only applies to `-n auto`: an
explicit `-n 4` or `-n 0` is the caller's choice, though an explicit
count is still recorded so the auto runs see it.

The claims are small JSON files in %TEMP%/pad-pytest-workers, one per
run, guarded by a mkdir lock.  Escape hatches:
  PAD_TEST_WORKERS=<n>   the budget (default xdist's own count)
  PAD_TEST_WORKERS=0     no budget at all (old behaviour)
  PAD_TEST_WAIT=<secs>   longest wait before starting on MIN_SHARE anyway
                         (default 1200)
CI runners run one suite per machine, so CI skips the budget.
"""

import json
import os
import sys
import tempfile
import time

MIN_SHARE = 2
LOCK_STALE_S = 30
CLAIM_MAX_AGE_S = 6 * 3600          # a claim older than this is dropped
HELD_ENV = "PAD_TEST_BUDGET_HELD"   # set by a run that holds workers

_held = {"path": None}


def budget_dir():
    return os.environ.get("PAD_TEST_BUDGET_DIR") or os.path.join(
        tempfile.gettempdir(), "pad-pytest-workers")


def enabled():
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        return False
    if os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return False                 # someone named the count outright
    if os.environ.get(HELD_ENV):
        return False                 # a run started from inside a run
    return os.environ.get("PAD_TEST_WORKERS", "").strip() != "0"


def budget(default):
    raw = os.environ.get("PAD_TEST_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, int(default))


# -- process liveness -------------------------------------------------------

def _create_time(pid):
    try:
        import psutil
        return psutil.Process(pid).create_time()
    except Exception:                                       # noqa: BLE001
        return None


def _alive(pid, created=None):
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            p = psutil.Process(pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                return False
            if created is not None and abs(p.create_time() - created) > 1:
                return False         # the pid was reused by another process
            return True
        except Exception:                                   # noqa: BLE001
            return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259             # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# -- the claim files --------------------------------------------------------

class _Lock:
    def __init__(self, d):
        self.path = os.path.join(d, ".lock")

    def __enter__(self):
        deadline = time.time() + 2 * LOCK_STALE_S
        while True:
            try:
                os.mkdir(self.path)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE_S:
                        os.rmdir(self.path)          # its owner died inside
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    return self                      # never block a run on it
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            os.rmdir(self.path)
        except OSError:
            pass


def _read(d):
    """-> (claims, waiters): live entries only; dead ones are deleted."""
    claims, waiters = [], []
    now = time.time()
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
            dead = (now - rec.get("since", now) > CLAIM_MAX_AGE_S
                    or not _alive(int(rec["pid"]), rec.get("created")))
        except (OSError, ValueError, KeyError, TypeError):
            dead = True
            rec = None
        if dead:
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        rec["_path"] = p
        (waiters if name.startswith("wait-") else claims).append(rec)
    return claims, waiters


def _write(path, rec):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, path)


def _record(pid, workers, where):
    return {"pid": pid, "created": _create_time(pid), "workers": workers,
            "where": where, "since": time.time()}


def share(total, live_workers, runs):
    """Workers the newest of *runs* runs wants, out of *total*: everything
    when it is alone, an even share (at least MIN_SHARE) otherwise."""
    if runs <= 1 and live_workers == 0:
        return total
    return max(min(MIN_SHARE, total), total // max(runs, 1))


def claim(total, where="", say=None, wait_s=None, poll_s=2.0, pid=None):
    """Take workers from the shared budget; blocks while too few are free.
    Returns the count to start.  *say* gets one line when it has to wait."""
    say = say or (lambda msg: None)
    pid = pid or os.getpid()
    if wait_s is None:
        try:
            wait_s = float(os.environ.get("PAD_TEST_WAIT", "1200"))
        except ValueError:
            wait_s = 1200.0
    d = budget_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return total
    mine = os.path.join(d, "run-%d.json" % pid)
    waitp = os.path.join(d, "wait-%d.json" % pid)
    t0 = time.time()
    told = 0.0
    while True:
        with _Lock(d):
            claims, waiters = _read(d)
            used = sum(int(c.get("workers", 0)) for c in claims)
            others = [w for w in waiters if int(w["pid"]) != pid]
            runs = len(claims) + len(others) + 1
            want = share(total, used, runs)
            free = total - used
            late = time.time() - t0 > wait_s
            if free >= want or not claims or late:
                n = want if free >= want or not claims else min(want, MIN_SHARE)
                _write(mine, _record(pid, n, where))
                try:
                    os.remove(waitp)
                except OSError:
                    pass
                _held["path"] = mine
                os.environ[HELD_ENV] = str(pid)
                if late and free < want:
                    say("test workers: waited %d s, starting on %d anyway"
                        % (time.time() - t0, n))
                return n
            if not os.path.exists(waitp):
                _write(waitp, _record(pid, 0, where))
        if time.time() - told >= 60:
            told = time.time()
            busy = ", ".join("%s (%d)" % (c.get("where") or "pid %s" % c["pid"],
                                          c.get("workers", 0)) for c in claims)
            say("test workers: %d of %d busy in other runs [%s]; waiting for "
                "%d to free up (PAD-1536 machine-wide budget)"
                % (used, total, busy, want))
        time.sleep(poll_s)


def record_fixed(n, where=""):
    """Note an explicit `-n N` run so auto runs count its workers."""
    d = budget_dir()
    try:
        os.makedirs(d, exist_ok=True)
        mine = os.path.join(d, "run-%d.json" % os.getpid())
        with _Lock(d):
            _write(mine, _record(os.getpid(), int(n), where))
        _held["path"] = mine
    except OSError:
        pass


def release():
    p, _held["path"] = _held["path"], None
    if p:
        try:
            os.remove(p)
        except OSError:
            pass
    if os.environ.get(HELD_ENV) == str(os.getpid()):
        del os.environ[HELD_ENV]


def where_label(rootdir):
    """A short name for the run: the ticket worktree's folder."""
    base = os.path.basename(os.path.normpath(str(rootdir)))
    return base or str(rootdir)


if __name__ == "__main__":          # `python tests/_worker_budget.py`: status
    claims, waiters = _read(budget_dir()) if os.path.isdir(budget_dir()) \
        else ([], [])
    for c in claims:
        print("run   pid %-6s %2d workers  %s" % (c["pid"], c["workers"],
                                                  c.get("where", "")))
    for w in waiters:
        print("wait  pid %-6s             %s" % (w["pid"], w.get("where", "")))
    if not claims and not waiters:
        print("no test runs hold workers")
    sys.exit(0)
