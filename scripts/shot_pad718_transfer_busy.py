"""PAD-718 proof shot: the footer while Transfer mods is comparing.

    python scripts/shot_pad718_transfer_busy.py <repo> <out_dir> <before|after>

Serves <repo> with two scratch extract folders on the Mod Pack tab and clicks Transfer mods.
The comparison is made slow on purpose (the launcher swaps mod_transfer.plan_transfer for one
that logs a few progress lines and waits 20 s, the way a real one over hundreds of clips does),
and the whole window is photographed half way through:

- <before|after>_transfer_busy.png

Before, the footer still says Ready and the bar sits where the last job left it, and the
Transfer button looks clickable. After, the bar moves with "working…", an elapsed clock and the
step's latest line, and the button reads "Transferring…" (disabled).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys, time
sys.path.insert(0, %r)
from pinball_decryptor.core import mod_transfer
def _slow_plan(source_dir, target_dir, log_cb=None, **kw):
    log = log_cb or (lambda *a: None)
    log("Transfer: pairing videos by content (312 clips)...")
    for n in (40, 120, 200):
        time.sleep(4)
        log("Transfer: video %%d of 312 compared" %% n)
    time.sleep(12)
    return {"totals": {"transfer": 0, "flagged": 0, "dropped": 1}}
mod_transfer.plan_transfer = _slow_plan
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _folder(scratch, name):
    d = os.path.join(scratch, name)
    os.makedirs(os.path.join(d, "video"))
    return d


def main():
    repo, out_dir, which = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad718-")
    old = _folder(scratch, "iron_maiden_le-1_16 my mods")
    new = _folder(scratch, "iron_maiden_le-1_18_0 extract")
    launcher = os.path.join(scratch, "launch718.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": new, "write_assets": new}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    out = os.path.join(out_dir, "%s_transfer_busy.png" % which)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "modpack")
            time.sleep(1.5)
            api("ui.set", "modpack", "src", old)
            api("ui.set", "modpack", "dst", new)
            time.sleep(1.5)
            threading.Thread(target=lambda: api("modpack.transfer"), daemon=True).start()
            time.sleep(9)
            page.locator(".mp-arow button").first.scroll_into_view_if_needed()
            time.sleep(1)
            page.screenshot(path=out)
            print("button:", page.locator(".mp-arow button").first.inner_text(), flush=True)
            print("footer:", page.locator(".lprog").inner_text(), "|",
                  page.locator(".statusbar").inner_text(), flush=True)
            print("saved", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
