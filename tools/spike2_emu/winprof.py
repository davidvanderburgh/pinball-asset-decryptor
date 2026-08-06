#!/usr/bin/env python3
"""winprof.py - profile the WINDOWS side of the boundary while the rig runs.

    py -3 winprof.py --secs 60 --label idle
    py -3 winprof.py --secs 90 --label attract
    py -3 winprof.py --compare winprof_idle.json winprof_attract.json

** RUN THIS ON WINDOWS, with `py`, NOT inside WSL. ** It is the whole point of
the script. Every CPU number this rig has ever taken was taken inside WSL, and
"my computer runs a little sluggish when the emulator is going" is a WINDOWS
symptom. That is the same shape that cost an afternoon on the audio item: a
sine came back mathematically perfect off RDPSink.monitor while the room heard
it breaking up, because the damage was on the far side of the boundary from
where the microphone was.

WHAT IT MEASURES, and why each one is here rather than the obvious alternative:

  * `\\Hyper-V Hypervisor Logical Processor(_Total)\\% Total Run Time` MINUS
    `\\Hyper-V Hypervisor Root Virtual Processor(_Total)\\% Total Run Time`.
    "Logical" is every physical core including guest time; "Root Virtual" is
    Windows' own share. The difference is the WSL VM.

    Two sanity checks it has already passed, both worth keeping because they
    are what makes the number believable:
      - at true idle the two sit within 0.08 points of each other;
      - during a run the difference (7.03% of 16 cores = 1.12 cores) agrees
        with `\\Process(vmmemWSL)\\% Processor Time` reading 122.57% of one
        core, by a completely independent route.

    ** A CLAIM THAT WAS IN THIS DOCSTRING AND WAS WRONG, corrected 2026-08-06
    by the first real run: "\\Process(vmmemWSL)\\% Processor Time reads a FLAT
    ZERO". It does not. ** It read 0.000000 three times running, so it was
    written down as a property of the counter - but WSL was IDLE at the time,
    and idle is what it was correctly reporting. The counter works and it is
    the cross-check above. The lesson is the ordinary one: a zero taken with
    nothing running is not evidence about an instrument, it is evidence about
    the machine.

    `\\Processor(_Total)\\% Processor Time` IS understated, though, and that
    part stands: it is the root partition's view, and it read 19.35 against the
    hypervisor's 23.61 for the same window, so it misses about 60% of what the
    VM costs. It is kept for exactly that comparison.

  * Per-process CPU and working set, via `\\Process(*)\\...`, so the Windows-side
    halves of the rig are visible: msrdc.exe (the RDP client that draws every
    WSLg window onto the desktop - it had accumulated 692 CPU-seconds before
    this script existed), dwm.exe, and our own two Windows processes,
    playfield.py and padplay.py, which are easy to forget are ours at all.

  * GPU per PID and per engine type, via `\\GPU Engine(*)\\Utilization
    Percentage`. The renderer is already on the GPU (GALLIUM_DRIVER=d3d12) and
    the handoff says in terms that none of the old CPU cost was the renderer -
    but that was measured INSIDE WSL, and the WSLg composite hop to the Windows
    desktop is not inside WSL.

  * Memory and queueing: available MB, hard faults (Pages Input/sec), processor
    queue length, context switches. A machine that feels slow because it is
    paging looks nothing like one that feels slow because it is oversubscribed.

  * TWO RESPONSIVENESS PROBES, because "sluggish" is a feeling and the item
    asks for a number:
      - wakeup jitter: how much longer than asked an 8 ms sleep actually takes.
        This is scheduler latency, which is what a laggy pointer or a slow
        window redraw is made of.
      - fixed work: a constant amount of pure-Python arithmetic, timed. This is
        CPU availability for something that already has the CPU.
    They answer different questions and can disagree, and that disagreement is
    itself a diagnosis.

    ** VALIDATED ON A LABELLED EXAMPLE, AND ONE OF THEM FAILED IT. ** 20 busy
    Python processes on a 16-core machine, against an idle control:
      - the machine really was saturated: CPU 8.4% -> 31.4% mean with samples
        at 100%, processor queue length 0 -> 17.25 mean and 80 at peak.
      - `fixed work` p50 went 0.72 -> 1.13 ms (+57%), p95 1.21 -> 1.44. It
        sees CPU contention. Trust it for that.
      - `8 ms sleep overshoot` did NOT MOVE: p50 0.50 -> 0.50, p95 0.53 ->
        0.53, p99 0.57 -> 0.58. Identical to two decimals under a load that
        pinned every core.
    So the jitter probe is BLIND to root-partition CPU saturation - a thread
    waking from a timer gets a priority boost and is scheduled anyway - and a
    flat jitter reading is NOT evidence that a machine is responsive.

    It is kept, deliberately, because the load it failed to see is not the load
    under test. Those 20 burners contend inside the ROOT PARTITION, where
    Windows' own scheduler arbitrates; a WSL run contends for PHYSICAL cores
    one level down, at the hypervisor, where the root partition's threads wait
    without Windows knowing why. Those are different mechanisms and the probe
    that is blind to one may well see the other. If jitter moves during a run
    having stayed flat under 20 burners, that difference is the finding.

    `timeBeginPeriod(1)` is set ALWAYS, on purpose. Without it Windows' timer
    granularity is ~15.6 ms and every sleep overshoots by up to a full tick
    whatever the load, so the jitter probe would be blind - item 9 was bitten by
    exactly that, where Tk's `after(29)` delivered 35 ms until the same call
    fixed it. Setting it unconditionally also means the baseline and the run
    capture are taken under the same timer, which they would not be otherwise,
    since playfield.py raises the resolution when it is up.

THE MEASUREMENT IS THE DIFFERENCE, NOT THE READING. Take an idle capture with
nothing running, take one during a run, and `--compare` them. A single capture
of a busy machine says nothing about whether the rig is why, and this repo has
been bitten more than once by a metric that scored the content instead of the
defect. The idle/run pair is the labelled example: David reports sluggish
during a run and fine without one, so any probe here that cannot tell those two
captures apart is a broken probe, and should be reported as one rather than
used to declare the fault absent.
"""
import argparse
import ctypes
import json
import os
import re
import statistics
import sys
import threading
import time
from ctypes import wintypes

# ---------------------------------------------------------------------------
# PDH, by ctypes rather than by shelling out to typeperf.
#
# typeperf was the first version and it is the wrong tool here for two reasons
# that only show up once it is running: its CSV goes through a pipe that is
# block-buffered when it is not a console, so a "live" sampler arrives four
# kilobytes at a time; and a wildcard passed on its command line is expanded
# ONCE at startup, so a run's processes - which do not exist yet when the
# baseline starts - would never appear. PDH in-process has neither problem and
# is less code than parsing the CSV would have been.
# ---------------------------------------------------------------------------
PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_FMT = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
PDH_MORE_DATA = 0x800007D2

_pdh = ctypes.WinDLL("pdh")


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", PDH_FMT_COUNTERVALUE)]


for _fn, _args in (
    ("PdhOpenQueryW", [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]),
    ("PdhAddEnglishCounterW", [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_void_p)]),
    ("PdhCollectQueryData", [ctypes.c_void_p]),
    ("PdhGetFormattedCounterValue", [ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD),
                                     ctypes.POINTER(PDH_FMT_COUNTERVALUE)]),
    ("PdhGetFormattedCounterArrayW", [ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]),
    ("PdhCloseQuery", [ctypes.c_void_p]),
):
    getattr(_pdh, _fn).argtypes = _args
    # PDH_STATUS is a LONG and the interesting codes have the top bit set, so
    # read it unsigned - otherwise PDH_MORE_DATA comes back negative and the
    # "did it just want a bigger buffer" test silently never matches.
    getattr(_pdh, _fn).restype = ctypes.c_uint32


class Query:
    """One PDH query. Counters are added by ENGLISH path, so this works on a
    localised Windows where the display names differ."""

    def __init__(self):
        self.h = ctypes.c_void_p()
        st = _pdh.PdhOpenQueryW(None, None, ctypes.byref(self.h))
        if st:
            raise OSError("PdhOpenQuery failed 0x%08x" % st)
        self.counters = {}
        self.missing = []

    def add(self, name, path):
        h = ctypes.c_void_p()
        st = _pdh.PdhAddEnglishCounterW(self.h, path, None, ctypes.byref(h))
        if st:
            self.missing.append((name, path, "0x%08x" % st))
            return False
        self.counters[name] = h
        return True

    def collect(self):
        _pdh.PdhCollectQueryData(self.h)

    def value(self, name):
        if name not in self.counters:
            return None
        v = PDH_FMT_COUNTERVALUE()
        st = _pdh.PdhGetFormattedCounterValue(self.counters[name], PDH_FMT, None,
                                              ctypes.byref(v))
        return None if st else v.doubleValue

    def array(self, name):
        """Wildcard counter -> {instance: value}. The instance list is whatever
        PDH sees at THIS collect, which is what makes a process that started
        after the query did still show up."""
        if name not in self.counters:
            return {}
        h = self.counters[name]
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        st = _pdh.PdhGetFormattedCounterArrayW(h, PDH_FMT, ctypes.byref(size),
                                               ctypes.byref(count), None)
        if st != PDH_MORE_DATA:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        st = _pdh.PdhGetFormattedCounterArrayW(h, PDH_FMT, ctypes.byref(size),
                                               ctypes.byref(count), buf)
        if st:
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
        out = {}
        for i in range(count.value):
            it = items[i]
            if it.FmtValue.CStatus in (0, 1):   # VALID_DATA / NEW_DATA
                out[it.szName] = it.FmtValue.doubleValue
        return out

    def close(self):
        if self.h:
            _pdh.PdhCloseQuery(self.h)
            self.h = None


# The scalar counters, in the order they are printed. Anything absent is
# reported as missing rather than silently skipped: a counter that quietly
# disappears is how a profile grows a blind spot.
SCALARS = [
    ("hv_logical",   r"\Hyper-V Hypervisor Logical Processor(_Total)\% Total Run Time"),
    ("hv_root",      r"\Hyper-V Hypervisor Root Virtual Processor(_Total)\% Total Run Time"),
    ("cpu_root",     r"\Processor(_Total)\% Processor Time"),
    # DPC and interrupt time are here because they are the classic cause of a
    # machine that FEELS slow while every throughput number says it is idle:
    # work stolen at raised IRQL that no thread is charged for and no queue
    # length reflects. A hypervisor with a VM doing 100k context switches a
    # second and a GPU driver feeding a compositor is exactly the shape that
    # generates them, and pass one did not measure either.
    ("dpc_time",     r"\Processor(_Total)\% DPC Time"),
    ("intr_time",    r"\Processor(_Total)\% Interrupt Time"),
    # Actual clock against nominal. If a run pushes the package into a power or
    # thermal limit, EVERY single-threaded thing on the desktop gets slower at
    # once, with no queue and no starvation - which would read as "a little
    # sluggish" and would be invisible to every counter pass one had.
    ("cpu_perf",     r"\Processor Information(_Total)\% Processor Performance"),
    ("avail_mb",     r"\Memory\Available MBytes"),
    ("hard_faults",  r"\Memory\Pages Input/sec"),
    ("run_queue",    r"\System\Processor Queue Length"),
    ("ctx_switches", r"\System\Context Switches/sec"),
    # A saturated disk feels exactly like a slow machine and shows in no CPU
    # counter at all. The run reads video clips continuously (an ffmpeg per live
    # clip), writes several logs, and lives in a VHD on the system SSD, so this
    # is a real candidate and pass one did not look at it.
    ("disk_queue",   r"\PhysicalDisk(_Total)\Avg. Disk Queue Length"),
    ("disk_bytes",   r"\PhysicalDisk(_Total)\Disk Bytes/sec"),
]

# Windows-side processes that are ours or are in the rig's path, so they are
# always kept even when they are quiet. Everything else is kept only when it
# uses something.
WATCH = re.compile(r"^(vmmem|vmmemwsl|wsl|wslservice|wslrelay|wslhost|msrdc|dwm|"
                   r"python|pythonw|py|conhost|windowsterminal)", re.I)


class Probe(threading.Thread):
    """Base for the two responsiveness probes. Both are daemons so a crash in
    the main loop cannot leave them running."""
    daemon = True

    def __init__(self):
        super().__init__()
        self.samples = []
        self.stop = threading.Event()


class JitterProbe(Probe):
    """How much longer than asked an 8 ms sleep really takes. Scheduler
    latency, in milliseconds of overshoot."""
    TARGET = 0.008

    def run(self):
        while not self.stop.is_set():
            t0 = time.perf_counter()
            time.sleep(self.TARGET)
            self.samples.append((time.perf_counter() - t0 - self.TARGET) * 1000.0)


class WorkProbe(Probe):
    """A CONSTANT amount of arithmetic, timed, every 100 ms.

    The iteration count is fixed rather than calibrated at startup on purpose.
    Calibrating would measure the machine as it is right now and then normalise
    the answer against it, which is precisely what must not happen when the
    whole question is "is it slower during a run than it was before one".
    Absolute milliseconds are comparable across captures on one machine."""
    ITERS = 40000

    def run(self):
        while not self.stop.is_set():
            t0 = time.perf_counter()
            x = 1.0
            for _ in range(self.ITERS):
                x = x * 1.0000001 + 1.0
            self.samples.append((time.perf_counter() - t0) * 1000.0)
            if x < 0:           # never true; keeps the loop from being optimised away
                print(x)
            time.sleep(0.1)


class DwmProbe(Probe):
    """THE COMPOSITOR'S OWN CADENCE - the closest thing here to "does the
    desktop feel smooth", and the probe pass one was missing.

    `DwmFlush()` blocks until the desktop compositor's next present. Timing
    successive returns therefore measures how regularly DWM is actually putting
    frames on the screen, which is the thing a human perceives as smooth or
    stuttery. It needs no window, no input injection and no GPU work of its
    own, so it does not perturb what it measures.

    Why this rather than the two probes pass one had: both of those asked "can
    a thread get CPU", and the answer during a run was an emphatic yes -
    processor queue length 0.00, fixed work slightly FASTER. Neither asks "does
    a frame reach the screen on time", and a run adds an always-updating
    1360x768 RAIL window that msrdc encodes and DWM composites. If the cost is
    presentation rather than throughput, this is the probe that sees it and
    those two cannot.

    Reported as: the interval percentiles in ms, plus `late_pct`, the share of
    intervals longer than 1.5x the median. On a healthy desktop every interval
    is one refresh period and late_pct is ~0."""

    def run(self):
        try:
            dwm = ctypes.WinDLL("dwmapi")
        except OSError:
            return
        flush = dwm.DwmFlush
        flush.restype = ctypes.c_long
        # Prime once: the first call can return immediately.
        flush()
        t0 = time.perf_counter()
        while not self.stop.is_set():
            if flush() != 0:        # composition disabled, or it failed
                time.sleep(0.05)
                t0 = time.perf_counter()
                continue
            t1 = time.perf_counter()
            self.samples.append((t1 - t0) * 1000.0)
            t0 = t1


class CursorProbe(Probe):
    """POINTER STUTTER - the symptom David actually reports.

    Asked on 2026-08-06 what "sluggish" feels like, the answer was **mouse and
    typing lag**, during **a game**. Every probe before this one measured
    something else: whether a thread could get CPU (it always could), and
    whether the compositor was presenting on time (it always was). Neither can
    see the input path, and the input path is what was being complained about.

    METHOD, and why it needs no input injection. `GetCursorPos` returns the
    position Windows' input stack has settled on, so polling it at 500 Hz and
    recording the interval between consecutive CHANGES measures how smoothly
    the pointer is actually moving. A mouse reports at 125-1000 Hz and this
    display refreshes at 120 Hz, so while the user is moving, the position
    should change every few milliseconds. A gap of tens of milliseconds is a
    freeze, and a freeze is exactly what "the pointer lags" means.

    Injection was never an option anyway: SendInput into a WSLg window is
    UIPI-blocked, which items 7 and 12 both recorded the hard way. This probe
    sidesteps that entirely - it reads what the human's own hand produced.

    THE FALSE-CLEAN GUARD MATTERS MORE THAN THE METRIC. A capture where nobody
    touched the mouse would otherwise report zero stutters and look like a pass.
    So `active_s` accumulates only observed movement, and a capture with too
    little of it must be reported as NOT MEASURED rather than as clean. That is
    the same trap as a click-counter scoring a silent file as flawless.

    Intervals longer than STOP_MS are dropped as "the user stopped moving"
    rather than counted as an infinite stall. That cutoff is a judgement call:
    too low and real freezes get discarded as pauses, too high and every pause
    becomes a fake stutter. 200 ms is far above any freeze that would still
    feel like lag rather than a hang."""
    POLL_S = 0.002          # 500 Hz, comfortably finer than a 120 Hz display
    STOP_MS = 200.0         # longer than this and the hand stopped, not the PC
    FELT_MS = 25.0          # a gap this long is visible as a stutter

    def run(self):
        user32 = ctypes.WinDLL("user32")
        pt = wintypes.POINT()
        last = None
        last_change = time.perf_counter()
        self.active_s = 0.0
        while not self.stop.is_set():
            user32.GetCursorPos(ctypes.byref(pt))
            now = time.perf_counter()
            cur = (pt.x, pt.y)
            if cur != last:
                if last is not None:
                    gap = (now - last_change) * 1000.0
                    if gap <= self.STOP_MS:
                        self.samples.append(gap)
                        self.active_s += gap / 1000.0
                last = cur
                last_change = now
            time.sleep(self.POLL_S)


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def stats(vals):
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 3),
        "p50": round(pct(vals, 50), 3),
        "p95": round(pct(vals, 95), 3),
        "p99": round(pct(vals, 99), 3),
        "max": round(max(vals), 3),
    }


# GPU engine instances look like
#   pid_1828_luid_0x00000000_0x00012481_phys_0_eng_0_engtype_3d
# The LUID identifies the ADAPTER, and this machine has two: an RTX 5090 that
# drives the 4K120 desktop and an integrated AMD Radeon that drives no display.
# Mesa's d3d12 picks the AMD one by default, so the emulator renders on the iGPU
# and the result then has to cross to the NVIDIA adapter to be shown. Splitting
# GPU time by LUID is what lets an adapter A/B show the work actually MOVING
# between the two, rather than only showing that the total changed.
GPU_INST = re.compile(r"^pid_(\d+)_luid_([0-9a-fA-Fx]+_[0-9a-fA-Fx]+)_.*_engtype_(.+)$")


def capture(secs, interval, label, outdir, quiet=False):
    # timeBeginPeriod ALWAYS - see the module docstring. Without it the jitter
    # probe measures the timer tick and not the machine.
    winmm = ctypes.WinDLL("winmm")
    winmm.timeBeginPeriod(1)
    try:
        return _capture(secs, interval, label, outdir, quiet)
    finally:
        winmm.timeEndPeriod(1)


def _capture(secs, interval, label, outdir, quiet):
    q = Query()
    for name, path in SCALARS:
        q.add(name, path)
    q.add("proc_cpu", r"\Process(*)\% Processor Time")
    q.add("proc_ws", r"\Process(*)\Working Set - Private")
    q.add("proc_pid", r"\Process(*)\ID Process")
    q.add("gpu", r"\GPU Engine(*)\Utilization Percentage")
    if q.missing and not quiet:
        for name, path, st in q.missing:
            print("[winprof] counter unavailable: %s (%s) %s" % (name, path, st))

    jit = JitterProbe()
    wrk = WorkProbe()
    dwm = DwmProbe()
    cur = CursorProbe()
    jit.start()
    wrk.start()
    dwm.start()
    cur.start()

    # PDH rate counters need two collects to have a delta at all, so the first
    # one is primed and thrown away.
    q.collect()
    time.sleep(interval)

    # Stamped before the loop, for the same reason rigprof.py does: a "started"
    # field filled in when the summary is built records the FINISH time, and a
    # cross-check against an external event window is then wrong by the whole
    # capture length.
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    series = {name: [] for name, _ in SCALARS}
    procs = {}          # key -> {"name","pid","cpu":[],"ws":[]}
    gpu_total, gpu_engtype, gpu_pid, gpu_luid = [], {}, {}, {}
    rows = []
    t_end = time.time() + secs
    n = 0
    while time.time() < t_end:
        q.collect()
        row = {"t": round(time.time(), 3)}
        for name, _ in SCALARS:
            v = q.value(name)
            if v is not None:
                series[name].append(v)
                row[name] = round(v, 3)

        cpu = q.array("proc_cpu")
        ws = q.array("proc_ws")
        pids = q.array("proc_pid")
        for inst, c in cpu.items():
            if inst in ("_Total", "Idle"):
                continue
            pid = int(pids.get(inst, 0))
            base = inst.split("#")[0]
            if c < 0.5 and not WATCH.match(base):
                continue
            key = "%s/%d" % (base, pid)
            e = procs.setdefault(key, {"name": base, "pid": pid, "cpu": [], "ws": []})
            e["cpu"].append(c)
            e["ws"].append(ws.get(inst, 0.0))

        g = q.array("gpu")
        tot = 0.0
        for inst, v in g.items():
            if v <= 0.0 or inst == "_Total":
                continue
            tot += v
            m = GPU_INST.match(inst)
            if m:
                p = int(m.group(1))
                luid = m.group(2)
                eng = m.group(3)
                gpu_engtype[eng] = gpu_engtype.get(eng, 0.0) + v
                gpu_pid[p] = gpu_pid.get(p, 0.0) + v
                gpu_luid[luid] = gpu_luid.get(luid, 0.0) + v
        gpu_total.append(tot)
        row["gpu_total"] = round(tot, 3)

        rows.append(row)
        n += 1
        if not quiet and n % 10 == 0:
            hv = (series["hv_logical"][-1] - series["hv_root"][-1]
                  if series.get("hv_logical") and series.get("hv_root") else 0.0)
            # flush=True, because without it Python block-buffers stdout the
            # moment it is not a console - which is every way this gets run from
            # a script - so a 90 s capture prints NOTHING until it finishes and
            # looks exactly like a hang. David reported one as "stuck".
            print("[winprof] %3ds  wsl_vm %5.1f%%  gpu %5.1f%%  jitter p95 %5.1f ms"
                  % (n, hv, tot, pct(jit.samples[-2000:], 95) or 0.0), flush=True)
        time.sleep(max(0.0, interval - 0.05))

    jit.stop.set()
    wrk.stop.set()
    dwm.stop.set()
    cur.stop.set()
    q.close()

    # "Late" is relative to this desktop's own refresh period, taken as the
    # median interval, rather than to a hard-coded 60 Hz. The monitor's rate is
    # not ours to assume and a wrong constant would manufacture a fault.
    dwm_med = pct(dwm.samples, 50) or 0.0
    dwm_late = (100.0 * sum(1 for v in dwm.samples if v > dwm_med * 1.5)
                / len(dwm.samples)) if dwm.samples else None

    # The WSL VM's own cost, per sample, so it gets percentiles like everything
    # else rather than being derived once from two means.
    wsl_vm = [a - b for a, b in zip(series.get("hv_logical", []), series.get("hv_root", []))]

    summary = {
        "label": label,
        "secs": secs,
        "samples": len(rows),
        "started": started,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": os.environ.get("COMPUTERNAME", "?"),
        "cores": os.cpu_count(),
        "scalars": {k: stats(v) for k, v in series.items() if v},
        "wsl_vm_cpu": stats(wsl_vm),
        # cpu_mean is over the WHOLE capture, not over the samples the process
        # happened to exist for. Dividing by its own lifetime ranked a burner
        # that lived 12 s of a 24 s window at 92% - above anything that really
        # cost the machine something for the full window - which is the wrong
        # answer to "what did this window cost". `present` keeps the short-lived
        # heavy process visible instead of hiding it.
        "procs": sorted(
            [{"name": e["name"], "pid": e["pid"],
              "cpu_mean": round(sum(e["cpu"]) / max(1, len(rows)), 2),
              "cpu_when_up": round(statistics.fmean(e["cpu"]), 2),
              "present": len(e["cpu"]),
              "cpu_max": round(max(e["cpu"]), 2),
              "ws_mb_max": round(max(e["ws"]) / 1048576.0, 1)} for e in procs.values()],
            key=lambda d: -d["cpu_mean"])[:25],
        "gpu": {
            "total": stats(gpu_total),
            "by_engtype": {k: round(v / max(1, len(rows)), 2)
                           for k, v in sorted(gpu_engtype.items(), key=lambda kv: -kv[1])},
            "by_pid": sorted([{"pid": p, "mean": round(v / max(1, len(rows)), 2)}
                              for p, v in gpu_pid.items()],
                             key=lambda d: -d["mean"])[:10],
            "by_adapter": {k: round(v / max(1, len(rows)), 2)
                           for k, v in sorted(gpu_luid.items(), key=lambda kv: -kv[1])},
        },
        "resp": {"jitter_ms": stats(jit.samples), "work_ms": stats(wrk.samples),
                 "dwm_frame_ms": stats(dwm.samples),
                 "dwm_late_pct": round(dwm_late, 2) if dwm_late is not None else None,
                 "cursor_gap_ms": stats(cur.samples),
                 # Seconds of ACTUAL pointer movement seen. Without this, a
                 # capture where nobody touched the mouse reports zero stutters
                 # and reads as a pass.
                 "cursor_active_s": round(getattr(cur, "active_s", 0.0), 1),
                 "cursor_stutters": sum(1 for v in cur.samples if v > CursorProbe.FELT_MS),
                 "cursor_stutters_per_active_s": (
                     round(sum(1 for v in cur.samples if v > CursorProbe.FELT_MS)
                           / cur.active_s, 2)
                     if getattr(cur, "active_s", 0.0) > 0.5 else None)},
        "missing_counters": [m[0] for m in q.missing],
    }

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        jpath = os.path.join(outdir, "winprof_%s.json" % label)
        with open(jpath, "w") as f:
            json.dump(summary, f, indent=2)
        cpath = os.path.join(outdir, "winprof_%s.csv" % label)
        cols = ["t"] + [k for k, _ in SCALARS] + ["gpu_total"]
        with open(cpath, "w") as f:
            f.write(",".join(cols) + "\n")
            for r in rows:
                f.write(",".join(str(r.get(c, "")) for c in cols) + "\n")
        summary["_json"] = jpath
        summary["_csv"] = cpath
    return summary


# A baseline is only worth having if the machine really was quiet, and on
# 2026-08-06 one was NOT and said nothing about it: vmmemWSL sat at 79.80% and
# context switches at 121,604 through a capture labelled "idle", because a
# background agent was running `find /` inside WSL. That baseline read BUSIER
# than the emulator run it was supposed to be the control for, which would have
# inverted every conclusion drawn from it.
#
# So the capture now checks itself. The thresholds are deliberately loose - this
# is a "you are about to fool yourself" alarm, not a measurement - and it fires
# on any capture, not just ones labelled idle, because a RUN capture polluted by
# something else is just as wrong and much harder to spot.
# THE CHECK MUST COVER BOTH SIDES, and the first version did not. It watched
# only the WSL VM and the context-switch rate, so it passed a baseline cleanly
# while an orphaned `grep -rl` from a stopped subagent ran at up to 101% of a
# core on the WINDOWS side, pulling 4.4 GB/s off the disk and dragging Defender
# to 110% behind it. A quiet-check that only looks at one side of the boundary
# is the same mistake this whole item is about, reproduced inside the
# instrument that exists to catch it.
QUIET_WSL_VM_PCT = 1.0          # % of the whole machine, hv logical - hv root
QUIET_CTX_SWITCHES = 45000      # per second, against ~20k on this machine idle
QUIET_MACHINE_PCT = 12.0        # hv logical: the WHOLE machine, both partitions
QUIET_DISK_QUEUE = 0.5          # sustained queue means something is grinding
QUIET_TOP_PROC_PCT = 25.0       # any one process this busy is not "background"


def quiet_check(s):
    """Returns a list of complaints, empty if the capture looks trustworthy as
    a BASELINE. A run capture is expected to fail these, which is the point."""
    out = []
    v = _get(s, ["wsl_vm_cpu", "mean"])
    if v is not None and v > QUIET_WSL_VM_PCT:
        out.append("WSL VM was using %.2f%% of the machine (quiet is under %.1f%%)"
                   % (v, QUIET_WSL_VM_PCT))
    c = _get(s, ["scalars", "ctx_switches", "mean"])
    if c is not None and c > QUIET_CTX_SWITCHES:
        out.append("%.0f context switches/sec (quiet is under %d)"
                   % (c, QUIET_CTX_SWITCHES))
    m = _get(s, ["scalars", "hv_logical", "mean"])
    if m is not None and m > QUIET_MACHINE_PCT:
        out.append("the whole machine was %.1f%% busy (quiet is under %.0f%%)"
                   % (m, QUIET_MACHINE_PCT))
    d = _get(s, ["scalars", "disk_queue", "mean"])
    if d is not None and d > QUIET_DISK_QUEUE:
        out.append("disk queue averaged %.2f (quiet is under %.1f) - something "
                   "is grinding the disk" % (d, QUIET_DISK_QUEUE))
    # Name the culprit rather than just complaining, since the whole point is to
    # let someone go and stop it. Our own probes are never this busy.
    for p in (s.get("procs") or [])[:5]:
        if p["cpu_mean"] > QUIET_TOP_PROC_PCT:
            out.append("%s (pid %d) averaged %.1f%% of a core"
                       % (p["name"], p["pid"], p["cpu_mean"]))
    return out


def show(s):
    print()
    print("=== winprof %s === %d samples over %ds, %s, %d cores"
          % (s["label"], s["samples"], s["secs"], s.get("host", "?"), s.get("cores", 0)))
    for c in quiet_check(s):
        print("  ** NOT QUIET: %s" % c)
    v = s.get("wsl_vm_cpu")
    if v:
        print("  WSL VM CPU (hv logical - hv root) : mean %6.2f%%  p95 %6.2f%%  max %6.2f%%"
              % (v["mean"], v["p95"], v["max"]))
    # Driven off SCALARS rather than a second hand-kept list: the disk counters
    # were added to the capture and to --compare but not to this loop, so they
    # were collected, written to the JSON, and never shown. Two places defining
    # one fact is the failure this rig has a standing rule about.
    for k, _p in SCALARS:
        st = s["scalars"].get(k)
        if st:
            print("  %-33s : mean %8.2f  p95 %8.2f  max %8.2f"
                  % (k, st["mean"], st["p95"], st["max"]))
    g = s["gpu"]["total"]
    if g:
        print("  GPU utilisation (all engines)     : mean %6.2f%%  p95 %6.2f%%  max %6.2f%%"
              % (g["mean"], g["p95"], g["max"]))
    if s["gpu"]["by_engtype"]:
        print("  GPU by engine : " + "  ".join("%s=%.1f" % (k, v)
                                               for k, v in list(s["gpu"]["by_engtype"].items())[:6]))
    if s["gpu"].get("by_adapter"):
        print("  GPU by adapter (luid): "
              + "  ".join("%s=%.2f" % (k, v) for k, v in s["gpu"]["by_adapter"].items()))
    print("  --- responsiveness (Windows side) ---")
    for k, label in (("jitter_ms", "8 ms sleep overshoot"), ("work_ms", "fixed work"),
                     ("dwm_frame_ms", "DWM frame interval")):
        st = s["resp"].get(k)
        if st:
            print("  %-33s : p50 %7.2f  p95 %7.2f  p99 %7.2f  max %8.2f  (n=%d)"
                  % (label, st["p50"], st["p95"], st["p99"], st["max"], st["n"]))
    if s["resp"].get("dwm_late_pct") is not None:
        print("  %-33s : %6.2f%% of frames over 1.5x the median interval"
              % ("DWM late frames", s["resp"]["dwm_late_pct"]))
    st = s["resp"].get("cursor_gap_ms")
    act = s["resp"].get("cursor_active_s", 0.0)
    if st and act >= 5.0:
        print("  %-33s : p50 %7.2f  p95 %7.2f  p99 %7.2f  max %8.2f  (n=%d)"
              % ("pointer gap between moves", st["p50"], st["p95"], st["p99"],
                 st["max"], st["n"]))
        print("  %-33s : %d over %.0f ms, %.2f per active second, %.1f s of movement seen"
              % ("pointer stutters", s["resp"]["cursor_stutters"], CursorProbe.FELT_MS,
                 s["resp"]["cursor_stutters_per_active_s"] or 0.0, act))
    else:
        print("  %-33s : NOT MEASURED - only %.1f s of pointer movement seen."
              % ("pointer stutters", act))
        print("  %-33s   Move the mouse during the capture or this proves NOTHING."
              % "")
    print("  --- top Windows processes by CPU (mean over the WHOLE window) ---")
    for p in s["procs"][:12]:
        print("  %-24s pid %-7d cpu mean %6.2f%%  max %6.2f%%  ws %8.1f MB  seen %d/%d"
              % (p["name"], p["pid"], p["cpu_mean"], p["cpu_max"], p["ws_mb_max"],
                 p.get("present", s["samples"]), s["samples"]))
    if s.get("missing_counters"):
        print("  MISSING COUNTERS: " + ", ".join(s["missing_counters"]))


def _get(s, path, default=None):
    cur = s
    for k in path:
        if cur is None or k not in cur:
            return default
        cur = cur[k]
    return cur


def compare(a, b):
    print()
    print("=== winprof compare:  %s  ->  %s ===" % (a["label"], b["label"]))
    # The BEFORE capture is the control, so if it was not quiet the whole
    # comparison is worthless and must say so before it prints a single number.
    bad = quiet_check(a)
    if bad:
        print("  ** THE BASELINE '%s' WAS NOT QUIET - this comparison is NOT "
              "trustworthy:" % a["label"])
        for c in bad:
            print("  **   %s" % c)
    print("%-36s %12s %12s %12s" % ("", a["label"], b["label"], "delta"))

    def line(name, va, vb, fmt="%12.2f"):
        if va is None or vb is None:
            return
        print(("%-36s " + fmt + " " + fmt + " " + fmt) % (name, va, vb, vb - va))

    line("WSL VM CPU %  (mean)", _get(a, ["wsl_vm_cpu", "mean"]), _get(b, ["wsl_vm_cpu", "mean"]))
    line("WSL VM CPU %  (p95)", _get(a, ["wsl_vm_cpu", "p95"]), _get(b, ["wsl_vm_cpu", "p95"]))
    for k, _p in SCALARS:
        line(k + " (mean)", _get(a, ["scalars", k, "mean"]), _get(b, ["scalars", k, "mean"]))
    line("GPU % (mean)", _get(a, ["gpu", "total", "mean"]), _get(b, ["gpu", "total", "mean"]))
    line("GPU % (p95)", _get(a, ["gpu", "total", "p95"]), _get(b, ["gpu", "total", "p95"]))
    # Per adapter, because the adapter A/B's whole question is whether the work
    # MOVED rather than whether the total changed.
    la = _get(a, ["gpu", "by_adapter"], {}) or {}
    lb = _get(b, ["gpu", "by_adapter"], {}) or {}
    for k in sorted(set(la) | set(lb)):
        line("GPU adapter " + k, la.get(k, 0.0), lb.get(k, 0.0))
    print("  --- responsiveness, which is the answer to \"does it feel slow\" ---")
    for k, nm in (("jitter_ms", "sleep overshoot ms"), ("work_ms", "fixed work ms"),
                  ("dwm_frame_ms", "DWM frame ms"), ("cursor_gap_ms", "pointer gap ms")):
        for p in ("p50", "p95", "p99", "max"):
            line("%s %s" % (nm, p), _get(a, ["resp", k, p]), _get(b, ["resp", k, p]))
    line("DWM late frames %", _get(a, ["resp", "dwm_late_pct"]), _get(b, ["resp", "dwm_late_pct"]))
    line("pointer stutters / active s",
         _get(a, ["resp", "cursor_stutters_per_active_s"]),
         _get(b, ["resp", "cursor_stutters_per_active_s"]))
    # The pointer numbers are only worth anything if the hand was moving in
    # BOTH captures, so say how much movement each one actually saw rather than
    # letting a still mouse read as a clean result.
    aa = _get(a, ["resp", "cursor_active_s"], 0.0) or 0.0
    ab = _get(b, ["resp", "cursor_active_s"], 0.0) or 0.0
    print("  pointer movement observed: %s %.1f s, %s %.1f s%s"
          % (a["label"], aa, b["label"], ab,
             "   ** TOO LITTLE TO COMPARE **" if min(aa, ab) < 5.0 else ""))

    # Named largest consumer, which the queue item asks for by name.
    pa = {p["name"]: p["cpu_mean"] for p in a["procs"]}
    print("  --- Windows processes that grew most ---")
    grew = sorted(b["procs"], key=lambda p: -(p["cpu_mean"] - pa.get(p["name"], 0.0)))
    for p in grew[:10]:
        before = pa.get(p["name"], 0.0)
        print("  %-24s pid %-7d %6.2f%% -> %6.2f%%   (%+6.2f)  ws %8.1f MB"
              % (p["name"], p["pid"], before, p["cpu_mean"], p["cpu_mean"] - before,
                 p["ws_mb_max"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secs", type=int, default=60, help="how long to sample")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between samples")
    ap.add_argument("--label", default="cap", help="names the output files")
    ap.add_argument("--out", default=None, help="directory for the .json/.csv (default: cwd)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE.json", "AFTER.json"),
                    help="print the delta between two captures and exit")
    a = ap.parse_args()

    if a.compare:
        with open(a.compare[0]) as f:
            before = json.load(f)
        with open(a.compare[1]) as f:
            after = json.load(f)
        compare(before, after)
        return 0

    if sys.platform != "win32":
        print("winprof.py must run on WINDOWS (py -3 winprof.py). Measuring the "
              "Windows side from inside WSL is the mistake it exists to prevent.",
              file=sys.stderr)
        return 2

    s = capture(a.secs, a.interval, a.label, a.out or os.getcwd(), a.quiet)
    show(s)
    if s.get("_json"):
        print("\n  wrote %s" % s["_json"])
        print("  wrote %s" % s["_csv"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
