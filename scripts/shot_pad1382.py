"""PAD-1382 proof shots: the Service menu tab.

    python scripts/shot_pad1382.py <repo> <out_dir> <before|after>

A scratch Godzilla LE 1.16 project (the stock card in D:/Pinball/images/Stern/spike2) asking for music modes, two
editions, co-op switched in the service menu and handicaps: four settings of the app's on a game with three spare rows.
before (main): the Play options tab, where Handicap is ticked - nothing shows the menu the card will get.
after: the Service menu tab - the Attract Mode page as the machine draws it, EDITION on a row of its own and the rest
sharing MORE SETTINGS; a second shot with MORE SETTINGS stepped to Co-op Play. Writes <out_dir>/<kind>_service_menu.png
(and after_service_menu_coop.png). Playwright + the installed Edge; the app on a scratch APPDATA (webui_shot.py).
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
    side = {"sound_modes": {"names": ["Standard", "Orchestral", "Heisei"],
                            "slots": {"audio/idx2095.wav": {"2": "C:/music/orchestral.wav",
                                                            "3": "C:/music/heisei.wav"}}},
            "editions": {"names": ["Standard", "Kaiju"]},
            "coop_play": {"on": True, "menu": True},
            "handicap": {"on": True}}
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(side, f)
    return project


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1382-")
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
            if kind == "before":
                webui_shot.api(url, "ui.select_tab", "playopts")
                time.sleep(3)
                page.screenshot(path=os.path.join(out_dir, "before_service_menu.png"))
            else:
                webui_shot.api(url, "ui.select_tab", "svcmenu")
                end = time.time() + 180
                while time.time() < end:
                    s = webui_shot.state(url).get("svcmenu") or {}
                    if s.get("menu") or s.get("why"):
                        break
                    time.sleep(1)
                print("why:", s.get("why"), "refused:", (s.get("menu") or {}).get("refused"))
                time.sleep(1.5)
                page.screenshot(path=os.path.join(out_dir, "after_service_menu.png"))
                more = page.locator(".sm-row", has_text="More Settings")
                more.click()
                time.sleep(0.4)
                for _ in range(1):
                    page.locator(".sm-step button").nth(1).click()
                    time.sleep(0.3)
                page.locator(".sm-row").nth(more.evaluate("e => [...e.parentNode.children].indexOf(e)") + 1).click()
                time.sleep(0.6)
                page.screenshot(path=os.path.join(out_dir, "after_service_menu_coop.png"))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
