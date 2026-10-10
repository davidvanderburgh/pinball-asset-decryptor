"""PAD-505 proof: Emulate's Start converting a whole game's pictures on a busy PC.

    python scripts/shot_pad505.py <repo> <out_dir> <prefix> [line_ms] [first|busy|second]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  A scratch Godzilla project gets every one of the game's own pictures
(Desktop\\gzho's images: 5,813, the scale DragonRR converts), each switched on under the
Images tab's Advanced box with the Black and white files profile, and "Apply my replaced
assets" ticked.  Start is pressed with the rig stood in (PAD_UI_NO_RIG: nothing reaches
WSL, no game is started).

THE BUSY PC IS STOOD IN TOO: every log line the app writes to its session log takes
<line_ms> more (default 8 ms).  DragonRR's own log pane stamped the picture lines 44 to
368 a second while his PC was busy (3 to 23 ms a line); this PC writes one in 0.4 ms and
never falls behind, so without the stand-in nothing here would lock.

  <prefix>_emulate_converting.png   ~30 s into the pictures: the State line, the footer's
                                    bar and the log pane together
  stdout                            what the State line said each second, the log's newest
                                    picture beside it, and how long a click (a cheap call
                                    on the app's loop) took to answer while it converted

Round 2 (DragonRR on v1.169.2: "still hanging staging files"), with [line_ms] 0:
  busy    Edge's CPU throttled 6x (a busy PC's browser): <prefix>_emulate_busy_page.png
          35 s in, and each second the State line the PAGE shows beside the server's and
          the page's worst stall.
  second  a first Start converts every picture and is cancelled past them; 3 s into a
          second Start, <prefix>_emulate_second_start.png.

Pictures are converted for real, in the scratch folder only; the server's TEMP is the
scratch folder too (the override build writes %TEMP%\\spike2_overrides).
"""

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

GZHO = r"C:\Users\david\OneDrive\Desktop\gzho"
# the card gzho was extracted from (round 1's shots ran the Pro card, which has none of
# its scene pictures: past the pictures that Start ends on "Nothing could be written")
CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"

LAUNCHER = r'''
import sys, time
sys.path.insert(0, @REPO@)
# the rig stood in: Start goes as far as the preparation and no further
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
from pinball_decryptor.core import rigslot
rigslot.claim_for_run = lambda *a, **k: 1
# the busy PC stood in: each session-log line costs what it cost DragonRR's
from pinball_decryptor.core import session_log
_append = session_log.append
def _slow(*a, **k):
    time.sleep(@SLEEP@)
    return _append(*a, **k)
session_log.append = _slow
import os
if os.environ.get("PAD505_TRACE"):
    # where the time goes: progress reported, the State painted, a drain's length
    _tf = open(os.environ["PAD505_TRACE"], "a", buffering=1)
    from pinball_decryptor.webui.tabs import emulate as _em
    from pinball_decryptor import app as _app
    _show, _paint, _poll = (_em.EmulateTab._show_preparing,
                            _em.EmulateTab._paint_preparing_due, _app.App._poll_queue)
    def _t_show(self, text, pct):
        print("%.3f show %s" % (time.monotonic(), text), file=_tf)
        return _show(self, text, pct)
    def _t_paint(self):
        print("%.3f paint %s" % (time.monotonic(), self._preparing), file=_tf)
        return _paint(self)
    def _t_poll(self):
        t = time.monotonic()
        n = self.msg_queue.qsize()
        r = _poll(self)
        print("%.3f poll %.3f s, queue was %d, now %d"
              % (t, time.monotonic() - t, n, self.msg_queue.qsize()), file=_tf)
        return r
    from pinball_decryptor.webui import loop as _lp, window as _win
    _pump, _dis = _lp.UiLoop.pump_until, _win.WebWindow.dismiss_toast
    def _t_pump(self, event, timeout=None):
        print("%.3f pump in (depth %d)" % (time.monotonic(), self._depth), file=_tf)
        try:
            return _pump(self, event, timeout)
        finally:
            print("%.3f pump out" % time.monotonic(), file=_tf)
    import functools
    @functools.wraps(_dis)
    def _t_dis(self, tid):
        import threading as _th
        print("%.3f click on %s" % (time.monotonic(), _th.current_thread().name), file=_tf)
        return _dis(self, tid)
    _lp.UiLoop.pump_until = _t_pump
    _win.WebWindow.dismiss_toast = _t_dis
    _em.EmulateTab._show_preparing = _t_show
    _em.EmulateTab._paint_preparing_due = _t_paint
    _app.App._poll_queue = _t_poll
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def make_project(repo, scratch):
    sys.path.insert(0, repo)
    from pinball_decryptor.core import colour_profile as cp
    from pinball_decryptor.core import staged_changes
    proj = os.path.join(scratch, "Godzilla Extract")
    os.makedirs(proj)
    shutil.copytree(os.path.join(GZHO, "images"), os.path.join(proj, "images"))
    sums, pics = [], {}
    with open(os.path.join(GZHO, ".checksums.md5"), encoding="utf-8") as f:
        for ln in f:
            rel = ln.split("\t")[0]
            if rel.startswith("images/") and os.path.isfile(
                    os.path.join(proj, *rel.split("/"))):
                sums.append(ln)
                if rel.lower().endswith(".png"):
                    pics[rel] = True
    with open(os.path.join(proj, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(sums)
    with open(os.path.join(proj, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "card_version": "1.16"}, f)
    staged_changes.save(proj, {"image_color_unlocked": True,
                               "image_color_slots": pics})
    cp.store_asset_profile(proj, dict(cp.PRESETS)["bw"])
    return proj, len(pics)


def _click_ms(url):
    """How long the app's loop takes to answer a cheap call (a click)."""
    t = time.monotonic()
    webui_shot.state(url)                  # served off the loop: always quick
    webui_shot.api(url, "ui.dismiss_toast", "pad505-probe")  # answered ON the loop
    return (time.monotonic() - t) * 1000.0


LAG_JS = """
(() => { window.__lag = []; let last = performance.now();
  (function tick() { setTimeout(() => { const now = performance.now();
    window.__lag.push(now - last - 50); last = now; tick(); }, 50); })(); })();
"""
_COUNT = re.compile(r"Converting pictures: ([\d,]+) of")


def _first(page, url, out_dir, prefix):
    """Round 1: the State line and the clicks while the pictures convert."""
    webui_shot.api(url, "emulate.toggle")
    t0 = time.time()
    clicks = []

    def clicker():
        # a click every 2 s while it converts
        while time.time() - t0 < 32:
            try:
                clicks.append(_click_ms(url))
            except Exception as exc:                 # noqa: BLE001
                clicks.append(float("inf"))
                print("click failed:", exc, flush=True)
            time.sleep(2)

    th = threading.Thread(target=clicker, daemon=True)
    th.start()
    pic = re.compile(r"Staging (\S+)")
    while time.time() - t0 < 30:
        time.sleep(1)
        st = webui_shot.state(url)
        said = (st.get("emulate") or {}).get("vals", {}).get("state")
        newest = next((pic.search(ln.get("text", "")).group(1)
                       for ln in reversed(page.evaluate(
                           "Array.from(document.querySelectorAll('.line'))"
                           ".slice(-40).map(e => ({text: e.textContent}))"))
                       if pic.search(ln.get("text", ""))), "")
        print("%4.0f s  state: %-60s  log's newest: %s"
              % (time.time() - t0, said, newest[-60:]), flush=True)
    out = os.path.join(out_dir, "%s_emulate_converting.png" % prefix)
    page.screenshot(path=out)
    print("shot", out, flush=True)
    th.join(150)
    print("clicks answered in (ms):",
          ", ".join("%.0f" % c for c in clicks), flush=True)


def _busy(page, url, out_dir, prefix, throttle=6.0, secs=35):
    """Round 2: the PAGE on a busy PC - Edge's CPU throttled *throttle* times,
    the State line as the page shows it beside the server's, and the page's
    worst stall each second."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
    page.evaluate(LAG_JS)
    out = os.path.join(out_dir, "%s_emulate_busy_page.png" % prefix)
    webui_shot.api(url, "emulate.toggle")
    t0 = time.time()
    shooter = None
    if HEADED:
        def shoot():
            server = ((webui_shot.state(url).get("emulate") or {}).get("vals", {})
                      .get("state") or "")
            _window_shot(out)
            print("%4.0f s  WINDOW SHOT; the server said: %s" % (time.time() - t0, server),
                  flush=True)
        shooter = threading.Timer(secs, shoot)
        shooter.start()
    seen = 0
    while time.time() - t0 < secs:
        time.sleep(1)
        server = ((webui_shot.state(url).get("emulate") or {}).get("vals", {})
                  .get("state") or "")
        t_ask = time.time()
        shown, n, lag = page.evaluate(
            "() => { const el = document.querySelector('.emu-state'); const l = window.__lag;"
            " return [el ? el.textContent : '', l.length, Math.max(0, ...l.slice(%d))]; }"
            % seen)
        seen = n
        m1, m2 = _COUNT.search(shown or ""), _COUNT.search(server)
        print("%4.0f s  page shows %-7s server %-7s  worst stall %6.0f ms  "
              "page answered in %6.0f ms"
              % (time.time() - t0, m1.group(1) if m1 else shown[:7],
                 m2.group(1) if m2 else server[:7], lag, (time.time() - t_ask) * 1000),
              flush=True)
    if shooter is not None:
        shooter.join()
        print("shot", out, flush=True)
        return
    t_shot = time.time()
    page.screenshot(path=out, timeout=300000)
    print("shot", out, "(took %.0f s to take)" % (time.time() - t_shot), flush=True)


#: PAD505_HEADED=1: a real Edge window, off screen (nothing shows on David's
#: desktop), captured from Windows the way a user sees it - the last frame the
#: window drew.  Playwright's own screenshot waits for the page, which on the
#: stalled page is the minute the user is looking at a frozen window.
HEADED = os.environ.get("PAD505_HEADED") == "1"
OFF_SCREEN_X = -3200


def _window_shot(out):
    """PrintWindow of the off-screen Edge window (tools/spike2_emu/shotwin.py),
    found by where it is, so no other window can be taken by mistake."""
    import ctypes
    from ctypes import wintypes
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools", "spike2_emu"))
    import shotwin
    for hwnd, title, _pid, w, h in shotwin.find_windows(""):
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.left <= OFF_SCREEN_X + 100 and w > 400 and h > 400:
            ok, _got, lit, _n = shotwin.snap(hwnd, w, h, out)
            print("window %r %dx%d captured: PrintWindow %s, %d lit samples"
                  % (title, w, h, ok, lit), flush=True)
            return
    raise RuntimeError("the off-screen Edge window was not found")


def _second(page, url, out_dir, prefix):
    """Round 2: a SECOND Start - the first one converts every picture and is
    cancelled once it is past them; 3 s into the second, the shot."""
    def state():
        return ((webui_shot.state(url).get("emulate") or {}).get("vals", {})
                .get("state") or "")

    webui_shot.api(url, "emulate.toggle")
    t0 = time.time()
    was = now = ""
    while time.time() - t0 < 600:
        time.sleep(1)
        now = state()
        if was.startswith("Converting pictures") \
                and not now.startswith("Converting pictures"):
            break
        was = now or was
    print("first Start past the pictures after %.0f s (%s); cancelling"
          % (time.time() - t0, now), flush=True)
    webui_shot.api(url, "emulate.toggle")
    t1 = time.time()
    btn = None
    while time.time() - t1 < 300:
        time.sleep(1)
        btn = (((webui_shot.state(url).get("emulate") or {}).get("run_btn") or {})
               .get("label"))
        if btn and "Cancel" not in btn and "…" not in btn:
            break
    print("first Start over after %.0f s more: button %r" % (time.time() - t1, btn),
          flush=True)
    time.sleep(2)
    webui_shot.api(url, "emulate.toggle")
    t2 = time.time()
    while time.time() - t2 < 3:
        time.sleep(1)
        print("%4.0f s into the second Start: %s" % (time.time() - t2, state()), flush=True)
    out = os.path.join(out_dir, "%s_emulate_second_start.png" % prefix)
    page.screenshot(path=out)
    print("shot", out, flush=True)
    kept = [ln for ln in page.evaluate(
        "Array.from(document.querySelectorAll('.line')).map(e => e.textContent)")
        if "left as they are" in ln]
    print("log:", kept[-1:] or "(no picture kept)", flush=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    mode = sys.argv[5] if len(sys.argv) > 5 else "first"
    line_ms = float(sys.argv[4]) if len(sys.argv) > 4 else 8.0
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad505-")
    project, n = make_project(repo, scratch)
    print("repo", repo, "project", project, "pictures", n, "line_ms", line_ms,
          "mode", mode, flush=True)
    launcher = os.path.join(scratch, "launch505.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER.replace("@REPO@", repr(repo))
                .replace("@SLEEP@", repr(line_ms / 1000.0)))
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "emulate_card": CARD, "emulate_overrides": True,
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    # the server's own temp: the override build writes %TEMP%\spike2_overrides,
    # which on this PC is David's real set
    tmp = os.path.join(scratch, "tmp")
    os.makedirs(tmp)
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "TEMP": tmp, "TMP": tmp}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = (p.chromium.launch(
                channel="msedge", headless=False,
                args=["--window-position=%d,40" % OFF_SCREEN_X,
                      "--window-size=1416,1100"])
                       if HEADED else p.chromium.launch(channel="msedge"))
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(3)
            {"first": _first, "busy": _busy, "second": _second}[mode](
                page, url, out_dir, prefix)
            try:
                webui_shot.api(url, "emulate.toggle")      # Cancel
            except Exception:                              # noqa: BLE001
                pass
            time.sleep(3)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                    # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
