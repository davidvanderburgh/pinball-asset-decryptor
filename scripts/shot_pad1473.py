"""PAD-1473 (PR #40) proof shots: Service menu rows ticked on a fresh project.

    python scripts/shot_pad1473.py <repo> <out_dir> <before|after>

A scratch Godzilla LE 1.16 project with nothing in it yet (no music modes, editions or themes) and Music Mode, Edition
and Image Set ticked on the Service menu tab. Writes <out_dir>/<kind>_service_menu.png (the Service menu tab) and
<kind>_write_tab.png (the Write tab's pending changes). Playwright + the installed Edge; the app on a scratch APPDATA
(webui_shot.py).
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


def make_project(root):
    project = os.path.join(root, "Godzilla LE project")
    os.makedirs(os.path.join(project, "audio"), exist_ok=True)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({"service_menu": {"on": ["music_mode", "edition", "image_set"]}}, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1473-")
    project = make_project(scratch)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_input": CARD, "write_original": CARD,
                                               "extract_output": project, "write_assets": project}}}, f)
    import site
    os.chdir(repo)
    proc, url = webui_shot.start_server(settings, scratch, extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "svcmenu")
            end = time.time() + 180
            s = {}
            while time.time() < end:
                s = webui_shot.state(url).get("svcmenu") or {}
                if s.get("menu") or s.get("why"):
                    break
                time.sleep(1)
            print("rows:", [(r.get("key"), r.get("can"), r.get("on"), r.get("note")) for r in s.get("rows") or []])
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, "%s_service_menu.png" % kind))
            webui_shot.api(url, "ui.select_tab", "write")
            time.sleep(8)
            page.screenshot(path=os.path.join(out_dir, "%s_write_tab.png" % kind))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
