# threadwatch2.py <pid> [secs] - per-thread utime+wchan at 2Hz, robust to
# transient tids. Joined against press timestamps, the thread whose CPU
# freezes during deaf stretches is the starved recorder-service thread.
import os
import sys
import time

PID = int(sys.argv[1])
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 200.0
t_end = time.time() + SECS
while time.time() < t_end:
    now = int(time.time() * 1000)
    parts = []
    try:
        tids = sorted(os.listdir(f"/proc/{PID}/task"), key=int)
    except OSError:
        print(f"{now} guest gone", flush=True)
        break
    for tid in tids:
        try:
            with open(f"/proc/{PID}/task/{tid}/stat") as f:
                st = f.read().rsplit(") ", 1)[1].split()
            try:
                wchan = open(f"/proc/{PID}/task/{tid}/wchan").read().strip()
            except OSError:
                wchan = "?"
            parts.append(f"{tid}:{st[11]}:{wchan[:18]}")
        except (OSError, IndexError):
            continue
    print(f"{now} {' '.join(parts)}", flush=True)
    time.sleep(0.5)
print("done", flush=True)
