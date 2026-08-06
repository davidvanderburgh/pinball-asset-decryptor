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
    ("avail_mb",     r"\Memory\Available MBytes"),
    ("hard_faults",  r"\Memory\Pages Input/sec"),
    ("run_queue",    r"\System\Processor Queue Length"),
    ("ctx_switches", r"\System\Context Switches/sec"),
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


GPU_INST = re.compile(r"^pid_(\d+)_.*_engtype_(.+)$")


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
    jit.start()
    wrk.start()

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
    gpu_total, gpu_engtype, gpu_pid = [], {}, {}
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
                eng = m.group(2)
                gpu_engtype[eng] = gpu_engtype.get(eng, 0.0) + v
                gpu_pid[p] = gpu_pid.get(p, 0.0) + v
        gpu_total.append(tot)
        row["gpu_total"] = round(tot, 3)

        rows.append(row)
        n += 1
        if not quiet and n % 10 == 0:
            hv = (series["hv_logical"][-1] - series["hv_root"][-1]
                  if series.get("hv_logical") and series.get("hv_root") else 0.0)
            print("[winprof] %3ds  wsl_vm %5.1f%%  gpu %5.1f%%  jitter p95 %5.1f ms"
                  % (n, hv, tot, pct(jit.samples[-2000:], 95) or 0.0))
        time.sleep(max(0.0, interval - 0.05))

    jit.stop.set()
    wrk.stop.set()
    q.close()

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
        },
        "resp": {"jitter_ms": stats(jit.samples), "work_ms": stats(wrk.samples)},
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


def show(s):
    print()
    print("=== winprof %s === %d samples over %ds, %s, %d cores"
          % (s["label"], s["samples"], s["secs"], s.get("host", "?"), s.get("cores", 0)))
    v = s.get("wsl_vm_cpu")
    if v:
        print("  WSL VM CPU (hv logical - hv root) : mean %6.2f%%  p95 %6.2f%%  max %6.2f%%"
              % (v["mean"], v["p95"], v["max"]))
    for k in ("hv_logical", "hv_root", "cpu_root", "avail_mb", "hard_faults",
              "run_queue", "ctx_switches"):
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
    print("  --- responsiveness (Windows side) ---")
    for k, label in (("jitter_ms", "8 ms sleep overshoot"), ("work_ms", "fixed work")):
        st = s["resp"].get(k)
        if st:
            print("  %-33s : p50 %7.2f  p95 %7.2f  p99 %7.2f  max %8.2f  (n=%d)"
                  % (label, st["p50"], st["p95"], st["p99"], st["max"], st["n"]))
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
    print("%-36s %12s %12s %12s" % ("", a["label"], b["label"], "delta"))

    def line(name, va, vb, fmt="%12.2f"):
        if va is None or vb is None:
            return
        print(("%-36s " + fmt + " " + fmt + " " + fmt) % (name, va, vb, vb - va))

    line("WSL VM CPU %  (mean)", _get(a, ["wsl_vm_cpu", "mean"]), _get(b, ["wsl_vm_cpu", "mean"]))
    line("WSL VM CPU %  (p95)", _get(a, ["wsl_vm_cpu", "p95"]), _get(b, ["wsl_vm_cpu", "p95"]))
    for k in ("hv_logical", "hv_root", "cpu_root", "avail_mb", "hard_faults",
              "run_queue", "ctx_switches"):
        line(k + " (mean)", _get(a, ["scalars", k, "mean"]), _get(b, ["scalars", k, "mean"]))
    line("GPU % (mean)", _get(a, ["gpu", "total", "mean"]), _get(b, ["gpu", "total", "mean"]))
    line("GPU % (p95)", _get(a, ["gpu", "total", "p95"]), _get(b, ["gpu", "total", "p95"]))
    print("  --- responsiveness, which is the answer to \"does it feel slow\" ---")
    for k, nm in (("jitter_ms", "sleep overshoot ms"), ("work_ms", "fixed work ms")):
        for p in ("p50", "p95", "p99", "max"):
            line("%s %s" % (nm, p), _get(a, ["resp", k, p]), _get(b, ["resp", k, p]))

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
