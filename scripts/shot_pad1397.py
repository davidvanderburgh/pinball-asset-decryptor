"""PAD-1397 proof shots: Send to machine on the Network tab and the Write tab (Stern Spike 2, Deadpool LE).

    python scripts/shot_pad1397.py <repo> <out_dir> [--card <raw>] [--project <dir>] [--address <a>]

Serves <repo> on scratch settings with the card and a project that has Remote access on, then shoots the Network
tab (out_dir/network.png) and the Write tab (out_dir/write.png).  Before (main) the Network tab has no Send to
machine card and the Write tab no Send to machine button; after, both are there.

Needs Playwright (the user site-packages one), the installed Edge and the card.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\deadpool_le-1_16_0.Release.8G.sdcard.raw")
    src_project = _arg("--project", r"C:\tmp\PAD-1397\proj_B")
    address = _arg("--address", "192.168.1.40")
    scratch = tempfile.mkdtemp(prefix="pad1397-")
    project = os.path.join(scratch, "project")
    shutil.copytree(src_project, project)
    launcher = os.path.join(scratch, "launch1397.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1250})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.use_recent", "input", card)
            time.sleep(6)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(3)
            try:
                webui_shot.api(url, "network.set_address", address)     # after only: main has no such call
            except Exception as e:                                       # noqa: BLE001
                print("no set_address here (%s)" % e, flush=True)
            time.sleep(2)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            try:
                page.get_by_text("Send to machine", exact=True).first.scroll_into_view_if_needed(timeout=3000)
            except Exception:                                            # noqa: BLE001 - main has none
                pass
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "network.png"))
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(5)
            page.screenshot(path=os.path.join(out_dir, "write.png"))
            print("saved", out_dir, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
