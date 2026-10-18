"""PAD-603 proof: what the Emulate tab's log says when venom_le 0.95 ends its run.

    python scripts/shot_pad603.py <repo> <out_dir> <prefix> <watch.out>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for
the "before" shot).  <watch.out> is the rig's whole output from a REAL hidden, muted run
of the card on that same tree (C:/tmp/PAD-603/boot.sh): the tab is shown with exactly
those lines, fed through the tab's own ``_log`` the way its drain feeds a live run's
(``"[emulate] " + line``).  No game is started here - a GUI Start would run with sound.

  <prefix>_emulate_log.png   the Emulate tab with the end of that run in its log
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import os, sys, threading, time
sys.path.insert(0, %r)
from pinball_decryptor.webui.tabs import emulate as _em
_init = _em.EmulateTab.__init__
def _init_and_replay(self, *a, **k):
    _init(self, *a, **k)
    def replay():
        time.sleep(6)
        with open(os.environ["PAD603_REPLAY"], encoding="utf-8", errors="replace") as f:
            for raw in f:
                self._log("[emulate] " + raw.rstrip("\r\n"))
                time.sleep(0.004)
        self._log("[emulate] (end of replay)")
    threading.Thread(target=replay, daemon=True).start()
_em.EmulateTab.__init__ = _init_and_replay
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    replay = os.path.abspath(sys.argv[4])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad603-")
    print("repo", repo, "replay", replay, flush=True)
    launcher = os.path.join(scratch, "launch603.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": "1",
           "PAD_UI_NO_PREREQS": "1", "PAD_TICKET": "", "PAD603_REPLAY": replay}
    proc, url = webui_shot.start_server(settings, scratch,
                                        app_cmd=[sys.executable, launcher],
                                        extra_env=env)
    print("server", url.split("?")[0], flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            t0 = time.time()
            while time.time() - t0 < 120:
                time.sleep(1)
                with open(os.path.join(scratch, "server.log"), encoding="utf-8",
                          errors="replace") as f:
                    if "(end of replay)" in f.read():
                        break
            time.sleep(4)
            # the log gets most of the window (drag the splitter up), then the
            # run's own exit report is scrolled to its top
            grip = page.locator("text=••••••").first
            if grip.count():
                box = grip.bounding_box()
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            else:
                x, y = 803, 770
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x, 130, steps=12)
            page.mouse.up()
            time.sleep(1.5)
            page.mouse.move(5, 995)
            found = page.evaluate("""() => {
                const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let hit = null, n;
                while ((n = w.nextNode()))
                    if (n.nodeValue.includes('the game exited')) hit = n;
                if (!hit) return 'no text';
                let box = hit.parentElement;
                while (box && !(box.scrollHeight > box.clientHeight + 2 &&
                       /(auto|scroll)/.test(getComputedStyle(box).overflowY)))
                    box = box.parentElement;
                if (!box) return 'no scroller';
                const r = document.createRange(); r.selectNodeContents(hit);
                box.scrollTop += r.getBoundingClientRect().top
                                 - box.getBoundingClientRect().top - 60;
                return 'ok';
            }""")
            print("exit report found:", found, flush=True)
            time.sleep(1)
            out = os.path.join(out_dir, "%s_emulate_log.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
    print("scratch", scratch, flush=True)


if __name__ == "__main__":
    main()
