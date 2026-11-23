#!/usr/bin/env python3
"""Headless JJP proof driver (PAD-1508): the switch matrix's ball feeder without its window, plus
a scripted list of steps.  Run as root in WSL beside a hidden JJP run (PAD_HIDDEN=1 watch.sh).
    jjpdrive.py <steps file>
A game needs credits (Wonka is not on free play) and the game in attract first: wait for
"game state 2 -> 4", give it a while, then coin up and press Start, holding each press 0.3 s.
Steps, one a line:  press <switch>  |  sleep <s>  |  wait <regex> [timeout s]  |  plunge  |  drain  |  note <text>
  |  hold <switch>[,<switch>...] <s> (PAD-1512: held together, e.g. both flipper buttons)
  |  shot <png> (the game's screen, grab.sh)
`wait` reads the runtime log (/var/tmp/jjp_run/jjpe/temp/jjpmodes.log by default)."""
import heapq, json, os, re, sys, time  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jjpsw, jjpball  # noqa: E402

LOG = os.environ.get("JJP_MODS_LOGFILE", "/var/tmp/jjp_run/jjpe/temp/jjpmodes.log")
devices = json.load(open(os.environ.get("JJP_DEVICES_JSON", "/var/tmp/jjp_devices.json")))
shm = jjpsw.SwitchShm(jjpsw.DEFAULT_SHM)
switches = {}
for s in devices.get("switches", []):
    fb, mask = s.get("frame_byte"), s.get("frame_bit")
    if fb is None or not mask or fb >= jjpsw.FRAME_LEN:
        continue
    switches.setdefault((fb, mask), s)
shm.inverted = {k for k, s in switches.items() if s.get("inverted") and not jjpsw.direct_byte(k[0])}
q = []
seq = [0]


def after(ms, fn):
    seq[0] += 1
    heapq.heappush(q, (time.monotonic() + ms / 1000.0, seq[0], fn))


def out(msg):
    print("%8.2f %s" % (time.monotonic() - T0, msg), flush=True)


T0 = time.monotonic()
feeder = jjpball.Feeder(shm, switches, devices.get("coils") or [], after=after,
                        log=lambda m: out("ball: " + m), now=time.monotonic, board=jjpsw.BOARD_IO)
for line in feeder.describe():
    out("ball: " + line)
for key in feeder.seat_trough():
    pass
out("ball: trough seated")


def pump(secs):
    end = time.monotonic() + secs
    while True:
        now = time.monotonic()
        while q and q[0][0] <= now:
            heapq.heappop(q)[2]()
        feeder.poll()
        if now >= end:
            return
        time.sleep(0.01)


def by_name(n):
    for k, s in switches.items():
        if s.get("symbol", "").lower() == n.lower():
            return k
    raise SystemExit("no switch %s" % n)


def log_text():
    try:
        return open(LOG, errors="replace").read()
    except OSError:
        return ""


rc = 0
for raw in open(sys.argv[1]):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    w = line.split(None, 1)
    op, arg = w[0], (w[1] if len(w) > 1 else "")
    if op == "press":
        k = by_name(arg)
        shm.set_switch(k[0], k[1], True); pump(0.3); shm.set_switch(k[0], k[1], False); pump(0.7)
        out("pressed " + arg)
    elif op == "hold":                 # PAD-1512: switches held down together for a while
        names, secs = arg.rsplit(None, 1)
        ks = [by_name(n) for n in names.split(",")]
        for k in ks:
            shm.set_switch(k[0], k[1], True)
        pump(float(secs))
        for k in ks:
            shm.set_switch(k[0], k[1], False)
        pump(0.5)
        out("held %s for %s s" % (names, secs))
    elif op == "shot":                 # PAD-1512: the game's screen now (grab.sh)
        import subprocess
        r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.abspath(__file__)), "grab.sh"), arg],
                           capture_output=True, text=True)
        out("shot %s: %s" % (arg, "ok" if r.returncode == 0 else (r.stderr or r.stdout).strip()[-200:]))
    elif op == "sleep":
        pump(float(arg))
    elif op == "plunge":
        out("plunge: %s" % feeder.plunge()); pump(0.5)
    elif op == "drain":
        out("drain: %s" % feeder.drain()); pump(0.5)
    elif op == "note":
        out("== " + arg)
    elif op == "wait":
        parts = arg.rsplit(None, 1)
        pat, tmo = (parts[0], float(parts[1])) if len(parts) == 2 and re.match(r"^\d+(\.\d+)?$", parts[1]) else (arg, 60.0)
        start_len = 0
        end = time.monotonic() + tmo
        while time.monotonic() < end and not re.search(pat, log_text()):
            pump(0.25)
        ok = bool(re.search(pat, log_text()))
        out("wait %r: %s" % (pat, "ok" if ok else "TIMED OUT"))
        if not ok:
            rc = 1
            break
print("driver done rc=%d" % rc)
sys.exit(rc)
