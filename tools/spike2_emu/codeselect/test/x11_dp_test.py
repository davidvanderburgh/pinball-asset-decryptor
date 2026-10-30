#!/usr/bin/env python3
"""x11_dp_test.py DPSELECT WORKDIR [FONT] - the Dutch Pinball menu (PAD-853) on an X server.

A private Xvfb, the menu drawing on it through x11_raw.c (no libX11), buttons as dpprocsw's
lines on its standard input (--input pipe):

  1. a 1366x768 screen: connected, the canvas 1:1, no X error; RIGHT then START boots
     image 1; the window really shows the menu (ffmpeg's x11grab, when there is one:
     the highlighted card's yellow frame is on the right card after RIGHT)
  2. a 1366x512 screen (the rig's TBL window size): the canvas is scaled to fit
  3. the pipe ends at once (no board library): no buttons, the countdown boots the default
  4. DISPLAY names nothing: the menu falls back to the framebuffer (none here) and gives up
     without hanging
"""
import os
import shutil
import subprocess
import sys
import time

BIN, WORK = sys.argv[1], sys.argv[2]
FONT = sys.argv[3] if len(sys.argv) > 3 else ""
FAILS = []
os.makedirs(WORK, exist_ok=True)
CONF = os.path.join(WORK, "dp_images.conf")
with open(CONF, "w") as f:
    f.write("image=1.13|THE BIG LEBOWSKI|Stock 1.13\nimage=9.01|THE BIG LEBOWSKI|My own build\n"
            "default=0\ntimeout=20\n")


def ok(msg):
    print("ok " + msg)


def bad(msg, log=None):
    print("FAIL " + msg)
    if log and os.path.exists(log):
        print(open(log).read())
    FAILS.append(msg)


def xvfb(num, size):
    p = subprocess.Popen(["Xvfb", ":%d" % num, "-screen", "0", size + "x24", "-noreset",
                          "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    return p


def menu(name, num, extra=(), env_extra=None):
    out = os.path.join(WORK, name + ".choice")
    log = os.path.join(WORK, name + ".log")
    for f in (out, log, os.path.join(WORK, name + ".last")):
        if os.path.exists(f):
            os.remove(f)
    env = dict(os.environ, DISPLAY=":%d" % num, HOME=WORK)
    env.pop("XAUTHORITY", None)
    env.update(env_extra or {})
    args = [BIN, "--input", "pipe", "--conf", CONF, "--out", out, "--last",
            os.path.join(WORK, name + ".last"), "--log", log, "--audio", "none"]
    if FONT:
        args += ["--font", FONT]
    p = subprocess.Popen(args + list(extra), stdin=subprocess.PIPE, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p, out, log


def grab(num, size, path):
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", size,
                        "-i", ":%d+0,0" % num, "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", path], capture_output=True)
    return r.returncode == 0


def yellow_at(path, w, x, y):
    with open(path, "rb") as f:
        f.seek((y * w + x) * 3)
        r, g, b = f.read(3)
    return r > 200 and g > 150 and b < 100


def read(path):
    try:
        return open(path).read()
    except OSError:
        return ""


NUM = 160 + os.getpid() % 30
# 1
x = xvfb(NUM, "1366x768")
try:
    p, out, log = menu("one", NUM)
    p.stdin.write(b"ready\nsw L 0\nsw R 0\nsw S 0\n")
    p.stdin.flush()
    time.sleep(1.0)
    p.stdin.write(b"sw R 1\n")
    p.stdin.flush()
    time.sleep(0.3)
    p.stdin.write(b"sw R 0\n")
    p.stdin.flush()
    time.sleep(0.6)
    raw = os.path.join(WORK, "one.rgb")
    grabbed = grab(NUM, "1366x768", raw)
    p.stdin.write(b"sw S 1\n")
    p.stdin.flush()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
    text = read(log)
    # card frames: the left card's edge at x=66, the right card's at x=704 (1:1 at 3,0)
    shown = (not grabbed) or (yellow_at(raw, 1366, 705, 370) and not yellow_at(raw, 1366, 67, 370))
    if (read(out).strip() == "1" and "x11: screen 1366x768" in text and "1:1 at 3,0" in text
            and "key: right" in text and "key: start" in text and "x11: error" not in text
            and "pipe: ready" in text and shown):
        ok("1 1366x768: drawn through the X protocol, RIGHT + START boot image 1%s"
           % (" (x11grab: the right card is highlighted)" if grabbed else " (no ffmpeg: picture not read)"))
    else:
        bad("1 1366x768 (choice %r, picture %s)" % (read(out), shown), log)
finally:
    x.terminate()
    x.wait()

# 2
x = xvfb(NUM, "1366x512")
try:
    p, out, log = menu("small", NUM, ["--timeout", "1"])
    p.stdin.write(b"ready\n")
    p.stdin.flush()
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()
    text = read(log)
    if "x11: screen 1366x512" in text and "scaled" in text and read(out).strip() == "0":
        ok("2 1366x512: the canvas scaled to fit, the countdown boots image 0")
    else:
        bad("2 1366x512", log)
finally:
    x.terminate()
    x.wait()

# 3
x = xvfb(NUM, "1366x768")
try:
    p, out, log = menu("ended", NUM, ["--timeout", "1"])
    p.stdin.close()
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()
    text = read(log)
    if "pipe ended" in text and read(out).strip() == "0":
        ok("3 the button pipe ends at once: no buttons, the countdown boots image 0")
    else:
        bad("3 pipe ended", log)
finally:
    x.terminate()
    x.wait()

# 4
p, out, log = menu("nodisplay", NUM + 1, ["--timeout", "1"],
                   {"PAD_SELECT_FB": os.path.join(WORK, "no-such-fb")})
p.stdin.close()
try:
    rc = p.wait(30)
except subprocess.TimeoutExpired:
    p.kill()
    rc = None
text = read(log)
if rc is not None and "cannot connect to display" in text and "cannot open" in text:
    ok("4 no X server and no framebuffer: gives up in time (exit %d)" % rc)
else:
    bad("4 no display (exit %r)" % rc, log)

print("x11_dp_test: %s" % ("OK" if not FAILS else "%d FAILED" % len(FAILS)))
sys.exit(1 if FAILS else 0)
