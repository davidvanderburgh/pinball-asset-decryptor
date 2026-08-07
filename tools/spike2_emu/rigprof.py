#!/usr/bin/env python3
"""rigprof.py - the WSL side of winprof.py. Per-process CPU and RSS, sampled.

    wsl -e python3 <rig>/rigprof.py --secs 90 --label attract --out ~

RUN IT INSIDE WSL. It is the twin of `winprof.py`, which runs on Windows; item
18 needs both sides of the boundary in the same window, because a slowdown that
is only visible on one side of it is the whole question.

WHY NOT JUST `ps`. The numbers this rig has quoted for the guest - "guest 20.8%,
padglhost 9.8%" - come from `ps -o %cpu`, and that column is a LIFETIME AVERAGE:
total CPU divided by how long the process has been alive. For a guest that
spends its first 15 seconds booting and then settles, a lifetime average is a
blend of two different machines and is not the number anyone wanted. Everything
here is a DELTA between two samples, so it is what the process was doing during
the window and nothing else.

Sampling is deliberately cheap - /proc reads only, no subprocesses - because a
profiler that costs 5% of what it is measuring is measuring itself.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time

HZ = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

# The rig's own processes, kept even when they are quiet so their absence is
# visible. This is the same list alive.sh counts - see the non-negotiable in
# plans/TODO.md about never letting two scripts define the same fact: this one
# is for LABELLING a sample, not for deciding whether the rig is clean, and it
# must never be used for the latter.
RIG = re.compile(r"padglhost|arm-binfmt|nodebus\.py|padvidhost\.py|playaudio\.sh|"
                 r"padrelay\.py|watch\.sh|autoattract\.sh|fuse2fs|playfield\.py|"
                 r"longplay\.sh|ffmpeg|qemu")


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def cpu_total():
    """Jiffies of all CPUs from /proc/stat, so a process's share of the WHOLE
    VM can be stated as well as its share of one core."""
    line = read("/proc/stat").split("\n", 1)[0]
    parts = [int(x) for x in line.split()[1:]]
    return sum(parts)


def snap():
    """{pid: (name, jiffies, rss_bytes)} for everything readable."""
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        st = read("/proc/%s/stat" % pid)
        if not st:
            continue
        # comm can contain spaces and brackets, so split on the LAST ')'.
        try:
            rp = st.rindex(")")
        except ValueError:
            continue
        comm = st[st.index("(") + 1:rp]
        f = st[rp + 2:].split()
        if len(f) < 22:
            continue
        utime, stime = int(f[11]), int(f[12])
        rss_pages = int(f[21])
        cmd = read("/proc/%s/cmdline" % pid).replace("\0", " ").strip()
        name = comm
        if cmd:
            # A shell script's comm is "bash"; its identity is in argv.
            m = RIG.search(cmd)
            if m and comm in ("bash", "sh", "python3", "init"):
                name = "%s[%s]" % (comm, os.path.basename(m.group(0)))
        out[int(pid)] = (name, utime + stime, rss_pages * PAGE, cmd)
    return out


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def stats(vals):
    if not vals:
        return None
    return {"n": len(vals), "mean": round(statistics.fmean(vals), 2),
            "p50": round(pct(vals, 50), 2), "p95": round(pct(vals, 95), 2),
            "max": round(max(vals), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=90)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--label", default="cap")
    ap.add_argument("--out", default=os.path.expanduser("~"))
    a = ap.parse_args()

    if not os.path.isdir("/proc/1"):
        print("rigprof.py: /proc is not readable - this is not a Linux shell.\n"
              "  Run it inside WSL: wsl -e python3 %s" % sys.argv[0], file=sys.stderr)
        return 2

    ncpu = os.cpu_count() or 1
    # Stamped HERE, not in the summary dict below. The first version built the
    # summary after the loop and called the field "started", so it recorded the
    # time the capture FINISHED - and a cross-check against a Defender scan
    # window was read off it and came out 70 s wrong in the direction that
    # mattered. A field whose name and value disagree is worse than no field.
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    procs = {}          # pid -> {"name","cpu":[],"rss":[]}
    load, availmb = [], []
    prev = snap()
    prev_tot = cpu_total()
    t_end = time.time() + a.secs
    n = 0
    while time.time() < t_end:
        time.sleep(a.interval)
        cur = snap()
        tot = cpu_total()
        dtot = max(1, tot - prev_tot)
        for pid, (name, jif, rss, cmd) in cur.items():
            if pid not in prev:
                continue
            djif = jif - prev[pid][1]
            # Percent of ONE core, which is how ps and top state it and how
            # this rig's existing numbers were quoted.
            core_pct = 100.0 * djif / dtot * ncpu
            if core_pct < 1.0 and not RIG.search(cmd or name):
                continue
            key = "%s/%d" % (name, pid)
            e = procs.setdefault(key, {"name": name, "pid": pid, "cpu": [], "rss": []})
            e["cpu"].append(core_pct)
            e["rss"].append(rss)
        load.append(float(read("/proc/loadavg", "0 0 0").split()[0]))
        m = re.search(r"MemAvailable:\s+(\d+) kB", read("/proc/meminfo"))
        if m:
            availmb.append(int(m.group(1)) / 1024.0)
        prev, prev_tot = cur, tot
        n += 1
        if n % 15 == 0:
            top = max(procs.values(), key=lambda e: e["cpu"][-1] if e["cpu"] else 0,
                      default=None)
            print("[rigprof] %3ds  load %.2f  top %s %.1f%%"
                  % (n, load[-1], top["name"] if top else "-",
                     top["cpu"][-1] if top and top["cpu"] else 0.0), flush=True)

    rows = sorted(
        [{"name": e["name"], "pid": e["pid"],
          "cpu_mean": round(sum(e["cpu"]) / max(1, n), 2),
          "cpu_max": round(max(e["cpu"]), 2),
          "present": len(e["cpu"]),
          "rss_mb_max": round(max(e["rss"]) / 1048576.0, 1)} for e in procs.values()],
        key=lambda d: -d["cpu_mean"])

    summary = {"label": a.label, "secs": a.secs, "samples": n, "cores": ncpu,
               "started": started, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
               "loadavg": stats(load), "avail_mb": stats(availmb),
               "total_rig_cpu": round(sum(r["cpu_mean"] for r in rows), 2),
               "procs": rows[:25]}

    path = os.path.join(a.out, "rigprof_%s.json" % a.label)
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=== rigprof %s === %d samples over %ds, %d cores in the VM"
          % (a.label, n, a.secs, ncpu))
    if summary["loadavg"]:
        print("  loadavg  mean %5.2f  p95 %5.2f  max %5.2f"
              % (summary["loadavg"]["mean"], summary["loadavg"]["p95"],
                 summary["loadavg"]["max"]))
    if summary["avail_mb"]:
        print("  MemAvailable MB  mean %8.0f  min-ish p50 %8.0f"
              % (summary["avail_mb"]["mean"], summary["avail_mb"]["p50"]))
    print("  --- per process, % of ONE core, delta-based, mean over the WHOLE window ---")
    for r in rows[:15]:
        print("  %-28s pid %-8d cpu mean %6.2f%%  max %6.2f%%  rss %8.1f MB  seen %d/%d"
              % (r["name"], r["pid"], r["cpu_mean"], r["cpu_max"], r["rss_mb_max"],
                 r["present"], n))
    print("  sum of the above: %.2f%% of one core" % summary["total_rig_cpu"])
    print("  wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
