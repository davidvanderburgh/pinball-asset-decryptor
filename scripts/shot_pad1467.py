"""PAD-1467 proof shots: the Network tab's Wi-Fi start-up option.

    python scripts/shot_pad1467.py <repo> <out_dir> [--card <raw>] [--project <dir>] [--before]

Serves <repo> on scratch settings with a Spike 2 card and a project folder (a copy of --project, else an empty one), and shoots the Network tab
(out_dir/network.png).  After (the ticket branch) it also turns the option on and shoots the tab again
(network_on.png) and the Write tab's row for it (write_row.png).  Before (main) there is no such option.

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
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.core import pad_ssh_key
pad_ssh_key.KEY_DIR = os.path.join(%r, "remote_access")
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    src_project = _arg("--project", "")
    scratch = tempfile.mkdtemp(prefix="pad1467-")
    project = os.path.join(scratch, "project")
    if src_project:
        shutil.copytree(src_project, project)
    else:
        os.makedirs(project)                # the option needs only a project folder to save its choice in
    launcher = os.path.join(scratch, "launch1467.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % (repo, scratch))
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
            page = browser.new_page(viewport={"width": 1500, "height": 1400})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.use_recent", "input", card)
            time.sleep(6)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(4)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                            # noqa: BLE001
                pass
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "network.png"), full_page=True)
            if "--before" not in sys.argv:
                page.get_by_text("Use the reliable Wi-Fi start-up on cards I write from this project").first.click()
                time.sleep(2)
                page.screenshot(path=os.path.join(out_dir, "network_on.png"), full_page=True)
                card_el = page.locator(".net-opt", has_text="Wi-Fi start-up").first
                card_el.screenshot(path=os.path.join(out_dir, "wifi_card.png"))
                webui_shot.api(url, "ui.select_tab", "write")
                time.sleep(8)
                page.screenshot(path=os.path.join(out_dir, "write_row.png"), full_page=True)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)
    print("shots in", out_dir)


if __name__ == "__main__":
    main()
