"""PAD-1595 proof shot: the log a few seconds after the app starts, over a copy of a real download cache.

    python scripts/shot_pad1595.py <app tree> <real payloads folder> <out.png>

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after").
The app is served with PAD_PAYLOAD_DIR on a fresh scratch folder of HARD LINKS to every file in <real
payloads folder> (David's: six superseded runtime tarballs, an old runtime-base and an old s1hwshim
beside the current runtime, 2.5 GB), so whatever the app deletes is a link and the real files stay.
Before, nothing is tidied; after, the start-up prune deletes what this version no longer pins and says
so in the log. Prints the folder's files and MB before and after the run.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %(repo)r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _folder(path):
    names = sorted(os.listdir(path))
    mb = sum(os.path.getsize(os.path.join(path, n)) for n in names) / 1e6
    return "%d files, %.0f MB" % (len(names), mb)


def main():
    repo, real, out = (os.path.abspath(p) for p in sys.argv[1:4])
    scratch = tempfile.mkdtemp(prefix="pad1595-")
    cache = os.path.join(scratch, "payloads")
    os.makedirs(cache)
    for name in os.listdir(real):
        os.link(os.path.join(real, name), os.path.join(cache, name))
    print("payloads before:", _folder(cache), flush=True)
    launcher = os.path.join(scratch, "launch1595.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"repo": repo})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True}, f)
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD_PAYLOAD_DIR": cache})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 760})
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '1'); "
                "localStorage.setItem('pad.log.h', '300'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            # the log pane belongs to a manufacturer's screen
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            back = page.locator("button.sx-gs-close, button:has-text('Back to Stern Pinball')")
            if back.count():
                back.first.click()
            time.sleep(10)          # the prune starts 3 s after the window
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
    print("payloads after:", _folder(cache), flush=True)


if __name__ == "__main__":
    main()
