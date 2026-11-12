r"""PAD-1198 proof: the playfield window's X asks the app to stop the run; a
window that closes because the run ended does not.

    python scripts/proof_pad1198_close.py <tree>

Runs scripts/playfield_demo.py from <tree> with a REAL window (pfweb's own
ladder, as a run opens it), handed a volume file as the app hands it
(PAD_AUDIO_CTL, rig 2), twice:

  x     - the window is sent WM_CLOSE (what its X does): stop_emulator_2.req
          must appear beside the volume file.
  gone  - the demo's run vanishes (its dump/ folder goes, so the LED block
          does): the window closes itself, and no request may appear.
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import tempfile
import time

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010


def windows_titled(part):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        n = user32.GetWindowTextLengthW(h)
        if n and user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            if part in buf.value:
                found.append((h, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return found


def one(tree, how):
    scratch = tempfile.mkdtemp(prefix="pad1198close-")
    ctl = os.path.join(scratch, "audio_ctl.json")
    with open(ctl, "w", encoding="utf-8") as f:
        f.write('{"gain": 0.0, "muted": true}')
    req = os.path.join(scratch, "stop_emulator_2.req")
    env = dict(os.environ, PAD_AUDIO_CTL=ctl, PAD_SLOT="2", PAD_LABEL="PAD-1198")
    log = os.path.join(scratch, "pf.log")
    demo = subprocess.Popen(
        [sys.executable, os.path.join(tree, "scripts", "playfield_demo.py"),
         "field", "--seconds", "90"],
        stdout=open(log, "w", encoding="utf-8"), stderr=subprocess.STDOUT, env=env)
    try:
        root = win = None
        for _ in range(240):
            txt = open(log, encoding="utf-8", errors="replace").read()
            for ln in txt.splitlines():
                if ln.startswith("demo root:"):
                    root = ln.split(":", 1)[1].strip()
            got = windows_titled("demo_pf - virtual playfield")
            if root and got and "pfweb: window up" in txt:
                win = got[0]
                break
            time.sleep(0.25)
        if not win:
            return "%s: the window never came up:\n%s" % (how, txt)
        time.sleep(3)                       # let the page and its run settle
        t0 = time.time()
        if how == "x":
            user32.PostMessageW(win[0], WM_CLOSE, 0, 0)
        else:
            dump = os.path.join(root, "root", "dump")
            for _ in range(40):
                try:
                    os.rename(dump, dump + ".gone")
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                return "gone: could not take the run's dump folder away"
        try:
            demo.wait(timeout=30)
            left = "the window process left after %.1f s (rc %s)" % (
                time.time() - t0, demo.returncode)
        except subprocess.TimeoutExpired:
            left = "the window process was STILL UP 30 s later"
        still = windows_titled("demo_pf - virtual playfield")
        said = [ln for ln in open(log, encoding="utf-8", errors="replace")
                .read().splitlines() if "asked the app to stop" in ln]
        body = open(req, encoding="utf-8").read().strip() \
            if os.path.isfile(req) else None
        return ("%s: window %r; %s; window still on screen: %s; "
                "stop request for the app: %s; log: %s"
                % (how, win[1], left, bool(still),
                   ("WRITTEN (rig %s)" % body) if body is not None else "none",
                   said or "-"))
    finally:
        if demo.poll() is None:
            demo.kill()


def main():
    tree = os.path.abspath(sys.argv[1])
    for how in ("x", "gone"):
        print(one(tree, how), flush=True)


if __name__ == "__main__":
    main()
