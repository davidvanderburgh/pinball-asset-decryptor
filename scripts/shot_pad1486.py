"""PAD-1486 proof shot: the Network tab with a Spike 2 card picked but its project not extracted yet.

    python scripts/shot_pad1486.py <repo> <out_png> [--card <raw>] [--extracted]

Serves <repo> on scratch settings with a Godzilla LE card and a project folder that does not exist yet (the
reporter's case: a folder named on the Extract tab, the card not extracted into it), and shoots the Network tab.
--extracted makes the folder and records the card in it first, so the Score feed and Online co-op boxes show.

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
    out_png = os.path.abspath(sys.argv[2])
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    card = _arg("--card", r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    scratch = tempfile.mkdtemp(prefix="pad1486-")
    project = os.path.join(scratch, "godzilla project")
    if "--extracted" in sys.argv:
        os.makedirs(project)
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": card, "input_name": os.path.basename(card), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1486.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "network")
            time.sleep(5)
            try:
                page.get_by_text("Hide log").first.click(timeout=3000)
            except Exception:                                    # noqa: BLE001
                pass
            time.sleep(1)
            page.screenshot(path=out_png)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)
    print("shot", out_png)


if __name__ == "__main__":
    main()
